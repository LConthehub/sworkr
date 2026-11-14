"""
A year's money summed up for a tax return or an accountant: income by kind, what places kept (fees, house
shares, including a brothel's share of gifts), expenses by main category and subcategory, and the profit.
Everything is your part after partners' shares, in the person's own time zone's calendar year.

It adds up; it doesn't advise. The one judgement left to the person is a set-aside percentage they choose
themselves, shown as "what that would be". Gifts are counted at what they're worth, as the income form
explains, since tax offices generally treat gifts from clients as income.
"""

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request

import collab

router = APIRouter(prefix="/api/tax-summary")
_get_db: Optional[Callable] = None

INCOME_LABELS = {
    "booking": "Bookings paid outside the calendar", "shift": "Shifts", "payout": "Payouts", "tips": "Tips",
    "sale": "Sales (PPV, customs, clips)", "subscription": "Subscriptions", "allowance": "Allowances",
    "gift": "Gifts (at what they're worth)", "other": "Other income",
}


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _year_bounds(year: int, tz_offset: int):
    """[start, end) of the local calendar year, as UTC ISO strings. tz_offset is getTimezoneOffset()."""
    shift = timedelta(minutes=tz_offset)
    start = datetime(year, 1, 1, tzinfo=timezone.utc) + shift
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) + shift
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


@router.get("")
def tax_summary(request: Request, year: int = Query(..., ge=2000, le=2100),
                tz_offset: int = Query(0, ge=-840, le=840), set_aside_percent: Optional[float] = Query(None, ge=0, le=100)):
    owner = request.state.user["id"]
    start, end = _year_bounds(year, tz_offset)
    db = _get_db()
    try:
        # Calendar bookings: what was actually received, less partners' shares.
        b = db.execute("""
            SELECT COUNT(*) AS n, COALESCE(SUM(a.amount_paid - """ + collab.partner_share_sql("appointment", "a.amount_paid", "a.id") + """), 0) AS mine
            FROM appointments a
            WHERE a.owner_id = ? AND a.kind = 'client' AND a.amount_paid > 0 AND a.scheduled_date >= ? AND a.scheduled_date < ?
        """, (owner, start, end)).fetchone()
        income = []
        if b["n"]:
            income.append({"key": "calendar", "label": "Calendar bookings (received)", "gross": round(b["mine"], 2), "fees": 0.0, "entries": b["n"]})

        # Other income, received: gross and what the place kept, scaled to your part when it's split.
        rows = db.execute("""
            SELECT i.kind, COUNT(*) AS n, SUM(i.gross) AS gross, SUM(i.fees) AS fees,
                   SUM((i.gross - i.fees) - """ + collab.partner_share_sql("income", "i.gross - i.fees", "i.id") + """) AS mine
            FROM income i WHERE i.owner_id = ? AND i.status = 'received' AND i.date >= ? AND i.date < ?
            GROUP BY i.kind
        """, (owner, start, end)).fetchall()
        for r in rows:
            net = r["gross"] - r["fees"]
            part = (r["mine"] / net) if net > 0 else 1.0   # your fraction of this income after partners
            income.append({"key": r["kind"], "label": INCOME_LABELS.get(r["kind"], r["kind"].title()),
                           "gross": round(r["gross"] * part, 2), "fees": round(r["fees"] * part, 2), "entries": r["n"]})
        income.sort(key=lambda x: -x["gross"])
        pending = db.execute("SELECT COALESCE(SUM(gross - fees), 0) FROM income WHERE owner_id = ? AND status = 'pending' "
                             "AND date >= ? AND date < ?", (owner, start, end)).fetchone()[0]

        # Expenses: your part, by main category, each with its subcategories.
        cats = {r["key"]: dict(r) for r in db.execute(
            "SELECT key, label, parent_key, sort_order FROM expense_categories WHERE owner_id = ?", (owner,))}
        spent = db.execute("""
            SELECT e.category, COUNT(*) AS n,
                   SUM(e.amount - """ + collab.partner_share_sql("expense", "e.amount", "e.id") + """) AS mine
            FROM expenses e WHERE e.owner_id = ? AND e.date >= ? AND e.date < ?
            GROUP BY e.category
        """, (owner, start, end)).fetchall()
        groups = {}
        for r in spent:
            cat = cats.get(r["category"], {"key": r["category"], "label": r["category"], "parent_key": None, "sort_order": 999})
            top_key = cat["parent_key"] or cat["key"]
            top = cats.get(top_key, cat)
            g = groups.setdefault(top_key, {"key": top_key, "label": top["label"], "total": 0.0, "entries": 0,
                                            "sort_order": top.get("sort_order", 999), "lines": []})
            g["total"] += r["mine"]
            g["entries"] += r["n"]
            g["lines"].append({"key": cat["key"], "label": "General" if cat["key"] == top_key else cat["label"],
                               "total": round(r["mine"], 2), "entries": r["n"]})
        expenses = []
        for g in sorted(groups.values(), key=lambda g: (g["sort_order"], g["label"])):
            g["total"] = round(g["total"], 2)
            g["lines"].sort(key=lambda x: -x["total"])
            g.pop("sort_order")
            expenses.append(g)

        gross = round(sum(i["gross"] for i in income), 2)
        fees = round(sum(i["fees"] for i in income), 2)
        total_expenses = round(sum(g["total"] for g in expenses), 2)
        profit = round(gross - fees - total_expenses, 2)
        out = {
            "year": year, "income": income, "gross_income": gross, "fees": fees, "expenses": expenses,
            "total_expenses": total_expenses, "profit": profit, "pending": round(pending, 2),
        }
        if set_aside_percent is not None:
            out["set_aside"] = {"percent": set_aside_percent, "amount": round(max(profit, 0) * set_aside_percent / 100, 2)}
        return out
    finally:
        db.close()
