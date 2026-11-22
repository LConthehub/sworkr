"""
Quick work logs, what an hour really pays, and steady pay.

- A log is "I did a shift / a stream / calls / a scene / a sale": when, how long, what came in. It makes the
  income entry for you and remembers the hours, so sworkr can say what an hour pays.
- Per hour: for each kind of work, what came in (after fees) divided by the hours it took. Bookings count their
  own length plus the getting-ready and travel time you set. The bottom line takes all your costs off too.
- Steady pay: for uneven months. You pay yourself the same amount each week out of a buffer envelope; sworkr
  suggests an amount from your last six months and says how many weeks the buffer covers.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import board

router = APIRouter()
_get_db: Optional[Callable] = None

KINDS = {"shift": "Shift", "stream": "Stream", "call": "Calls & chat", "scene": "Scene", "sale": "Sale"}
INCOME_KIND = {"shift": "shift", "stream": "shift", "call": "shift", "scene": "booking", "sale": "sale"}
UNITS = {"shift": "dances or bookings", "stream": "tokens", "call": "minutes", "scene": None, "sale": "items"}


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _setting(db, owner: int, key: str) -> Optional[str]:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (owner, key)).fetchone()
    return r["value"] if r else None


def _put(db, owner: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, key, value))


class LogIn(BaseModel):
    kind: str
    source_id: Optional[int] = None
    day: Optional[date] = None
    hours: Optional[float] = None
    units: Optional[float] = None        # tokens, minutes, dances, items
    gross: float = 0                     # what came in, tips included, before the place's cut
    fees: float = 0                      # what the club, site or agent kept
    pending: bool = False                # not paid out to you yet
    note: Optional[str] = None


def _rows(db, owner: int, since: str) -> List[dict]:
    return [dict(r) for r in db.execute("""
        SELECT w.id, w.kind, w.source_id, s.name AS source_name, w.day, w.hours, w.units, w.note, w.income_id,
               i.gross, i.fees, i.status
        FROM work_logs w LEFT JOIN income_sources s ON s.id = w.source_id LEFT JOIN income i ON i.id = w.income_id
        WHERE w.owner_id = ? AND w.day >= ? ORDER BY w.day DESC, w.id DESC
    """, (owner, since))]


@router.get("/api/worklog")
def list_logs(request: Request, days: int = Query(90, ge=1, le=3660)):
    db = _get_db()
    try:
        return _rows(db, request.state.user["id"], (date.today() - timedelta(days=days)).isoformat())
    finally:
        db.close()


@router.post("/api/worklog", status_code=201)
def add_log(body: LogIn, request: Request):
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail="A shift, stream, calls, scene or sale")
    if body.hours is not None and not 0 <= body.hours <= 24:
        raise HTTPException(status_code=400, detail="Hours are 0 to 24")
    if not 0 <= body.gross < 1e7 or not 0 <= body.fees <= max(body.gross, 0):
        raise HTTPException(status_code=400, detail="Check the amounts: the cut can't be more than what came in")
    owner = request.state.user["id"]
    day = body.day or date.today()
    db = _get_db()
    try:
        source_name = None
        if body.source_id is not None:
            s = db.execute("SELECT name FROM income_sources WHERE id = ? AND owner_id = ?", (body.source_id, owner)).fetchone()
            if not s:
                raise HTTPException(status_code=404, detail="Workplace or platform not found")
            source_name = s["name"]
        income_id = None
        if body.gross > 0:
            cur = db.execute("""
                INSERT INTO income (date, description, kind, gross, fees, status, source_id, owner_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (f"{day.isoformat()}T12:00:00+00:00", " – ".join(x for x in (KINDS[body.kind], source_name) if x),
                  INCOME_KIND[body.kind], round(body.gross, 2), round(body.fees, 2), "pending" if body.pending else "received",
                  body.source_id, owner, _now(), _now()))
            income_id = cur.lastrowid
        cur = db.execute("INSERT INTO work_logs (owner_id, kind, source_id, day, hours, units, income_id, note, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (owner, body.kind, body.source_id, day.isoformat(), body.hours, body.units, income_id,
                          (body.note or "").strip()[:300] or None, _now()))
        board.income_changed(db, owner, body.source_id)
        db.commit()
        return next(r for r in _rows(db, owner, day.isoformat()) if r["id"] == cur.lastrowid)
    finally:
        db.close()


@router.delete("/api/worklog/{log_id}", status_code=204)
def delete_log(log_id: int, request: Request):
    """Remove a log and the income entry it made."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        r = db.execute("SELECT income_id, source_id FROM work_logs WHERE id = ? AND owner_id = ?", (log_id, owner)).fetchone()
        if r:
            if r["income_id"]:
                db.execute("DELETE FROM income WHERE id = ? AND owner_id = ?", (r["income_id"], owner))
            db.execute("DELETE FROM work_logs WHERE id = ?", (log_id,))
            board.income_changed(db, owner, r["source_id"])
            db.commit()
    finally:
        db.close()


# ==================== WHAT AN HOUR REALLY PAYS ====================

class PrepIn(BaseModel):
    prep_minutes: int


@router.put("/api/per-hour/prep")
def save_prep(body: PrepIn, request: Request):
    if not 0 <= body.prep_minutes <= 600:
        raise HTTPException(status_code=400, detail="From 0 to 600 minutes")
    db = _get_db()
    try:
        _put(db, request.state.user["id"], "prep_minutes", str(body.prep_minutes))
        db.commit()
        return {"prep_minutes": body.prep_minutes}
    finally:
        db.close()


@router.get("/api/per-hour")
def per_hour(request: Request, days: int = Query(90, ge=7, le=730)):
    owner = request.state.user["id"]
    since = (date.today() - timedelta(days=days)).isoformat()
    db = _get_db()
    try:
        prep = int(_setting(db, owner, "prep_minutes") or 60)
        rows = []
        # Getting ready and travel count for each booking, except parties during a stay at a workplace (a house):
        # you're already there.
        b = db.execute("""
            SELECT COUNT(*) AS n, COALESCE(SUM(a.duration_minutes), 0) AS minutes, COALESCE(SUM(a.amount_paid), 0) AS paid,
                   SUM(CASE WHEN EXISTS (SELECT 1 FROM tours t WHERE t.owner_id = a.owner_id AND t.kind = 'tour'
                        AND t.source_id IS NOT NULL AND substr(a.scheduled_date, 1, 10) BETWEEN t.start_date AND t.end_date)
                       THEN 0 ELSE 1 END) AS travelled
            FROM appointments a WHERE a.owner_id = ? AND a.kind = 'client' AND a.status = 'completed' AND a.scheduled_date >= ?
        """, (owner, since)).fetchone()
        if b["n"]:
            hours = (b["minutes"] + prep * (b["travelled"] or 0)) / 60
            rows.append({"label": "Bookings", "count": b["n"], "net": round(b["paid"], 2), "hours": round(hours, 1),
                         "per_hour": round(b["paid"] / hours, 2) if hours else None,
                         "note": f"their length plus {prep} minutes each for getting ready and travel"})
        for r in db.execute("""
            SELECT w.kind, s.name AS source, COUNT(*) AS n, COALESCE(SUM(w.hours), 0) AS hours,
                   COALESCE(SUM(i.gross - i.fees), 0) AS net
            FROM work_logs w LEFT JOIN income_sources s ON s.id = w.source_id LEFT JOIN income i ON i.id = w.income_id
            WHERE w.owner_id = ? AND w.day >= ? GROUP BY w.kind, w.source_id ORDER BY net DESC
        """, (owner, since)):
            rows.append({"label": " – ".join(x for x in (KINDS[r["kind"]], r["source"]) if x), "count": r["n"],
                         "net": round(r["net"], 2), "hours": round(r["hours"], 1),
                         "per_hour": round(r["net"] / r["hours"], 2) if r["hours"] else None, "note": None})
        # Only income with hours behind it: a payout with no hours logged would make an hour look better than it is.
        income = sum(r["net"] for r in rows if r["hours"])
        costs = db.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE owner_id = ? AND date >= ?", (owner, since)).fetchone()[0]
        hours = sum(r["hours"] for r in rows)
        return {"days": days, "prep_minutes": prep, "rows": rows,
                "overall": {"income": round(income, 2), "costs": round(costs, 2), "hours": round(hours, 1),
                            "per_hour": round((income - costs) / hours, 2) if hours else None}}
    finally:
        db.close()


# ==================== STEADY PAY ====================

def _first_record(db, owner: int) -> Optional[str]:
    days = [db.execute(sql, (owner,)).fetchone()[0] for sql in (
        "SELECT MIN(scheduled_date) FROM appointments WHERE owner_id = ? AND kind = 'client'",
        "SELECT MIN(date) FROM income WHERE owner_id = ?",
        "SELECT MIN(date) FROM expenses WHERE owner_id = ?")]
    days = [d[:10] for d in days if d]
    return min(days) if days else None


def _monthly_net(db, owner: int, today: date) -> List[float]:
    """What was left each of the last six full months: everything received, less everything spent. Months
    before your first record are left out: they're months before you used sworkr, not months with no income."""
    out = []
    began = _first_record(db, owner)
    first = today.replace(day=1)
    for _ in range(6):
        end = first
        first = (first - timedelta(days=1)).replace(day=1)
        if began is None or end.isoformat() <= began:
            break
        lo, hi = first.isoformat(), end.isoformat()
        booked = db.execute("SELECT COALESCE(SUM(amount_paid), 0) FROM appointments WHERE owner_id = ? AND kind = 'client' "
                            "AND status != 'cancelled' AND scheduled_date >= ? AND scheduled_date < ?", (owner, lo, hi)).fetchone()[0]
        other = db.execute("SELECT COALESCE(SUM(gross - fees), 0) FROM income WHERE owner_id = ? AND status = 'received' "
                           "AND date >= ? AND date < ?", (owner, lo, hi)).fetchone()[0]
        spent = db.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE owner_id = ? AND date >= ? AND date < ?",
                           (owner, lo, hi)).fetchone()[0]
        out.append(round(booked + other - spent, 2))
    return out


class SteadyIn(BaseModel):
    weekly: Optional[float] = None       # what you pay yourself each week; empty turns it off
    goal_id: Optional[int] = None        # the wallet envelope that is your buffer


@router.get("/api/steady-pay")
def steady_pay(request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        months = _monthly_net(db, owner, date.today())
        average = sum(months) / len(months) if months else 0
        lean = sorted(months)[1] if len(months) > 1 else average   # the second-leanest month: a careful base
        suggested = max(0, int((min(average * 0.8, max(lean, average * 0.5)) / 4.33) // 10 * 10))
        weekly = float(_setting(db, owner, "steady_weekly") or 0) or None
        goal_id = int(_setting(db, owner, "steady_goal") or 0) or None
        buffer = None
        if goal_id:
            g = db.execute("SELECT name FROM goals WHERE id = ? AND owner_id = ?", (goal_id, owner)).fetchone()
            if g:
                balance = db.execute("SELECT COALESCE(SUM(amount), 0) FROM goal_entries WHERE goal_id = ?", (goal_id,)).fetchone()[0]
                buffer = {"goal_id": goal_id, "name": g["name"], "balance": round(balance, 2),
                          "weeks": round(balance / weekly, 1) if weekly else None}
        return {"months": months, "average_month": round(average, 2), "suggested_weekly": suggested, "weekly": weekly, "buffer": buffer}
    finally:
        db.close()


@router.put("/api/steady-pay")
def save_steady_pay(body: SteadyIn, request: Request):
    if body.weekly is not None and not 0 < body.weekly < 1e6:
        raise HTTPException(status_code=400, detail="A weekly amount above 0")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        if body.goal_id is not None and not db.execute("SELECT 1 FROM goals WHERE id = ? AND owner_id = ?", (body.goal_id, owner)).fetchone():
            raise HTTPException(status_code=404, detail="Envelope not found")
        _put(db, owner, "steady_weekly", str(body.weekly) if body.weekly else None)
        _put(db, owner, "steady_goal", str(body.goal_id) if body.goal_id else None)
        db.commit()
    finally:
        db.close()
    return steady_pay(request)
