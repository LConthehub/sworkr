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


# ==================== PRICES BY TAG ====================

class TagRuleIn(BaseModel):
    tag: str
    kind: str                             # percent (off), amount (off) or locked (keeps the rate they last paid)
    value: Optional[float] = None


def _tag_rules(db, owner_id: int) -> List[dict]:
    return [dict(r) for r in db.execute("SELECT id, tag, kind, value FROM tag_rules WHERE owner_id = ? ORDER BY tag", (owner_id,))]


@router.get("/api/rates/tag-rules")
def list_tag_rules(request: Request):
    db = _get_db()
    try:
        return _tag_rules(db, _owner(request))
    finally:
        db.close()


@router.post("/api/rates/tag-rules")
def save_tag_rule(body: TagRuleIn, request: Request):
    """Set (or change) what a tag does to the price. One rule per tag."""
    tag = body.tag.strip().lower().lstrip("#")[:60]
    if not tag:
        raise HTTPException(status_code=400, detail="Which tag?")
    if body.kind not in ("percent", "amount", "locked"):
        raise HTTPException(status_code=400, detail="A tag gives a percentage off, an amount off, or a locked-in rate")
    value = None if body.kind == "locked" else body.value
    if body.kind != "locked" and (value is None or not (0 <= value < 1e9) or (body.kind == "percent" and value > 100)):
        raise HTTPException(status_code=400, detail="Say how much off: 0 to 100%, or an amount of 0 or more")
    owner = _owner(request)
    db = _get_db()
    try:
        db.execute("INSERT INTO tag_rules (owner_id, tag, kind, value, created_at) VALUES (?, ?, ?, ?, ?) "
                   "ON CONFLICT(owner_id, tag) DO UPDATE SET kind = excluded.kind, value = excluded.value", (owner, tag, body.kind, value, _now()))
        db.commit()
        return _tag_rules(db, owner)
    finally:
        db.close()


@router.delete("/api/rates/tag-rules/{rule_id}", status_code=204)
def delete_tag_rule(rule_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM tag_rules WHERE id = ? AND owner_id = ?", (rule_id, _owner(request)))
        db.commit()
    finally:
        db.close()


def _client_rule(db, owner_id: int, client_id: int) -> Optional[dict]:
    """The pricing rule that applies to a client, from their tags. A locked-in rate wins; otherwise the biggest discount."""
    rules = [dict(r) for r in db.execute("""
        SELECT r.tag, r.kind, r.value FROM tag_rules r JOIN client_tags t ON LOWER(t.tag_name) = r.tag
        JOIN clients c ON c.id = t.client_id WHERE r.owner_id = ? AND c.owner_id = ? AND t.client_id = ?
    """, (owner_id, owner_id, client_id))]
    if not rules:
        return None
    locked = [r for r in rules if r["kind"] == "locked"]
    return locked[0] if locked else rules[0] if len(rules) == 1 else rules     # several discounts: the caller picks the best for the price


@router.get("/api/rates/quote")
def quote(request: Request, client_id: int, service: str, minutes: Optional[int] = None):
    """
    What to charge this client for a service on the rate card, after any rule their tags carry. Says why, so
    the booking form can show it. No card price for that service: nothing to quote.
    """
    owner = _owner(request)
    db = _get_db()
    try:
        card = [r for r in _rows(db, owner) if not r["archived"] and r["label"].casefold() == service.strip().casefold()]
        match = next((r for r in card if r["minutes"] == minutes), card[0] if card else None)
        if not match:
            return {"card_price": None, "price": None, "reason": None}
        price, reason = match["price"], None
        rule = _client_rule(db, owner, client_id)
        if isinstance(rule, list):       # several discount tags: whichever gives the lowest price
            rule = min(rule, key=lambda r: price * (1 - r["value"] / 100) if r["kind"] == "percent" else price - r["value"])
        if rule and rule["kind"] == "locked":
            last = db.execute("""
                SELECT rate FROM appointments WHERE owner_id = ? AND client_id = ? AND kind = 'client' AND status != 'cancelled' AND rate > 0
                  AND LOWER(service_type) = LOWER(?) AND (? IS NULL OR duration_minutes = ?) ORDER BY scheduled_date DESC LIMIT 1
            """, (owner, client_id, service.strip(), match["minutes"], match["minutes"])).fetchone()
            if last and last["rate"] < price:
                price, reason = last["rate"], f"Locked-in rate (#{rule['tag']}): what they last paid"
        elif rule and rule["kind"] == "percent" and rule["value"]:
            price, reason = round(price * (1 - rule["value"] / 100), 2), f"{rule['value']:g}% off (#{rule['tag']})"
        elif rule and rule["kind"] == "amount" and rule["value"]:
            price, reason = round(max(price - rule["value"], 0), 2), f"${rule['value']:g} off (#{rule['tag']})"
        return {"card_price": match["price"], "price": price, "reason": reason, "minutes": match["minutes"]}
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
              AND NOT EXISTS (SELECT 1 FROM client_tags t JOIN tag_rules r ON r.tag = LOWER(t.tag_name) AND r.owner_id = a.owner_id
                              WHERE t.client_id = c.id AND r.kind = 'locked')
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
