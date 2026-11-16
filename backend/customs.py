"""
Custom content: made-to-order photos and videos, from the request to the delivery.

An order records who asked, what they want, the price, what's been paid, when it's due and where it stands:
requested, quoted, to make, delivered (or declined). Taking a payment adds it to the order and writes it into
income as a sale, with the platform's fee worked out from the place it was paid through. Two things are kept in
view because they're the ones that go wrong: orders being made before they're paid for, and paid orders that
are running late.

A menu holds the usual prices ("5 minute video", "say my name"), to quote from and to copy as text.

The finished files stay in the person's own library; an order can only point at the folder they're in.
"""

from datetime import date, datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import finance
import personas

router = APIRouter()
_get_db: Optional[Callable] = None

STATUSES = ("requested", "quoted", "to_make", "delivered", "declined")
OPEN = ("requested", "quoted", "to_make")


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


def _clean(text: Optional[str], limit: int = 10000) -> Optional[str]:
    return (text or "").strip()[:limit] or None


def _money_ok(value: Optional[float]) -> bool:
    return value is None or 0 <= value < float("inf")


class OrderIn(BaseModel):
    buyer: str                            # a name or a handle
    title: str                            # what it is, in a few words
    details: Optional[str] = None         # the script: what to say, wear, do
    client_id: Optional[int] = None
    source_id: Optional[int] = None       # the place it's paid through (OnlyFans, a clip site, cash app…)
    persona_id: Optional[int] = None
    requested_at: Optional[datetime] = None
    price: Optional[float] = None
    status: str = "requested"
    due_date: Optional[date] = None
    delivery_note: Optional[str] = None   # how and where it was sent
    set_path: Optional[str] = None        # the folder in your library the finished files are in
    can_resell: bool = False              # nothing personal in it, and the buyer didn't pay for it to be theirs alone
    notes: Optional[str] = None


class PaymentIn(BaseModel):
    amount: float
    paid_on: Optional[datetime] = None
    fees: Optional[float] = None          # left out: worked out from the place's fee
    payment_method: Optional[str] = None  # cash, a payment app, the platform…
    log_income: bool = True


class DeliveredIn(BaseModel):
    delivered_at: Optional[datetime] = None
    delivery_note: Optional[str] = None


class StatusIn(BaseModel):
    status: str


class MenuItemIn(BaseModel):
    label: str
    price: Optional[float] = None
    notes: Optional[str] = None


def _row(r, today: date) -> dict:
    d = dict(r)
    d["can_resell"] = bool(d["can_resell"])
    price, paid = d["price"], d["amount_paid"] or 0
    d["owed"] = round(max(price - paid, 0), 2) if price is not None else 0
    d["payment"] = "none" if price is None and not paid else "paid" if price is None or paid >= price else "part" if paid > 0 else "unpaid"
    d["days_left"] = (date.fromisoformat(d["due_date"]) - today).days if d["due_date"] else None
    d["late"] = d["status"] in OPEN and d["days_left"] is not None and d["days_left"] < 0
    return d


SELECT = """
    SELECT o.*, c.display_name AS client_name, s.name AS source_name
    FROM custom_orders o LEFT JOIN clients c ON c.id = o.client_id LEFT JOIN income_sources s ON s.id = o.source_id
"""


def _get(db, order_id: int, owner_id: int) -> Optional[dict]:
    r = db.execute(SELECT + " WHERE o.id = ? AND o.owner_id = ?", (order_id, owner_id)).fetchone()
    return _row(r, datetime.now(timezone.utc).date()) if r else None


def _need(db, order_id: int, owner_id: int) -> dict:
    order = _get(db, order_id, owner_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def _values(db, owner_id: int, body: OrderIn, before: Optional[dict] = None) -> tuple:
    import content
    buyer, title = _clean(body.buyer, 120), _clean(body.title, 200)
    if not buyer or not title:
        raise HTTPException(status_code=400, detail="Say who it's for and what it is")
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")
    if not _money_ok(body.price):
        raise HTTPException(status_code=400, detail="The price must be 0 or more")
    if body.client_id is not None and not db.execute(
            "SELECT 1 FROM clients WHERE id = ? AND owner_id = ?", (body.client_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That contact doesn't exist")
    if body.source_id is not None and not finance.get_source(db, body.source_id, owner_id):
        raise HTTPException(status_code=400, detail="That workplace or platform doesn't exist")
    delivered_at = before["delivered_at"] if before else None
    if body.status == "delivered" and not delivered_at:
        delivered_at = _now()
    if body.status != "delivered":
        delivered_at = None
    return (buyer, title, _clean(body.details), body.client_id, body.source_id, personas.check(db, owner_id, body.persona_id),
            _iso(body.requested_at) or (before["requested_at"] if before else _now()), body.price, body.status,
            body.due_date.isoformat() if body.due_date else None, delivered_at, _clean(body.delivery_note, 500),
            content.clean_path(body.set_path) or None, int(body.can_resell), _clean(body.notes))


@router.get("/api/customs")
def list_orders(request: Request, show: str = Query("open", description="open, delivered, declined or all")):
    """Orders, the ones due soonest first, with what needs attention counted."""
    wheres = {"open": f"o.status IN ({', '.join(repr(s) for s in OPEN)})", "delivered": "o.status = 'delivered'",
              "declined": "o.status = 'declined'", "all": "1 = 1"}
    if show not in wheres:
        raise HTTPException(status_code=400, detail="show must be open, delivered, declined or all")
    owner = _owner(request)
    today = datetime.now(timezone.utc).date()
    db = _get_db()
    try:
        order = "o.delivered_at DESC, o.id DESC" if show == "delivered" else "o.due_date IS NULL, o.due_date, o.requested_at, o.id"
        orders = [_row(r, today) for r in db.execute(SELECT + f" WHERE o.owner_id = ? AND {wheres[show]} ORDER BY {order} LIMIT 1000", (owner,))]
        open_orders = orders if show == "open" else [_row(r, today) for r in db.execute(SELECT + f" WHERE o.owner_id = ? AND {wheres['open']}", (owner,))]
    finally:
        db.close()
    making = [o for o in open_orders if o["status"] == "to_make"]
    return {"orders": orders, "attention": {
        "to_make": len(making), "late": sum(o["late"] for o in open_orders),
        "not_paid": sum(o["payment"] in ("unpaid", "part") for o in making),       # being made before it's paid for
        "paid_waiting": round(sum(o["amount_paid"] or 0 for o in making), 2),        # money taken for work not yet delivered
        "to_answer": sum(o["status"] == "requested" for o in open_orders)}}


@router.post("/api/customs", status_code=201)
def create_order(body: OrderIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        cur = db.execute("""
            INSERT INTO custom_orders (buyer, title, details, client_id, source_id, persona_id, requested_at, price, status, due_date,
                                       delivered_at, delivery_note, set_path, can_resell, notes, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_values(db, owner, body), owner, _now(), _now()))
        db.commit()
        return _get(db, cur.lastrowid, owner)
    finally:
        db.close()


@router.put("/api/customs/{order_id}")
def update_order(order_id: int, body: OrderIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        before = _need(db, order_id, owner)
        db.execute("""
            UPDATE custom_orders SET buyer = ?, title = ?, details = ?, client_id = ?, source_id = ?, persona_id = ?, requested_at = ?,
                   price = ?, status = ?, due_date = ?, delivered_at = ?, delivery_note = ?, set_path = ?, can_resell = ?, notes = ?,
                   updated_at = ? WHERE id = ? AND owner_id = ?
        """, (*_values(db, owner, body, before), _now(), order_id, owner))
        db.commit()
        return _get(db, order_id, owner)
    finally:
        db.close()


@router.post("/api/customs/{order_id}/status")
def move_order(order_id: int, body: StatusIn, request: Request):
    """Quote it, accept it, decline it or reopen it."""
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")
    owner = _owner(request)
    db = _get_db()
    try:
        before = _need(db, order_id, owner)
        delivered_at = (before["delivered_at"] or _now()) if body.status == "delivered" else None
        db.execute("UPDATE custom_orders SET status = ?, delivered_at = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                   (body.status, delivered_at, _now(), order_id, owner))
        db.commit()
        return _get(db, order_id, owner)
    finally:
        db.close()


@router.post("/api/customs/{order_id}/payment")
def take_payment(order_id: int, body: PaymentIn, request: Request):
    """
    Money came in for this order (a deposit, or all of it). It's added to the order, the order moves to "to
    make" if it was still being discussed, and the payment is written into income as a sale: the platform's
    fee comes from the place it was paid through unless one is given.
    """
    if not (0 < body.amount < float("inf")) or not _money_ok(body.fees):
        raise HTTPException(status_code=400, detail="The amount must be more than 0")
    owner = _owner(request)
    db = _get_db()
    try:
        order = _need(db, order_id, owner)
        amount = round(body.amount, 2)
        status = "to_make" if order["status"] in ("requested", "quoted") else order["status"]
        db.execute("UPDATE custom_orders SET amount_paid = amount_paid + ?, status = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                   (amount, status, _now(), order_id, owner))
        if body.log_income:
            source = finance.get_source(db, order["source_id"], owner) if order["source_id"] else None
            fees = body.fees if body.fees is not None else amount * (source.get("fee_percent") or 0) / 100 if source else 0
            db.execute("""
                INSERT INTO income (source_id, date, description, kind, gross, fees, status, currency, client_id, custom_order_id,
                                    payment_method, owner_id, created_at, updated_at)
                VALUES (?, ?, ?, 'sale', ?, ?, 'received', ?, ?, ?, ?, ?, ?, ?)
            """, (order["source_id"], _iso(body.paid_on) or _now(), f"Custom: {order['title']} ({order['buyer']})", amount,
                  round(min(fees, amount), 2), (source or {}).get("currency") or "USD", order["client_id"], order_id,
                  (_clean(body.payment_method, 40) or None), owner, _now(), _now()))
        db.commit()
        return _get(db, order_id, owner)
    finally:
        db.close()


@router.post("/api/customs/{order_id}/delivered")
def mark_delivered(order_id: int, body: DeliveredIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        order = _need(db, order_id, owner)
        db.execute("UPDATE custom_orders SET status = 'delivered', delivered_at = ?, delivery_note = COALESCE(?, delivery_note), updated_at = ? "
                   "WHERE id = ? AND owner_id = ?",
                   (_iso(body.delivered_at) or order["delivered_at"] or _now(), _clean(body.delivery_note, 500), _now(), order_id, owner))
        db.commit()
        return _get(db, order_id, owner)
    finally:
        db.close()


@router.delete("/api/customs/{order_id}", status_code=204)
def delete_order(order_id: int, request: Request):
    """The order goes. Payments already written into income stay there."""
    db = _get_db()
    try:
        db.execute("DELETE FROM custom_orders WHERE id = ? AND owner_id = ?", (order_id, _owner(request)))
        db.commit()
    finally:
        db.close()


@router.get("/api/customs/summary")
def summary(request: Request, start: datetime = Query(...), end: datetime = Query(...)):
    """Of the orders requested between start and end: how many, how many were delivered or declined, what
    they've paid, the usual price and turnaround, and which places they came through."""
    if end <= start:
        raise HTTPException(status_code=400, detail="The end must be after the start")
    today = datetime.now(timezone.utc).date()
    db = _get_db()
    try:
        orders: List[dict] = [_row(r, today) for r in db.execute(
            SELECT + " WHERE o.owner_id = ? AND o.requested_at >= ? AND o.requested_at < ?", (_owner(request), _iso(start), _iso(end)))]
    finally:
        db.close()
    delivered = [o for o in orders if o["status"] == "delivered"]
    priced = [o["price"] for o in orders if o["price"] and o["status"] != "declined"]
    turnaround = [(datetime.fromisoformat(o["delivered_at"]) - datetime.fromisoformat(o["requested_at"])).days for o in delivered if o["delivered_at"]]
    places = {}
    for o in orders:
        p = places.setdefault(o["source_id"] or 0, {"source_id": o["source_id"], "label": o["source_name"] or "No place set", "orders": 0, "paid": 0.0})
        p["orders"] += 1
        p["paid"] = round(p["paid"] + (o["amount_paid"] or 0), 2)
    return {
        "orders": len(orders), "delivered": len(delivered), "declined": sum(o["status"] == "declined" for o in orders),
        "open": sum(o["status"] in OPEN for o in orders),
        "paid": round(sum(o["amount_paid"] or 0 for o in orders), 2),
        "owed": round(sum(o["owed"] for o in orders if o["status"] != "declined"), 2),
        "average_price": round(sum(priced) / len(priced), 2) if priced else None,
        "average_days": round(sum(turnaround) / len(turnaround), 1) if turnaround else None,
        "can_resell": sum(o["can_resell"] for o in delivered),
        "places": sorted(places.values(), key=lambda p: (-p["paid"], p["label"].lower())),
    }


# ==================== THE MENU ====================

def _menu_values(body: MenuItemIn) -> tuple:
    label = _clean(body.label, 120)
    if not label:
        raise HTTPException(status_code=400, detail="Give it a name")
    if not _money_ok(body.price):
        raise HTTPException(status_code=400, detail="The price must be 0 or more")
    return label, body.price, _clean(body.notes, 500)


@router.get("/api/customs/menu")
def list_menu(request: Request):
    db = _get_db()
    try:
        return [dict(r) for r in db.execute("SELECT id, label, price, notes FROM custom_menu WHERE owner_id = ? ORDER BY sort_order, id",
                                            (_owner(request),))]
    finally:
        db.close()


@router.post("/api/customs/menu", status_code=201)
def add_menu_item(body: MenuItemIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        label, price, notes = _menu_values(body)
        last = db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM custom_menu WHERE owner_id = ?", (owner,)).fetchone()[0]
        cur = db.execute("INSERT INTO custom_menu (label, price, notes, sort_order, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (label, price, notes, last + 1, owner, _now(), _now()))
        db.commit()
        return {"id": cur.lastrowid, "label": label, "price": price, "notes": notes}
    finally:
        db.close()


@router.put("/api/customs/menu/{item_id}")
def update_menu_item(item_id: int, body: MenuItemIn, request: Request):
    db = _get_db()
    try:
        label, price, notes = _menu_values(body)
        done = db.execute("UPDATE custom_menu SET label = ?, price = ?, notes = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                          (label, price, notes, _now(), item_id, _owner(request)))
        if not done.rowcount:
            raise HTTPException(status_code=404, detail="Not found")
        db.commit()
        return {"id": item_id, "label": label, "price": price, "notes": notes}
    finally:
        db.close()


@router.delete("/api/customs/menu/{item_id}", status_code=204)
def delete_menu_item(item_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM custom_menu WHERE id = ? AND owner_id = ?", (item_id, _owner(request)))
        db.commit()
    finally:
        db.close()
