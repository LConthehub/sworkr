"""
Drivers and their rates. A driver (or anyone you pay to get you places) is a contact you work with, and each
keeps their own price list: "Airport run, $60 a trip", "Waiting, $30 an hour", "Per mile, $2".

On a booking, a ride with one of those rates is logged as a travel expense on the booking's day (so it counts in
that tour's budget and in your money), linked to the booking.
"""

from datetime import datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import finance

router = APIRouter()
_get_db: Optional[Callable] = None
UNITS = ("trip", "hour", "mile", "km", "day")


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RateIn(BaseModel):
    label: str                 # "Airport run", "Hotel to home", "Waiting"
    amount: float
    unit: str = "trip"


def _contact(db, owner: int, contact_id: int):
    r = db.execute("SELECT id, display_name FROM clients WHERE id = ? AND owner_id = ?", (contact_id, owner)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Contact not found")
    return r


def _rates(db, owner: int, contact_id: int) -> List[dict]:
    return [dict(r) for r in db.execute(
        "SELECT id, label, amount, unit FROM driver_rates WHERE owner_id = ? AND contact_id = ? ORDER BY sort_order, id",
        (owner, contact_id))]


def _check(body: RateIn) -> RateIn:
    body.label = (body.label or "").strip()[:80]
    if not body.label:
        raise HTTPException(status_code=400, detail="Name the rate, like Airport run")
    if not 0 <= body.amount < 1e6:
        raise HTTPException(status_code=400, detail="The rate must be 0 or more")
    if body.unit not in UNITS:
        raise HTTPException(status_code=400, detail="Per trip, hour, mile, km or day")
    return body


@router.get("/api/drivers")
def drivers(request: Request):
    """Everyone with rates, for choosing a ride."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        out = []
        for c in db.execute("SELECT DISTINCT c.id, c.display_name FROM clients c JOIN driver_rates r ON r.contact_id = c.id "
                            "WHERE c.owner_id = ? ORDER BY c.display_name COLLATE NOCASE", (owner,)):
            out.append({"id": c["id"], "name": c["display_name"], "rates": _rates(db, owner, c["id"])})
        return out
    finally:
        db.close()


@router.get("/api/clients/{contact_id}/rates")
def list_rates(contact_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _contact(db, owner, contact_id)
        return _rates(db, owner, contact_id)
    finally:
        db.close()


@router.post("/api/clients/{contact_id}/rates", status_code=201)
def add_rate(contact_id: int, body: RateIn, request: Request):
    _check(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _contact(db, owner, contact_id)
        order = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM driver_rates WHERE contact_id = ?", (contact_id,)).fetchone()[0]
        db.execute("INSERT INTO driver_rates (owner_id, contact_id, label, amount, unit, sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (owner, contact_id, body.label, round(body.amount, 2), body.unit, order, _now()))
        db.commit()
        return _rates(db, owner, contact_id)
    finally:
        db.close()


@router.delete("/api/clients/{contact_id}/rates/{rate_id}", status_code=204)
def delete_rate(contact_id: int, rate_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM driver_rates WHERE id = ? AND contact_id = ? AND owner_id = ?",
                   (rate_id, contact_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


class RideIn(BaseModel):
    rate_id: int
    quantity: float = 1        # trips, hours, miles…
    note: Optional[str] = None


@router.post("/api/appointments/{appointment_id}/ride", status_code=201)
def log_ride(appointment_id: int, body: RideIn, request: Request):
    """A ride for this booking: the driver's rate times how much, as a travel expense on the booking's day."""
    owner = request.state.user["id"]
    if not 0 < body.quantity < 10000:
        raise HTTPException(status_code=400, detail="How many trips, hours or miles?")
    db = _get_db()
    try:
        a = db.execute("SELECT id, scheduled_date FROM appointments WHERE id = ? AND owner_id = ?", (appointment_id, owner)).fetchone()
        if not a:
            raise HTTPException(status_code=404, detail="Booking not found")
        rate = db.execute("SELECT r.*, c.display_name FROM driver_rates r JOIN clients c ON c.id = r.contact_id "
                          "WHERE r.id = ? AND r.owner_id = ?", (body.rate_id, owner)).fetchone()
        if not rate:
            raise HTTPException(status_code=404, detail="Rate not found")
        amount = round(rate["amount"] * body.quantity, 2)
        lookup = finance.category_lookup(db, owner)
        category = lookup.get("rides") or lookup.get("travel > rides") or lookup.get("travel") or "travel"
        qty = "" if body.quantity == 1 and rate["unit"] == "trip" else f" ({body.quantity:g} {rate['unit']}{'' if body.quantity == 1 else 's'})"
        cur = db.execute("""
            INSERT INTO expenses (description, amount, category, date, notes, owner_id, created_at, currency, appointment_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'USD', ?)
        """, (f"Ride: {rate['label']}{qty} – {rate['display_name']}", amount, category, a["scheduled_date"],
              (body.note or "").strip()[:300] or None, owner, _now(), appointment_id))
        db.commit()
        return {"expense_id": cur.lastrowid, "amount": amount, "category": category}
    finally:
        db.close()
