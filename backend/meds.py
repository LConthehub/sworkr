"""
Birth control and regular meds (PrEP, doxyPEP, hormones, anything taken on a schedule). Opt-in and private,
next to the period tracker.

Each method has its own rhythm: a pill every day, a patch changed weekly, a ring in for three weeks and out
for one, a shot every 12 weeks, an implant or IUD replaced after some years. sworkr works out what's due next
from what you log, and keeps one reminder task for the next change, shot, replacement or refill (tasks sync to
your phone's calendar). A daily pill gets no task: a phone alarm does that better. Task titles say only "Health
reminder" unless you turn that off, since tasks can show up on a shared calendar.
"""

import datetime as dt
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import calendar_sync

router = APIRouter(prefix="/api/meds")
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Method(str, Enum):
    PILL = "pill"
    PATCH = "patch"
    RING = "ring"
    SHOT = "shot"
    IMPLANT = "implant"
    IUD = "iud"
    CONDOMS = "condoms"
    DAILY = "daily"          # PrEP, hormones, anything daily
    AS_NEEDED = "as_needed"  # doxyPEP, emergency contraception
    OTHER = "other"


# What each method's "change" is called, and how many days apart.
RHYTHM = {
    Method.PATCH: ("Change the patch", 7),
    Method.SHOT: ("Next shot", 84),          # 12 weeks (most allow up to 13)
}
RING_IN, RING_OUT = 21, 7


class LogKind(str, Enum):
    TAKEN = "taken"          # a pill or daily dose
    MISSED = "missed"
    CHANGED = "changed"      # a new patch, ring in, ring out, a shot, a new implant/IUD
    REFILLED = "refilled"


class MedIn(BaseModel):
    name: str                                # "Pill", "PrEP", "Depo shot"…
    method: Method = Method.PILL
    started_on: Optional[date] = None        # the first day (a ring's first day in, a patch's first change)
    replace_by: Optional[date] = None        # an implant or IUD
    refill_every_days: Optional[int] = None  # e.g. 28 or 90
    cost: Optional[float] = None             # a refill's cost, added to expenses when you log a refill
    discreet: bool = True
    active: bool = True
    notes: Optional[str] = None


class LogIn(BaseModel):
    kind: LogKind
    date: Optional[dt.date] = None           # (dt.date: a field called `date` would hide the type)
    note: Optional[str] = None
    cost: Optional[float] = None             # a refill this time, if different


def _last(db, med_id: int, kinds) -> Optional[date]:
    marks = ",".join("?" * len(kinds))
    r = db.execute(f"SELECT MAX(date) FROM med_logs WHERE med_id = ? AND kind IN ({marks})", (med_id, *kinds)).fetchone()
    return date.fromisoformat(r[0]) if r and r[0] else None


def status(db, med: dict, today: Optional[date] = None) -> dict:
    """What's due next: {"next": {"what", "on"}, "refill_on", "taken_today", "ring": "in"/"out"}."""
    today = today or date.today()
    method = Method(med["method"])
    started = date.fromisoformat(med["started_on"]) if med["started_on"] else None
    changed = _last(db, med["id"], ["changed"]) or started
    out = {"next": None, "refill_on": None, "taken_today": False, "ring": None}
    if method in (Method.PILL, Method.DAILY):
        out["taken_today"] = _last(db, med["id"], ["taken"]) == today
        out["next"] = {"what": "Today's dose" if not out["taken_today"] else "Tomorrow's dose",
                       "on": (today if not out["taken_today"] else today + timedelta(days=1)).isoformat()}
    elif method in RHYTHM and changed:
        what, every = RHYTHM[method]
        due = changed + timedelta(days=every)
        out["next"] = {"what": what, "on": due.isoformat()}
    elif method == Method.RING and started:
        # Three weeks in, one week out, from the first day in.
        day = (today - started).days % (RING_IN + RING_OUT)
        cycle_start = today - timedelta(days=day)
        if day < RING_IN:
            out["ring"] = "in"
            out["next"] = {"what": "Take the ring out", "on": (cycle_start + timedelta(days=RING_IN)).isoformat()}
        else:
            out["ring"] = "out"
            out["next"] = {"what": "Put a new ring in", "on": (cycle_start + timedelta(days=RING_IN + RING_OUT)).isoformat()}
    elif method in (Method.IMPLANT, Method.IUD) and med["replace_by"]:
        out["next"] = {"what": f"Replace the {'implant' if method == Method.IMPLANT else 'IUD'}", "on": med["replace_by"]}
    if med["refill_every_days"]:
        refilled = _last(db, med["id"], ["refilled"]) or started
        if refilled:
            out["refill_on"] = (refilled + timedelta(days=med["refill_every_days"])).isoformat()
    return out


def _sync_task(db, med_id: int, owner_id: int) -> List[int]:
    """One open reminder task for the next non-daily thing due (a change, a shot, a replacement or a refill,
    whichever is sooner). Returns task ids for calendar sync."""
    med = _get(db, med_id, owner_id)
    if not med:
        return []
    st = status(db, med)
    due = []
    if med["active"] and st["next"] and Method(med["method"]) not in (Method.PILL, Method.DAILY):
        due.append((st["next"]["on"], st["next"]["what"]))
    if med["active"] and st["refill_on"]:
        due.append((st["refill_on"], f"Refill {med['name']}"))
    task = db.execute("SELECT id, done_at FROM tasks WHERE id = ? AND owner_id = ?", (med["task_id"], owner_id)).fetchone() \
        if med["task_id"] else None
    if not due:
        db.execute("UPDATE med_schedules SET task_id = NULL WHERE id = ?", (med_id,))
        if task and not task["done_at"]:
            db.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))
            return [task["id"]]
        return []
    on, what = min(due)
    title = "Health reminder" if med["discreet"] else f"{what} ({med['name']})" if med["name"].lower() not in what.lower() else what
    now = _now()
    if task:
        db.execute("UPDATE tasks SET title = ?, due_date = ?, done_at = NULL, updated_at = ? WHERE id = ?", (title, on, now, task["id"]))
        return [task["id"]]
    cur = db.execute("INSERT INTO tasks (title, due_date, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                     (title, on, owner_id, now, now))
    db.execute("UPDATE med_schedules SET task_id = ? WHERE id = ?", (cur.lastrowid, med_id))
    return [cur.lastrowid]


def _get(db, med_id: int, owner_id: int) -> Optional[dict]:
    r = db.execute("SELECT * FROM med_schedules WHERE id = ? AND owner_id = ?", (med_id, owner_id)).fetchone()
    return dict(r) if r else None


def _out(db, med: dict) -> dict:
    logs = [dict(r) for r in db.execute(
        "SELECT id, date, kind, note FROM med_logs WHERE med_id = ? ORDER BY date DESC, id DESC LIMIT 10", (med["id"],))]
    return {**med, "discreet": bool(med["discreet"]), "active": bool(med["active"]), "status": status(db, med), "recent": logs}


def _validate(body: MedIn) -> MedIn:
    body.name = (body.name or "").strip()
    if not body.name or len(body.name) > 60:
        raise HTTPException(status_code=400, detail="Give it a name (up to 60 characters)")
    if body.refill_every_days is not None and not (1 <= body.refill_every_days <= 400):
        raise HTTPException(status_code=400, detail="Refills must be between 1 and 400 days apart")
    if body.cost is not None and not (0 <= body.cost < 1e7):
        raise HTTPException(status_code=400, detail="The cost must be 0 or more")
    if body.method not in (Method.IMPLANT, Method.IUD):
        body.replace_by = None
    return body


def _values(b: MedIn) -> tuple:
    return (b.name, b.method.value, b.started_on.isoformat() if b.started_on else None,
            b.replace_by.isoformat() if b.replace_by else None, b.refill_every_days, b.cost, int(b.discreet),
            int(b.active), (b.notes or "").strip() or None)


def _after(owner_id: int, task_ids: List[int]):
    for task_id in task_ids:
        calendar_sync.queue_item("task", task_id, owner_id)


@router.get("")
def list_meds(request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return [_out(db, dict(r)) for r in db.execute(
            "SELECT * FROM med_schedules WHERE owner_id = ? ORDER BY active DESC, name COLLATE NOCASE", (owner,))]
    finally:
        db.close()


@router.post("", status_code=201)
def create_med(body: MedIn, request: Request):
    _validate(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        now = _now()
        cur = db.execute("""
            INSERT INTO med_schedules (name, method, started_on, replace_by, refill_every_days, cost, discreet, active,
                                       notes, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_values(body), owner, now, now))
        tasks = _sync_task(db, cur.lastrowid, owner)
        db.commit()
        _after(owner, tasks)
        return _out(db, _get(db, cur.lastrowid, owner))
    finally:
        db.close()


@router.put("/{med_id}")
def update_med(med_id: int, body: MedIn, request: Request):
    _validate(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        if not _get(db, med_id, owner):
            raise HTTPException(status_code=404, detail="Not found")
        db.execute("""
            UPDATE med_schedules SET name = ?, method = ?, started_on = ?, replace_by = ?, refill_every_days = ?, cost = ?,
                   discreet = ?, active = ?, notes = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_values(body), _now(), med_id, owner))
        tasks = _sync_task(db, med_id, owner)
        db.commit()
        _after(owner, tasks)
        return _out(db, _get(db, med_id, owner))
    finally:
        db.close()


@router.delete("/{med_id}", status_code=204)
def delete_med(med_id: int, request: Request):
    """Its log goes with it; expenses from refills stay."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        med = _get(db, med_id, owner)
        if not med:
            return
        if med["task_id"]:
            db.execute("DELETE FROM tasks WHERE id = ? AND owner_id = ? AND done_at IS NULL", (med["task_id"], owner))
        db.execute("DELETE FROM med_schedules WHERE id = ? AND owner_id = ?", (med_id, owner))
        db.commit()
        _after(owner, [med["task_id"]] if med["task_id"] else [])
    finally:
        db.close()


@router.post("/{med_id}/log", status_code=201)
def log_med(med_id: int, body: LogIn, request: Request):
    """Log a dose taken or missed, a change (new patch, ring in or out, a shot, a new implant) or a refill.
    A refill with a cost adds it to expenses (Health & safety)."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        med = _get(db, med_id, owner)
        if not med:
            raise HTTPException(status_code=404, detail="Not found")
        when = body.date or date.today()
        if body.kind == LogKind.TAKEN and db.execute(
                "SELECT 1 FROM med_logs WHERE med_id = ? AND date = ? AND kind = 'taken'", (med_id, when.isoformat())).fetchone():
            return _out(db, med)   # already logged today
        db.execute("INSERT INTO med_logs (med_id, owner_id, date, kind, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (med_id, owner, when.isoformat(), body.kind.value, (body.note or "").strip() or None, _now()))
        if body.kind == LogKind.CHANGED and med["method"] == Method.RING.value:
            # Putting a ring in starts a new three weeks; taking it out starts the week off.
            ring = status(db, med, when)["ring"]
            first_in = when if ring != "in" else when - timedelta(days=RING_IN)
            db.execute("UPDATE med_schedules SET started_on = ? WHERE id = ?", (first_in.isoformat(), med_id))
        cost = body.cost if body.cost is not None else med["cost"]
        if body.kind == LogKind.REFILLED and cost:
            db.execute("INSERT INTO expenses (description, amount, category, date, owner_id, created_at, source) "
                       "VALUES (?, ?, 'health', ?, ?, ?, 'meds')",
                       ("Health refill" if med["discreet"] else f"{med['name']} refill", cost,
                        datetime(when.year, when.month, when.day, 12, tzinfo=timezone.utc).isoformat(timespec="seconds"),
                        owner, _now()))
        tasks = _sync_task(db, med_id, owner)
        db.commit()
        _after(owner, tasks)
        return _out(db, _get(db, med_id, owner))
    finally:
        db.close()
