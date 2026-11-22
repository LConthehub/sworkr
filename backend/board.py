"""
Free room and board: a workplace's rules for when it doesn't charge you for a day or a week.

Houses have their own deals: "a $1,000 party and that day's room and board is free", "make $5,000 in a week and the
week is on us". You set up your house's rules on the place, and sworkr applies them to your stays there:

- what counts: one entry of income, all of a day's income, or a week's (weeks count from the day the stay began)
- what's measured: what the client paid (the gross; tips don't count), or what you kept (the gross less the
  house's share)
- what it frees: that day, or that whole week
- when the rule applies: from a day, and until a day, so a house changing its deal doesn't rewrite older stays

A stay logs its room and board as expenses by itself (main.py, sync_stay_charges). Here, each of those is set
to $0 on the days that are free, with the reason, and the full amount is kept beside it, so it comes back if the
income that earned the free day is edited or removed. Only income logged at the same place counts.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _instant(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def describe(r) -> str:
    """A rule in words: "A party of $1,000 or more: that day is free"."""
    kept = " (what you kept)" if r["basis"] == "her_share" else ""
    counts = {"party": f"A party of ${r['reaches']:,.0f} or more{kept}",
              "day": f"${r['reaches']:,.0f} or more in a day{kept}",
              "week": f"${r['reaches']:,.0f} or more in a week of the stay{kept}"}[r["counts"]]
    return f"{counts}: {'that day' if r['frees'] == 'day' else 'that whole week'} is free"


# ==================== WHICH DAYS ARE FREE ====================

def free_days(db, owner_id: int, tour: dict) -> dict:
    """{day index of the stay (0 is its first day): the rule that made it free}. Empty when the stay isn't at a
    place, or the place has no rules."""
    if not tour.get("source_id") or tour.get("kind") != "tour":
        return {}
    first_day = date.fromisoformat(tour["start_date"])
    days = (date.fromisoformat(tour["end_date"]) - first_day).days + 1
    on_day = lambda i: (first_day + timedelta(days=i)).isoformat()  # noqa: E731
    rules = db.execute("SELECT * FROM place_board_rules WHERE owner_id = ? AND source_id = ? ORDER BY id",
                       (owner_id, tour["source_id"])).fetchall()
    if not rules:
        return {}
    starts = _instant(tour["starts_at"])
    # What the stay's statement counts as earned there: income logged at the place, and completed bookings.
    income = []
    for r in db.execute("SELECT date, kind, gross, fees FROM income WHERE owner_id = ? AND source_id = ? AND date >= ? AND date < ?",
                        (owner_id, tour["source_id"], tour["starts_at"], tour["ends_at"])):
        income.append((min(max((_instant(r["date"]) - starts).days, 0), days - 1), dict(r)))
    place = db.execute("SELECT fee_percent FROM income_sources WHERE id = ?", (tour["source_id"],)).fetchone()
    cut = ((place and place["fee_percent"]) or 0) / 100
    for a in db.execute("SELECT scheduled_date, rate FROM appointments WHERE owner_id = ? AND kind = 'client' AND status = 'completed' "
                        "AND scheduled_date >= ? AND scheduled_date < ? AND rate > 0", (owner_id, tour["starts_at"], tour["ends_at"])):
        income.append((min(max((_instant(a["scheduled_date"]) - starts).days, 0), days - 1),
                       {"kind": "booking", "gross": a["rate"], "fees": round(a["rate"] * cut, 2)}))
    free = {}
    for rule in rules:
        in_force = lambda i: ((not rule["starts_on"] or rule["starts_on"] <= on_day(i))  # noqa: E731
                              and (not rule["ends_on"] or on_day(i) <= rule["ends_on"]))
        if rule["basis"] == "her_share":
            value = lambda r: r["gross"] - r["fees"]  # noqa: E731
        else:
            value = lambda r: 0 if r["kind"] == "tips" else r["gross"]  # noqa: E731
        by_day, by_week, earned = {}, {}, set()
        for i, r in income:
            if not in_force(i):
                continue
            by_day[i] = by_day.get(i, 0) + value(r)
            by_week[i // 7] = by_week.get(i // 7, 0) + value(r)
            if rule["counts"] == "party" and value(r) >= rule["reaches"] - 0.005:
                earned.add(i)
        if rule["counts"] == "day":
            earned = {i for i, total in by_day.items() if total >= rule["reaches"] - 0.005}
        elif rule["counts"] == "week":
            earned = {w * 7 for w, total in by_week.items() if total >= rule["reaches"] - 0.005}
        for i in earned:
            freed = [i] if rule["frees"] == "day" else range(i // 7 * 7, i // 7 * 7 + 7)
            for f in freed:
                if f < days and in_force(f):
                    free.setdefault(f, describe(rule))
    return free


def apply(db, owner_id: int, tour_id: int):
    """Set a stay's room and board to $0 on its free days, and back to the full amount on the others.
    A charge that covers several days (by the week, month or stay) is free only when every day it covers is."""
    tour = db.execute("SELECT * FROM tours WHERE id = ? AND owner_id = ?", (tour_id, owner_id)).fetchone()
    if not tour:
        return
    tour = dict(tour)
    rows = db.execute("SELECT id, description, date, amount, board_full FROM expenses WHERE owner_id = ? AND tour_id = ? "
                      "AND (source = 'tour_room' OR (source = 'stay_charge' AND category = 'room_rent')) ORDER BY description, date",
                      (owner_id, tour_id)).fetchall()
    if not rows:
        return
    free = free_days(db, owner_id, tour)
    days = (date.fromisoformat(tour["end_date"]) - date.fromisoformat(tour["start_date"])).days + 1
    starts = _instant(tour["starts_at"])
    by_charge = {}
    for r in rows:
        by_charge.setdefault(r["description"], []).append(r)
    for group in by_charge.values():
        index = [(_instant(r["date"]) - starts).days for r in group]
        for n, r in enumerate(group):
            covers = range(index[n], index[n + 1] if n + 1 < len(group) else days)
            full = r["board_full"] if r["board_full"] is not None else r["amount"]
            why = free.get(index[n]) if covers and all(d in free for d in covers) else None
            if why:
                db.execute("UPDATE expenses SET amount = 0, board_full = ?, board_free = ? WHERE id = ?", (full, why, r["id"]))
            elif r["board_full"] is not None:
                db.execute("UPDATE expenses SET amount = ?, board_full = NULL, board_free = NULL WHERE id = ?", (full, r["id"]))


def income_changed(db, owner_id: int, *source_ids):
    """After income at these places was added, changed or removed: their stays' free days may have changed."""
    for source_id in {s for s in source_ids if s}:
        if not db.execute("SELECT 1 FROM place_board_rules WHERE owner_id = ? AND source_id = ? LIMIT 1", (owner_id, source_id)).fetchone():
            continue
        for (tour_id,) in db.execute("SELECT id FROM tours WHERE owner_id = ? AND source_id = ? AND kind = 'tour'",
                                     (owner_id, source_id)).fetchall():
            apply(db, owner_id, tour_id)


def booking_changed(db, owner_id: int, *instants):
    """After a booking was completed, changed or removed: the stays it fell in may have new free days."""
    for when in {w for w in instants if w}:
        for (tour_id, source_id) in db.execute(
                "SELECT id, source_id FROM tours WHERE owner_id = ? AND kind = 'tour' AND source_id IS NOT NULL "
                "AND starts_at <= ? AND ends_at > ?", (owner_id, when, when)).fetchall():
            if db.execute("SELECT 1 FROM place_board_rules WHERE owner_id = ? AND source_id = ? LIMIT 1", (owner_id, source_id)).fetchone():
                apply(db, owner_id, tour_id)


def _rules_changed(db, owner_id: int, source_id: int):
    for (tour_id,) in db.execute("SELECT id FROM tours WHERE owner_id = ? AND source_id = ? AND kind = 'tour'",
                                 (owner_id, source_id)).fetchall():
        apply(db, owner_id, tour_id)


# ==================== THE RULES, SET UP ON A PLACE ====================

class BoardRuleIn(BaseModel):
    counts: str = Field(..., pattern="^(party|day|week)$")        # one entry of income, a day's, a week's
    basis: str = Field("price", pattern="^(price|her_share)$")    # what the client paid, or what you kept
    reaches: float = Field(..., gt=0, le=10_000_000)
    frees: str = Field(..., pattern="^(day|week)$")
    starts_on: Optional[date] = None                              # the house's deal since then (empty: always)
    ends_on: Optional[date] = None                                # and until then (empty: still)


def _out(r) -> dict:
    return {**dict(r), "words": describe(r)}


def _place(db, owner_id: int, source_id: int):
    if not db.execute("SELECT 1 FROM income_sources WHERE id = ? AND owner_id = ?", (source_id, owner_id)).fetchone():
        raise HTTPException(status_code=404, detail="Place not found")


def _rule(db, owner_id: int, rule_id: int):
    row = db.execute("SELECT * FROM place_board_rules WHERE id = ? AND owner_id = ?", (rule_id, owner_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return row


def _values(body: BoardRuleIn) -> tuple:
    if body.starts_on and body.ends_on and body.ends_on < body.starts_on:
        raise HTTPException(status_code=400, detail="It can't end before it starts")
    return (body.counts, body.basis, body.reaches, body.frees,
            body.starts_on.isoformat() if body.starts_on else None, body.ends_on.isoformat() if body.ends_on else None)


@router.get("/api/income-sources/{source_id}/board-rules")
def list_rules(source_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _place(db, owner, source_id)
        return [_out(r) for r in db.execute("SELECT * FROM place_board_rules WHERE owner_id = ? AND source_id = ? ORDER BY id",
                                            (owner, source_id))]
    finally:
        db.close()


@router.post("/api/income-sources/{source_id}/board-rules", status_code=201)
def add_rule(source_id: int, body: BoardRuleIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _place(db, owner, source_id)
        cur = db.execute("INSERT INTO place_board_rules (owner_id, source_id, counts, basis, reaches, frees, starts_on, ends_on, "
                         "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (owner, source_id, *_values(body), _now(), _now()))
        _rules_changed(db, owner, source_id)
        db.commit()
        return _out(_rule(db, owner, cur.lastrowid))
    finally:
        db.close()


@router.put("/api/board-rules/{rule_id}")
def update_rule(rule_id: int, body: BoardRuleIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        old = _rule(db, owner, rule_id)
        db.execute("UPDATE place_board_rules SET counts = ?, basis = ?, reaches = ?, frees = ?, starts_on = ?, ends_on = ?, "
                   "updated_at = ? WHERE id = ?", (*_values(body), _now(), rule_id))
        _rules_changed(db, owner, old["source_id"])
        db.commit()
        return _out(_rule(db, owner, rule_id))
    finally:
        db.close()


@router.delete("/api/board-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        old = _rule(db, owner, rule_id)
        db.execute("DELETE FROM place_board_rules WHERE id = ?", (rule_id,))
        _rules_changed(db, owner, old["source_id"])
        db.commit()
    finally:
        db.close()
