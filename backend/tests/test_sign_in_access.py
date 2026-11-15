"""Tests for sign-in hardening: the lasting throttle, where a visitor really comes from, signed-in devices and
sign-in history, new-device emails, passkeys only away from home, authenticator-app codes and recovery codes.
Run with:  docker compose run --rm tests"""
import os
import sys
import tempfile
import time
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402

import access  # noqa: E402
import auth  # noqa: E402
import main  # noqa: E402
import signin  # noqa: E402

PASSWORD = "correct-horse-battery"
HOME = {"X-Forwarded-For": "192.168.1.20, 172.18.0.1"}        # a phone on the home network, through the proxies


def away(n=None):
    """A visitor from the internet (each test gets its own address, so throttles don't mix)."""
    return {"X-Forwarded-For": f"8.8.{(n if n is not None else uuid.uuid4().int) % 250}.{uuid.uuid4().int % 250}, 172.18.0.1"}


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def notices(monkeypatch):
    """Emails to the person land here instead of being sent."""
    sent = []
    monkeypatch.setattr(access, "notify", lambda user_id, subject, body: sent.append((user_id, subject, body)))
    return sent


@pytest.fixture
def account(admin, notices):
    name = "a-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return name, c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def login(name, password=PASSWORD, headers=None, client=None):
    return (client or TestClient(main.app)).post("/api/auth/login", json={"username": name, "password": password}, headers=headers or {})


def user_id(name):
    db = main.get_db()
    try:
        return db.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()["id"]
    finally:
        db.close()


def request_with(xff=None, peer="172.18.0.5"):
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET", "path": "/", "query_string": b""})


# ---------- where a request came from ----------

@pytest.mark.parametrize("xff, peer, ip, local", [
    ("203.0.114.9, 172.18.0.1", "172.18.0.5", "203.0.114.9", False),           # through Caddy and nginx
    ("127.0.0.1, 203.0.114.9, 172.18.0.1", "172.18.0.5", "203.0.114.9", False),  # the visitor typed a fake first entry
    ("192.168.1.20, 172.18.0.1", "172.18.0.5", "192.168.1.20", True),          # the home network
    ("100.101.102.103, 172.18.0.1", "172.18.0.5", "100.101.102.103", True),    # a private-network tool (Tailscale)
    (None, "127.0.0.1", "127.0.0.1", True),                                    # straight to the API on this computer
    (None, "testclient", "testclient", False),                                 # not an address at all: never "home"
    ("::ffff:8.8.8.8", "172.18.0.5", "8.8.8.8", False),
])
def test_the_visitor_is_the_first_public_address_from_the_right(xff, peer, ip, local):
    r = request_with(xff, peer)
    assert access.client_ip(r) == ip
    assert access.is_local(r) is local


# ---------- throttling ----------

def test_the_throttle_outlives_a_restart_and_cannot_grow_without_limit():
    key = "restart-" + uuid.uuid4().hex
    t = auth.LoginThrottle("test", free_attempts=2)
    t.failure(key)
    assert t.seconds_locked(key) == 0
    t.failure(key)
    assert auth.LoginThrottle("test", free_attempts=2).seconds_locked(key) > 0    # a new object: it's in the database
    t.success(key)
    assert t.seconds_locked(key) == 0

    small = auth.LoginThrottle("flood")
    small.MAX_TRACKED = 50
    for i in range(120):
        small.failure(f"user{i}-{key}")
    db = main.get_db()
    try:
        assert db.execute("SELECT COUNT(*) FROM login_throttle").fetchone()[0] <= 51
    finally:
        db.close()


def test_a_stranger_guessing_cannot_lock_the_owner_out(account):
    name, _ = account
    stranger = away(1)
    for _ in range(auth.pair_throttle.FREE_ATTEMPTS):
        assert login(name, "wrong-password-x", stranger).status_code == 401
    assert login(name, PASSWORD, stranger).status_code == 429       # that address is locked for this username
    assert login(name, PASSWORD, HOME).status_code == 200           # the owner, from somewhere else, still gets in


def test_short_passwords_are_refused(admin):
    r = admin.post("/api/users", json={"username": "short-" + uuid.uuid4().hex[:6], "password": "only11chars"})
    assert r.status_code == 400 and "12" in r.json()["detail"]


def test_https_answers_tell_the_browser_to_stay_on_https(admin):
    assert "Strict-Transport-Security" not in admin.get("/api/health").headers
    assert admin.get("/api/health", headers={"X-Forwarded-Proto": "https"}).headers["Strict-Transport-Security"].startswith("max-age=")


# ---------- signed-in devices and history ----------

def test_devices_are_listed_and_can_be_logged_out(account):
    name, here = account
    other = TestClient(main.app)
    ua = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605 Version/18.0 Mobile Safari/604.1"}
    ok(login(name, headers={**away(), **ua}, client=other))

    sessions = ok(here.get("/api/account/sessions"))
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    phone = next(s for s in sessions if not s["current"])
    assert phone["device"] == "Safari on iPhone" and phone["ip"].startswith("8.8.") and phone["method"] == "password"

    ok(here.delete(f"/api/account/sessions/{phone['id']}"), 204)
    assert other.get("/api/account/sessions").status_code == 401
    assert len(ok(here.get("/api/account/sessions"))) == 1

    third = TestClient(main.app)
    ok(login(name, client=third))
    assert ok(here.post("/api/account/sessions/log-out-others")) == {"logged_out": 1}
    assert third.get("/api/account/settings").status_code == 401
    assert here.get("/api/account/settings").status_code == 200


def test_nobody_can_log_out_someone_elses_device(account, admin):
    _, here = account
    mine = ok(here.get("/api/account/sessions"))[0]
    ok(admin.delete(f"/api/account/sessions/{mine['id']}"), 204)     # not theirs: nothing happens
    assert here.get("/api/account/settings").status_code == 200


def test_sign_ins_and_failed_tries_are_kept(account):
    name, here = account
    assert login(name, "wrong-password-x", away()).status_code == 401
    events = ok(here.get("/api/account/sign-ins"))
    assert [e["outcome"] for e in events] == ["wrong_password", "ok"]
    assert events[0]["ip"].startswith("8.8.") and events[1]["method"] == "password"
    # A made-up username leaves nothing behind (or a flood of them would fill the table).
    db = main.get_db()
    try:
        before = db.execute("SELECT COUNT(*) FROM signin_events").fetchone()[0]
        login("nobody-" + uuid.uuid4().hex[:6], "wrong-password-x", away())
        assert db.execute("SELECT COUNT(*) FROM signin_events").fetchone()[0] == before
    finally:
        db.close()


def test_a_browser_new_to_the_account_gets_an_email_once(account, notices):
    name, here = account
    assert notices == []                                   # the account's very first sign-in isn't news
    ok(here.post("/api/auth/logout"), 204)
    ok(login(name, client=here))
    assert notices == []                                   # same browser again
    new_phone = TestClient(main.app)
    ok(login(name, headers=away(), client=new_phone))
    assert len(notices) == 1 and notices[0][1] == "New sign-in"
    assert "sworkr" not in notices[0][2].lower() and "Safari" not in notices[0][2]
    ok(new_phone.post("/api/auth/logout"), 204)
    ok(login(name, client=new_phone))
    assert len(notices) == 1                               # known now

    ok(here.put("/api/account/access", json={"alerts": False}))
    ok(login(name, headers=away()))
    assert len(notices) == 1                               # turned off


# ---------- passkeys only away from home ----------

def add_passkey(name, rp_id):
    db = main.get_db()
    try:
        cur = db.execute("INSERT INTO passkeys (user_id, credential_id, public_key, rp_id, name, created_at) VALUES (?, ?, 'x', ?, 'Phone', ?)",
                         (user_id(name), uuid.uuid4().hex, rp_id, "2026-01-01T00:00:00+00:00"))
        db.commit()
        return cur.lastrowid
    finally:
        db.close()


def test_passwords_can_be_turned_off_for_the_internet(account):
    name, here = account
    status = ok(here.get("/api/account/access", headers=away()))
    assert status["local"] is False and status["passkey_only"] is False
    assert ok(here.get("/api/account/access", headers=HOME))["local"] is True

    add_passkey(name, "localhost")                          # a passkey for this computer doesn't help away from home
    r = here.put("/api/account/access", json={"passkey_only": True})
    assert r.status_code == 400 and "passkey" in r.json()["detail"]
    key = add_passkey(name, "sworkr.example.org")
    assert ok(here.put("/api/account/access", json={"passkey_only": True}))["passkey_only"] is True

    visitor = away()
    refused = login(name, PASSWORD, visitor)
    wrong = login(name, "wrong-password-x", visitor)
    assert refused.status_code == wrong.status_code == 401 and refused.json() == wrong.json()   # looks the same
    assert "set-cookie" not in refused.headers
    assert login(name, PASSWORD, HOME).status_code == 200   # at home the password still works
    assert [e["outcome"] for e in ok(here.get("/api/account/sign-ins"))][:3] == ["ok", "wrong_password", "password_off"]

    assert TestClient(main.app).get("/api/auth/status", headers=away()).json().get("passkey_hint") is True
    assert "passkey_hint" not in TestClient(main.app).get("/api/auth/status", headers=HOME).json()

    r = here.delete(f"/api/account/passkeys/{key}")         # the only way in from outside: kept
    assert r.status_code == 400
    ok(here.put("/api/account/access", json={"passkey_only": False}))
    ok(here.delete(f"/api/account/passkeys/{key}"), 204)
    assert login(name, PASSWORD, away()).status_code == 200


# ---------- authenticator app and recovery codes ----------

def turn_on_app(here):
    start = ok(here.post("/api/account/two-step/app/start", json={"label": "Notes"}))
    secret = start["secret"].replace(" ", "")
    assert "sworkr" not in start["uri"].lower() and start["uri"].startswith("otpauth://totp/Notes:")
    assert start["qr"] is None or start["qr"].startswith("data:image/svg+xml")
    wrong = here.post("/api/account/two-step/app/confirm", json={"challenge": start["challenge"], "code": "000000"})
    if wrong.status_code != 400:                            # one time in a million 000000 is the code
        return secret, ok(wrong)["recovery_codes"]
    code = signin.totp_code(secret, int(time.time() // 30))
    done = ok(here.post("/api/account/two-step/app/confirm", json={"challenge": start["challenge"], "code": code}))
    return secret, done["recovery_codes"]


def test_totp_matches_the_standard():
    # RFC 6238's test key ("12345678901234567890") at 59 seconds gives 94287082; apps show the last six digits.
    assert signin.totp_code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59 // 30) == "287082"


def test_signing_in_with_an_app_code(account, monkeypatch):
    name, here = account
    secret, codes = turn_on_app(here)
    assert len(codes) == 10 and len(set(codes)) == 10
    status = ok(here.get("/api/account/two-step"))
    assert status["enabled"] and status["method"] == "app" and status["recovery_codes"] == 10

    c = TestClient(main.app)
    step = ok(login(name, client=c))
    assert step["two_step"] and step["method"] == "app" and c.get("/api/account/settings").status_code == 401
    assert c.post("/api/auth/login/code/resend", json={"challenge": step["challenge"]}).status_code == 400

    db = main.get_db()
    try:
        now = int(signin._setting(db, user_id(name), "totp_last_step"))
    finally:
        db.close()
    used = signin.totp_code(secret, now)                    # the code that turned it on can't be used again
    assert c.post("/api/auth/login/code", json={"challenge": step["challenge"], "code": used}).status_code == 400
    monkeypatch.setattr(signin, "time", SimpleNamespace(time=lambda: (now + 2) * 30 + 1))
    fresh = signin.totp_code(secret, now + 2)
    ok(c.post("/api/auth/login/code", json={"challenge": step["challenge"], "code": fresh}))
    assert c.get("/api/account/settings").status_code == 200
    assert ok(here.get("/api/account/sign-ins"))[0]["method"] == "app"

    again = TestClient(main.app)                            # the same code a second time: refused
    step = ok(login(name, client=again))
    assert again.post("/api/auth/login/code", json={"challenge": step["challenge"], "code": fresh}).status_code == 400


def test_a_recovery_code_works_once(account, notices):
    name, here = account
    _, codes = turn_on_app(here)

    c = TestClient(main.app)
    step = ok(login(name, client=c))
    ok(c.post("/api/auth/login/code", json={"challenge": step["challenge"], "code": codes[0].upper()}))
    assert c.get("/api/account/settings").status_code == 200
    assert ok(here.get("/api/account/two-step"))["recovery_codes"] == 9
    assert any(subject == "A recovery code was used" for _, subject, _ in notices)

    again = TestClient(main.app)
    step = ok(login(name, client=again))
    assert again.post("/api/auth/login/code", json={"challenge": step["challenge"], "code": codes[0]}).status_code == 400
    ok(again.post("/api/auth/login/code", json={"challenge": step["challenge"], "code": codes[1]}))

    # Only hashes are stored.
    db = main.get_db()
    try:
        stored = [r["code_hash"] for r in db.execute("SELECT code_hash FROM recovery_codes WHERE user_id = ?", (user_id(name),))]
    finally:
        db.close()
    assert len(stored) == 10 and not any(code.replace("-", "") in "".join(stored) for code in codes)

    # New codes need the password, and replace the old ones.
    assert here.post("/api/account/recovery-codes", json={"password": "wrong-password-x"}).status_code == 400
    new = ok(here.post("/api/account/recovery-codes", json={"password": PASSWORD}))["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(codes)
    last = TestClient(main.app)
    step = ok(login(name, client=last))
    assert last.post("/api/auth/login/code", json={"challenge": step["challenge"], "code": codes[2]}).status_code == 400

    ok(here.post("/api/account/two-step/off", json={"password": PASSWORD}))
    assert ok(here.get("/api/account/two-step"))["recovery_codes"] == 0
    assert "two_step" not in ok(login(name))


def test_one_account_cannot_use_anothers_recovery_code(account, admin, notices):
    name, here = account
    _, codes = turn_on_app(here)
    other = "b-" + uuid.uuid4().hex[:8]
    ok(admin.post("/api/users", json={"username": other, "password": PASSWORD}), 201)
    theirs = TestClient(main.app)
    ok(login(other, client=theirs))
    turn_on_app(theirs)
    c = TestClient(main.app)
    step = ok(login(other, client=c))
    assert c.post("/api/auth/login/code", json={"challenge": step["challenge"], "code": codes[0]}).status_code == 400
