"""
Rates and deposits.

The rate card is the list of what a person charges: a service, how long it is, the price, and which of their
names it's under. It fills in a booking's length and price, and copies as text to send to someone asking.

Two lists come from comparing it with the calendar:
- deposits to collect: bookings ahead where the deposit (the booking policy's percentage) hasn't come in yet.
- on an old rate: clients whose last booking of a service cost less than the card says now. Useful before
  telling regulars about a new price, or for deciding who keeps the old one.
"""

from datetime import datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import noshow
import personas

router = APIRouter()
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _owner(request: Request) -> int:
    return request.state.user["id"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RateIn(BaseModel):
    label: str                            # the service, as it's written on bookings: "Dinner date"
    minutes: Optional[int] = None
    price: float
    notes: Optional[str] = None           # "incall", "outcall +$100", "2 hour minimum"
    persona_id: Optional[int] = None
    archived: bool = False


def _values(db, owner_id: int, body: RateIn) -> tuple:
    label = " ".join((body.label or "").split())[:120]
    if not label:
        raise HTTPException(status_code=400, detail="Say what the rate is for")
    if not (0 <= body.price < 1e9):
        raise HTTPException(status_code=400, detail="The price must be 0 or more")
    if body.minutes is not None and not (1 <= body.minutes <= 60 * 24 * 14):
        raise HTTPException(status_code=400, detail="The length is in minutes, up to two weeks")
    return (label, body.minutes, round(body.price, 2), (body.notes or "").strip()[:300] or None,
            personas.check(db, owner_id, body.persona_id), int(body.archived))


def _rows(db, owner_id: int, rate_id: Optional[int] = None) -> List[dict]:
    return [{**dict(r), "archived": bool(r["archived"])} for r in db.execute("""
        SELECT r.*, p.name AS persona_name FROM rates r LEFT JOIN personas p ON p.id = r.persona_id
        WHERE r.owner_id = ? AND (? IS NULL OR r.id = ?)
        ORDER BY r.archived, p.name IS NULL DESC, p.name COLLATE NOCASE, r.minutes IS NULL, r.minutes, r.price, r.id
    """, (owner_id, rate_id, rate_id))]


@router.get("/api/rates")
def list_rates(request: Request):
    db = _get_db()
    try:
        return _rows(db, _owner(request))
    finally:
        db.close()


@router.post("/api/rates", status_code=201)
def add_rate(body: RateIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        cur = db.execute("INSERT INTO rates (label, minutes, price, notes, persona_id, archived, owner_id, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (*_values(db, owner, body), owner, _now(), _now()))
        db.commit()
        return _rows(db, owner, cur.lastrowid)[0]
    finally:
        db.close()


@router.put("/api/rates/{rate_id}")
def update_rate(rate_id: int, body: RateIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        done = db.execute("UPDATE rates SET label = ?, minutes = ?, price = ?, notes = ?, persona_id = ?, archived = ?, updated_at = ? "
                          "WHERE id = ? AND owner_id = ?", (*_values(db, owner, body), _now(), rate_id, owner))
        if not done.rowcount:
            raise HTTPException(status_code=404, detail="Rate not found")
        db.commit()
        return _rows(db, owner, rate_id)[0]
    finally:
        db.close()


@router.delete("/api/rates/{rate_id}", status_code=204)
def delete_rate(rate_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM rates WHERE id = ? AND owner_id = ?", (rate_id, _owner(request)))
        db.commit()
    finally:
        db.close()


@router.get("/api/rates/deposits")
def deposits(request: Request):
    """
    Bookings ahead and their deposits, soonest first: what the deposit is (your policy's percentage of the
    rate), what's been paid, and what's still to come in. With no deposit percentage set, nothing is due.
    """
    owner = _owner(request)
    db = _get_db()
    try:
        percent = noshow.policy(db, owner)["deposit_percent"]
        rows = db.execute("""
            SELECT a.id, a.client_id, a.scheduled_date, a.service_type, a.rate, a.amount_paid, c.display_name AS client_name
            FROM appointments a LEFT JOIN clients c ON c.id = a.client_id
            WHERE a.owner_id = ? AND a.kind = 'client' AND a.status = 'scheduled' AND a.scheduled_date >= ? AND a.rate > 0
            ORDER BY a.scheduled_date
        """, (owner, _now())).fetchall()
    finally:
        db.close()
    out, held = [], 0.0
    for r in rows:
        due = round(r["rate"] * percent / 100, 2)
        paid = r["amount_paid"] or 0
        held += paid
        if due > 0 and paid + 0.005 < due:
            out.append({**dict(r), "deposit": due, "missing": round(due - paid, 2)})
    return {"deposit_percent": percent, "to_collect": out, "missing": round(sum(o["missing"] for o in out), 2),
            "held": round(held, 2), "bookings_ahead": len(rows)}


@router.get("/api/rates/behind")
def behind(request: Request):
    """
    Clients whose latest booking of a service on your rate card (same name and length) was at a lower price
    than the card says now. The biggest gaps first.
    """
    owner = _owner(request)
    db = _get_db()
    try:
        card = {}
        for r in _rows(db, owner):
            if not r["archived"] and r["minutes"]:
                key = (r["label"].casefold(), r["minutes"])
                card[key] = max(card.get(key, 0), r["price"])        # the same service under two names: the higher price
        latest = db.execute("""
            SELECT a.client_id, c.display_name AS client_name, a.service_type, a.duration_minutes, a.rate, a.scheduled_date,
                   (SELECT COUNT(*) FROM appointments n WHERE n.client_id = a.client_id AND n.status != 'cancelled' AND n.kind = 'client') AS bookings
            FROM appointments a JOIN clients c ON c.id = a.client_id
            WHERE a.owner_id = ? AND a.kind = 'client' AND a.status != 'cancelled' AND a.rate > 0
              AND c.is_active = 1 AND c.do_not_see = 0
              AND a.scheduled_date = (SELECT MAX(b.scheduled_date) FROM appointments b
                                      WHERE b.client_id = a.client_id AND b.kind = 'client' AND b.status != 'cancelled' AND b.rate > 0
                                        AND LOWER(b.service_type) = LOWER(a.service_type) AND b.duration_minutes = a.duration_minutes)
        """, (owner,)).fetchall()
    finally:
        db.close()
    out = []
    for r in latest:
        now_price = card.get(((r["service_type"] or "").strip().casefold(), r["duration_minutes"]))
        if now_price and r["rate"] + 0.005 < now_price:
            out.append({"client_id": r["client_id"], "client_name": r["client_name"], "service": r["service_type"],
                        "minutes": r["duration_minutes"], "their_rate": r["rate"], "card_rate": now_price,
                        "gap": round(now_price - r["rate"], 2), "last_booked": r["scheduled_date"], "bookings": r["bookings"]})
    out.sort(key=lambda o: (-o["gap"], o["client_name"].lower()))
    return out
