"""
Cycle tracking: opt-in, private, and only for planning.

- You log when a period starts (and ends). sworkr works out your usual cycle and period length from the
  last six cycles (28 and 5 days until there's enough history) and predicts the next ones.
- Logged and predicted period days show on the calendar; booking a client on one can ask you first; a tour
  says when your period is predicted during it.
- Estimated fertile days are off unless you turn them on. They're a rough guide, never contraception.
- Nothing here is synced to calendars, exported to CSV or shown to anyone else.
"""

import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import datetime as dt

router = APIRouter(prefix="/api/cycle")
_get_db: Optional[Callable] = None

DEFAULT_CYCLE, DEFAULT_PERIOD = 28, 5
MIN_CYCLE, MAX_CYCLE = 15, 60          # gaps outside this are treated as missed logs, not cycles
LOOKBACK = 6
PREDICT = 6


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(db, user_id, key, default=None):
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return row[0] if row and row[0] is not None else default


def _set(db, user_id, key, value):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, value))


def settings(db, user_id: int) -> dict:
    return {
        "enabled": _get(db, user_id, "cycle_enabled") == "1",
        "warn_on_booking": _get(db, user_id, "cycle_warn", "1") == "1",
        "show_fertile": _get(db, user_id, "cycle_fertile") == "1",
        "typical_cycle": int(_get(db, user_id, "cycle_typical", DEFAULT_CYCLE)),
        "typical_period": int(_get(db, user_id, "cycle_period", DEFAULT_PERIOD)),
    }


def _entries(db, user_id: int) -> List[dict]:
    return [dict(r) for r in db.execute(
        "SELECT * FROM cycle_entries WHERE owner_id = ? ORDER BY start_date", (user_id,))]


def summary(db, user_id: int, today: date) -> dict:
    """Averages, where today falls in the cycle, and the next predicted periods."""
    s = settings(db, user_id)
    entries = _entries(db, user_id)
    starts = [date.fromisoformat(e["start_date"]) for e in entries]
    gaps = [(b - a).days for a, b in zip(starts, starts[1:]) if MIN_CYCLE <= (b - a).days <= MAX_CYCLE][-LOOKBACK:]
    lengths = [(date.fromisoformat(e["end_date"]) - date.fromisoformat(e["start_date"])).days + 1
               for e in entries if e["end_date"]][-LOOKBACK:]
    cycle_len = round(statistics.mean(gaps)) if gaps else s["typical_cycle"]
    period_len = round(statistics.mean(lengths)) if lengths else s["typical_period"]
    spread = statistics.pstdev(gaps) if len(gaps) >= 3 else None

    predictions = []
    if starts:
        nxt = starts[-1] + timedelta(days=cycle_len)
        while nxt <= today - timedelta(days=period_len):   # missed logs: roll forward to the next one still to come
            nxt += timedelta(days=cycle_len)
        for _ in range(PREDICT):
            predictions.append({"start": nxt.isoformat(), "end": (nxt + timedelta(days=period_len - 1)).isoformat()})
            nxt += timedelta(days=cycle_len)

    current = None
    if starts and starts[-1] <= today:
        last = entries[-1]
        end = date.fromisoformat(last["end_date"]) if last["end_date"] else starts[-1] + timedelta(days=period_len - 1)
        cycle_day = (today - starts[-1]).days + 1
        on_period = today <= end
        current = {"cycle_day": cycle_day, "on_period": on_period, "open_entry": last["end_date"] is None and cycle_day <= 14,
                   "entry_id": last["id"]}
    next_start = date.fromisoformat(predictions[0]["start"]) if predictions else None
    return {
        "settings": s,
        "entries": entries[-24:][::-1],
        "average_cycle": cycle_len,
        "average_period": period_len,
        "cycles_counted": len(gaps),
        "irregular": spread is not None and spread > 7,
        "today": current,
        "next_period": predictions[0] if predictions else None,
        "days_until_next": (next_start - today).days if next_start else None,
        "predictions": predictions,
    }


def days_between(db, user_id: int, start: date, end: date, today: Optional[date] = None) -> List[dict]:
    """Each day from start to end (exclusive) that's a logged period day, a predicted one, or (if turned on)
    an estimated fertile day."""
    today = today or date.today()
    info = summary(db, user_id, today)
    marks = {}

    def mark(first: date, last: date, kind: str):
        d = max(first, start)
        while d <= last and d < end:
            marks.setdefault(d, kind)   # a logged day beats a prediction
            d += timedelta(days=1)

    for e in info["entries"]:
        first = date.fromisoformat(e["start_date"])
        last = date.fromisoformat(e["end_date"]) if e["end_date"] else (
            min(first + timedelta(days=info["average_period"] - 1), max(today, first)))
        mark(first, last, "period")
    for p in info["predictions"]:
        mark(date.fromisoformat(p["start"]), date.fromisoformat(p["end"]), "predicted")
    if info["settings"]["show_fertile"]:
        for p in info["predictions"]:
            ovulation = date.fromisoformat(p["start"]) - timedelta(days=14)
            mark(ovulation - timedelta(days=5), ovulation + timedelta(days=1), "fertile")
    return [{"date": d.isoformat(), "kind": k} for d, k in sorted(marks.items())]


def booking_warning(db, user_id: int, when: datetime, tz_offset: int) -> Optional[str]:
    """For the booking warnings: is this a period day (logged or predicted)? Only when tracking and warnings are on."""
    s = settings(db, user_id)
    if not (s["enabled"] and s["warn_on_booking"]):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    day = (when.astimezone(timezone.utc) - timedelta(minutes=tz_offset)).date()
    found = days_between(db, user_id, day, day + timedelta(days=1))
    if found and found[0]["kind"] in ("period", "predicted"):
        return "Your period is " + ("logged" if found[0]["kind"] == "period" else "predicted") + " for this day"
    return None


# ==================== API ====================

class CycleSettings(BaseModel):
    enabled: bool = False
    warn_on_booking: bool = True
    show_fertile: bool = False
    typical_cycle: int = DEFAULT_CYCLE
    typical_period: int = DEFAULT_PERIOD


class EntryIn(BaseModel):
    start_date: dt.date
    end_date: Optional[dt.date] = None
    flow: Optional[str] = None
    notes: Optional[str] = None


def _today(value: Optional[dt.date]) -> date:
    """The browser says what day it is where the person is; otherwise the server's date."""
    return value or date.today()


@router.get("/settings")
def get_settings(request: Request):
    db = _get_db()
    try:
        return settings(db, request.state.user["id"])
    finally:
        db.close()


@router.put("/settings")
def save_settings(body: CycleSettings, request: Request):
    if not (MIN_CYCLE <= body.typical_cycle <= MAX_CYCLE) or not (1 <= body.typical_period <= 14):
        raise HTTPException(status_code=400, detail="A usual cycle is 15–60 days and a period 1–14 days")
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        for key, value in (("cycle_enabled", body.enabled), ("cycle_warn", body.warn_on_booking), ("cycle_fertile", body.show_fertile)):
            _set(db, user_id, key, "1" if value else "0")
        _set(db, user_id, "cycle_typical", str(body.typical_cycle))
        _set(db, user_id, "cycle_period", str(body.typical_period))
        db.commit()
        return settings(db, user_id)
    finally:
        db.close()


@router.get("")
def get_cycle(request: Request, today: Optional[dt.date] = None):
    db = _get_db()
    try:
        return summary(db, request.state.user["id"], _today(today))
    finally:
        db.close()


@router.get("/days")
def get_days(request: Request, start: dt.date, end: dt.date, today: Optional[dt.date] = None):
    if (end - start).days > 400 or end < start:
        raise HTTPException(status_code=400, detail="Ask for at most about a year at a time")
    db = _get_db()
    try:
        if not settings(db, request.state.user["id"])["enabled"]:
            return []
        return days_between(db, request.state.user["id"], start, end, _today(today))
    finally:
        db.close()


def _check(body: EntryIn):
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="It can't end before it starts")
    if body.end_date and (body.end_date - body.start_date).days > 20:
        raise HTTPException(status_code=400, detail="That's longer than 3 weeks: check the dates")
    if body.flow not in (None, "light", "medium", "heavy"):
        raise HTTPException(status_code=400, detail="Flow is light, medium or heavy")


def _overlaps(db, user_id, body: EntryIn, exclude_id=None) -> bool:
    end = (body.end_date or body.start_date + timedelta(days=7)).isoformat()
    return bool(db.execute("""
        SELECT 1 FROM cycle_entries WHERE owner_id = ? AND id IS NOT ?
          AND start_date <= ? AND COALESCE(end_date, date(start_date, '+7 day')) >= ?
    """, (user_id, exclude_id, end, body.start_date.isoformat())).fetchone())


@router.post("/entries", status_code=201)
def add_entry(body: EntryIn, request: Request):
    _check(body)
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        if _overlaps(db, user_id, body):
            raise HTTPException(status_code=400, detail="That overlaps a period you've already logged")
        now = _now()
        cur = db.execute("INSERT INTO cycle_entries (owner_id, start_date, end_date, flow, notes, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (user_id, body.start_date.isoformat(), body.end_date.isoformat() if body.end_date else None,
                          body.flow, (body.notes or "").strip() or None, now, now))
        db.commit()
        return dict(db.execute("SELECT * FROM cycle_entries WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        db.close()


@router.put("/entries/{entry_id}")
def update_entry(entry_id: int, body: EntryIn, request: Request):
    _check(body)
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        if not db.execute("SELECT 1 FROM cycle_entries WHERE id = ? AND owner_id = ?", (entry_id, user_id)).fetchone():
            raise HTTPException(status_code=404, detail="Not found")
        if _overlaps(db, user_id, body, exclude_id=entry_id):
            raise HTTPException(status_code=400, detail="That overlaps a period you've already logged")
        db.execute("UPDATE cycle_entries SET start_date = ?, end_date = ?, flow = ?, notes = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                   (body.start_date.isoformat(), body.end_date.isoformat() if body.end_date else None, body.flow,
                    (body.notes or "").strip() or None, _now(), entry_id, user_id))
        db.commit()
        return dict(db.execute("SELECT * FROM cycle_entries WHERE id = ?", (entry_id,)).fetchone())
    finally:
        db.close()


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM cycle_entries WHERE id = ? AND owner_id = ?", (entry_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()
