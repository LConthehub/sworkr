"""
Inquiries: people who got in touch, from the first message to a booking (or to nothing).

Each inquiry moves through stages: new, replied, screening, deposit, booked. Any of them can be marked lost,
with a reason, and remembers the stage it was lost from. That makes two things visible that are otherwise
guesswork: where inquiries drop out, and which ad sites and accounts send people who actually book.

An inquiry can be linked to a contact once the person is worth keeping. Nothing here sends a message: replies
are written and sent by the person, with their saved text one tap away.
"""

from datetime import datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import marketing

router = APIRouter()
_get_db: Optional[Callable] = None

STAGES = ("new", "replied", "screening", "deposit", "booked")
LOST = "lost"
OPEN = STAGES[:-1]


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _owner(request: Request) -> int:
    return request.state.user["id"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _clean(text: Optional[str], limit: int = 5000) -> Optional[str]:
    return (text or "").strip()[:limit] or None


class InquiryIn(BaseModel):
    name: str                             # whatever they go by: a name, a handle
    contact: Optional[str] = None         # how to reach them: a number, an email, a handle
    found_via: Optional[str] = None       # where they came from (same idea as on a contact)
    received_at: Optional[datetime] = None
    wanted: Optional[str] = None          # what they asked for
    wanted_date: Optional[datetime] = None
    stage: str = "new"
    lost_reason: Optional[str] = None
    client_id: Optional[int] = None       # the contact they became
    notes: Optional[str] = None


class StageIn(BaseModel):
    stage: str
    lost_reason: Optional[str] = None


SELECT = """
    SELECT e.*, c.display_name AS client_name FROM inquiries e LEFT JOIN clients c ON c.id = e.client_id
"""


def _get(db, inquiry_id: int, owner_id: int) -> Optional[dict]:
    r = db.execute(SELECT + " WHERE e.id = ? AND e.owner_id = ?", (inquiry_id, owner_id)).fetchone()
    return dict(r) if r else None


def _check_stage(stage: str):
    if stage not in STAGES and stage != LOST:
        raise HTTPException(status_code=400, detail="The stage is new, replied, screening, deposit, booked or lost")


def _lost_from(stage: str, before: Optional[dict]) -> Optional[str]:
    """The stage an inquiry was in when it was lost (kept if it was lost already)."""
    if stage != LOST:
        return None
    if before is None:
        return "new"
    return before["lost_from"] if before["stage"] == LOST else before["stage"]


def _values(db, owner_id: int, body: InquiryIn, before: Optional[dict] = None) -> tuple:
    name = _clean(body.name, 120)
    if not name:
        raise HTTPException(status_code=400, detail="Who is it from? A name or a handle is enough")
    _check_stage(body.stage)
    if body.client_id is not None and not db.execute(
            "SELECT 1 FROM clients WHERE id = ? AND owner_id = ?", (body.client_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That contact doesn't exist")
    return (name, _clean(body.contact, 200), marketing.clean_found_via(body.found_via),
            _iso(body.received_at) or (before["received_at"] if before else _now()), _clean(body.wanted), _iso(body.wanted_date),
            body.stage, _lost_from(body.stage, before), _clean(body.lost_reason, 300) if body.stage == LOST else None,
            body.client_id, _clean(body.notes))


@router.get("/api/inquiries")
def list_inquiries(request: Request, show: str = Query("open", description="open, booked, lost or all"),
                   limit: int = Query(500, ge=1, le=2000)):
    wheres = {"open": f"e.stage IN ({', '.join(repr(s) for s in OPEN)})", "booked": "e.stage = 'booked'",
              "lost": "e.stage = 'lost'", "all": "1 = 1"}
    if show not in wheres:
        raise HTTPException(status_code=400, detail="show must be open, booked, lost or all")
    db = _get_db()
    try:
        return [dict(r) for r in db.execute(
            SELECT + f" WHERE e.owner_id = ? AND {wheres[show]} ORDER BY e.received_at DESC, e.id DESC LIMIT ?",
            (_owner(request), limit))]
    finally:
        db.close()


@router.post("/api/inquiries", status_code=201)
def create_inquiry(body: InquiryIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        cur = db.execute("""
            INSERT INTO inquiries (name, contact, found_via, received_at, wanted, wanted_date, stage, lost_from, lost_reason,
                                   client_id, notes, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_values(db, owner, body), owner, _now(), _now()))
        db.commit()
        return _get(db, cur.lastrowid, owner)
    finally:
        db.close()


@router.put("/api/inquiries/{inquiry_id}")
def update_inquiry(inquiry_id: int, body: InquiryIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        before = _get(db, inquiry_id, owner)
        if not before:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        db.execute("""
            UPDATE inquiries SET name = ?, contact = ?, found_via = ?, received_at = ?, wanted = ?, wanted_date = ?, stage = ?,
                   lost_from = ?, lost_reason = ?, client_id = ?, notes = ?, updated_at = ? WHERE id = ? AND owner_id = ?
        """, (*_values(db, owner, body, before), _now(), inquiry_id, owner))
        db.commit()
        return _get(db, inquiry_id, owner)
    finally:
        db.close()


@router.post("/api/inquiries/{inquiry_id}/stage")
def move_inquiry(inquiry_id: int, body: StageIn, request: Request):
    """Move it along (or mark it lost, with why). The quick buttons use this."""
    _check_stage(body.stage)
    owner = _owner(request)
    db = _get_db()
    try:
        before = _get(db, inquiry_id, owner)
        if not before:
            raise HTTPException(status_code=404, detail="Inquiry not found")
        db.execute("UPDATE inquiries SET stage = ?, lost_from = ?, lost_reason = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                   (body.stage, _lost_from(body.stage, before), _clean(body.lost_reason, 300) if body.stage == LOST else None,
                    _now(), inquiry_id, owner))
        db.commit()
        return _get(db, inquiry_id, owner)
    finally:
        db.close()


@router.delete("/api/inquiries/{inquiry_id}", status_code=204)
def delete_inquiry(inquiry_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM inquiries WHERE id = ? AND owner_id = ?", (inquiry_id, _owner(request)))
        db.commit()
    finally:
        db.close()


@router.get("/api/inquiries/summary")
def summary(request: Request, start: datetime = Query(...), end: datetime = Query(...)):
    """
    Of the inquiries received between start and end: how many got as far as each stage, how many are still open,
    why the lost ones were lost, and for each place they came from, how many booked.
    """
    if end <= start:
        raise HTTPException(status_code=400, detail="The end must be after the start")
    db = _get_db()
    try:
        rows: List[dict] = [dict(r) for r in db.execute(
            "SELECT stage, lost_from, lost_reason, found_via FROM inquiries WHERE owner_id = ? AND received_at >= ? AND received_at < ?",
            (_owner(request), _iso(start), _iso(end)))]
    finally:
        db.close()
    reached = [STAGES.index((r["lost_from"] or "new") if r["stage"] == LOST else r["stage"]) for r in rows]
    funnel = [{"stage": s, "count": sum(1 for got in reached if got >= i)} for i, s in enumerate(STAGES)]
    total = len(rows)
    booked = sum(r["stage"] == "booked" for r in rows)
    reasons, sources, spellings = {}, {}, {}
    for r in rows:
        if r["stage"] == LOST:
            reason = r["lost_reason"] or "No reason given"
            reasons[reason] = reasons.get(reason, 0) + 1
        key = marketing.source_key(r["found_via"])
        s = sources.setdefault(key, {"key": key, "label": "Not recorded", "inquiries": 0, "booked": 0, "lost": 0})
        s["inquiries"] += 1
        s["booked"] += r["stage"] == "booked"
        s["lost"] += r["stage"] == LOST
        if key != marketing.NOT_RECORDED:
            counts = spellings.setdefault(key, {})
            counts[r["found_via"]] = counts.get(r["found_via"], 0) + 1
    for key, counts in spellings.items():
        sources[key]["label"] = marketing._most_used(counts)
    for s in sources.values():
        s["rate"] = round(s["booked"] / s["inquiries"], 4)
    return {
        "total": total, "booked": booked, "lost": sum(r["stage"] == LOST for r in rows),
        "open": sum(r["stage"] in OPEN for r in rows), "rate": round(booked / total, 4) if total else None,
        "funnel": funnel,
        "lost_reasons": sorted(({"reason": k, "count": v} for k, v in reasons.items()), key=lambda x: (-x["count"], x["reason"])),
        "sources": sorted(sources.values(), key=lambda s: (s["key"] == marketing.NOT_RECORDED, -s["inquiries"], s["label"].lower())),
    }
