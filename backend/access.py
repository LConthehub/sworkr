"""
Who is signed in, and from where.

- Every sign-in is recorded (and failed ones for a real account): when, how (password, emailed or app code,
  passkey, recovery code), the address it came from and the browser. The person sees the last of them on
  their settings page. Entries older than 90 days are dropped.
- Signed-in devices are listed, and any of them can be logged out from another.
- A sign-in from a browser this account hasn't used before sends an email ("New sign-in"), if sworkr has a
  way to email the person. Browsers are told apart by a random cookie, not by anything about the device.
- "Passkeys only away from home": the password stops working for requests that come in from the internet;
  only a passkey signs in there. The password keeps working on the computer sworkr runs on and on the home
  network, so losing a phone never locks anyone out.

"From the internet" is worked out from the addresses the request passed through (X-Forwarded-For, written by
the reverse proxies in front of sworkr). If every one of them is a private or loopback address, the request is
local. A proxy that doesn't pass the visitor's address on would make everyone look local, so the settings page
shows what sworkr sees for the current visit.
"""

import hashlib
import ipaddress
import logging
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

import auth

log = logging.getLogger("sworkr.access")
router = APIRouter()
_get_db: Optional[Callable] = None

DEVICE_COOKIE = "sworkr_device"
DEVICE_DAYS = 400
KEEP_EVENTS_DAYS = 90
KEEP_EVENTS = 200          # per account
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

# Send cookies only over HTTPS. COOKIE_SECURE=1 forces it; otherwise it's on whenever the request came
# in over HTTPS through a reverse proxy (Caddy, nginx) that says so in X-Forwarded-Proto.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

# Loopback, home and office networks, link-local, and the range private-network tools (Tailscale) use.
_LOCAL_NETS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10",
    "::1/128", "fc00::/7", "fe80::/10")]


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _setting(db, user_id: int, key: str) -> Optional[str]:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return r["value"] if r else None


def _set(db, user_id: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, value))


# ==================== WHERE A REQUEST CAME FROM ====================

def is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return COOKIE_SECURE or request.url.scheme == "https" or forwarded == "https"


def _ip(text: str):
    try:
        ip = ipaddress.ip_address(text.strip().strip("[]"))
    except ValueError:
        return None
    return getattr(ip, "ipv4_mapped", None) or ip


def _is_local_ip(ip) -> bool:
    return any(ip.version == net.version and ip in net for net in _LOCAL_NETS)


def _hops(request: Request) -> List[str]:
    """The addresses the request passed through, visitor first: X-Forwarded-For, then whoever connected to us."""
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    peer = request.client.host if request.client else ""
    # Something that isn't an address (a unix socket, the test client) says nothing when a proxy has spoken.
    if peer and (_ip(peer) or not hops):
        hops.append(peer)
    return hops


def client_ip(request: Request) -> str:
    """The visitor's address. Each proxy adds the address it heard from on the right, so the visitor is the
    first public address counting from the right: anything further left was typed by the visitor and can't be
    trusted. When no address is public (at home), it's the leftmost one."""
    hops = _hops(request)
    for hop in reversed(hops):
        ip = _ip(hop)
        if ip and not _is_local_ip(ip):
            return str(ip)
    return hops[0] if hops else "unknown"


def is_local(request: Request) -> bool:
    """True when the request never crossed the internet: every address it passed through is private or loopback."""
    hops = _hops(request)
    return bool(hops) and all((ip := _ip(h)) is not None and _is_local_ip(ip) for h in hops)


def describe_device(user_agent: Optional[str]) -> str:
    """'Safari on iPhone' from a browser's user-agent line. A rough label for the person to recognise, no more."""
    ua = user_agent or ""
    if not ua:
        return "Unknown device"
    system = next((name for mark, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                                           ("Windows", "Windows"), ("Macintosh", "Mac"), ("CrOS", "Chromebook"),
                                           ("Linux", "Linux")) if mark in ua), None)
    browser = next((name for mark, name in (("Edg", "Edge"), ("OPR", "Opera"), ("Firefox", "Firefox"), ("FxiOS", "Firefox"),
                                            ("CriOS", "Chrome"), ("Chrome", "Chrome"), ("Safari", "Safari"))
                    if mark in ua), None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or "Unknown device"


# ==================== SIGNING IN ====================

def _device(request: Request, response: Optional[Response]) -> str:
    """This browser's random id (a cookie), as a hash. A new one is set when the browser has none."""
    token = request.cookies.get(DEVICE_COOKIE)
    if not token or len(token) > 100:
        token = secrets.token_urlsafe(24)
    if response is not None:
        response.set_cookie(DEVICE_COOKIE, token, max_age=DEVICE_DAYS * 86400, httponly=True, samesite="lax",
                            secure=is_https(request), path="/")
    return hashlib.sha256(token.encode()).hexdigest()


def record(db, user_id: int, outcome: str, method: Optional[str], request: Request, device_hash: Optional[str] = None):
    """Note a sign-in or a failed try for a real account. The caller commits."""
    db.execute("INSERT INTO signin_events (user_id, outcome, method, ip, user_agent, device_hash, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (user_id, outcome, method, client_ip(request), (request.headers.get("user-agent") or "")[:300] or None,
                device_hash, _now()))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_EVENTS_DAYS)).isoformat(timespec="seconds")
    db.execute("DELETE FROM signin_events WHERE user_id = ? AND (at < ? OR id NOT IN "
               "(SELECT id FROM signin_events WHERE user_id = ? ORDER BY id DESC LIMIT ?))",
               (user_id, cutoff, user_id, KEEP_EVENTS))


def set_session_cookie(response: Response, token: str, request: Request):
    response.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=is_https(request), path="/")


def sign_in(db, user_id: int, request: Request, response: Response, method: str):
    """Open a session for someone who has just proved who they are: set the cookies, note the sign-in, and
    email them if this browser is new to their account. Commits."""
    device = _device(request, response)
    seen_before = db.execute("SELECT 1 FROM signin_events WHERE user_id = ? AND outcome = 'ok' LIMIT 1", (user_id,)).fetchone()
    known = db.execute("SELECT 1 FROM signin_events WHERE user_id = ? AND outcome = 'ok' AND device_hash = ? LIMIT 1",
                       (user_id, device)).fetchone()
    ip, user_agent = client_ip(request), request.headers.get("user-agent")
    token = auth.create_session(db, user_id, method=method, ip=ip, user_agent=user_agent, device_hash=device)
    record(db, user_id, "ok", method, request, device)
    db.commit()
    set_session_cookie(response, token, request)
    # The very first sign-in an account ever makes isn't news; a browser it has never used, after that, is.
    if seen_before and not known and _setting(db, user_id, "signin_alerts") != "0":
        notify(user_id, "New sign-in",
               "Your account was just signed in to from a browser it hasn't used before.\n\n"
               f"Device: {describe_device(user_agent)}\nAddress: {ip}\n\n"
               "If that was you, there's nothing to do. If it wasn't: change your password, then log out the other "
               "devices under Settings > Security & privacy.\n")


def password_blocked(db, user_id: int, request: Request) -> bool:
    """Passkeys only away from home: is a password sign-in for this account refused for this request?"""
    return _setting(db, user_id, "passkey_only_remote") == "1" and not is_local(request)


def passkey_hint(db, request: Request) -> bool:
    """For the login page: passwords may not work from here, so point at the passkey button."""
    if is_local(request):
        return False
    return bool(db.execute("SELECT 1 FROM user_settings WHERE key = 'passkey_only_remote' AND value = '1' LIMIT 1").fetchone())


def remote_passkeys(db, user_id: int) -> int:
    """Passkeys that work on an address other than this computer's own (those are the ones usable away from home)."""
    marks = ", ".join("?" for _ in LOCAL_HOSTS)
    return db.execute(f"SELECT COUNT(*) FROM passkeys WHERE user_id = ? AND rp_id NOT IN ({marks})",
                      (user_id, *LOCAL_HOSTS)).fetchone()[0]


# ==================== EMAILING THE PERSON ====================

def alert_address(db, user_id: int) -> Optional[str]:
    """Where a notice for this person goes: their own connected email, or else the address their sign-in codes
    go to (through the server's email)."""
    import signin
    d = signin.delivery(db, user_id)
    if d["via"] == "own":
        return d["address"]
    if d["via"] == "server":
        return _setting(db, user_id, "two_step_address")
    return None


def send_notice(user_id: int, subject: str, body: str):
    """Email the person. Like sign-in codes, the email doesn't say "sworkr"."""
    import mail
    import safety
    import signin
    db = _get_db()
    try:
        address = alert_address(db, user_id)
        if not address:
            return
        own = signin.own_mail(db, user_id)
        if own and address == own["from_address"]:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = own["from_address"], address, subject
            msg.set_content(body)
            mail.send(own, msg)
        else:
            safety.send_email(address, subject, body)
    except Exception as e:   # noqa: BLE001 - a notice that can't be sent mustn't break signing in
        log.warning("A sign-in notice couldn't be sent: %s", e)
    finally:
        db.close()


def notify(user_id: int, subject: str, body: str):
    """send_notice, without making the person wait for the mail server."""
    threading.Thread(target=send_notice, args=(user_id, subject, body), daemon=True).start()


# ==================== API ====================

class AccessSettings(BaseModel):
    passkey_only: Optional[bool] = None
    alerts: Optional[bool] = None


def _status(db, user_id: int, request: Request) -> dict:
    address = alert_address(db, user_id)
    import signin
    return {
        "local": is_local(request),
        "ip": client_ip(request),
        "passkey_only": _setting(db, user_id, "passkey_only_remote") == "1",
        "remote_passkeys": remote_passkeys(db, user_id),
        "alerts": _setting(db, user_id, "signin_alerts") != "0",
        "alerts_address": signin.mask(address),
    }


@router.get("/api/account/access")
def get_access(request: Request):
    db = _get_db()
    try:
        return _status(db, request.state.user["id"], request)
    finally:
        db.close()


@router.put("/api/account/access")
def save_access(body: AccessSettings, request: Request):
    import demo
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        if body.passkey_only is not None:
            if demo.ENABLED:
                raise HTTPException(status_code=403, detail="This is turned off in the demo: everyone shares its login")
            if body.passkey_only and not remote_passkeys(db, user_id):
                raise HTTPException(status_code=400, detail="Add a passkey on your public address first (open sworkr there, "
                                    "then Settings > Security & privacy > Passkeys). Otherwise you couldn't sign in away from home.")
            _set(db, user_id, "passkey_only_remote", "1" if body.passkey_only else "0")
        if body.alerts is not None:
            _set(db, user_id, "signin_alerts", "1" if body.alerts else "0")
        db.commit()
        return _status(db, user_id, request)
    finally:
        db.close()


@router.get("/api/account/sessions")
def list_sessions(request: Request):
    """The devices signed in to this account, most recently used first."""
    current = auth._token_hash(request.cookies.get(auth.SESSION_COOKIE) or "")
    db = _get_db()
    try:
        now = _now()
        return [{"id": r["rowid"], "current": r["token_hash"] == current, "device": describe_device(r["user_agent"]),
                 "ip": r["ip"], "method": r["method"], "created_at": r["created_at"], "last_seen_at": r["last_seen_at"]}
                for r in db.execute("SELECT rowid, * FROM sessions WHERE user_id = ? AND expires_at > ? "
                                    "ORDER BY last_seen_at DESC", (request.state.user["id"], now))]
    finally:
        db.close()


@router.delete("/api/account/sessions/{session_id}", status_code=204)
def end_session(session_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM sessions WHERE rowid = ? AND user_id = ?", (session_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


@router.post("/api/account/sessions/log-out-others")
def log_out_others(request: Request):
    db = _get_db()
    try:
        before = db.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (request.state.user["id"],)).fetchone()[0]
        auth.delete_user_sessions(db, request.state.user["id"], keep_token=request.cookies.get(auth.SESSION_COOKIE))
        return {"logged_out": max(before - 1, 0)}
    finally:
        db.close()


@router.get("/api/account/sign-ins")
def list_sign_ins(request: Request):
    """Recent sign-ins and failed tries for this account, newest first."""
    db = _get_db()
    try:
        return [{"id": r["id"], "outcome": r["outcome"], "method": r["method"], "ip": r["ip"],
                 "device": describe_device(r["user_agent"]), "at": r["at"]}
                for r in db.execute("SELECT * FROM signin_events WHERE user_id = ? ORDER BY id DESC LIMIT 50",
                                    (request.state.user["id"],))]
    finally:
        db.close()
