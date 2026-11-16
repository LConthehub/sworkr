"""
The health tests a person takes, set up the way their own rules need.

How often a test is required, and what it costs, depends on where someone works: a county, a venue or an
agency each set their own rules, and some people test on their own schedule. So nothing here is fixed.
Each kind of test has a name, how many days apart it's due (or no schedule), and its usual cost. Everyone
starts with weekly, monthly and yearly, and can rename them, change how often and how much, add others
("Every 14 days", "Quarterly bloodwork") and hide the ones they don't use.

From a test's last date and its interval, sworkr works out when the next one is due, and says so before then.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
_get_db: Optional[Callable] = None

# (key, name, days apart). The keys are the ones tests have always been saved with.
STARTERS = [("weekly", "Weekly test", 7), ("monthly", "Monthly test", 30), ("yearly", "Yearly test", 365)]
SOON_DAYS = 3


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _owner(request: Request) -> int:
    return request.state.user["id"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_kinds(db, owner_id: int):
    """Everyone has the three starter kinds, added the first time they're needed. A cost remembered from before
    kinds could be changed comes along."""
    have = {r[0] for r in db.execute("SELECT key FROM test_kinds WHERE owner_id = ?", (owner_id,))}
    added = False
    for order, (key, label, days) in enumerate(STARTERS):
        if key in have:
            continue
        old = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (owner_id, f"test_cost_{key}")).fetchone()
        try:
            cost = float(old[0]) if old and old[0] not in (None, "") else None
        except ValueError:
            cost = None
        db.execute("INSERT OR IGNORE INTO test_kinds (owner_id, key, label, every_days, cost, sort_order, created_at, updated_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (owner_id, key, label, days, cost, order, _now(), _now()))
        added = True
    if added:
        db.commit()


def get_kind(db, owner_id: int, key: Optional[str]) -> Optional[dict]:
    ensure_kinds(db, owner_id)
    r = db.execute("SELECT * FROM test_kinds WHERE owner_id = ? AND key = ?", (owner_id, key or "")).fetchone()
    return dict(r) if r else None


def check(db, owner_id: int, key: Optional[str]) -> dict:
    """The kind of test with this key, or a 400 saying to choose one."""
    kind = get_kind(db, owner_id, key)
    if not kind:
        raise HTTPException(status_code=400, detail="Choose which health test this is")
    return kind


def remember_cost(db, owner_id: int, key: str, cost: float):
    """The next test of this kind starts with what this one cost."""
    db.execute("UPDATE test_kinds SET cost = ?, updated_at = ? WHERE owner_id = ? AND key = ?", (cost, _now(), owner_id, key))


def kinds(db, owner_id: int) -> List[dict]:
    """Each kind with when it was last done, when it's next due, and whether one is already booked."""
    ensure_kinds(db, owner_id)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    out = []
    for r in db.execute("""
        SELECT k.*,
               (SELECT MAX(a.scheduled_date) FROM appointments a WHERE a.owner_id = k.owner_id AND a.kind = 'test'
                  AND a.test_type = k.key AND a.status != 'cancelled' AND a.scheduled_date <= ?) AS last_done,
               (SELECT MIN(a.scheduled_date) FROM appointments a WHERE a.owner_id = k.owner_id AND a.kind = 'test'
                  AND a.test_type = k.key AND a.status = 'scheduled' AND a.scheduled_date > ?) AS next_booked,
               (SELECT COUNT(*) FROM appointments a WHERE a.owner_id = k.owner_id AND a.test_type = k.key) AS tests
        FROM test_kinds k WHERE k.owner_id = ? ORDER BY k.archived, k.sort_order, k.id
    """, (now_iso, now_iso, owner_id)):
        d = dict(r)
        d["archived"] = bool(d["archived"])
        d["starter"] = d["key"] in {s[0] for s in STARTERS}
        d["next_due"], d["due_in_days"], d["state"] = None, None, "none"
        if d["every_days"] and d["last_done"] and not d["archived"]:
            due = datetime.fromisoformat(d["last_done"]) + timedelta(days=d["every_days"])
            d["next_due"] = due.isoformat(timespec="seconds")
            d["due_in_days"] = (due.date() - now.date()).days
            covered = d["next_booked"] and datetime.fromisoformat(d["next_booked"]).date() <= due.date()
            d["state"] = "booked" if covered else "overdue" if d["due_in_days"] < 0 else "soon" if d["due_in_days"] <= SOON_DAYS else "ok"
        out.append(d)
    return out


class KindIn(BaseModel):
    label: str
    every_days: Optional[int] = None      # how many days apart it's due; None: no schedule
    cost: Optional[float] = None          # what it usually costs
    archived: bool = False


def _values(body: KindIn) -> tuple:
    label = re.sub(r"\s+", " ", body.label or "").strip()[:60]
    if not label:
        raise HTTPException(status_code=400, detail="Give the test a name")
    if body.every_days is not None and not (1 <= body.every_days <= 3650):
        raise HTTPException(status_code=400, detail="Days between tests is 1 to 3650 (or leave it empty for no schedule)")
    if body.cost is not None and not (0 <= body.cost < 1e9):
        raise HTTPException(status_code=400, detail="The cost must be 0 or more")
    return label, body.every_days, body.cost, int(body.archived)


def _one(db, owner_id: int, kind_id: int) -> Optional[dict]:
    return next((k for k in kinds(db, owner_id) if k["id"] == kind_id), None)


@router.get("/api/test-kinds")
def list_kinds(request: Request):
    db = _get_db()
    try:
        return kinds(db, _owner(request))
    finally:
        db.close()


@router.post("/api/test-kinds", status_code=201)
def add_kind(body: KindIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        ensure_kinds(db, owner)
        label, days, cost, archived = _values(body)
        last = db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM test_kinds WHERE owner_id = ?", (owner,)).fetchone()[0]
        cur = db.execute("INSERT INTO test_kinds (owner_id, key, label, every_days, cost, archived, sort_order, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (owner, "t" + uuid.uuid4().hex[:10], label, days, cost, archived, last + 1, _now(), _now()))
        db.commit()
        return _one(db, owner, cur.lastrowid)
    finally:
        db.close()


@router.put("/api/test-kinds/{kind_id}")
def update_kind(kind_id: int, body: KindIn, request: Request):
    """Rename it, change how often it's due or what it costs, or hide it. Tests already on the calendar keep
    the name they were saved with."""
    owner = _owner(request)
    db = _get_db()
    try:
        ensure_kinds(db, owner)
        done = db.execute("UPDATE test_kinds SET label = ?, every_days = ?, cost = ?, archived = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                          (*_values(body), _now(), kind_id, owner))
        if not done.rowcount:
            raise HTTPException(status_code=404, detail="Not found")
        db.commit()
        return _one(db, owner, kind_id)
    finally:
        db.close()


@router.delete("/api/test-kinds/{kind_id}", status_code=204)
def delete_kind(kind_id: int, request: Request):
    """A kind that has never been used is removed. One with tests on the calendar, or a starter, is hidden
    instead, so the history keeps its name."""
    owner = _owner(request)
    db = _get_db()
    try:
        kind = _one(db, owner, kind_id)
        if not kind:
            return
        used = kind["tests"] or db.execute("SELECT 1 FROM place_charges WHERE owner_id = ? AND test_type = ?", (owner, kind["key"])).fetchone()
        if used or kind["starter"]:
            db.execute("UPDATE test_kinds SET archived = 1, updated_at = ? WHERE id = ? AND owner_id = ?", (_now(), kind_id, owner))
        else:
            db.execute("DELETE FROM test_kinds WHERE id = ? AND owner_id = ?", (kind_id, owner))
        db.commit()
    finally:
        db.close()
