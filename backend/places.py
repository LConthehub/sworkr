"""
Charges a place makes: what you pay a brothel, club, studio or event, as opposed to the share it keeps
of your pay (that's the place's fee_percent / fee_per_shift, in finance.py).

A charge has a cadence (per booking, shift, day, week, month, year, per stay, or once) and an expense
category. Logging one adds an expense; a charge with a test_type (a house doctor) is logged as a health test
instead, so it shows in your test history too. A yearly or one-off charge can have a renewal date (a license
or work card): sworkr keeps a reminder task for it two weeks before, and logging a yearly one moves the date
on a year.

Stays (tours linked to a place) log the per-day, per-week and per-stay charges by themselves; see main.py.
"""

from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import calendar_sync
import finance

router = APIRouter()
_get_db: Optional[Callable] = None
_log_health_test: Optional[Callable] = None
_sync_stays: Optional[Callable] = None
REMIND_DAYS_BEFORE = 14


def setup(get_db: Callable, log_health_test: Callable, sync_stays: Callable):
    """From main.py: log_health_test(db, owner_id, when, test_type, cost, label, tour_id) -> appointment id, and
    sync_stays(db, owner_id, source_id) -> health test ids touched (logs a place's charges for its stays again)."""
    global _get_db, _log_health_test, _sync_stays
    _get_db = get_db
    _log_health_test = log_health_test
    _sync_stays = sync_stays


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip()
    return text or None


class Cadence(str, Enum):
    PER_BOOKING = "per_booking"
    PER_SHIFT = "per_shift"
    PER_DAY = "per_day"
    PER_WEEK = "per_week"
    PER_MONTH = "per_month"
    PER_QUARTER = "per_quarter"    # every three months (some licenses)
    PER_YEAR = "per_year"
    PER_STAY = "per_stay"
    ONCE = "once"


RENEWABLE = {Cadence.PER_QUARTER, Cadence.PER_YEAR, Cadence.ONCE}
# Paying a renewable charge within this many days of its renewal date moves the date on (by this many months).
# Earlier than that, it's taken as catching up on an old payment, and the date stays.
RENEW_WINDOW = {Cadence.PER_QUARTER.value: (30, 3), Cadence.PER_YEAR.value: (90, 12)}


class TestType(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class ChargeIn(BaseModel):
    label: str
    amount: Optional[float] = None       # empty until the person knows it
    cadence: Cadence = Cadence.PER_DAY
    category: str = "other"              # an expense category key
    test_type: Optional[TestType] = None  # set: a house doctor; logged as a health test
    renews_on: Optional[date] = None      # a license or work card's expiry (yearly or one-off charges)


class LogIn(BaseModel):
    date: Optional[datetime] = None       # when it was paid; now if left out
    amount: Optional[float] = None        # this time only, if different
    tour_id: Optional[int] = None


def get_charge(db, charge_id: int, owner_id: int) -> Optional[dict]:
    r = db.execute("""
        SELECT c.*, s.name AS place_name FROM place_charges c JOIN income_sources s ON s.id = c.source_id
        WHERE c.id = ? AND c.owner_id = ?
    """, (charge_id, owner_id)).fetchone()
    return dict(r) if r else None


def charges_for(db, owner_id: int, source_id: Optional[int] = None) -> List[dict]:
    sql = """SELECT c.*, s.name AS place_name FROM place_charges c JOIN income_sources s ON s.id = c.source_id
             WHERE c.owner_id = ?"""
    params = [owner_id]
    if source_id is not None:
        sql += " AND c.source_id = ?"
        params.append(source_id)
    return [dict(r) for r in db.execute(sql + " ORDER BY c.source_id, c.sort_order, c.id", params)]


def _validate(db, owner_id: int, body: ChargeIn) -> ChargeIn:
    body.label = _clean(body.label) or ""
    if not body.label or len(body.label) > 80:
        raise HTTPException(status_code=400, detail="Give the charge a name (up to 80 characters)")
    if body.amount is not None and not (0 <= body.amount < 1e9):
        raise HTTPException(status_code=400, detail="The amount must be 0 or more")
    body.category = finance.check_category(db, owner_id, body.category)
    if body.test_type:
        body.category = "medical"   # health tests are always logged under Tests & doctor
    if body.cadence not in RENEWABLE:
        body.renews_on = None
    return body


def _sync_renewal_task(db, charge_id: int, owner_id: int) -> List[int]:
    """A charge with a renewal date has one open reminder task, due two weeks before; without one, none.
    Returns the task ids to send to calendar sync once committed."""
    c = get_charge(db, charge_id, owner_id)
    if not c:
        return []
    task = db.execute("SELECT id, done_at FROM tasks WHERE id = ? AND owner_id = ?", (c["task_id"], owner_id)).fetchone() \
        if c["task_id"] else None
    if not c["renews_on"]:
        db.execute("UPDATE place_charges SET task_id = NULL WHERE id = ?", (charge_id,))
        if task and not task["done_at"]:
            db.execute("DELETE FROM tasks WHERE id = ? AND owner_id = ?", (task["id"], owner_id))
            return [task["id"]]
        return []
    renews = date.fromisoformat(c["renews_on"])
    due = max(renews - timedelta(days=REMIND_DAYS_BEFORE), date.today()) if renews >= date.today() else renews
    title = f"Renew {c['label']} – {c['place_name']}"
    notes = f"Runs out on {renews.strftime('%d %b %Y').lstrip('0')}. (A reminder from {c['place_name']}'s charges.)"
    now = _now()
    if task:
        # A new date reopens a reminder that was ticked off for the last one.
        db.execute("UPDATE tasks SET title = ?, notes = ?, due_date = ?, done_at = CASE WHEN due_date = ? THEN done_at END, "
                   "updated_at = ? WHERE id = ? AND owner_id = ?",
                   (title, notes, due.isoformat(), due.isoformat(), now, task["id"], owner_id))
        return [task["id"]]
    cur = db.execute("INSERT INTO tasks (title, notes, due_date, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (title, notes, due.isoformat(), owner_id, now, now))
    db.execute("UPDATE place_charges SET task_id = ? WHERE id = ?", (cur.lastrowid, charge_id))
    return [cur.lastrowid]


def _sync_after_commit(owner_id: int, task_ids=(), appointment_ids=()):
    for task_id in task_ids:
        calendar_sync.queue_item("task", task_id, owner_id)
    for appointment_id in appointment_ids:
        calendar_sync.queue_appointment(appointment_id)


def log_charge(db, owner_id: int, charge: dict, when: datetime, amount: Optional[float] = None,
               tour_id: Optional[int] = None, source: str = "place_charge", description: Optional[str] = None) -> dict:
    """Record one payment of a charge: an expense, or for a house doctor a health test (which makes its expense).
    Returns {"expense_id"} or {"appointment_id"}."""
    amount = charge["amount"] if amount is None else amount
    if amount is None:
        raise HTTPException(status_code=400, detail=f"Enter how much {charge['label']} costs first")
    description = description or f"{charge['label']} – {charge['place_name']}"
    if charge["test_type"]:
        return {"appointment_id": _log_health_test(db, owner_id, when, charge["test_type"], amount, description, tour_id)}
    cur = db.execute("""
        INSERT INTO expenses (description, amount, category, date, owner_id, created_at, tour_id, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (description, amount, charge["category"], when.astimezone(timezone.utc).isoformat(timespec="seconds"),
          owner_id, _now(), tour_id, source))
    return {"expense_id": cur.lastrowid}


def _add_months(d: date, months: int) -> date:
    """The same day `months` later, or the month's last day if it's shorter (31 Jan + 3 months: 30 Apr)."""
    month = d.month - 1 + months
    year, month = d.year + month // 12, month % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue


# ==================== API ====================

@router.get("/api/place-charges")
def list_charges(request: Request):
    db = _get_db()
    try:
        return charges_for(db, request.state.user["id"])
    finally:
        db.close()


@router.post("/api/income-sources/{source_id}/charges", status_code=201)
def create_charge(source_id: int, body: ChargeIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        if not finance.get_source(db, source_id, owner):
            raise HTTPException(status_code=404, detail="Place not found")
        _validate(db, owner, body)
        order = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM place_charges WHERE source_id = ?", (source_id,)).fetchone()[0]
        now = _now()
        cur = db.execute("""
            INSERT INTO place_charges (owner_id, source_id, label, amount, cadence, category, test_type, renews_on,
                                       sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (owner, source_id, body.label, body.amount, body.cadence.value, body.category,
              body.test_type.value if body.test_type else None, body.renews_on.isoformat() if body.renews_on else None,
              order, now, now))
        tasks = _sync_renewal_task(db, cur.lastrowid, owner)
        tests = _sync_stays(db, owner, source_id)
        db.commit()
        _sync_after_commit(owner, tasks, tests)
        return get_charge(db, cur.lastrowid, owner)
    finally:
        db.close()


@router.put("/api/place-charges/{charge_id}")
def update_charge(charge_id: int, body: ChargeIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        existing = get_charge(db, charge_id, owner)
        if not existing:
            raise HTTPException(status_code=404, detail="Charge not found")
        _validate(db, owner, body)
        db.execute("""
            UPDATE place_charges SET label = ?, amount = ?, cadence = ?, category = ?, test_type = ?, renews_on = ?,
                   updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (body.label, body.amount, body.cadence.value, body.category,
              body.test_type.value if body.test_type else None, body.renews_on.isoformat() if body.renews_on else None,
              _now(), charge_id, owner))
        tasks = _sync_renewal_task(db, charge_id, owner)
        tests = _sync_stays(db, owner, existing["source_id"])
        db.commit()
        _sync_after_commit(owner, tasks, tests)
        return get_charge(db, charge_id, owner)
    finally:
        db.close()


@router.delete("/api/place-charges/{charge_id}", status_code=204)
def delete_charge(charge_id: int, request: Request):
    """Delete a charge. Expenses already logged from it stay; an open renewal reminder goes."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        c = get_charge(db, charge_id, owner)
        if not c:
            raise HTTPException(status_code=404, detail="Charge not found")
        if c["task_id"]:
            db.execute("DELETE FROM tasks WHERE id = ? AND owner_id = ? AND done_at IS NULL", (c["task_id"], owner))
        db.execute("DELETE FROM place_charges WHERE id = ? AND owner_id = ?", (charge_id, owner))
        tests = _sync_stays(db, owner, c["source_id"])
        db.commit()
        _sync_after_commit(owner, [c["task_id"]] if c["task_id"] else [], tests)
    finally:
        db.close()


@router.post("/api/place-charges/{charge_id}/log", status_code=201)
def log_charge_now(charge_id: int, body: LogIn, request: Request):
    """Pay a charge once: adds the expense (or health test). Paying a yearly or quarterly charge with a renewal
    date moves the date on a year or three months, and its reminder with it."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        c = get_charge(db, charge_id, owner)
        if not c:
            raise HTTPException(status_code=404, detail="Charge not found")
        if body.amount is not None and not (0 <= body.amount < 1e9):
            raise HTTPException(status_code=400, detail="The amount must be 0 or more")
        if body.tour_id is not None and not db.execute("SELECT 1 FROM tours WHERE id = ? AND owner_id = ?",
                                                       (body.tour_id, owner)).fetchone():
            raise HTTPException(status_code=404, detail="Tour not found")
        when = body.date or datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        result = log_charge(db, owner, c, when, body.amount, body.tour_id)
        tasks = []
        if c["cadence"] in RENEW_WINDOW and c["renews_on"]:
            window, months = RENEW_WINDOW[c["cadence"]]
            renews = date.fromisoformat(c["renews_on"])
            if renews - timedelta(days=window) <= when.date():   # paying for the next period, not catching up
                db.execute("UPDATE place_charges SET renews_on = ?, updated_at = ? WHERE id = ?",
                           (_add_months(renews, months).isoformat(), _now(), charge_id))
                tasks = _sync_renewal_task(db, charge_id, owner)
        db.commit()
        _sync_after_commit(owner, tasks, [result["appointment_id"]] if "appointment_id" in result else [])
        return {**result, "charge": get_charge(db, charge_id, owner)}
    finally:
        db.close()
