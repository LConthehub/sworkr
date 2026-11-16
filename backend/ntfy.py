"""
Push notifications to your phone with ntfy (https://ntfy.sh): a free app that shows a message when a server
tells it to. sworkr sends two kinds, both optional:

- a heads-up before a booking (or health test): "A booking starts at 7:00 PM";
- a daily summary at the hour you pick: "2 bookings today, 1 deposit to collect, 1 post to put up", sent only
  on days there's something to say.

Privacy first. A notification passes through the ntfy server (the public one at ntfy.sh, or your own), so:
- the wording is generic unless you tick "include names": no client or place is named by default;
- on the public server the topic (the name your phone listens to) must be long and random, since anyone who
  knows a topic can read it; sworkr refuses a short one and the settings page makes a good one for you;
- an access token (for a server that needs one) is stored sealed, never sent back to the page, and never sent
  to a different server than the one it was saved for;
- sworkr never sends anything in the demo.

Each notification is sent once: what was sent is remembered (ntfy_sent), so a restart doesn't repeat it.
"""

import ipaddress
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import vault

log = logging.getLogger("sworkr.ntfy")
router = APIRouter(prefix="/api/ntfy")
_get_db: Optional[Callable] = None

PUBLIC_SERVER = "https://ntfy.sh"
TIMEOUT = 10
MIN_PUBLIC_TOPIC = 16          # characters, on the public server
DEFAULT_LEAD = 60              # minutes before a booking
DEFAULT_DIGEST_HOUR = 9
LEADS = (0, 15, 30, 60, 120, 240)


class NtfyError(Exception):
    pass


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _demo() -> bool:
    import demo
    return demo.ENABLED


# ==================== SETTINGS ====================

def _get(db, user_id: int, key: str) -> Optional[str]:
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return vault.unseal(key, row["value"]) if row else None


def _set(db, user_id: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, vault.seal(key, value)))


def _int(value: Optional[str], default: Optional[int]) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def load_settings(db, user_id: int) -> dict:
    digest = _get(db, user_id, "ntfy_digest_hour")
    return {
        "enabled": _get(db, user_id, "ntfy_enabled") == "1",
        "server": _get(db, user_id, "ntfy_server") or PUBLIC_SERVER,
        "topic": _get(db, user_id, "ntfy_topic") or "",
        "token": _get(db, user_id, "ntfy_token"),
        "lead_minutes": _int(_get(db, user_id, "ntfy_lead"), DEFAULT_LEAD),
        "digest_hour": None if digest == "off" else _int(digest, DEFAULT_DIGEST_HOUR),
        "details": _get(db, user_id, "ntfy_details") == "1",
        "timezone": _get(db, user_id, "ntfy_timezone") or "UTC",
    }


def _public(s: dict) -> dict:
    out = {k: v for k, v in s.items() if k != "token"}
    out["has_token"] = bool(s.get("token"))
    out["demo"] = _demo()
    out["public_server"] = _host(s["server"]) == "ntfy.sh"
    return out


def _host(server: str) -> str:
    return (urlsplit(server).hostname or "").lower()


def _is_local_host(host: str) -> bool:
    """A server on this computer or home network, where plain http is fine."""
    if host in ("localhost", "") or host.endswith((".local", ".lan", ".home", ".internal", ".localdomain")) or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def clean_server(raw: str) -> str:
    server = (raw or "").strip().rstrip("/") or PUBLIC_SERVER
    if "://" not in server:
        server = "https://" + server
    parts = urlsplit(server)
    try:
        parts.port   # a port that isn't a number raises
        host_ok = bool(parts.hostname) and re.fullmatch(r"[a-z0-9.\-]+|[0-9a-f:]+", parts.hostname.lower()) is not None
    except ValueError:
        host_ok = False
    if parts.scheme not in ("http", "https") or not host_ok or parts.username or parts.password or parts.query or parts.fragment:
        raise HTTPException(status_code=400, detail="The server is an address like https://ntfy.sh")
    if parts.scheme == "http" and not _is_local_host(parts.hostname.lower()):
        raise HTTPException(status_code=400, detail="A server on the internet has to use https, so nobody can read your notifications on the way")
    return f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/")


def clean_topic(topic: str, server: str) -> str:
    topic = (topic or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
        raise HTTPException(status_code=400, detail="A topic is letters, numbers, - and _ (up to 64)")
    if _host(server) == "ntfy.sh" and len(topic) < MIN_PUBLIC_TOPIC:
        raise HTTPException(status_code=400, detail=f"On the public server anyone who guesses your topic can read it. Use at least {MIN_PUBLIC_TOPIC} "
                                                    "random characters (the Make one button does it), or run your own ntfy server")
    return topic


def clean_timezone(name: Optional[str]) -> str:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(name or "UTC")
        return name or "UTC"
    except Exception:
        return "UTC"


class NtfyIn(BaseModel):
    enabled: bool = False
    server: str = PUBLIC_SERVER
    topic: str = ""
    token: Optional[str] = None          # blank or missing: keep the saved one
    clear_token: bool = False
    lead_minutes: int = DEFAULT_LEAD     # 0: no heads-up before bookings
    digest_hour: Optional[int] = DEFAULT_DIGEST_HOUR   # None: no daily summary
    details: bool = False                # name clients in the messages
    timezone: str = "UTC"                # the browser's, so "9 am" means 9 am where you are


@router.get("/settings")
def get_settings(request: Request):
    db = _get_db()
    try:
        return _public(load_settings(db, request.state.user["id"]))
    finally:
        db.close()


@router.put("/settings")
def save_settings(body: NtfyIn, request: Request):
    if _demo():
        raise HTTPException(status_code=403, detail="Notifications are turned off in the demo. Never enter real details in a demo.")
    server = clean_server(body.server)
    if body.lead_minutes not in LEADS:
        raise HTTPException(status_code=400, detail="Pick how long before a booking from the list")
    if body.digest_hour is not None and not (0 <= body.digest_hour <= 23):
        raise HTTPException(status_code=400, detail="The daily summary hour is 0 to 23")
    topic = clean_topic(body.topic, server) if (body.topic or body.enabled) else ""
    if body.enabled and not topic:
        raise HTTPException(status_code=400, detail="Choose a topic first")
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        saved = load_settings(db, user_id)
        typed = (body.token or "").strip()
        if body.clear_token:
            token = None
        elif typed:
            token = typed[:300]
        elif saved["token"] and _host(saved["server"]) != _host(server):
            # A saved token only ever goes back to the server it was saved for, or anyone logged in could point
            # this at their own server and have sworkr send them the token.
            raise HTTPException(status_code=400, detail="The server changed, so enter the access token again")
        else:
            token = saved["token"]
        values = {"enabled": "1" if body.enabled else "0", "server": server, "topic": topic, "token": token,
                  "lead": str(body.lead_minutes), "digest_hour": "off" if body.digest_hour is None else str(body.digest_hour),
                  "details": "1" if body.details else "0", "timezone": clean_timezone(body.timezone)}
        for key, value in values.items():
            _set(db, user_id, f"ntfy_{key}", value)
        db.commit()
        return _public(load_settings(db, user_id))
    finally:
        db.close()


# ==================== SENDING ====================

def publish(settings: dict, title: str, message: str, priority: int = 3, tags: Optional[List[str]] = None) -> None:
    """Send one notification. Raises NtfyError with something a person can act on."""
    headers = {"Content-Type": "application/json"}
    if settings.get("token"):
        headers["Authorization"] = f"Bearer {settings['token']}"
    payload = {"topic": settings["topic"], "title": title, "message": message, "priority": priority, "tags": tags or []}
    try:
        r = httpx.post(settings["server"], content=json.dumps(payload), headers=headers, timeout=TIMEOUT, follow_redirects=False)
    except httpx.HTTPError as e:
        raise NtfyError(f"Couldn't reach {_host(settings['server'])}: {type(e).__name__}") from e
    if r.status_code in (401, 403):
        raise NtfyError("The server turned it down: it needs an access token, or the one saved isn't allowed to use this topic")
    if r.status_code == 429:
        raise NtfyError("The server says you're sending too many; try again later")
    if r.status_code >= 300:
        raise NtfyError(f"The server answered {r.status_code}")


@router.post("/test")
def send_test(request: Request):
    """Send a test to the saved settings."""
    if _demo():
        raise HTTPException(status_code=403, detail="Notifications are turned off in the demo.")
    db = _get_db()
    try:
        s = load_settings(db, request.state.user["id"])
    finally:
        db.close()
    if not s["topic"]:
        raise HTTPException(status_code=400, detail="Save a topic first")
    try:
        publish(s, "Sworkr", "This is a test. If you can read it, notifications work.", tags=["white_check_mark"])
    except NtfyError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True}


# ==================== WHAT TO SAY, AND WHEN ====================

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _local_time(dt: datetime, tz) -> str:
    return dt.astimezone(tz).strftime("%I:%M %p").lstrip("0")


def digest_lines(db, owner: int, tz, now: datetime, details: bool) -> List[str]:
    """What today holds, one short line each, only for what there's something to say about."""
    import healthtests
    import listings
    import noshow
    local = now.astimezone(tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = _iso(day_start), _iso(day_start + timedelta(days=1))
    today = local.date().isoformat()
    lines: List[str] = []

    booked = db.execute("""
        SELECT a.scheduled_date, a.kind, a.service_type, c.display_name FROM appointments a LEFT JOIN clients c ON c.id = a.client_id
        WHERE a.owner_id = ? AND a.status = 'scheduled' AND a.scheduled_date >= ? AND a.scheduled_date < ? ORDER BY a.scheduled_date
    """, (owner, start, end)).fetchall()
    bookings = [b for b in booked if b["kind"] == "client"]
    if bookings:
        who = ""
        if details:
            who = ": " + ", ".join(f"{b['display_name'] or 'Booking'} {_local_time(datetime.fromisoformat(b['scheduled_date']), tz)}" for b in bookings[:5])
        lines.append(f"{_plural(len(bookings), 'booking')} today{who}")
    n = db.execute("SELECT COUNT(*) FROM tasks WHERE owner_id = ? AND done_at IS NULL AND due_date IS NOT NULL AND due_date <= ?", (owner, today)).fetchone()[0]
    if n:
        lines.append(f"{_plural(n, 'task')} due")
    n = db.execute("SELECT COUNT(*) FROM posts WHERE owner_id = ? AND status IN ('ready', 'scheduled') AND scheduled_at IS NOT NULL AND scheduled_at < ?", (owner, end)).fetchone()[0]
    if n:
        lines.append(f"{_plural(n, 'post')} to put up")
    percent = noshow.policy(db, owner)["deposit_percent"]
    if percent > 0:
        n = db.execute("SELECT COUNT(*) FROM appointments WHERE owner_id = ? AND kind = 'client' AND status = 'scheduled' AND scheduled_date >= ? "
                       "AND rate > 0 AND amount_paid + 0.005 < rate * ? / 100", (owner, _iso(now), percent)).fetchone()[0]
        if n:
            lines.append(f"{_plural(n, 'deposit')} to collect")
    n = sum(1 for k in healthtests.kinds(db, owner) if k["state"] in ("overdue", "soon"))
    if n:
        lines.append(f"{_plural(n, 'health test')} due")
    n = db.execute("SELECT COUNT(*) FROM listings WHERE owner_id = ? AND paused = 0 AND end_date IS NOT NULL AND end_date <= ?",
                   (owner, (local.date() + timedelta(days=listings.SOON_DAYS)).isoformat())).fetchone()[0]
    if n:
        lines.append(f"{_plural(n, 'ad')} running out")
    n = db.execute("SELECT COUNT(*) FROM inquiries WHERE owner_id = ? AND stage = 'new'", (owner,)).fetchone()[0]
    if n:
        lines.append(f"{_plural(n, 'inquiry', 'inquiries')} to answer")
    n = db.execute("SELECT COUNT(*) FROM custom_orders WHERE owner_id = ? AND status IN ('requested', 'quoted', 'to_make') AND due_date IS NOT NULL AND due_date < ?", (owner, today)).fetchone()[0]
    if n:
        lines.append(f"{_plural(n, 'custom')} late")
    n = db.execute("SELECT COUNT(*) FROM shoots WHERE owner_id = ? AND status IN ('idea', 'planning', 'booked') AND shoot_date BETWEEN ? AND ?",
                   (owner, today, (local.date() + timedelta(days=3)).isoformat())).fetchone()[0]
    if n:
        lines.append(f"{_plural(n, 'shoot')} in the next 3 days")
    n = db.execute("SELECT COUNT(*) FROM documents WHERE owner_id = ? AND expires_on IS NOT NULL AND expires_on <= ?",
                   (owner, (local.date() + timedelta(days=14)).isoformat())).fetchone()[0]
    if n:
        lines.append(f"{_plural(n, 'document')} running out soon")
    return lines


def _sent(db, owner: int, key: str) -> bool:
    return db.execute("SELECT 1 FROM ntfy_sent WHERE owner_id = ? AND key = ?", (owner, key)).fetchone() is not None


def _remember(db, owner: int, key: str, now: datetime):
    db.execute("INSERT OR IGNORE INTO ntfy_sent (owner_id, key, sent_at) VALUES (?, ?, ?)", (owner, key, _iso(now)))
    db.commit()


def run_for(db, owner: int, s: dict, now: datetime) -> int:
    """Send this person's notifications that are due at `now`. Returns how many were sent."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(clean_timezone(s["timezone"]))
    sent = 0

    if s["lead_minutes"]:
        rows = db.execute("""
            SELECT a.id, a.scheduled_date, a.kind, a.service_type, c.display_name FROM appointments a LEFT JOIN clients c ON c.id = a.client_id
            WHERE a.owner_id = ? AND a.status = 'scheduled' AND a.scheduled_date > ? AND a.scheduled_date <= ? ORDER BY a.scheduled_date
        """, (owner, _iso(now), _iso(now + timedelta(minutes=s["lead_minutes"])))).fetchall()
        for r in rows:
            key = f"appt:{r['id']}:{r['scheduled_date']}"
            if _sent(db, owner, key):
                continue
            when = _local_time(datetime.fromisoformat(r["scheduled_date"]), tz)
            if r["kind"] == "test":
                text = f"A health test at {when}"
            elif s["details"]:
                text = f"{r['display_name'] or 'A booking'} at {when}" + (f", {r['service_type']}" if r["service_type"] else "")
            else:
                text = f"A booking starts at {when}"
            try:
                publish(s, "Coming up", text, tags=["calendar"])
            except NtfyError as e:
                log.warning("ntfy: %s", e)
                return sent                      # the server's down or refusing: try again next minute
            _remember(db, owner, key, now)
            sent += 1

    if s["digest_hour"] is not None:
        local = now.astimezone(tz)
        key = f"digest:{local.date().isoformat()}"
        if local.hour >= s["digest_hour"] and not _sent(db, owner, key):
            lines = digest_lines(db, owner, tz, now, s["details"])
            if lines:
                try:
                    publish(s, "Today", "\n".join(lines), tags=["sunrise"])
                except NtfyError as e:
                    log.warning("ntfy: %s", e)
                    return sent
                sent += 1
            _remember(db, owner, key, now)       # nothing to say today is also done for today
    return sent


def run_once(get_db: Callable, now: Optional[datetime] = None, only: Optional[int] = None) -> int:
    """One pass over everyone who has notifications on (or just `only`, for tests)."""
    now = now or datetime.now(timezone.utc)
    db = get_db()
    try:
        db.execute("DELETE FROM ntfy_sent WHERE sent_at < ?", (_iso(now - timedelta(days=90)),))
        db.commit()
        owners = [r[0] for r in db.execute("SELECT user_id FROM user_settings WHERE key = 'ntfy_enabled' AND value = '1'")
                  if only is None or r[0] == only]
        total = 0
        for owner in owners:
            s = load_settings(db, owner)
            if s["enabled"] and s["topic"]:
                try:
                    total += run_for(db, owner, s, now)
                except Exception:
                    log.exception("ntfy: couldn't send for user %s", owner)
        return total
    finally:
        db.close()


def _worker():
    while True:
        time.sleep(60)
        if _demo():
            continue
        try:
            run_once(_get_db)
        except Exception:
            log.exception("ntfy: a pass failed")


def start(get_db: Callable, background: bool = True):
    global _get_db
    _get_db = get_db
    if background:
        threading.Thread(target=_worker, name="ntfy", daemon=True).start()
