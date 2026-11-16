"""
Documents that expire: a license or work card, ID or passport, a health card, a platform's ID verification,
insurance. sworkr keeps one reminder task for each, some days before it runs out (30 unless changed).

Only what's needed to remember a renewal is kept: a name, dates and notes. There's deliberately no field for
an ID or license number; keep those in the document itself, not here.

A license or work card is paid to the government or a licensing office, not to a workplace, so it lives here. Renewing
one moves its date and, if it cost something, logs that as an ordinary expense under Fees & licenses.

The list also shows the renewal dates set on a place's own yearly charges, so everything that runs out is in one
place, without entering it twice.
"""

import datetime as dt
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import calendar_sync
import finance

router = APIRouter(prefix="/api/documents")
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Kind(str, Enum):
    LICENSE = "license"
    WORK_CARD = "work_card"
    ID = "id"
    PASSPORT = "passport"
    HEALTH_CARD = "health_card"
    VERIFICATION = "verification"   # a platform's ID check
    INSURANCE = "insurance"
    OTHER = "other"


class DocumentIn(BaseModel):
    name: str
    kind: Kind = Kind.OTHER
    issued_on: Optional[dt.date] = None
    expires_on: Optional[dt.date] = None
    remind_days_before: int = 30
    source_id: Optional[int] = None     # the place it's for, if any
    persona_id: Optional[int] = None    # the name it's under, if any
    notes: Optional[str] = None


def _get(db, doc_id: int, owner_id: int) -> Optional[dict]:
    r = db.execute("""
        SELECT d.*, s.name AS place_name FROM documents d LEFT JOIN income_sources s ON s.id = d.source_id
        WHERE d.id = ? AND d.owner_id = ?
    """, (doc_id, owner_id)).fetchone()
    return dict(r) if r else None


def _validate(db, owner_id: int, body: DocumentIn) -> DocumentIn:
    body.name = (body.name or "").strip()
    if not body.name or len(body.name) > 80:
        raise HTTPException(status_code=400, detail="Give it a name (up to 80 characters)")
    if not (0 <= body.remind_days_before <= 365):
        raise HTTPException(status_code=400, detail="Remind between 0 and 365 days before")
    if body.issued_on and body.expires_on and body.expires_on < body.issued_on:
        raise HTTPException(status_code=400, detail="It can't run out before it was issued")
    if body.source_id is not None and not db.execute("SELECT 1 FROM income_sources WHERE id = ? AND owner_id = ?",
                                                     (body.source_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That place doesn't exist")
    if body.persona_id is not None and not db.execute("SELECT 1 FROM personas WHERE id = ? AND owner_id = ?",
                                                      (body.persona_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That persona doesn't exist")
    body.notes = (body.notes or "").strip()[:2000] or None
    return body


def _values(b: DocumentIn) -> tuple:
    return (b.name, b.kind.value, b.issued_on.isoformat() if b.issued_on else None,
            b.expires_on.isoformat() if b.expires_on else None, b.remind_days_before, b.source_id, b.persona_id, b.notes)


def _sync_task(db, doc_id: int, owner_id: int) -> List[int]:
    """One open reminder task while it has an expiry date. Returns task ids for calendar sync."""
    d = _get(db, doc_id, owner_id)
    if not d:
        return []
    task = db.execute("SELECT id FROM tasks WHERE id = ? AND owner_id = ?", (d["task_id"], owner_id)).fetchone() \
        if d["task_id"] else None
    if not d["expires_on"]:
        db.execute("UPDATE documents SET task_id = NULL WHERE id = ?", (doc_id,))
        if task:
            db.execute("DELETE FROM tasks WHERE id = ? AND done_at IS NULL", (task["id"],))
            return [task["id"]]
        return []
    expires = date.fromisoformat(d["expires_on"])
    due = max(expires - timedelta(days=d["remind_days_before"]), min(date.today(), expires))
    title = f"Renew {d['name']}"
    notes = f"Runs out on {expires.isoformat()}."
    now = _now()
    if task:
        db.execute("UPDATE tasks SET title = ?, notes = ?, due_date = ?, "
                   "done_at = CASE WHEN due_date = ? THEN done_at END, updated_at = ? WHERE id = ?",
                   (title, notes, due.isoformat(), due.isoformat(), now, task["id"]))
        return [task["id"]]
    cur = db.execute("INSERT INTO tasks (title, notes, due_date, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (title, notes, due.isoformat(), owner_id, now, now))
    db.execute("UPDATE documents SET task_id = ? WHERE id = ?", (cur.lastrowid, doc_id))
    return [cur.lastrowid]


def _after(owner_id: int, task_ids: List[int]):
    for task_id in task_ids:
        calendar_sync.queue_item("task", task_id, owner_id)


def _days_left(expires_on: Optional[str]) -> Optional[int]:
    return (date.fromisoformat(expires_on) - date.today()).days if expires_on else None


@router.get("")
def list_documents(request: Request):
    """Your documents, soonest to run out first, then renewal dates from places' charges (read-only here)."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        docs = [{**dict(r), "days_left": _days_left(r["expires_on"])} for r in db.execute("""
            SELECT d.*, s.name AS place_name FROM documents d LEFT JOIN income_sources s ON s.id = d.source_id
            WHERE d.owner_id = ? ORDER BY d.expires_on IS NULL, d.expires_on, d.name COLLATE NOCASE
        """, (owner,))]
        charges = [{"charge_id": r["id"], "name": r["label"], "place_name": r["place_name"], "source_id": r["source_id"],
                    "expires_on": r["renews_on"], "days_left": _days_left(r["renews_on"]), "cadence": r["cadence"]}
                   for r in db.execute("""
            SELECT c.id, c.label, c.renews_on, c.cadence, c.source_id, s.name AS place_name
            FROM place_charges c JOIN income_sources s ON s.id = c.source_id
            WHERE c.owner_id = ? AND c.renews_on IS NOT NULL ORDER BY c.renews_on
        """, (owner,))]
        return {"documents": docs, "from_places": charges}
    finally:
        db.close()


@router.post("", status_code=201)
def create_document(body: DocumentIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _validate(db, owner, body)
        now = _now()
        cur = db.execute("""
            INSERT INTO documents (name, kind, issued_on, expires_on, remind_days_before, source_id, persona_id, notes,
                                   owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_values(body), owner, now, now))
        tasks = _sync_task(db, cur.lastrowid, owner)
        db.commit()
        _after(owner, tasks)
        return _get(db, cur.lastrowid, owner)
    finally:
        db.close()


@router.put("/{doc_id}")
def update_document(doc_id: int, body: DocumentIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        if not _get(db, doc_id, owner):
            raise HTTPException(status_code=404, detail="Not found")
        _validate(db, owner, body)
        db.execute("""
            UPDATE documents SET name = ?, kind = ?, issued_on = ?, expires_on = ?, remind_days_before = ?,
                   source_id = ?, persona_id = ?, notes = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_values(body), _now(), doc_id, owner))
        tasks = _sync_task(db, doc_id, owner)
        db.commit()
        _after(owner, tasks)
        return _get(db, doc_id, owner)
    finally:
        db.close()


class RenewedIn(BaseModel):
    expires_on: dt.date                 # the new date it runs out
    paid: Optional[float] = None        # what the renewal cost
    paid_to: Optional[str] = None       # who was paid: the county, the state board
    paid_on: Optional[dt.date] = None   # left out: today


@router.post("/{doc_id}/renewed")
def renewed(doc_id: int, body: RenewedIn, request: Request):
    """It was renewed: the new expiry date (and its reminder), and what it cost, as an expense."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        d = _get(db, doc_id, owner)
        if not d:
            raise HTTPException(status_code=404, detail="Not found")
        paid_on = body.paid_on or date.today()
        if body.expires_on <= paid_on:
            raise HTTPException(status_code=400, detail="The new date has to be after the day you renewed it")
        if body.paid is not None and not (0 <= body.paid < 1e9):
            raise HTTPException(status_code=400, detail="What you paid must be 0 or more")
        db.execute("UPDATE documents SET issued_on = ?, expires_on = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                   (paid_on.isoformat(), body.expires_on.isoformat(), _now(), doc_id, owner))
        if body.paid:
            lookup = finance.category_lookup(db, owner)
            category = lookup.get("licenses & permits") or lookup.get("fees & licenses > licenses & permits") or "fees"
            to = (body.paid_to or "").strip()[:80]
            db.execute("""
                INSERT INTO expenses (description, amount, category, date, notes, owner_id, created_at, currency)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'USD')
            """, (f"{d['name']} renewal", round(body.paid, 2), category, f"{paid_on.isoformat()}T12:00:00+00:00",
                  f"Paid to {to}" if to else None, owner, _now()))
        tasks = _sync_task(db, doc_id, owner)
        db.commit()
        _after(owner, tasks)
        return _get(db, doc_id, owner)
    finally:
        db.close()


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        d = _get(db, doc_id, owner)
        if not d:
            return
        if d["task_id"]:
            db.execute("DELETE FROM tasks WHERE id = ? AND owner_id = ? AND done_at IS NULL", (d["task_id"], owner))
        db.execute("DELETE FROM documents WHERE id = ? AND owner_id = ?", (doc_id, owner))
        db.commit()
        _after(owner, [d["task_id"]] if d["task_id"] else [])
    finally:
        db.close()
