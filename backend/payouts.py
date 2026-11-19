"""
The payout calendar: when money that's been earned but not yet paid out should land.

Income marked "pending" is money a platform or a house still holds. Each place can have a payout rule (every
Friday, the 1st and 15th, a day of the month, or so many days after it's earned). A pending entry lands on its
own payout date when one was typed in, and otherwise on the next day its place's rule gives. Entries with
neither are listed apart, so nothing is lost.

It only reads income and never changes it: marking a payout as arrived is done in Money, as before.
"""

import calendar
from datetime import date, timedelta
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/payouts")
_get_db: Optional[Callable] = None

EVERY = ("weekly", "twice_monthly", "monthly", "days_after")


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


class RuleIn(BaseModel):
    every: str
    day: int = 0        # weekly: 0 Monday .. 6 Sunday; monthly: day of the month (1-28); days_after: how many days


def _check(body: RuleIn):
    if body.every not in EVERY:
        raise HTTPException(status_code=400, detail="Choose how often it pays out")
    limits = {"weekly": (0, 6), "twice_monthly": (0, 0), "monthly": (1, 28), "days_after": (0, 120)}[body.every]
    if body.every == "twice_monthly":
        body.day = 0
    if not limits[0] <= body.day <= limits[1]:
        raise HTTPException(status_code=400, detail="That day doesn't fit")


def lands_on(earned: date, every: str, day: int) -> date:
    """The first payout day after the money was earned."""
    if every == "days_after":
        return earned + timedelta(days=day)
    if every == "weekly":
        return earned + timedelta(days=((day - earned.weekday() - 1) % 7) + 1)
    days = (1, 15) if every == "twice_monthly" else (day,)
    year, month = earned.year, earned.month
    for _ in range(3):
        for d in days:
            candidate = date(year, month, min(d, calendar.monthrange(year, month)[1]))
            if candidate > earned:
                return candidate
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return earned


def describe(every: str, day: int) -> str:
    if every == "weekly":
        return f"Every {calendar.day_name[day]}"
    if every == "twice_monthly":
        return "The 1st and the 15th"
    if every == "monthly":
        return f"Day {day} of each month"
    return "The same day" if day == 0 else f"{day} day{'s' if day != 1 else ''} after it's earned"


@router.get("")
def payout_calendar(request: Request, today: Optional[date] = None):
    owner = request.state.user["id"]
    today = today or date.today()
    db = _get_db()
    try:
        rules = {r["source_id"]: dict(r) for r in db.execute("SELECT * FROM payout_rules WHERE owner_id = ?", (owner,))}
        places = [{"source_id": r["id"], "name": r["name"], "payout_note": r["payout_note"],
                   "every": rules[r["id"]]["every"] if r["id"] in rules else None,
                   "day": rules[r["id"]]["day"] if r["id"] in rules else None,
                   "rule": describe(rules[r["id"]]["every"], rules[r["id"]]["day"]) if r["id"] in rules else None}
                  for r in db.execute("SELECT id, name, payout_note FROM income_sources WHERE owner_id = ? AND archived = 0 ORDER BY name",
                                      (owner,))]
        days, undated = {}, []
        for r in db.execute("""
            SELECT i.id, i.date, i.description, i.kind, i.gross, i.fees, i.payout_date, i.currency, i.source_id, s.name AS source_name
            FROM income i LEFT JOIN income_sources s ON s.id = i.source_id
            WHERE i.owner_id = ? AND i.status = 'pending' ORDER BY i.date, i.id
        """, (owner,)):
            item = {"id": r["id"], "earned_on": r["date"][:10], "description": r["description"], "kind": r["kind"],
                    "source_name": r["source_name"], "net": round(r["gross"] - r["fees"], 2), "currency": r["currency"]}
            rule = rules.get(r["source_id"])
            if r["payout_date"]:
                when, item["guessed"] = r["payout_date"][:10], False
            elif rule:
                when, item["guessed"] = lands_on(date.fromisoformat(item["earned_on"]), rule["every"], rule["day"]).isoformat(), True
            else:
                undated.append(item)
                continue
            days.setdefault(when, []).append(item)
        out, late = [], 0.0
        for when in sorted(days):
            total = round(sum(i["net"] for i in days[when]), 2)
            is_late = when < today.isoformat()
            late += total if is_late else 0
            out.append({"date": when, "days_away": (date.fromisoformat(when) - today).days, "late": is_late,
                        "total": total, "items": days[when]})
        return {"days": out, "undated": undated, "places": places,
                "expected": round(sum(d["total"] for d in out), 2), "late": round(late, 2),
                "undated_total": round(sum(i["net"] for i in undated), 2)}
    finally:
        db.close()


@router.put("/rules/{source_id}")
def save_rule(source_id: int, body: RuleIn, request: Request):
    _check(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        if not db.execute("SELECT 1 FROM income_sources WHERE id = ? AND owner_id = ?", (source_id, owner)).fetchone():
            raise HTTPException(status_code=404, detail="That place doesn't exist")
        db.execute("INSERT INTO payout_rules (source_id, owner_id, every, day) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(source_id) DO UPDATE SET every = excluded.every, day = excluded.day",
                   (source_id, owner, body.every, body.day))
        db.commit()
        return {"source_id": source_id, "every": body.every, "day": body.day, "rule": describe(body.every, body.day)}
    finally:
        db.close()


@router.delete("/rules/{source_id}", status_code=204)
def delete_rule(source_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM payout_rules WHERE source_id = ? AND owner_id = ?", (source_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()
