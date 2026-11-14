"""
Arrangements: a client's regular allowance (sugar dating, a regular with a retainer). Each contact can have one:
an amount and how often (per meet, weekly, every two weeks, monthly), and when it's next due. A due allowance
gets a reminder task; marking it received logs the income (kind "allowance", from that contact) and moves the
due date on. A per-meet allowance has no schedule: log it when you meet.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import calendar_sync

router = APIRouter()
_get_db: Optional[Callable] = None
CADENCES = ("per_meet", "weekly", "biweekly", "monthly")


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year, month = d.year + month // 12, month % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue


def next_after(d: date, cadence: str) -> Optional[date]:
    if cadence == "weekly":
        return d + timedelta(days=7)
    if cadence == "biweekly":
        return d + timedelta(days=14)
    if cadence == "monthly":
        return _add_months(d, 1)
    return None


class ArrangementIn(BaseModel):
    amount: Optional[float] = None
    cadence: str = "monthly"
    next_due: Optional[date] = None
    notes: Optional[str] = None
    active: bool = True


class ReceivedIn(BaseModel):
    amount: Optional[float] = None      # this time, if different
    date: Optional[datetime] = None


def _get(db, owner: int, client_id: int) -> Optional[dict]:
    r = db.execute("""
        SELECT a.*, c.display_name AS client_name FROM arrangements a JOIN clients c ON c.id = a.client_id
        WHERE a.owner_id = ? AND a.client_id = ?
    """, (owner, client_id)).fetchone()
    return {**dict(r), "active": bool(r["active"])} if r else None


def _sync_task(db, owner: int, client_id: int) -> List[int]:
    """One open reminder task on the due date of an active, scheduled allowance; none otherwise."""
    a = _get(db, owner, client_id)
    if not a:
        return []
    task = db.execute("SELECT id FROM tasks WHERE id = ? AND owner_id = ?", (a["task_id"], owner)).fetchone() if a["task_id"] else None
    if not (a["active"] and a["next_due"] and a["cadence"] != "per_meet"):
        db.execute("UPDATE arrangements SET task_id = NULL WHERE id = ?", (a["id"],))
        if task and db.execute("DELETE FROM tasks WHERE id = ? AND done_at IS NULL", (task["id"],)).rowcount:
            return [task["id"]]
        return []
    title = f"Allowance due from {a['client_name']}"
    notes = f"${a['amount']:.2f}" if a["amount"] else None
    now = _now()
    if task:
        db.execute("UPDATE tasks SET title = ?, notes = ?, due_date = ?, done_at = NULL, client_id = ?, updated_at = ? WHERE id = ?",
                   (title, notes, a["next_due"], client_id, now, task["id"]))
        return [task["id"]]
    cur = db.execute("INSERT INTO tasks (title, notes, due_date, client_id, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (title, notes, a["next_due"], client_id, owner, now, now))
    db.execute("UPDATE arrangements SET task_id = ? WHERE id = ?", (cur.lastrowid, a["id"]))
    return [cur.lastrowid]


def _after(owner: int, task_ids: List[int]):
    for task_id in task_ids:
        calendar_sync.queue_item("task", task_id, owner)


def _client(db, owner: int, client_id: int):
    if not db.execute("SELECT 1 FROM clients WHERE id = ? AND owner_id = ?", (client_id, owner)).fetchone():
        raise HTTPException(status_code=404, detail="Contact not found")


@router.get("/api/arrangements")
def list_arrangements(request: Request):
    """Every arrangement, soonest due first."""
    db = _get_db()
    try:
        owner = request.state.user["id"]
        return [{**dict(r), "active": bool(r["active"])} for r in db.execute("""
            SELECT a.*, c.display_name AS client_name FROM arrangements a JOIN clients c ON c.id = a.client_id
            WHERE a.owner_id = ? ORDER BY a.active DESC, a.next_due IS NULL, a.next_due
        """, (owner,))]
    finally:
        db.close()


@router.get("/api/clients/{client_id}/arrangement")
def get_arrangement(client_id: int, request: Request):
    db = _get_db()
    try:
        owner = request.state.user["id"]
        _client(db, owner, client_id)
        return _get(db, owner, client_id)
    finally:
        db.close()


@router.put("/api/clients/{client_id}/arrangement")
def save_arrangement(client_id: int, body: ArrangementIn, request: Request):
    if body.cadence not in CADENCES:
        raise HTTPException(status_code=400, detail="How often: per meet, weekly, every two weeks or monthly")
    if body.amount is not None and not 0 <= body.amount < 1e9:
        raise HTTPException(status_code=400, detail="The amount must be 0 or more")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _client(db, owner, client_id)
        next_due = body.next_due.isoformat() if body.next_due and body.cadence != "per_meet" else None
        notes = (body.notes or "").strip()[:1000] or None
        now = _now()
        db.execute("""
            INSERT INTO arrangements (owner_id, client_id, amount, cadence, next_due, notes, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET amount = excluded.amount, cadence = excluded.cadence,
                next_due = excluded.next_due, notes = excluded.notes, active = excluded.active, updated_at = excluded.updated_at
        """, (owner, client_id, body.amount, body.cadence, next_due, notes, int(body.active), now, now))
        tasks = _sync_task(db, owner, client_id)
        db.commit()
        _after(owner, tasks)
        return _get(db, owner, client_id)
    finally:
        db.close()


@router.delete("/api/clients/{client_id}/arrangement", status_code=204)
def delete_arrangement(client_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        a = _get(db, owner, client_id)
        if not a:
            return
        if a["task_id"]:
            db.execute("DELETE FROM tasks WHERE id = ? AND owner_id = ? AND done_at IS NULL", (a["task_id"], owner))
        db.execute("DELETE FROM arrangements WHERE id = ?", (a["id"],))
        db.commit()
        _after(owner, [a["task_id"]] if a["task_id"] else [])
    finally:
        db.close()


@router.post("/api/clients/{client_id}/arrangement/received", status_code=201)
def received(client_id: int, body: ReceivedIn, request: Request):
    """The allowance came in: logged as income from this contact, and the next one is due a period later."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        a = _get(db, owner, client_id)
        if not a:
            raise HTTPException(status_code=404, detail="No arrangement with this contact")
        amount = body.amount if body.amount is not None else a["amount"]
        if amount is None or not 0 < amount < 1e9:
            raise HTTPException(status_code=400, detail="Enter the amount received")
        when = body.date or datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        now = _now()
        cur = db.execute("""
            INSERT INTO income (date, description, kind, gross, fees, status, client_id, owner_id, created_at, updated_at)
            VALUES (?, ?, 'allowance', ?, 0, 'received', ?, ?, ?, ?)
        """, (when.astimezone(timezone.utc).isoformat(timespec="seconds"), "Allowance", round(amount, 2), client_id, owner, now, now))
        if a["next_due"] and a["cadence"] != "per_meet":
            due = date.fromisoformat(a["next_due"])
            nxt = next_after(due, a["cadence"])
            # Paid well ahead or catching up: keep moving on until the next one is after this payment's period.
            while nxt and nxt <= when.date():
                nxt = next_after(nxt, a["cadence"])
            db.execute("UPDATE arrangements SET next_due = ?, updated_at = ? WHERE id = ?", (nxt.isoformat(), now, a["id"]))
        tasks = _sync_task(db, owner, client_id)
        db.commit()
        _after(owner, tasks)
        return {"income_id": cur.lastrowid, "arrangement": _get(db, owner, client_id)}
    finally:
        db.close()
