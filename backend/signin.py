"""
Signing in more safely: passkeys, and two-step sign-in with an emailed code.

Two-step sign-in: after the right password, sworkr emails a 6-digit code and only signs you in once it's typed.
The code goes out through the email account you connected in Settings > Email (from your own address to
itself), or, if you haven't connected one, through the server's email (SMTP_* in .env) to an address you give.
Turning it on sends a first code, so it's only on once a code has actually arrived. Codes last 10 minutes and
allow 5 tries. The email doesn't say "sworkr", only "Sign-in code".

Passkeys: sign in with the phone or computer's own lock (face, fingerprint, PIN) instead of a password. A
passkey is tied to the web address it was made on (localhost and your public address each need their own),
and browsers only offer them on https or localhost. Signing in with a passkey skips the emailed code: a passkey
is already two things at once (the device, and your face, finger or PIN).

If email stops working, sign in with a passkey, or the admin runs:
    docker compose exec api python manage.py turn-off-two-step <username>
"""

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Callable, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

import auth

router = APIRouter()
_get_db: Optional[Callable] = None
_set_cookie: Optional[Callable] = None
CODE_MINUTES = 10
CODE_TRIES = 5
RESEND_SECONDS = 60
PASSKEY_MINUTES = 5


def setup(get_db: Callable, set_cookie: Callable):
    """set_cookie(response, token, request): main.py's session cookie."""
    global _get_db, _set_cookie
    _get_db = get_db
    _set_cookie = set_cookie


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _setting(db, user_id: int, key: str) -> Optional[str]:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return r["value"] if r else None


def _set(db, user_id: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, value))


def _demo() -> bool:
    import demo
    return demo.ENABLED


def _user_out(u) -> dict:
    return {"id": u["id"], "username": u["username"], "is_admin": bool(u["is_admin"])}


# ==================== CHALLENGES (short-lived, single use) ====================

def _new_challenge(db, kind: str, user_id: Optional[int], secret: str, data: Optional[dict], minutes: int) -> str:
    db.execute("DELETE FROM auth_challenges WHERE expires_at < ?", (_iso(_now()),))
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO auth_challenges (token_hash, kind, user_id, secret, data, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
               (_hash(token), kind, user_id, secret, json.dumps(data) if data else None, _iso(_now() + timedelta(minutes=minutes))))
    return token


def _challenge(db, token: Optional[str], kind: str) -> Optional[dict]:
    if not token:
        return None
    r = db.execute("SELECT * FROM auth_challenges WHERE token_hash = ? AND kind = ?", (_hash(token), kind)).fetchone()
    if not r:
        return None
    if r["expires_at"] < _iso(_now()):
        db.execute("DELETE FROM auth_challenges WHERE token_hash = ?", (r["token_hash"],))
        db.commit()
        return None
    out = dict(r)
    out["data"] = json.loads(r["data"]) if r["data"] else {}
    return out


def _drop(db, token: str):
    db.execute("DELETE FROM auth_challenges WHERE token_hash = ?", (_hash(token),))


# ==================== SENDING A CODE ====================

def _own_mail(db, user_id: int) -> Optional[dict]:
    """The person's connected email account, if it can send."""
    import mail
    s = mail.load_settings(db, user_id)
    if s.get("smtp_host") and s.get("username") and s.get("password") and s.get("from_address"):
        return s
    return None


def delivery(db, user_id: int) -> dict:
    """How a code would reach this person: {"via": "own" | "server" | None, "address": ...}."""
    if _demo():
        return {"via": None, "address": None}
    own = _own_mail(db, user_id)
    if own:
        return {"via": "own", "address": own["from_address"]}
    import safety
    if safety.smtp_configured():
        return {"via": "server", "address": _setting(db, user_id, "two_step_address")}
    return {"via": None, "address": None}


def mask(address: Optional[str]) -> Optional[str]:
    if not address or "@" not in address:
        return address
    name, domain = address.split("@", 1)
    return f"{name[:2]}{'•' * max(len(name) - 2, 1)}@{domain}"


def send_code(db, user_id: int, address: str, code: str):
    """Raises RuntimeError with a readable reason if it can't be sent."""
    subject = "Sign-in code"
    body = (f"Your sign-in code is {code}\n\nIt works for {CODE_MINUTES} minutes. If you didn't just try to sign in, "
            f"someone may know your password: change it.\n")
    own = _own_mail(db, user_id)
    if own and address == own["from_address"]:
        import mail
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = own["from_address"], address, subject
        msg.set_content(body)
        try:
            mail.send(own, msg)
        except mail.MailError as e:
            raise RuntimeError(str(e)) from e
        return
    import safety
    try:
        safety.send_email(address, subject, body)
    except Exception as e:   # noqa: BLE001 - shown to the person
        raise RuntimeError(f"The email couldn't be sent: {e}") from e


def _make_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def two_step_on(db, user_id: int) -> bool:
    return _setting(db, user_id, "two_step") == "1"


def start_login_code(db, user) -> dict:
    """After a correct password, for someone with two-step on: send a code, and return what the page needs."""
    d = delivery(db, user["id"])
    address = d["address"] if d["via"] == "own" else _setting(db, user["id"], "two_step_address")
    if not d["via"] or not address:
        raise HTTPException(status_code=503, detail="Your sign-in code can't be sent: email isn't working. Sign in with "
                            "a passkey, or ask whoever runs sworkr to turn two-step sign-in off for you.")
    code = _make_code()
    token = _new_challenge(db, "login_code", user["id"], "", {"address": address, "sent": _iso(_now())}, CODE_MINUTES)
    db.execute("UPDATE auth_challenges SET secret = ? WHERE token_hash = ?", (_hash(token + code), _hash(token)))
    try:
        send_code(db, user["id"], address, code)
    except RuntimeError as e:
        _drop(db, token)
        db.commit()
        raise HTTPException(status_code=503, detail=f"Your sign-in code couldn't be sent ({e}). Sign in with a passkey, "
                            "or ask whoever runs sworkr to turn two-step sign-in off for you.")
    db.commit()
    return {"two_step": True, "challenge": token, "sent_to": mask(address)}


def _check_code(db, token: str, kind: str, code: str) -> dict:
    c = _challenge(db, token, kind)
    if not c:
        raise HTTPException(status_code=400, detail="That code has run out. Start again.")
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if not secrets.compare_digest(c["secret"], _hash(token + code)):
        tries = c["attempts"] + 1
        if tries >= CODE_TRIES:
            _drop(db, token)
            db.commit()
            raise HTTPException(status_code=400, detail="Too many wrong codes. Start again.")
        db.execute("UPDATE auth_challenges SET attempts = ? WHERE token_hash = ?", (tries, _hash(token)))
        db.commit()
        raise HTTPException(status_code=400, detail=f"That code isn't right ({CODE_TRIES - tries} tries left)")
    _drop(db, token)
    return c


class CodeIn(BaseModel):
    challenge: str
    code: str


class ChallengeIn(BaseModel):
    challenge: str


@router.post("/api/auth/login/code")
def finish_login_code(body: CodeIn, request: Request, response: Response):
    db = _get_db()
    try:
        c = _check_code(db, body.challenge, "login_code", body.code)
        user = db.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (c["user_id"],)).fetchone()
        if not user:
            raise HTTPException(status_code=400, detail="That account no longer exists")
        _set_cookie(response, auth.create_session(db, user["id"]), request)
        db.commit()
        return _user_out(user)
    finally:
        db.close()


@router.post("/api/auth/login/code/resend")
def resend_login_code(body: ChallengeIn):
    """A new code for the same sign-in, at most once a minute. The old code stops working."""
    db = _get_db()
    try:
        c = _challenge(db, body.challenge, "login_code")
        if not c:
            raise HTTPException(status_code=400, detail="That sign-in has run out. Start again.")
        sent = datetime.fromisoformat(c["data"]["sent"])
        wait = RESEND_SECONDS - int((_now() - sent).total_seconds())
        if wait > 0:
            raise HTTPException(status_code=429, detail=f"Wait {wait} seconds before asking for another code")
        code = _make_code()
        try:
            send_code(db, c["user_id"], c["data"]["address"], code)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        db.execute("UPDATE auth_challenges SET secret = ?, attempts = 0, data = ?, expires_at = ? WHERE token_hash = ?",
                   (_hash(body.challenge + code), json.dumps({**c["data"], "sent": _iso(_now())}),
                    _iso(_now() + timedelta(minutes=CODE_MINUTES)), _hash(body.challenge)))
        db.commit()
        return {"sent_to": mask(c["data"]["address"])}
    finally:
        db.close()


# ==================== TURNING TWO-STEP ON AND OFF ====================

class TwoStepStart(BaseModel):
    address: Optional[str] = None     # only when sending through the server's email


class PasswordIn(BaseModel):
    password: str


@router.get("/api/account/two-step")
def two_step_status(request: Request):
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        d = delivery(db, user_id)
        address = d["address"] if d["via"] == "own" else _setting(db, user_id, "two_step_address")
        return {"enabled": two_step_on(db, user_id), "via": d["via"], "address": mask(address) if two_step_on(db, user_id) else address,
                "passkeys": db.execute("SELECT COUNT(*) FROM passkeys WHERE user_id = ?", (user_id,)).fetchone()[0]}
    finally:
        db.close()


@router.post("/api/account/two-step/start")
def two_step_start(body: TwoStepStart, request: Request):
    """Send a first code, to make sure codes arrive before two-step is switched on."""
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        d = delivery(db, user_id)
        if not d["via"]:
            raise HTTPException(status_code=400, detail="Connect your email in Settings > Connections first, so sworkr can send you codes")
        address = d["address"] if d["via"] == "own" else (body.address or "").strip()
        if "@" not in (address or "") or len(address) > 200:
            raise HTTPException(status_code=400, detail="Enter the email address to send codes to")
        code = _make_code()
        token = _new_challenge(db, "setup_code", user_id, "", {"address": address}, CODE_MINUTES)
        db.execute("UPDATE auth_challenges SET secret = ? WHERE token_hash = ?", (_hash(token + code), _hash(token)))
        try:
            send_code(db, user_id, address, code)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        db.commit()
        return {"challenge": token, "sent_to": address}
    finally:
        db.close()


@router.post("/api/account/two-step/confirm")
def two_step_confirm(body: CodeIn, request: Request):
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        c = _check_code(db, body.challenge, "setup_code", body.code)
        if c["user_id"] != user_id:
            raise HTTPException(status_code=400, detail="That code is for someone else")
        _set(db, user_id, "two_step", "1")
        _set(db, user_id, "two_step_address", c["data"]["address"])
        db.commit()
        return {"enabled": True}
    finally:
        db.close()


@router.post("/api/account/two-step/off")
def two_step_off(body: PasswordIn, request: Request):
    user = request.state.user
    db = _get_db()
    try:
        if not auth.check_login(db, user["username"], body.password):
            raise HTTPException(status_code=400, detail="That password isn't right")
        _set(db, user["id"], "two_step", "0")
        db.commit()
        return {"enabled": False}
    finally:
        db.close()


# ==================== PASSKEYS ====================

def _origin(request: Request):
    """The page's own address (the browser sends it). Changes are only accepted from sworkr's own pages (see
    security_guard in main.py), so it's sworkr's address as the visitor sees it. PASSKEY_ORIGINS (comma
    separated) can limit it further."""
    origin = (request.headers.get("origin") or "").rstrip("/")
    host = urlsplit(origin).hostname if origin else None
    if not host:
        raise HTTPException(status_code=400, detail="Passkeys need a browser")
    allowed = [o.strip().rstrip("/") for o in os.environ.get("PASSKEY_ORIGINS", "").split(",") if o.strip()]
    if allowed and origin not in allowed:
        raise HTTPException(status_code=400, detail="Passkeys aren't allowed on this address")
    return host, origin


def _user_handle(db, user_id: int) -> bytes:
    """A random id for this account that passkeys carry (not the username or the database number)."""
    handle = _setting(db, user_id, "webauthn_handle")
    if not handle:
        handle = secrets.token_hex(16)
        _set(db, user_id, "webauthn_handle", handle)
    return bytes.fromhex(handle)


class PasskeyFinish(BaseModel):
    challenge: str
    credential: dict
    name: Optional[str] = None


@router.get("/api/account/passkeys")
def list_passkeys(request: Request):
    db = _get_db()
    try:
        return [dict(r) for r in db.execute(
            "SELECT id, name, rp_id, created_at, last_used_at FROM passkeys WHERE user_id = ? ORDER BY created_at",
            (request.state.user["id"],))]
    finally:
        db.close()


@router.post("/api/account/passkeys/begin")
def passkey_register_begin(request: Request):
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                          ResidentKeyRequirement, UserVerificationRequirement)
    if _demo():
        raise HTTPException(status_code=403, detail="Passkeys are turned off in the demo: everyone shares its login")
    rp_id, _ = _origin(request)
    user = request.state.user
    db = _get_db()
    try:
        existing = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(r["credential_id"]))
                    for r in db.execute("SELECT credential_id FROM passkeys WHERE user_id = ? AND rp_id = ?", (user["id"], rp_id))]
        options = generate_registration_options(
            rp_id=rp_id, rp_name="sworkr", user_id=_user_handle(db, user["id"]), user_name=user["username"],
            user_display_name=user["username"], exclude_credentials=existing,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED))
        token = _new_challenge(db, "passkey_add", user["id"], options.challenge.hex(), None, PASSKEY_MINUTES)
        db.commit()
        return {"challenge": token, "options": json.loads(options_to_json(options))}
    finally:
        db.close()


@router.post("/api/account/passkeys/finish", status_code=201)
def passkey_register_finish(body: PasskeyFinish, request: Request):
    from webauthn import verify_registration_response
    from webauthn.helpers import bytes_to_base64url
    rp_id, origin = _origin(request)
    user = request.state.user
    db = _get_db()
    try:
        c = _challenge(db, body.challenge, "passkey_add")
        if not c or c["user_id"] != user["id"]:
            raise HTTPException(status_code=400, detail="That took too long. Try again.")
        _drop(db, body.challenge)
        try:
            v = verify_registration_response(credential=body.credential, expected_challenge=bytes.fromhex(c["secret"]),
                                             expected_rp_id=rp_id, expected_origin=origin, require_user_verification=True)
        except Exception as e:   # noqa: BLE001 - the library raises several kinds
            db.commit()
            raise HTTPException(status_code=400, detail=f"The passkey couldn't be checked: {e}")
        name = (body.name or "").strip()[:60] or "Passkey"
        transports = body.credential.get("response", {}).get("transports")
        db.execute("INSERT INTO passkeys (user_id, credential_id, public_key, sign_count, transports, rp_id, name, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (user["id"], bytes_to_base64url(v.credential_id), bytes_to_base64url(v.credential_public_key),
                    v.sign_count, json.dumps(transports) if transports else None, rp_id, name, _iso(_now())))
        db.commit()
        return {"name": name}
    finally:
        db.close()


@router.delete("/api/account/passkeys/{passkey_id}", status_code=204)
def delete_passkey(passkey_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM passkeys WHERE id = ? AND user_id = ?", (passkey_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


@router.post("/api/auth/passkey/begin")
def passkey_login_begin(request: Request):
    """Sign in with a passkey: no username needed, the browser offers the passkeys it has for this address."""
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import UserVerificationRequirement
    rp_id, _ = _origin(request)
    db = _get_db()
    try:
        options = generate_authentication_options(rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED)
        token = _new_challenge(db, "passkey_login", None, options.challenge.hex(), None, PASSKEY_MINUTES)
        db.commit()
        return {"challenge": token, "options": json.loads(options_to_json(options))}
    finally:
        db.close()


@router.post("/api/auth/passkey/finish")
def passkey_login_finish(body: PasskeyFinish, request: Request, response: Response):
    from webauthn import verify_authentication_response
    from webauthn.helpers import base64url_to_bytes
    rp_id, origin = _origin(request)
    db = _get_db()
    try:
        c = _challenge(db, body.challenge, "passkey_login")
        if not c:
            raise HTTPException(status_code=400, detail="That took too long. Try again.")
        _drop(db, body.challenge)
        db.commit()
        key = db.execute("SELECT * FROM passkeys WHERE credential_id = ? AND rp_id = ?",
                         (str(body.credential.get("id") or ""), rp_id)).fetchone()
        if not key:
            raise HTTPException(status_code=400, detail="sworkr doesn't know that passkey. Sign in with your password, "
                                "then add this passkey in Settings > Security & privacy.")
        try:
            v = verify_authentication_response(
                credential=body.credential, expected_challenge=bytes.fromhex(c["secret"]), expected_rp_id=rp_id,
                expected_origin=origin, credential_public_key=base64url_to_bytes(key["public_key"]),
                credential_current_sign_count=key["sign_count"], require_user_verification=True)
        except Exception as e:   # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"The passkey couldn't be checked: {e}")
        user = db.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (key["user_id"],)).fetchone()
        db.execute("UPDATE passkeys SET sign_count = ?, last_used_at = ? WHERE id = ?", (v.new_sign_count, _iso(_now()), key["id"]))
        _set_cookie(response, auth.create_session(db, user["id"]), request)
        db.commit()
        return _user_out(user)
    finally:
        db.close()
