"""
Ad listings: an ad on a directory or ad site that runs for a while and costs money.

Unlike a post, a listing has a lifetime. It starts, it expires, and it is renewed (or bumped) every so many
days for a price. Each listing keeps its site, city, dates, cost and ad text. Renewing one moves its end date
on and writes the cost into expenses under Marketing, so the spend shows up in the money pages and next to
what that site's clients bring in, without typing it twice.

sworkr never contacts the ad site. It keeps the dates and the money.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import currencies
import finance
import personas

router = APIRouter()
_get_db: Optional[Callable] = None

SOON_DAYS = 3      # "expiring soon" from this many days before the end


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _owner(request: Request) -> int:
    return request.state.user["id"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text: Optional[str], limit: int = 10000) -> Optional[str]:
    return (text or "").strip()[:limit] or None


class ListingIn(BaseModel):
    site: str
    title: Optional[str] = None           # which ad it is, when there are several: "Chicago", "Duo with Jade"
    city: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None       # when it expires
    cost: Optional[float] = None          # what one run or renewal costs
    renew_days: Optional[int] = None      # how long one renewal lasts
    ad_text: Optional[str] = None
    link: Optional[str] = None
    paused: bool = False
    notes: Optional[str] = None
    tour_id: Optional[int] = None
    persona_id: Optional[int] = None
    currency: str = currencies.DEFAULT


class RenewIn(BaseModel):
    cost: Optional[float] = None          # left out: the listing's usual cost
    days: Optional[int] = None            # left out: the listing's usual length
    paid_on: Optional[date] = None        # left out: today
    log_expense: bool = True


def _state(row: dict, today: date) -> str:
    if row["paused"]:
        return "paused"
    if not row["end_date"]:
        return "live"
    left = (date.fromisoformat(row["end_date"]) - today).days
    return "expired" if left < 0 else "soon" if left <= SOON_DAYS else "live"


def _rows(db, owner_id: int, listing_id: Optional[int] = None) -> List[dict]:
    today = datetime.now(timezone.utc).date()
    out = []
    for r in db.execute("""
        SELECT l.*, t.name AS tour_name,
               (SELECT COALESCE(SUM(e.amount), 0) FROM expenses e WHERE e.listing_id = l.id) AS spent,
               (SELECT COUNT(*) FROM expenses e WHERE e.listing_id = l.id) AS payments
        FROM listings l LEFT JOIN tours t ON t.id = l.tour_id
        WHERE l.owner_id = ? AND (? IS NULL OR l.id = ?)
    """, (owner_id, listing_id, listing_id)):
        d = dict(r)
        d["paused"] = bool(d["paused"])
        d["state"] = _state(d, today)
        d["days_left"] = (date.fromisoformat(d["end_date"]) - today).days if d["end_date"] else None
        d["per_month"] = round(d["cost"] * 30 / d["renew_days"], 2) if d["cost"] and d["renew_days"] else None
        out.append(d)
    order = {"expired": 0, "soon": 1, "live": 2, "paused": 3}
    out.sort(key=lambda d: (order[d["state"]], d["end_date"] or "9999", d["site"].lower()))
    return out


def _values(db, owner_id: int, body: ListingIn) -> tuple:
    site = _clean(body.site, 60)
    if not site:
        raise HTTPException(status_code=400, detail="Which site is the ad on?")
    if body.cost is not None and not (0 <= body.cost < float("inf")):
        raise HTTPException(status_code=400, detail="The cost must be 0 or more")
    if body.renew_days is not None and not (1 <= body.renew_days <= 3650):
        raise HTTPException(status_code=400, detail="A renewal lasts 1 to 3650 days")
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="The ad ends before it starts")
    link = _clean(body.link, 500)
    if link and not link.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="The link must start with https://")
    if body.tour_id is not None and not db.execute(
            "SELECT 1 FROM tours WHERE id = ? AND owner_id = ?", (body.tour_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That tour doesn't exist")
    return (site, _clean(body.title, 120), _clean(body.city, 120), body.start_date.isoformat() if body.start_date else None,
            body.end_date.isoformat() if body.end_date else None, body.cost, body.renew_days, _clean(body.ad_text), link,
            int(body.paused), _clean(body.notes), body.tour_id, currencies.check(body.currency),
            personas.check(db, owner_id, body.persona_id))


@router.get("/api/listings")
def list_listings(request: Request):
    """Every ad, the ones that need attention first, with what's been spent on each and what all the live
    ones cost a month."""
    db = _get_db()
    try:
        rows = _rows(db, _owner(request))
    finally:
        db.close()
    running = [r for r in rows if r["state"] in ("live", "soon")]
    return {"listings": rows, "soon_days": SOON_DAYS,
            "per_month": round(sum(r["per_month"] or 0 for r in running), 2),
            "need_attention": sum(r["state"] in ("expired", "soon") for r in rows)}


@router.post("/api/listings", status_code=201)
def create_listing(body: ListingIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        cur = db.execute("""
            INSERT INTO listings (site, title, city, start_date, end_date, cost, renew_days, ad_text, link, paused, notes,
                                  tour_id, currency, persona_id, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_values(db, owner, body), owner, _now(), _now()))
        db.commit()
        return _rows(db, owner, cur.lastrowid)[0]
    finally:
        db.close()


@router.put("/api/listings/{listing_id}")
def update_listing(listing_id: int, body: ListingIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        if not _rows(db, owner, listing_id):
            raise HTTPException(status_code=404, detail="Ad not found")
        db.execute("""
            UPDATE listings SET site = ?, title = ?, city = ?, start_date = ?, end_date = ?, cost = ?, renew_days = ?, ad_text = ?,
                   link = ?, paused = ?, notes = ?, tour_id = ?, currency = ?, persona_id = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_values(db, owner, body), _now(), listing_id, owner))
        db.commit()
        return _rows(db, owner, listing_id)[0]
    finally:
        db.close()


@router.post("/api/listings/{listing_id}/renew")
def renew_listing(listing_id: int, body: RenewIn, request: Request):
    """
    Paid for another run. The end date moves on by the renewal's length (from the old end date, or from today
    if the ad had already expired), and the cost is written into expenses under Marketing.
    """
    owner = _owner(request)
    db = _get_db()
    try:
        found = _rows(db, owner, listing_id)
        if not found:
            raise HTTPException(status_code=404, detail="Ad not found")
        listing = found[0]
        days = body.days if body.days is not None else listing["renew_days"]
        cost = body.cost if body.cost is not None else listing["cost"]
        if not days or not (1 <= days <= 3650):
            raise HTTPException(status_code=400, detail="Say how many days the renewal lasts")
        if cost is not None and not (0 <= cost < float("inf")):
            raise HTTPException(status_code=400, detail="The cost must be 0 or more")
        paid_on = body.paid_on or datetime.now(timezone.utc).date()
        old_end = date.fromisoformat(listing["end_date"]) if listing["end_date"] else None
        new_end = (old_end if old_end and old_end >= paid_on else paid_on) + timedelta(days=days)
        db.execute("UPDATE listings SET end_date = ?, start_date = COALESCE(start_date, ?), paused = 0, updated_at = ? WHERE id = ? AND owner_id = ?",
                   (new_end.isoformat(), paid_on.isoformat(), _now(), listing_id, owner))
        if body.log_expense and cost:
            finance.ensure_categories(db, owner)
            label = " ".join(x for x in (listing["site"], "ad", f"({listing['title'] or listing['city']})" if listing["title"] or listing["city"] else "") if x)
            db.execute("""
                INSERT INTO expenses (description, amount, category, date, notes, tour_id, currency, owner_id, created_at, source, listing_id)
                VALUES (?, ?, 'marketing', ?, ?, ?, ?, ?, ?, 'listing', ?)
            """, (f"{label}: {days} days", cost, f"{paid_on.isoformat()}T12:00:00+00:00", f"Runs until {new_end.isoformat()}",
                  listing["tour_id"], listing["currency"], owner, _now(), listing_id))
        db.commit()
        return _rows(db, owner, listing_id)[0]
    finally:
        db.close()


@router.delete("/api/listings/{listing_id}", status_code=204)
def delete_listing(listing_id: int, request: Request):
    """The ad goes. What was spent on it stays in expenses."""
    db = _get_db()
    try:
        db.execute("DELETE FROM listings WHERE id = ? AND owner_id = ?", (listing_id, _owner(request)))
        db.commit()
    finally:
        db.close()
