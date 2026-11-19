"""
Safety check-in.

An appointment can be marked "check in afterwards". If its end time passes, plus a grace period,
and the user has not checked in (or marked it completed), an email goes to their trusted contact.

Limits worth knowing:
- The alert is sent by this computer. It only works while sworkr is running and online.
- It needs an email account to send from (the SMTP_* settings in .env). Without that, nothing is sent
  and the Account page says so.
- An alert that was missed because the computer was off is sent when it comes back, up to a day late.

Settings per user: who to alert, the grace period, whether to include the client's details, and a
short "what to do" message.
"""

import logging
import os
import smtplib
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

CHECK_EVERY = 60                  # seconds between looks for overdue check-ins
GIVE_UP_AFTER = timedelta(hours=24)
GRACE_CHOICES = (15, 30, 45, 60, 90, 120)
DEFAULT_GRACE = 30

log = logging.getLogger("sworkr.safety")
_get_db: Optional[Callable] = None


# ==================== EMAIL ====================

def smtp_config() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "port": int(os.environ.get("SMTP_PORT", "587") or 587),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "sender": (os.environ.get("SMTP_FROM", "") or os.environ.get("SMTP_USER", "")).strip(),
        "security": (os.environ.get("SMTP_SECURITY", "starttls") or "starttls").strip().lower(),
    }


def smtp_configured() -> bool:
    cfg = smtp_config()
    return bool(cfg["host"] and cfg["sender"])


def send_email(to: str, subject: str, body: str) -> None:
    cfg = smtp_config()
    if not (cfg["host"] and cfg["sender"]):
        raise RuntimeError("Email isn't set up (SMTP_HOST and SMTP_FROM in .env)")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["sender"], to, subject
    msg.set_content(body)
    context = ssl.create_default_context()
    if cfg["security"] == "ssl":
        server = smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30, context=context)
    else:
        server = smtplib.SMTP(cfg["host"], cfg["port"], timeout=30)
    try:
        if cfg["security"] == "starttls":
            server.starttls(context=context)
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


# ==================== SETTINGS ====================

def _get(db, user_id: int, key: str, default: Optional[str] = None) -> Optional[str]:
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return row[0] if row and row[0] is not None else default


def _put(db, user_id: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, value))


def settings_for(db, user_id: int) -> dict:
    try:
        grace = int(_get(db, user_id, "safety_grace_minutes", str(DEFAULT_GRACE)))
    except ValueError:
        grace = DEFAULT_GRACE
    contact_email = _get(db, user_id, "safety_contact_email", "")
    return {
        "contact_name": _get(db, user_id, "safety_contact_name", ""),
        "contact_email": contact_email,
        "grace_minutes": grace,
        "include_details": _get(db, user_id, "safety_details", "1") == "1",
        "instructions": _get(db, user_id, "safety_instructions", ""),
        "timezone": _get(db, user_id, "safety_timezone", "UTC"),
        "email_configured": smtp_configured(),
        # Alerts will really go out only when both of these are in place.
        "contact_push": _get(db, user_id, "safety_contact_push", ""),
        "armed": (bool(contact_email) and smtp_configured()) or bool(_get(db, user_id, "safety_contact_push", "")),
        "last_error": _get(db, user_id, "safety_last_error"),
        "grace_choices": list(GRACE_CHOICES),
    }


# ==================== FINDING OVERDUE CHECK-INS ====================

def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _local(dt: datetime, tz_name: str) -> str:
    try:
        from zoneinfo import ZoneInfo
        return dt.astimezone(ZoneInfo(tz_name)).strftime("%a %d %b %Y, %H:%M") + f" ({tz_name})"
    except Exception:
        return dt.astimezone(timezone.utc).strftime("%a %d %b %Y, %H:%M") + " (UTC)"


def watched_appointments(db, owner_id: Optional[int] = None, now: Optional[datetime] = None) -> List[dict]:
    """
    Appointments with check-in switched on that have started, aren't cancelled and haven't been
    checked in, from the last day. Each gets `ends_at` and `alert_at` (end + the owner's grace period).
    """
    now = now or datetime.now(timezone.utc)
    rows = db.execute(f"""
        SELECT a.*, c.display_name AS client_name, c.contact_phone AS client_phone, u.username
        FROM appointments a
        LEFT JOIN clients c ON a.client_id = c.id
        JOIN users u ON u.id = a.owner_id
        WHERE a.safety_checkin = 1 AND a.status != 'cancelled' AND a.checked_in_at IS NULL
          AND a.scheduled_date <= ? AND a.scheduled_date >= ?
          {"AND a.owner_id = ?" if owner_id is not None else ""}
        ORDER BY a.scheduled_date
    """, (now.isoformat(timespec="seconds"), (now - timedelta(days=8)).isoformat(timespec="seconds"),
          *([owner_id] if owner_id is not None else [])))
    out, grace_cache = [], {}
    for row in rows:
        appt = dict(row)
        owner = appt["owner_id"]
        if owner not in grace_cache:
            grace_cache[owner] = settings_for(db, owner)["grace_minutes"]
        ends = _parse(appt["scheduled_date"]) + timedelta(minutes=appt["duration_minutes"])
        if now - ends > GIVE_UP_AFTER:
            continue
        appt["ends_at"] = ends.isoformat(timespec="seconds")
        appt["alert_at"] = (ends + timedelta(minutes=grace_cache[owner])).isoformat(timespec="seconds")
        out.append(appt)
    return out


def alert_text(appt: dict, cfg: dict, now: datetime) -> tuple:
    tz = cfg["timezone"]
    start = _parse(appt["scheduled_date"])
    ends = _parse(appt["ends_at"])
    who = appt["username"]
    lines = [
        f"{who} asked to have you alerted if they did not check in after an appointment.",
        "",
        f"The appointment was due to end at {_local(ends, tz)}.",
        f"It is now {_local(now, tz)} and they have not checked in.",
        "",
        "Please try to reach them now.",
    ]
    if cfg["instructions"]:
        lines += ["", f"Their instructions: {cfg['instructions']}"]
    if cfg["include_details"]:
        lines += ["", "Appointment details:", f"  Started: {_local(start, tz)}"]
        if appt.get("client_name"):
            lines.append(f"  With: {appt['client_name']}" + (f" ({appt['client_phone']})" if appt.get("client_phone") else ""))
        where = " ".join(x for x in (appt.get("location_type"), appt.get("location")) if x)
        if where:
            lines.append(f"  Where: {where}")
        if appt.get("service_type"):
            lines.append(f"  Booking: {appt['service_type']}")
    lines += ["", "This message was sent automatically by their own copy of sworkr."]
    return f"Safety alert: {who} has not checked in", "\n".join(lines)


PUSH_TRANSPORT = None    # tests put a pretend ntfy here


def send_push(url: str, title: str, body: str) -> None:
    """A push to the trusted contact's phone: they subscribe to this ntfy address in the ntfy app."""
    import httpx
    with httpx.Client(timeout=20, transport=PUSH_TRANSPORT, follow_redirects=False) as http:
        r = http.post(url, content=body.encode(), headers={"Title": title.encode("ascii", "replace").decode(),
                                                           "Priority": "5", "Tags": "rotating_light"})
    if r.status_code >= 300:
        raise RuntimeError(f"The push server answered {r.status_code}")


def deliver(cfg: dict, subject: str, body: str) -> None:
    """Send by every way that's set up (push is seconds, email can be minutes). Fails only if none got through."""
    ways, errors = 0, []
    if cfg.get("contact_push"):
        ways += 1
        try:
            send_push(cfg["contact_push"], subject, body)
        except Exception as e:
            errors.append(f"push: {e}")
    if cfg.get("contact_email") and smtp_configured():
        ways += 1
        try:
            send_email(cfg["contact_email"], subject, body)
        except Exception as e:
            errors.append(f"email: {e}")
    if ways == 0:
        raise RuntimeError("No way to reach your trusted contact is set up")
    if len(errors) == ways:
        raise RuntimeError("; ".join(errors))


def timer_text(timer: dict, cfg: dict, user_name: str) -> tuple:
    who = cfg["contact_name"] or "there"
    lines = [f"Hi {who},", "", f"{user_name} set a safety timer and hasn't tapped \"I'm safe\" in time.",
             f"It was due at {_local(_parse(timer['due_at']), cfg['timezone'])}."]
    if timer.get("note"):
        lines += ["", f"Their note: {timer['note']}"]
    if cfg["instructions"]:
        lines += ["", "What they asked you to do:", cfg["instructions"]]
    lines += ["", "Try to reach them now."]
    return f"Safety timer: {user_name} hasn't checked in", "\n".join(lines)


def run_timers(db, now: datetime) -> int:
    sent = 0
    for t in [dict(r) for r in db.execute(
            "SELECT t.*, u.username FROM safety_timers t JOIN users u ON u.id = t.owner_id "
            "WHERE t.done_at IS NULL AND t.alert_sent_at IS NULL AND t.due_at <= ?", (now.isoformat(timespec="seconds"),))]:
        cfg = settings_for(db, t["owner_id"])
        try:
            deliver(cfg, *timer_text(t, cfg, t["username"]))
            db.execute("UPDATE safety_timers SET alert_sent_at = ?, alert_error = NULL WHERE id = ?",
                       (now.isoformat(timespec="seconds"), t["id"]))
            sent += 1
        except Exception as e:
            db.execute("UPDATE safety_timers SET alert_error = ? WHERE id = ?", (str(e)[:300], t["id"]))
        db.commit()
    return sent


def run_alerts(now: Optional[datetime] = None) -> int:
    """Send any alerts that are due. Returns how many were sent."""
    now = now or datetime.now(timezone.utc)
    db = _get_db()
    sent = 0
    try:
        sent += run_timers(db, now)
        for appt in watched_appointments(db, now=now):
            if appt["alert_sent_at"] or _parse(appt["alert_at"]) > now:
                continue
            cfg = settings_for(db, appt["owner_id"])
            if not cfg["contact_email"] and not cfg["contact_push"]:
                continue
            try:
                subject, body = alert_text(appt, cfg, now)
                deliver(cfg, subject, body)
                db.execute("UPDATE appointments SET alert_sent_at = ?, alert_error = NULL WHERE id = ?",
                           (now.isoformat(timespec="seconds"), appt["id"]))
                _put(db, appt["owner_id"], "safety_last_error", None)
                sent += 1
            except Exception as e:   # try again on the next round
                log.warning("Safety alert for appointment %s failed: %s", appt["id"], e)
                db.execute("UPDATE appointments SET alert_error = ? WHERE id = ?", (str(e)[:300], appt["id"]))
                _put(db, appt["owner_id"], "safety_last_error", str(e)[:300])
            db.commit()
    finally:
        db.close()
    return sent


def _worker():
    while True:
        try:
            run_alerts()
        except Exception as e:
            log.warning("Safety worker: %s", e)
        time.sleep(CHECK_EVERY)


def start(get_db: Callable, background: bool = True):
    global _get_db
    _get_db = get_db
    if background:
        threading.Thread(target=_worker, name="safety-check-in", daemon=True).start()


# ==================== API ====================

router = APIRouter(prefix="/api/safety")


class SafetySettings(BaseModel):
    contact_name: str = ""
    contact_email: str = ""
    grace_minutes: int = DEFAULT_GRACE
    include_details: bool = True
    instructions: str = ""
    timezone: str = "UTC"
    contact_push: str = ""        # an ntfy address your contact subscribes to, e.g. https://ntfy.sh/a-long-random-name


@router.get("")
def get_settings(request: Request):
    db = _get_db()
    try:
        return settings_for(db, request.state.user["id"])
    finally:
        db.close()


@router.put("")
def save_settings(body: SafetySettings, request: Request):
    email = body.contact_email.strip()
    if email and ("@" not in email or " " in email or "." not in email.split("@")[-1]):
        raise HTTPException(status_code=400, detail="That doesn't look like an email address")
    if body.grace_minutes not in GRACE_CHOICES:
        raise HTTPException(status_code=400, detail="Pick one of the listed waiting times")
    push = body.contact_push.strip()
    if push and (not push.startswith("https://") or len(push.rstrip("/").rsplit("/", 1)[-1]) < 12):
        raise HTTPException(status_code=400, detail="The push address starts with https:// and ends in a long, hard-to-guess name")
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        for key, value in (("safety_contact_push", push),
                           ("safety_contact_name", body.contact_name.strip()),
                           ("safety_contact_email", email),
                           ("safety_grace_minutes", str(body.grace_minutes)),
                           ("safety_details", "1" if body.include_details else "0"),
                           ("safety_instructions", body.instructions.strip()[:500]),
                           ("safety_timezone", body.timezone.strip() or "UTC")):
            _put(db, user_id, key, value)
        db.commit()
        return settings_for(db, user_id)
    finally:
        db.close()


_last_test_sent = {}   # user id -> when their last test email went out
TEST_COOLDOWN_SECONDS = 60


@router.post("/test")
def send_test(request: Request):
    """Send the trusted contact a test message, so both of you know alerts arrive."""
    user = request.state.user
    waited = time.time() - _last_test_sent.get(user["id"], 0)
    if waited < TEST_COOLDOWN_SECONDS:
        raise HTTPException(status_code=429, detail=f"A test was just sent. Try again in {int(TEST_COOLDOWN_SECONDS - waited) + 1} seconds.")
    db = _get_db()
    try:
        cfg = settings_for(db, user["id"])
    finally:
        db.close()
    if not cfg["contact_email"] and not cfg["contact_push"]:
        raise HTTPException(status_code=400, detail="Save your trusted contact's email or push address first")
    if not cfg["contact_push"] and not cfg["email_configured"]:
        raise HTTPException(status_code=400, detail="Email isn't set up yet. Add the SMTP settings to the .env file and restart.")
    try:
        deliver(cfg, f"Test: {user['username']}'s sworkr safety alerts",
                   f"This is a test. {user['username']} has named you as their trusted contact in sworkr.\n\n"
                   "If they don't check in after an appointment or a safety timer, you'll get a message like this one saying so.\n"
                   "Nothing is wrong right now.")
        _last_test_sent[user["id"]] = time.time()   # only a test that went out starts the wait
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"The test couldn't be sent: {e}")
    return {"sent_to": cfg["contact_email"] or "their phone"}


@router.get("/watch")
def watch(request: Request):
    """Appointments waiting for a check-in right now, for the banner at the top of the app."""
    db = _get_db()
    try:
        return [{
            "id": a["id"], "client_name": a["client_name"], "scheduled_date": a["scheduled_date"],
            "duration_minutes": a["duration_minutes"], "ends_at": a["ends_at"], "alert_at": a["alert_at"],
            "alert_sent_at": a["alert_sent_at"], "alert_error": a["alert_error"],
        } for a in watched_appointments(db, owner_id=request.state.user["id"])]
    finally:
        db.close()


# ==================== A TIMER FOR ANYTHING ====================
# "I'm walking home: tell my contact if I haven't tapped I'm safe in 20 minutes."

class TimerIn(BaseModel):
    minutes: int
    note: str = ""


def _active_timer(db, owner: int):
    r = db.execute("SELECT id, due_at, note, alert_sent_at FROM safety_timers WHERE owner_id = ? AND done_at IS NULL "
                   "ORDER BY id DESC LIMIT 1", (owner,)).fetchone()
    return dict(r) if r else None


@router.get("/timer")
def get_timer(request: Request):
    db = _get_db()
    try:
        return {"timer": _active_timer(db, request.state.user["id"]), "armed": settings_for(db, request.state.user["id"])["armed"]}
    finally:
        db.close()


@router.post("/timer", status_code=201)
def start_timer(body: TimerIn, request: Request):
    if not 1 <= body.minutes <= 24 * 60:
        raise HTTPException(status_code=400, detail="From 1 minute to 24 hours")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        if not settings_for(db, owner)["armed"]:
            raise HTTPException(status_code=409, detail="Set up your trusted contact first (Settings → Security & privacy → Safety check-in)")
        now = datetime.now(timezone.utc)
        db.execute("UPDATE safety_timers SET done_at = ? WHERE owner_id = ? AND done_at IS NULL", (now.isoformat(timespec="seconds"), owner))
        db.execute("INSERT INTO safety_timers (owner_id, due_at, note, created_at) VALUES (?, ?, ?, ?)",
                   (owner, (now + timedelta(minutes=body.minutes)).isoformat(timespec="seconds"), body.note.strip()[:300] or None,
                    now.isoformat(timespec="seconds")))
        db.commit()
        return {"timer": _active_timer(db, owner)}
    finally:
        db.close()


@router.post("/timer/safe")
def timer_safe(request: Request):
    """I'm safe: stop the timer. If the alert already went out, your contact is told you're fine."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        t = _active_timer(db, owner)
        if t:
            db.execute("UPDATE safety_timers SET done_at = ? WHERE owner_id = ? AND done_at IS NULL",
                       (datetime.now(timezone.utc).isoformat(timespec="seconds"), owner))
            db.commit()
            if t["alert_sent_at"]:
                cfg = settings_for(db, owner)
                try:
                    deliver(cfg, f"All clear: {request.state.user['username']} is safe",
                            f"{request.state.user['username']} just tapped \"I'm safe\". No need to do anything more.")
                except Exception as e:
                    log.warning("All-clear message failed: %s", e)
        return {"timer": None}
    finally:
        db.close()
