"""
Progress: small private rewards for the things that keep the business healthy. All of it optional, never public,
never compared with anyone, and none of it pushes working more: goals are only the ones the person sets, and
badges are for setup and safety, not output. One switch turns everything off.

- Streaks: posting what you planned, finishing a routine, logging money. One missed day pauses a streak; two in
  a row end it (rest is part of the job).
- Weekly goals the person sets ("3 posts", "log money 5 days"), counted Monday to Sunday.
- Personal bests: best week, best tour per working day, most inquiries from one post, longest posting streak.
- Badges for setup and safety.
- Tour wrap-up for a tour that ended in the last two weeks.
- Wallet level: how many months of costs the Wallet covers.
"""

import os
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Set

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/progress")
_get_db: Optional[Callable] = None

GOAL_KINDS = {
    "posts": "Posts put up",
    "money_days": "Days money was logged",
    "routines": "Routines finished",
    "checkins": "Wellness check-ins",
    "bookings": "Bookings logged",
}


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _setting(db, owner: int, key: str) -> Optional[str]:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (owner, key)).fetchone()
    return r["value"] if r else None


# ==================== STREAKS ====================

def streak(days: Set[str], today: date, skip: Optional[Set[str]] = None) -> dict:
    """Days in a row ending today (or yesterday) that count. One missing day pauses, two in a row end it.
    `skip` days (nothing was planned) neither count nor break."""
    skip = skip or set()
    count, misses, d, paused = 0, 0, today, False
    if d.isoformat() not in days and d.isoformat() not in skip:
        d -= timedelta(days=1)          # today isn't over yet
    for _ in range(3660):
        key = d.isoformat()
        if key in days:
            if count == 0 and misses:
                paused = True           # the most recent day that counted has a missed day after it
            count, misses = count + 1, 0
        elif key in skip:
            pass
        else:
            misses += 1
            if misses >= 2:
                break
        d -= timedelta(days=1)
    return {"days": count, "paused": paused and count > 0}


def longest(days: Iterable[str]) -> int:
    """The longest run ever, with the same pause rule (one gap allowed)."""
    best, run, last = 0, 0, None
    for key in sorted(set(days)):
        d = date.fromisoformat(key)
        run = run + 1 if last and (d - last).days <= 2 else 1
        best, last = max(best, run), d
    return best


def _post_days(db, owner: int):
    """Days every planned post went up, and days nothing was planned (they pause, not break)."""
    planned, done = {}, {}
    for r in db.execute("SELECT substr(COALESCE(scheduled_at, posted_at), 1, 10) AS d, status FROM posts "
                        "WHERE owner_id = ? AND status != 'skipped' AND COALESCE(scheduled_at, posted_at) IS NOT NULL", (owner,)):
        planned[r["d"]] = planned.get(r["d"], 0) + 1
        done[r["d"]] = done.get(r["d"], 0) + (r["status"] == "posted")
    return {d for d, n in planned.items() if done[d] == n}, set(planned)


def _routine_days(db, owner: int) -> Set[str]:
    return {r["day"] for r in db.execute("""
        SELECT c.day, s.routine_id, COUNT(*) AS ticked,
               (SELECT COUNT(*) FROM routine_steps x WHERE x.routine_id = s.routine_id) AS total
        FROM routine_checks c JOIN routine_steps s ON s.id = c.step_id
        WHERE c.owner_id = ? GROUP BY c.day, s.routine_id HAVING ticked >= total
    """, (owner,))}


def _money_days(db, owner: int) -> Set[str]:
    days = set()
    for table in ("expenses", "income"):
        days |= {r[0] for r in db.execute(f"SELECT DISTINCT substr(created_at, 1, 10) FROM {table} WHERE owner_id = ?", (owner,))}
    return days


# ==================== WEEKLY GOALS ====================

def _week(today: date):
    start = today - timedelta(days=today.weekday())
    return start.isoformat(), (start + timedelta(days=7)).isoformat()


def week_count(db, owner: int, kind: str, today: date) -> int:
    lo, hi = _week(today)
    if kind == "posts":
        return db.execute("SELECT COUNT(*) FROM posts WHERE owner_id = ? AND status = 'posted' AND posted_at >= ? AND posted_at < ?",
                          (owner, lo, hi)).fetchone()[0]
    if kind == "money_days":
        return sum(1 for d in _money_days(db, owner) if lo <= d < hi)
    if kind == "routines":
        return db.execute("""
            SELECT COUNT(*) FROM (SELECT c.day, s.routine_id, COUNT(*) AS ticked,
                   (SELECT COUNT(*) FROM routine_steps x WHERE x.routine_id = s.routine_id) AS total
                   FROM routine_checks c JOIN routine_steps s ON s.id = c.step_id
                   WHERE c.owner_id = ? AND c.day >= ? AND c.day < ? GROUP BY c.day, s.routine_id HAVING ticked >= total)
        """, (owner, lo, hi)).fetchone()[0]
    if kind == "checkins":
        return db.execute("SELECT COUNT(*) FROM wellness_days WHERE owner_id = ? AND day >= ? AND day < ?", (owner, lo, hi)).fetchone()[0]
    if kind == "bookings":
        return db.execute("SELECT COUNT(*) FROM appointments WHERE owner_id = ? AND kind = 'client' AND created_at >= ? AND created_at < ?",
                          (owner, lo, hi)).fetchone()[0]
    return 0


class GoalIn(BaseModel):
    kind: str
    target: int


@router.post("/goals", status_code=201)
def add_goal(body: GoalIn, request: Request):
    if body.kind not in GOAL_KINDS:
        raise HTTPException(status_code=400, detail="Unknown kind of goal")
    if not 1 <= body.target <= 100:
        raise HTTPException(status_code=400, detail="A weekly goal is 1 to 100")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        db.execute("INSERT INTO progress_goals (owner_id, kind, target) VALUES (?, ?, ?) "
                   "ON CONFLICT(owner_id, kind) DO UPDATE SET target = excluded.target", (owner, body.kind, body.target))
        db.commit()
        return {"kind": body.kind, "target": body.target}
    finally:
        db.close()


@router.delete("/goals/{kind}", status_code=204)
def delete_goal(kind: str, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM progress_goals WHERE owner_id = ? AND kind = ?", (request.state.user["id"], kind))
        db.commit()
    finally:
        db.close()


# ==================== BESTS, BADGES, WRAP-UP, WALLET ====================

def _earned_by_day(db, owner: int) -> Dict[str, float]:
    out = {}
    for r in db.execute("SELECT substr(scheduled_date, 1, 10) AS d, SUM(amount_paid) AS v FROM appointments "
                        "WHERE owner_id = ? AND kind = 'client' AND status != 'cancelled' GROUP BY d", (owner,)):
        out[r["d"]] = out.get(r["d"], 0) + (r["v"] or 0)
    for r in db.execute("SELECT substr(date, 1, 10) AS d, SUM(gross - fees) AS v FROM income "
                        "WHERE owner_id = ? AND status = 'received' GROUP BY d", (owner,)):
        out[r["d"]] = out.get(r["d"], 0) + (r["v"] or 0)
    return out


def bests(db, owner: int, post_days: Set[str]) -> List[dict]:
    out = []
    weeks = {}
    for d, v in _earned_by_day(db, owner).items():
        try:
            day = date.fromisoformat(d)
        except ValueError:
            continue
        monday = (day - timedelta(days=day.weekday())).isoformat()
        weeks[monday] = weeks.get(monday, 0) + v
    if weeks:
        wk, v = max(weeks.items(), key=lambda kv: kv[1])
        if v > 0:
            out.append({"title": "Best week", "value": round(v, 2), "money": True, "when": f"week of {wk}"})
    import main
    best_tour = None
    for t in db.execute("SELECT * FROM tours WHERE owner_id = ? AND kind = 'tour' AND end_date < ? ORDER BY end_date DESC LIMIT 60",
                        (owner, date.today().isoformat())):
        f = main.tour_figures(db, owner, dict(t))
        if f.get("profit_per_day") is not None and (best_tour is None or f["profit_per_day"] > best_tour[1]):
            best_tour = (t["name"], f["profit_per_day"])
    if best_tour and best_tour[1] > 0:
        out.append({"title": "Best tour per working day", "value": best_tour[1], "money": True, "when": best_tour[0]})
    r = db.execute("SELECT platform, inquiries, posted_at FROM posts WHERE owner_id = ? AND inquiries > 0 "
                   "ORDER BY inquiries DESC LIMIT 1", (owner,)).fetchone()
    if r:
        out.append({"title": "Most inquiries from one post", "value": r["inquiries"], "money": False,
                    "when": f"{r['platform']}, {(r['posted_at'] or '')[:10]}"})
    run = longest(post_days)
    if run:
        out.append({"title": "Longest posting streak", "value": run, "money": False, "when": "days"})
    return out


def badges(db, owner: int, routine_days: Set[str]) -> List[dict]:
    import backup
    import signin
    try:
        backed_up = bool(backup.list_backups())
    except OSError:
        backed_up = False
    passkey = bool(db.execute("SELECT 1 FROM passkeys WHERE user_id = ?", (owner,)).fetchone())
    two_step = signin.two_step_on(db, owner)
    checkin = bool(db.execute("SELECT 1 FROM appointments WHERE owner_id = ? AND safety_checkin = 1 AND checked_in_at IS NOT NULL",
                              (owner,)).fetchone())
    week_of_routines = any(all((date.fromisoformat(d) + timedelta(days=i)).isoformat() in routine_days for i in range(7))
                           for d in routine_days)
    closed = db.execute("""
        SELECT substr(date, 1, 7) AS m FROM expenses WHERE owner_id = ? AND date < ?
        GROUP BY m HAVING COUNT(*) >= 3 AND SUM(CASE WHEN category IS NULL OR category = 'other' THEN 1 ELSE 0 END) = 0 LIMIT 1
    """, (owner, date.today().replace(day=1).isoformat())).fetchone()
    return [
        {"id": "backup", "title": "Backed up", "how": "Turn on backups (Settings → Data & users)", "earned": backed_up},
        {"id": "two_step", "title": "Two locks", "how": "Turn on two-step sign-in", "earned": two_step},
        {"id": "passkey", "title": "Face or fingerprint", "how": "Add a passkey", "earned": passkey},
        {"id": "checkin", "title": "Someone has your back", "how": "Use the safety check-in on a booking", "earned": checkin},
        {"id": "routines_week", "title": "A week of routines", "how": "Finish a routine 7 days in a row", "earned": week_of_routines},
        {"id": "books_closed", "title": "Books closed", "how": "A month where every expense has a category", "earned": bool(closed)},
    ]


def tour_wrapup(db, owner: int, today: date) -> Optional[dict]:
    """The tour that ended most recently, if within the last two weeks."""
    import main
    t = db.execute("SELECT * FROM tours WHERE owner_id = ? AND kind = 'tour' AND end_date < ? AND end_date >= ? "
                   "ORDER BY end_date DESC LIMIT 1", (owner, today.isoformat(), (today - timedelta(days=14)).isoformat())).fetchone()
    if not t:
        return None
    t = dict(t)
    f = main.tour_figures(db, owner, t)
    by_day = {d: v for d, v in _earned_by_day(db, owner).items() if t["start_date"] <= d <= t["end_date"]}
    best_day = max(by_day.items(), key=lambda kv: kv[1]) if by_day else None
    new_regulars = db.execute("""
        SELECT COUNT(*) FROM clients c WHERE c.owner_id = ? AND
          (SELECT MIN(substr(scheduled_date, 1, 10)) FROM appointments a WHERE a.client_id = c.id AND a.kind = 'client'
             AND a.status != 'cancelled') BETWEEN ? AND ?
    """, (owner, t["start_date"], t["end_date"])).fetchone()[0]
    return {"tour_id": t["id"], "name": t["name"], "income": f["income"], "expenses": f["expenses"], "profit": f["profit"],
            "profit_per_day": f["profit_per_day"], "best_day": {"day": best_day[0], "earned": round(best_day[1], 2)} if best_day and best_day[1] > 0 else None,
            "new_clients": new_regulars}


def wallet_level(db, owner: int, today: date) -> Optional[dict]:
    balance = 0.0
    for g in db.execute("SELECT id, source_id FROM goals WHERE owner_id = ? AND archived = 0 AND kind = 'savings'", (owner,)):
        balance += db.execute("SELECT COALESCE(SUM(amount), 0) FROM goal_entries WHERE goal_id = ?", (g["id"],)).fetchone()[0]
    since = (today.replace(day=1) - timedelta(days=180)).isoformat()
    spent = db.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE owner_id = ? AND date >= ? AND date < ?",
                       (owner, since, today.replace(day=1).isoformat())).fetchone()[0]
    monthly = spent / 6
    if balance <= 0 or monthly <= 0:
        return None
    months = balance / monthly
    level = 3 if months >= 6 else 2 if months >= 3 else 1 if months >= 1 else 0
    return {"balance": round(balance, 2), "monthly_costs": round(monthly, 2), "months": round(months, 1), "level": level,
            "next": [1, 3, 6][level] if level < 3 else None}


# ==================== THE CARD ====================

class OnOff(BaseModel):
    enabled: bool


@router.put("/settings")
def save_settings(body: OnOff, request: Request):
    db = _get_db()
    try:
        db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, 'progress_off', ?) "
                   "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
                   (request.state.user["id"], "0" if body.enabled else "1"))
        db.commit()
        return {"enabled": body.enabled}
    finally:
        db.close()


@router.get("")
def progress(request: Request, day: Optional[date] = None):
    owner = request.state.user["id"]
    today = day or date.today()         # the browser's day: the server's clock is UTC
    db = _get_db()
    try:
        if _setting(db, owner, "progress_off") == "1":
            return {"enabled": False}
        post_days, planned_days = _post_days(db, owner)
        routine_days = _routine_days(db, owner)
        money_days = _money_days(db, owner)
        goals = [{"kind": r["kind"], "label": GOAL_KINDS.get(r["kind"], r["kind"]), "target": r["target"],
                  "done": week_count(db, owner, r["kind"], today)}
                 for r in db.execute("SELECT kind, target FROM progress_goals WHERE owner_id = ? ORDER BY rowid", (owner,))]
        all_days = {(today - timedelta(days=i)).isoformat() for i in range(3660)}
        return {
            "enabled": True,
            "streaks": [
                {"id": "posting", "title": "Posting what you planned", **streak(post_days, today, skip=all_days - planned_days)},
                {"id": "routines", "title": "Finishing a routine", **streak(routine_days, today)},
                {"id": "money", "title": "Logging money", **streak(money_days, today)},
            ],
            "goals": goals,
            "goal_kinds": GOAL_KINDS,
            "bests": bests(db, owner, post_days),
            "badges": badges(db, owner, routine_days),
            "tour_wrapup": tour_wrapup(db, owner, today),
            "wallet": wallet_level(db, owner, today),
        }
    finally:
        db.close()
