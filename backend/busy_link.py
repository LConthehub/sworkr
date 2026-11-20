"""
A busy link, per person: a private web address a home or family calendar can follow to see WHEN you're
working, and nothing else.

What the link answers with is a calendar file (iCalendar) holding only times:
- each booking that isn't cancelled, as "Busy" from its start to its end;
- each tour, as whole days called "Away";
- each day off or vacation, as whole days called "Off".

No client, no service, no place, no notes, no money, and not even sworkr's own numbers for the bookings:
none of it is put in the file, so none of it can leave through the link, whatever follows it.

A calendar app can't sign in, so the long random part of the address is the only key. It is off until the
person makes a link; making a new one stops the old one working; turning it off forgets it. It reaches from
a month back to a year ahead.
"""

import hmac
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

import calendar_sync

router = APIRouter()
_get_db: Optional[Callable] = None

DAYS_BACK, DAYS_AHEAD = 31, 365
ADDRESS = re.compile(r"^(\d{1,12})-([0-9a-f]{64})\.ics$")
FILE_HEADERS = {"Content-Type": "text/calendar; charset=utf-8", "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _stamp(day: date) -> str:
    return day.isoformat().replace("-", "")


def busy_file(db, user_id: int, today: date) -> bytes:
    """The whole file for one person: times only."""
    first, last = today - timedelta(days=DAYS_BACK), today + timedelta(days=DAYS_AHEAD)
    now = calendar_sync._utc_stamp(datetime.now(timezone.utc))
    lines: List[str] = ["X-WR-CALNAME:Busy", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    count = 0

    def event(*body: str):
        nonlocal count
        count += 1
        # Numbered in the order written, not by sworkr's own ids, so the file says nothing about how many
        # bookings there have ever been.
        lines.extend(["BEGIN:VEVENT", f"UID:busy-{count}@sworkr", f"DTSTAMP:{now}", *body, "END:VEVENT"])

    for row in db.execute(
            "SELECT scheduled_date, duration_minutes FROM appointments WHERE owner_id = ? AND status != 'cancelled' "
            "AND scheduled_date >= ? AND scheduled_date < ? ORDER BY scheduled_date, id",
            (user_id, first.isoformat(), (last + timedelta(days=1)).isoformat())):
        start = datetime.fromisoformat(row["scheduled_date"].replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = start + timedelta(minutes=row["duration_minutes"] or 0)
        event(f"DTSTART:{calendar_sync._utc_stamp(start)}", f"DTEND:{calendar_sync._utc_stamp(end)}", "SUMMARY:Busy")

    for row in db.execute(
            "SELECT kind, start_date, end_date FROM tours WHERE owner_id = ? AND end_date >= ? AND start_date <= ? "
            "ORDER BY start_date, id", (user_id, first.isoformat(), last.isoformat())):
        until = date.fromisoformat(row["end_date"]) + timedelta(days=1)   # a whole day ends at the start of the next
        event(f"DTSTART;VALUE=DATE:{row['start_date'].replace('-', '')}", f"DTEND;VALUE=DATE:{_stamp(until)}",
              f"SUMMARY:{'Away' if row['kind'] == 'tour' else 'Off'}", "TRANSP:TRANSPARENT")

    return calendar_sync._calendar(lines)


def _status(db, user_id: int) -> dict:
    token = calendar_sync.get_setting(db, user_id, "busy_token")
    return {
        "on": bool(token),
        # The part of the address after the site's own: the page puts its own address in front.
        "path": f"/busy/{user_id}-{token}.ics" if token else None,
        "read_at": calendar_sync.get_setting(db, user_id, "busy_read_at"),
        "days_back": DAYS_BACK, "days_ahead": DAYS_AHEAD,
    }


def _set_token(db, user_id: int, token: Optional[str]):
    calendar_sync.set_setting(db, user_id, "busy_token", token)
    calendar_sync.set_setting(db, user_id, "busy_read_at", None)


@router.get("/api/busy-link")
def status(request: Request):
    db = _get_db()
    try:
        return _status(db, request.state.user["id"])
    finally:
        db.close()


@router.put("/api/busy-link")
def turn_on(request: Request):
    """Make the link. If there already is one, it stays as it is."""
    db = _get_db()
    try:
        user_id = request.state.user["id"]
        if not calendar_sync.get_setting(db, user_id, "busy_token"):
            _set_token(db, user_id, secrets.token_hex(32))
        return _status(db, user_id)
    finally:
        db.close()


@router.post("/api/busy-link/renew")
def renew(request: Request):
    """A new address. The old one stops working at once."""
    db = _get_db()
    try:
        user_id = request.state.user["id"]
        if not calendar_sync.get_setting(db, user_id, "busy_token"):
            raise HTTPException(status_code=404, detail="There's no link to replace")
        _set_token(db, user_id, secrets.token_hex(32))
        return _status(db, user_id)
    finally:
        db.close()


@router.delete("/api/busy-link")
def turn_off(request: Request):
    db = _get_db()
    try:
        _set_token(db, request.state.user["id"], None)
        return _status(db, request.state.user["id"])
    finally:
        db.close()


@router.get("/busy/{name}", include_in_schema=False)
def busy(name: str):
    """What a calendar app is given. No sign-in: the address is the key. Anything else is simply not found."""
    found = ADDRESS.match(name)
    if not found:
        raise HTTPException(status_code=404, detail="Not found")
    user_id, given = int(found.group(1)), found.group(2)
    db = _get_db()
    try:
        token = calendar_sync.get_setting(db, user_id, "busy_token")
        if not token or not hmac.compare_digest(token, given):
            raise HTTPException(status_code=404, detail="Not found")
        body = busy_file(db, user_id, datetime.now(timezone.utc).date())
        calendar_sync.set_setting(db, user_id, "busy_read_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return Response(content=body, headers=FILE_HEADERS)
    finally:
        db.close()
