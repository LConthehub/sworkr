"""
A quick daily wellness log (sleep, water, food, energy) and how it lines up with money.

Optional and private, like the period tracker. Each day has at most one entry. The comparison puts each logged
day next to what you earned that day, then shows the average for better and worse days (enough sleep or not,
enough water or not...). It's a pattern to notice, not a rule: few days logged means little to go on.

Apple Health can't be read by a website or a self-hosted app (only by an iPhone app); importing its export file
is a later step.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/wellness")
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


class DayIn(BaseModel):
    day: date
    sleep_hours: Optional[float] = None
    water_glasses: Optional[int] = None
    food: Optional[int] = None        # 1 (poor) .. 5 (great)
    energy: Optional[int] = None      # 1 .. 5
    note: Optional[str] = None


def _check(body: DayIn) -> DayIn:
    if body.sleep_hours is not None and not 0 <= body.sleep_hours <= 24:
        raise HTTPException(status_code=400, detail="Sleep is 0 to 24 hours")
    if body.water_glasses is not None and not 0 <= body.water_glasses <= 50:
        raise HTTPException(status_code=400, detail="Water is 0 to 50 glasses")
    for k in ("food", "energy"):
        v = getattr(body, k)
        if v is not None and not 1 <= v <= 5:
            raise HTTPException(status_code=400, detail="Food and energy are 1 to 5")
    body.note = (body.note or "").strip()[:500] or None
    return body


def _rows(db, owner: int, since: str) -> List[dict]:
    return [dict(r) for r in db.execute(
        "SELECT day, sleep_hours, water_glasses, food, energy, note FROM wellness_days WHERE owner_id = ? AND day >= ? ORDER BY day DESC",
        (owner, since))]


@router.get("")
def list_days(request: Request, days: int = Query(30, ge=1, le=730)):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return _rows(db, owner, (date.today() - timedelta(days=days - 1)).isoformat())
    finally:
        db.close()


@router.put("")
def save_day(body: DayIn, request: Request):
    _check(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        db.execute("""
            INSERT INTO wellness_days (owner_id, day, sleep_hours, water_glasses, food, energy, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, day) DO UPDATE SET sleep_hours = excluded.sleep_hours, water_glasses = excluded.water_glasses,
                food = excluded.food, energy = excluded.energy, note = excluded.note, updated_at = excluded.updated_at
        """, (owner, body.day.isoformat(), body.sleep_hours, body.water_glasses, body.food, body.energy, body.note,
              datetime.now(timezone.utc).isoformat(timespec="seconds")))
        db.commit()
        return dict(db.execute(
            "SELECT day, sleep_hours, water_glasses, food, energy, note FROM wellness_days WHERE owner_id = ? AND day = ?",
            (owner, body.day.isoformat())).fetchone())
    finally:
        db.close()


def earned_by_day(db, owner: int, since: str) -> dict:
    """What came in each day: paid bookings plus other income received, after fees."""
    out = {}
    for r in db.execute("SELECT substr(scheduled_date, 1, 10) AS d, SUM(amount_paid) AS v FROM appointments "
                        "WHERE owner_id = ? AND kind = 'client' AND status != 'cancelled' AND scheduled_date >= ? GROUP BY d", (owner, since)):
        out[r["d"]] = out.get(r["d"], 0) + (r["v"] or 0)
    for r in db.execute("SELECT substr(date, 1, 10) AS d, SUM(gross - fees) AS v FROM income "
                        "WHERE owner_id = ? AND status = 'received' AND date >= ? GROUP BY d", (owner, since)):
        out[r["d"]] = out.get(r["d"], 0) + (r["v"] or 0)
    return out


RULES = [  # (title, field, test for "better", label better, label worse)
    ("Sleep", "sleep_hours", lambda v: v >= 7, "7 hours or more", "less than 7"),
    ("Water", "water_glasses", lambda v: v >= 6, "6 glasses or more", "fewer than 6"),
    ("Food", "food", lambda v: v >= 4, "ate well (4–5)", "ate less well (1–3)"),
    ("Energy", "energy", lambda v: v >= 4, "high energy (4–5)", "lower energy (1–3)"),
]


@router.get("/vs-money")
def versus_money(request: Request, days: int = Query(180, ge=14, le=730)):
    """Average earned on better days and worse days, for each thing logged."""
    owner = request.state.user["id"]
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    db = _get_db()
    try:
        logged = _rows(db, owner, since)
        earned = earned_by_day(db, owner, since)
        out = []
        for title, field, better, yes, no in RULES:
            groups = {"better": [], "worse": []}
            for d in logged:
                if d[field] is not None:
                    groups["better" if better(d[field]) else "worse"].append(earned.get(d["day"], 0))
            avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
            out.append({"title": title, "better_label": yes, "worse_label": no,
                        "better_days": len(groups["better"]), "worse_days": len(groups["worse"]),
                        "better_avg": avg(groups["better"]), "worse_avg": avg(groups["worse"])})
        return {"days_logged": len(logged), "comparisons": out}
    finally:
        db.close()


class OnOff(BaseModel):
    enabled: bool


@router.get("/settings")
def get_settings(request: Request):
    db = _get_db()
    try:
        r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = 'wellness_on'", (request.state.user["id"],)).fetchone()
        return {"enabled": bool(r and r["value"] == "1")}
    finally:
        db.close()


@router.put("/settings")
def save_settings(body: OnOff, request: Request):
    db = _get_db()
    try:
        db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, 'wellness_on', ?) "
                   "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
                   (request.state.user["id"], "1" if body.enabled else "0"))
        db.commit()
        return {"enabled": body.enabled}
    finally:
        db.close()
