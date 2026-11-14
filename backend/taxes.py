"""
A year's money summed up for a tax return or an accountant: income by kind, what places kept (fees, house
shares, including a brothel's share of gifts), expenses by main category and subcategory, and the profit.
Everything is your part after partners' shares, in the person's own time zone's calendar year.

It adds up; it doesn't advise. The one judgement left to the person is a set-aside percentage they choose
themselves, shown as "what that would be". Gifts are counted at what they're worth, as the income form
explains, since tax offices generally treat gifts from clients as income.
"""

import datetime as dt
import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

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
        out["estimated_payments"] = [dict(r) for r in db.execute(
            "SELECT authority, ROUND(SUM(amount), 2) AS total, COUNT(*) AS payments FROM tax_payments "
            "WHERE owner_id = ? AND year = ? GROUP BY authority ORDER BY authority", (owner, year))]
        if set_aside_percent is not None:
            out["set_aside"] = {"percent": set_aside_percent, "amount": round(max(profit, 0) * set_aside_percent / 100, 2)}
        return out
    finally:
        db.close()


# ==================== US QUARTERLY ESTIMATED TAX ====================
# The IRS's four payment periods aren't calendar quarters: Jan-Mar, Apr-May, Jun-Aug, Sep-Dec, due on 15 April,
# 15 June, 15 September and 15 January. A due date on a weekend moves to the Monday (a public holiday can
# move it a day too; the IRS site has the exact dates). States with estimated tax mostly use the same dates.

PERIODS = [((1, 1), (4, 1), (4, 15)), ((4, 1), (6, 1), (6, 15)), ((6, 1), (9, 1), (9, 15)), ((9, 1), (1, 1), (1, 15))]


def due_date(year: int, quarter: int) -> dt.date:
    month, day = PERIODS[quarter - 1][2]
    d = dt.date(year + 1 if quarter == 4 else year, month, day)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _period(year: int, quarter: int, tz_offset: int):
    shift = timedelta(minutes=tz_offset)
    (sm, sd), (em, ed), _ = PERIODS[quarter - 1]
    start = datetime(year, sm, sd, tzinfo=timezone.utc) + shift
    end = datetime(year + 1 if quarter == 4 else year, em, ed, tzinfo=timezone.utc) + shift
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def profit_between(db, owner: int, start: str, end: str) -> float:
    """Your profit in [start, end): bookings received, plus other income received after what places kept, less
    expenses, all your part after partners' shares."""
    bookings = db.execute("""
        SELECT COALESCE(SUM(a.amount_paid - """ + collab.partner_share_sql("appointment", "a.amount_paid", "a.id") + """), 0)
        FROM appointments a WHERE a.owner_id = ? AND a.kind = 'client' AND a.amount_paid > 0
          AND a.scheduled_date >= ? AND a.scheduled_date < ?
    """, (owner, start, end)).fetchone()[0]
    income = db.execute("""
        SELECT COALESCE(SUM((i.gross - i.fees) - """ + collab.partner_share_sql("income", "i.gross - i.fees", "i.id") + """), 0)
        FROM income i WHERE i.owner_id = ? AND i.status = 'received' AND i.date >= ? AND i.date < ?
    """, (owner, start, end)).fetchone()[0]
    spent = db.execute("""
        SELECT COALESCE(SUM(e.amount - """ + collab.partner_share_sql("expense", "e.amount", "e.id") + """), 0)
        FROM expenses e WHERE e.owner_id = ? AND e.date >= ? AND e.date < ?
    """, (owner, start, end)).fetchone()[0]
    return round(bookings + income - spent, 2)


class PaymentIn(BaseModel):
    year: int
    quarter: int
    authority: str = "federal"      # federal | state
    amount: float
    paid_on: dt.date
    note: Optional[str] = None


@router.get("/quarters")
def quarters(request: Request, year: int = Query(..., ge=2000, le=2100), tz_offset: int = Query(0, ge=-840, le=840),
             set_aside_percent: Optional[float] = Query(None, ge=0, le=100)):
    """Each estimated-tax period of the year: its dates, your profit in it, what your own set-aside percentage of
    that comes to, and the payments logged for it (federal and state)."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        payments = [dict(r) for r in db.execute(
            "SELECT * FROM tax_payments WHERE owner_id = ? AND year = ? ORDER BY paid_on, id", (owner, year))]
        today = datetime.now(timezone.utc).date()
        out = []
        for q in (1, 2, 3, 4):
            start, end = _period(year, q, tz_offset)
            profit = profit_between(db, owner, start, end)
            mine = [p for p in payments if p["quarter"] == q]
            due = due_date(year, q)
            out.append({
                "quarter": q, "starts": start, "ends": end, "due": due.isoformat(),
                "days_until_due": (due - today).days, "profit": profit,
                "set_aside": round(max(profit, 0) * set_aside_percent / 100, 2) if set_aside_percent is not None else None,
                "paid_federal": round(sum(p["amount"] for p in mine if p["authority"] == "federal"), 2),
                "paid_state": round(sum(p["amount"] for p in mine if p["authority"] == "state"), 2),
                "payments": mine,
            })
        return {"year": year, "quarters": out, "total_paid": round(sum(p["amount"] for p in payments), 2)}
    finally:
        db.close()


@router.post("/payments", status_code=201)
def add_payment(body: PaymentIn, request: Request):
    """Log an estimated tax payment. It isn't a business expense, so it's kept apart from expenses."""
    if not 1 <= body.quarter <= 4 or not 2000 <= body.year <= 2100:
        raise HTTPException(status_code=400, detail="Choose a year and a quarter (1 to 4)")
    if body.authority not in ("federal", "state"):
        raise HTTPException(status_code=400, detail="Federal or state")
    if not 0 < body.amount < 1e9:
        raise HTTPException(status_code=400, detail="Enter the amount paid")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        cur = db.execute("INSERT INTO tax_payments (owner_id, year, quarter, authority, amount, paid_on, note, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (owner, body.year, body.quarter, body.authority, round(body.amount, 2), body.paid_on.isoformat(),
                          (body.note or "").strip()[:500] or None, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        db.commit()
        return dict(db.execute("SELECT * FROM tax_payments WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        db.close()


@router.delete("/payments/{payment_id}", status_code=204)
def delete_payment(payment_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM tax_payments WHERE id = ? AND owner_id = ?", (payment_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


class RemindersIn(BaseModel):
    enabled: bool


def _reminder_ids(db, owner: int) -> list:
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = 'tax_reminder_tasks'", (owner,)).fetchone()
    try:
        return json.loads(row["value"]) if row and row["value"] else []
    except ValueError:
        return []


@router.get("/reminders")
def get_reminders(request: Request):
    db = _get_db()
    try:
        return {"enabled": bool(_reminder_ids(db, request.state.user["id"]))}
    finally:
        db.close()


@router.put("/reminders")
def set_reminders(body: RemindersIn, request: Request):
    """Reminder tasks a week before each estimated-tax due date in the coming year. Turning them off removes the
    ones not yet done."""
    import calendar_sync
    owner = request.state.user["id"]
    db = _get_db()
    try:
        touched = []
        for task_id in _reminder_ids(db, owner):
            if db.execute("DELETE FROM tasks WHERE id = ? AND owner_id = ? AND done_at IS NULL", (task_id, owner)).rowcount:
                touched.append(task_id)
        new = []
        if body.enabled:
            today = datetime.now(timezone.utc).date()
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for year in (today.year - 1, today.year, today.year + 1):
                for q in (1, 2, 3, 4):
                    due = due_date(year, q)
                    if today <= due <= today + timedelta(days=366):
                        cur = db.execute("INSERT INTO tasks (title, notes, due_date, owner_id, created_at, updated_at) "
                                         "VALUES (?, ?, ?, ?, ?, ?)",
                                         (f"Estimated tax payment due {due.strftime('%b')} {due.day}",
                                          f"For {year} Q{q}. Money > Taxes shows what you've set aside and paid.",
                                          (due - timedelta(days=7)).isoformat(), owner, now, now))
                        new.append(cur.lastrowid)
        db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, 'tax_reminder_tasks', ?) "
                   "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, json.dumps(new)))
        db.commit()
        for task_id in touched + new:
            calendar_sync.queue_item("task", task_id, owner)
        return {"enabled": body.enabled, "tasks": len(new)}
    finally:
        db.close()
