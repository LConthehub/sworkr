"""Tests for two-step sign-in (emailed codes) and passkeys. Run with:  docker compose run --rm tests"""
import base64
import hashlib
import json
import os
import sys
import tempfile
import uuid

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cbor2  # noqa: E402  (comes with the webauthn library)
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import signin  # noqa: E402

PASSWORD = "correct-horse-battery"
ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def account(admin):
    name = "g-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return name, c


@pytest.fixture
def mailbox(monkeypatch):
    """Codes 'sent' land here; the server's email counts as set up."""
    sent = []
    monkeypatch.setattr(signin, "send_code", lambda db, user_id, address, code: sent.append((address, code)))
    import safety
    monkeypatch.setattr(safety, "smtp_configured", lambda: True)
    return sent


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


# ---------- two-step sign-in ----------

def turn_on(c, mailbox, address="me@example.com"):
    start = ok(c.post("/api/account/two-step/start", json={"address": address}))
    ok(c.post("/api/account/two-step/confirm", json={"challenge": start["challenge"], "code": mailbox[-1][1]}))


def test_two_step_is_only_on_once_a_code_has_arrived(account, mailbox):
    name, c = account
    assert ok(c.get("/api/account/two-step"))["via"] == "server"
    start = ok(c.post("/api/account/two-step/start", json={"address": "me@example.com"}))
    assert mailbox[-1][0] == "me@example.com"
    assert c.post("/api/account/two-step/confirm", json={"challenge": start["challenge"], "code": "000000"}).status_code == 400
    assert not ok(c.get("/api/account/two-step"))["enabled"]
    ok(c.post("/api/account/two-step/confirm", json={"challenge": start["challenge"], "code": mailbox[-1][1]}))
    assert ok(c.get("/api/account/two-step"))["enabled"]


def test_signing_in_needs_the_emailed_code(account, mailbox):
    name, c = account
    turn_on(c, mailbox)
    fresh = TestClient(main.app)
    r = ok(fresh.post("/api/auth/login", json={"username": name, "password": PASSWORD}))
    assert r["two_step"] and r["sent_to"] == "me•@example.com" and "id" not in r
    assert fresh.get("/api/clients").status_code == 401          # no session yet
    wrong = fresh.post("/api/auth/login/code", json={"challenge": r["challenge"], "code": "999999"})
    assert wrong.status_code == 400 and "4 tries left" in wrong.text
    me = ok(fresh.post("/api/auth/login/code", json={"challenge": r["challenge"], "code": mailbox[-1][1]}))
    assert me["username"] == name and fresh.get("/api/clients").status_code == 200
    # A code works once.
    assert fresh.post("/api/auth/login/code", json={"challenge": r["challenge"], "code": mailbox[-1][1]}).status_code == 400


def test_five_wrong_codes_end_the_attempt(account, mailbox):
    name, c = account
    turn_on(c, mailbox)
    fresh = TestClient(main.app)
    r = ok(fresh.post("/api/auth/login", json={"username": name, "password": PASSWORD}))
    for _ in range(5):
        fresh.post("/api/auth/login/code", json={"challenge": r["challenge"], "code": "111111"})
    assert fresh.post("/api/auth/login/code", json={"challenge": r["challenge"], "code": mailbox[-1][1]}).status_code == 400


def test_a_new_code_waits_a_minute_and_replaces_the_old_one(account, mailbox):
    name, c = account
    turn_on(c, mailbox)
    fresh = TestClient(main.app)
    r = ok(fresh.post("/api/auth/login", json={"username": name, "password": PASSWORD}))
    assert fresh.post("/api/auth/login/code/resend", json={"challenge": r["challenge"]}).status_code == 429


def test_turning_it_off_needs_the_password(account, mailbox):
    name, c = account
    turn_on(c, mailbox)
    assert c.post("/api/account/two-step/off", json={"password": "nope"}).status_code == 400
    ok(c.post("/api/account/two-step/off", json={"password": PASSWORD}))
    assert "id" in ok(TestClient(main.app).post("/api/auth/login", json={"username": name, "password": PASSWORD}))


def test_no_email_means_it_cant_be_turned_on(account, monkeypatch):
    name, c = account
    import safety
    monkeypatch.setattr(safety, "smtp_configured", lambda: False)
    assert ok(c.get("/api/account/two-step"))["via"] is None
    assert c.post("/api/account/two-step/start", json={"address": "me@example.com"}).status_code == 400


def test_the_admin_can_turn_it_off_from_the_command_line(account, mailbox, monkeypatch):
    name, c = account
    turn_on(c, mailbox)
    import manage
    monkeypatch.setattr(sys, "argv", ["manage.py", "turn-off-two-step", name])
    manage.main()
    assert "id" in ok(TestClient(main.app).post("/api/auth/login", json={"username": name, "password": PASSWORD}))


# ---------- passkeys, with a small software authenticator ----------

def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SoftKey:
    """Does what a phone's or laptop's passkey does, for "localhost"."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.count = 0
        self.handle = os.urandom(16)

    def create(self, options, origin="http://localhost"):
        rp_hash = hashlib.sha256(options["rp"]["id"].encode()).digest()
        self.handle = unb64(options["user"]["id"])
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        auth_data = (rp_hash + bytes([0x45]) + (0).to_bytes(4, "big") + bytes(16)
                     + len(self.cred_id).to_bytes(2, "big") + self.cred_id + cose)
        client = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": origin}).encode()
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(client), "transports": ["internal"],
                             "attestationObject": b64(cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data}))}}

    def get(self, options, origin="http://localhost"):
        self.count += 1
        auth_data = hashlib.sha256(options["rpId"].encode()).digest() + bytes([0x05]) + self.count.to_bytes(4, "big")
        client = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": origin}).encode()
        sig = self.key.sign(auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(client), "authenticatorData": b64(auth_data), "signature": b64(sig),
                             "userHandle": b64(self.handle)}}


def add_passkey(c, key, name="My phone"):
    begin = ok(c.post("/api/account/passkeys/begin", headers=ORIGIN))
    assert begin["options"]["rp"]["id"] == "localhost"
    return ok(c.post("/api/account/passkeys/finish", headers=ORIGIN,
                     json={"challenge": begin["challenge"], "credential": key.create(begin["options"]), "name": name}), 201)


def sign_in_with(key, client=None):
    client = client or TestClient(main.app)
    begin = ok(client.post("/api/auth/passkey/begin", headers=ORIGIN))
    return client, client.post("/api/auth/passkey/finish", headers=ORIGIN,
                               json={"challenge": begin["challenge"], "credential": key.get(begin["options"])})


def test_a_passkey_signs_in_without_a_password(account):
    name, c = account
    key = SoftKey()
    add_passkey(c, key)
    assert [p["name"] for p in ok(c.get("/api/account/passkeys"))] == ["My phone"]
    client, r = sign_in_with(key)
    assert ok(r)["username"] == name and client.get("/api/clients").status_code == 200
    _, again = sign_in_with(key)              # the counter goes up each time; still fine
    assert again.status_code == 200


def test_a_passkey_skips_the_emailed_code(account, mailbox):
    name, c = account
    key = SoftKey()
    add_passkey(c, key)
    turn_on(c, mailbox)
    _, r = sign_in_with(key)
    assert ok(r)["username"] == name


def test_a_passkey_from_another_address_or_an_unknown_one_is_refused(account):
    name, c = account
    key = SoftKey()
    add_passkey(c, key)
    client = TestClient(main.app)
    begin = ok(client.post("/api/auth/passkey/begin", headers=ORIGIN))
    forged = key.get(begin["options"], origin="http://evil.example")
    assert client.post("/api/auth/passkey/finish", headers=ORIGIN, json={"challenge": begin["challenge"], "credential": forged}).status_code == 400
    _, r = sign_in_with(SoftKey())
    assert r.status_code == 400 and "doesn't know that passkey" in r.text


def test_a_deleted_passkey_no_longer_works(account):
    name, c = account
    key = SoftKey()
    add_passkey(c, key)
    pid = ok(c.get("/api/account/passkeys"))[0]["id"]
    assert c.delete(f"/api/account/passkeys/{pid}").status_code == 204
    _, r = sign_in_with(key)
    assert r.status_code == 400


def test_challenges_are_single_use(account):
    name, c = account
    key = SoftKey()
    begin = ok(c.post("/api/account/passkeys/begin", headers=ORIGIN))
    cred = key.create(begin["options"])
    ok(c.post("/api/account/passkeys/finish", headers=ORIGIN, json={"challenge": begin["challenge"], "credential": cred}), 201)
    assert c.post("/api/account/passkeys/finish", headers=ORIGIN, json={"challenge": begin["challenge"], "credential": cred}).status_code == 400
