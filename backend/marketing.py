"""
Where clients come from, and what each of those brings in.

Each client can say how they found you: an ad site, a social account, a referral, anything typed in. This
module turns that into a comparison: for each way of being found, how many clients, how many of them are new,
what they paid you, and what you spent on it. That last part is the point: an ad site that costs more than
its clients bring in shows up as a loss.

Nothing here is sent anywhere. It is only arithmetic over records the person already keeps.
"""

import re
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request

import collab

router = APIRouter()
_get_db: Optional[Callable] = None

NOT_RECORDED = "none"
MAX_LENGTH = 80
# The same place written two ways counts once.
ALIASES = {"twitter": "x", "x (twitter)": "x", "x/twitter": "x", "insta": "instagram", "ig": "instagram",
           "word of mouth": "referral", "referred": "referral", "a friend": "referral"}


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def clean_found_via(text: Optional[str]) -> Optional[str]:
    """What gets saved on the client: trimmed, single spaces, not too long."""
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:MAX_LENGTH] or None


def source_key(text: Optional[str]) -> str:
    """'Tryst', ' tryst ' and 'TRYST' are one group; so are 'Twitter' and 'X'."""
    key = (clean_found_via(text) or "").casefold()
    return ALIASES.get(key, key) or NOT_RECORDED


def _most_used(counts: dict) -> str:
    """The spelling used most; when it's a tie, the capitalised one."""
    return min(counts, key=lambda s: (-counts[s], s))


def expense_is_for(label: str, expense: dict) -> bool:
    """
    Whether a marketing expense was spent on this way of being found.

    `label` is how the person wrote it on their clients ("Tryst", "X", "Referral"…).
    `expense` has: description (text), notes (text or None), category (the category's key),
    category_label (its name, e.g. "Ads & verification") and amount.
    """
    # Whole words only, so "X" doesn't match "Taxi" and "Eros" doesn't match "Heroes".
    text = f"{expense.get('description') or ''} {expense.get('notes') or ''}"
    names = {label.casefold()} | {alias for alias, key in ALIASES.items() if key == source_key(label)}
    return any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE) for name in names)


@router.get("/api/marketing/found-via")
def found_via(request: Request, start: datetime = Query(...), end: datetime = Query(...)):
    """
    For each way clients found you: how many clients, how many were added in this period, the bookings and
    money from them in this period (your share, after co-workers' splits), what you spent on it, and what's
    left. Clients with nothing recorded are one group, so it's clear how much is still unknown.
    """
    if end <= start:
        raise HTTPException(status_code=400, detail="The end must be after the start")
    owner = request.state.user["id"]
    start_iso, end_iso = _utc_iso(start), _utc_iso(end)
    db = _get_db()
    try:
        rows, spellings = {}, {}

        def row(text, a_client=False):
            key = source_key(text)
            if a_client and key != NOT_RECORDED:
                counts = spellings.setdefault(key, {})
                counts[clean_found_via(text)] = counts.get(clean_found_via(text), 0) + 1
            return rows.setdefault(key, {"key": key, "label": "Not recorded", "clients": 0, "new_clients": 0,
                                         "bookings": 0, "income": 0.0, "spend": 0.0})

        for c in db.execute("SELECT found_via, created_at FROM clients WHERE owner_id = ? AND role = 'client'", (owner,)):
            r = row(c["found_via"], a_client=True)
            r["clients"] += 1
            r["new_clients"] += start_iso <= c["created_at"] < end_iso

        for a in db.execute("""
            SELECT c.found_via, COUNT(*) AS n,
                   COALESCE(SUM(a.amount_paid - """ + collab.partner_share_sql("appointment", "a.amount_paid", "a.id") + """), 0) AS mine
            FROM appointments a JOIN clients c ON c.id = a.client_id
            WHERE a.owner_id = ? AND a.kind = 'client' AND a.amount_paid > 0 AND a.scheduled_date >= ? AND a.scheduled_date < ?
            GROUP BY c.found_via
        """, (owner, start_iso, end_iso)).fetchall():
            r = row(a["found_via"])
            r["bookings"] += a["n"]
            r["income"] += a["mine"]

        # Gifts and allowances recorded against a client count for the way that client found you.
        for i in db.execute("""
            SELECT c.found_via,
                   COALESCE(SUM((i.gross - i.fees) - """ + collab.partner_share_sql("income", "i.gross - i.fees", "i.id") + """), 0) AS mine
            FROM income i JOIN clients c ON c.id = i.client_id
            WHERE i.owner_id = ? AND i.status = 'received' AND i.date >= ? AND i.date < ?
            GROUP BY c.found_via
        """, (owner, start_iso, end_iso)).fetchall():
            row(i["found_via"])["income"] += i["mine"]

        # The label is the spelling used on the most clients.
        for key, counts in spellings.items():
            rows[key]["label"] = _most_used(counts)

        spent, unmatched = 0.0, 0.0
        for e in db.execute("""
            SELECT e.description, e.notes, e.category, cat.label AS category_label,
                   e.amount - """ + collab.partner_share_sql("expense", "e.amount", "e.id") + """ AS amount
            FROM expenses e JOIN expense_categories cat ON cat.owner_id = e.owner_id AND cat.key = e.category
            WHERE e.owner_id = ? AND e.date >= ? AND e.date < ? AND (cat.key = 'marketing' OR cat.parent_key = 'marketing')
        """, (owner, start_iso, end_iso)):
            expense = dict(e)
            spent += expense["amount"]
            matches = [r for r in rows.values() if r["key"] != NOT_RECORDED and expense_is_for(r["label"], expense)]
            if not matches:
                unmatched += expense["amount"]
            for r in matches:       # an expense that names two places is shared between them
                r["spend"] += expense["amount"] / len(matches)

        total = sum(r["income"] for r in rows.values())
        out = []
        for r in rows.values():
            r["income"], r["spend"] = round(r["income"], 2), round(r["spend"], 2)
            r["profit"] = round(r["income"] - r["spend"], 2)
            r["per_client"] = round(r["income"] / r["clients"], 2) if r["clients"] else None
            r["share"] = round(r["income"] / total, 4) if total > 0 else None
            out.append(r)
        out.sort(key=lambda r: (r["key"] == NOT_RECORDED, -r["income"], r["label"].lower()))
        return {"rows": out, "total": round(total, 2), "spent": round(spent, 2), "unmatched_spend": round(unmatched, 2)}
    finally:
        db.close()


@router.get("/api/marketing/lapsed")
def lapsed_regulars(request: Request, days: int = Query(60, ge=7, le=3650)):
    """
    Regulars who have gone quiet: clients seen at least twice, not seen for `days` days, with nothing booked
    ahead. Each comes with how often they used to book, so "a month late" and "a year gone" look different.
    The ones who have paid the most come first.
    """
    owner = request.state.user["id"]
    now = datetime.now(timezone.utc)
    now_iso = _utc_iso(now)
    db = _get_db()
    try:
        out = []
        for r in db.execute("""
            SELECT c.id, c.display_name, c.found_via, c.contact_phone, c.email, c.persona_id,
                   COUNT(a.id) AS bookings, MIN(a.scheduled_date) AS first_seen, MAX(a.scheduled_date) AS last_seen,
                   COALESCE(SUM(a.amount_paid), 0) AS paid
            FROM clients c JOIN appointments a ON a.client_id = c.id
            WHERE c.owner_id = ? AND c.role = 'client' AND c.is_active = 1 AND c.do_not_see = 0
              AND a.kind = 'client' AND a.scheduled_date < ? AND (a.status = 'completed' OR (a.status != 'cancelled' AND a.amount_paid > 0))
              AND NOT EXISTS (SELECT 1 FROM appointments n WHERE n.client_id = c.id AND n.status = 'scheduled' AND n.scheduled_date >= ?)
            GROUP BY c.id HAVING COUNT(a.id) >= 2
        """, (owner, now_iso, now_iso)):
            first, last = datetime.fromisoformat(r["first_seen"]), datetime.fromisoformat(r["last_seen"])
            since = (now - last).days
            if since < days:
                continue
            usual = max(round((last - first).days / (r["bookings"] - 1)), 1)
            out.append({"id": r["id"], "display_name": r["display_name"], "found_via": r["found_via"], "contact_phone": r["contact_phone"],
                        "email": r["email"], "persona_id": r["persona_id"], "bookings": r["bookings"], "last_seen": r["last_seen"],
                        "days_since": since, "usual_gap_days": usual, "total_paid": round(r["paid"], 2),
                        "per_booking": round(r["paid"] / r["bookings"], 2)})
        out.sort(key=lambda c: (-c["total_paid"], c["display_name"].lower()))
        return out
    finally:
        db.close()


@router.get("/api/marketing/found-via/options")
def found_via_options(request: Request):
    """The ways of being found this person has already typed, most used first (for the suggestions list)."""
    db = _get_db()
    try:
        counts = {}
        for c in db.execute("SELECT found_via FROM clients WHERE owner_id = ? AND found_via IS NOT NULL", (request.state.user["id"],)):
            counts.setdefault(source_key(c["found_via"]), {}).setdefault(c["found_via"], 0)
            counts[source_key(c["found_via"])][c["found_via"]] += 1
        ranked = sorted(counts.values(), key=lambda spellings: -sum(spellings.values()))
        return [_most_used(spellings) for spellings in ranked]
    finally:
        db.close()
