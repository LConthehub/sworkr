"""
Routines: checklists that go together and come round again, like a morning routine, a night routine, or what to
do before and after a booking. Each is fully the person's own: its name, when it's for, and its steps.

Steps are ticked off for a day; tomorrow starts fresh. Routines are kept apart from tasks, so they don't fill
the to-do list or the calendar. Until someone saves one, a few starters are offered as ideas.
"""

from datetime import date, datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/routines")
_get_db: Optional[Callable] = None

WHEN = ("morning", "night", "before_booking", "after_booking", "any")
MAX_STEPS = 50

# Ideas, not rules: shown until the person saves a routine of their own.
STARTERS = [
    ("Morning", "morning", ["Water and something to eat", "Check today's bookings", "Answer new inquiries",
                            "Put up the posts due today"]),
    ("Before a booking", "before_booking", ["Screening checked", "Safety check-in turned on",
                                            "Bag packed (see your pack list)", "Someone you trust knows where you are"]),
    ("After a booking", "after_booking", ["Check in: I'm safe", "Log the payment and any tip",
                                          "A few notes about how it went", "Rest, shower, eat"]),
    ("Night", "night", ["Log today's money", "Look at tomorrow", "Phone charging", "Something just for you"]),
]


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RoutineIn(BaseModel):
    name: str
    when: str = "any"
    steps: List[str] = []


def _check(body: RoutineIn) -> RoutineIn:
    body.name = (body.name or "").strip()[:80]
    if not body.name:
        raise HTTPException(status_code=400, detail="Give the routine a name")
    if body.when not in WHEN:
        raise HTTPException(status_code=400, detail="Unknown time for the routine")
    body.steps = [s.strip()[:200] for s in body.steps if (s or "").strip()][:MAX_STEPS]
    if not body.steps:
        raise HTTPException(status_code=400, detail="Add at least one step")
    return body


def _routines(db, owner: int, day: str) -> List[dict]:
    out = []
    for r in db.execute("SELECT id, name, when_for, sort_order FROM routines WHERE owner_id = ? ORDER BY sort_order, id", (owner,)):
        steps = [{"id": s["id"], "label": s["label"], "done": bool(s["done"])} for s in db.execute(
            "SELECT st.id, st.label, EXISTS(SELECT 1 FROM routine_checks c WHERE c.step_id = st.id AND c.day = ?) AS done "
            "FROM routine_steps st WHERE st.routine_id = ? ORDER BY st.sort_order, st.id", (day, r["id"]))]
        out.append({"id": r["id"], "name": r["name"], "when": r["when_for"], "steps": steps,
                    "done": sum(s["done"] for s in steps), "total": len(steps)})
    return out


def _owned(db, owner: int, routine_id: int):
    if not db.execute("SELECT 1 FROM routines WHERE id = ? AND owner_id = ?", (routine_id, owner)).fetchone():
        raise HTTPException(status_code=404, detail="Routine not found")


def _save_steps(db, owner: int, routine_id: int, steps: List[str]):
    db.execute("DELETE FROM routine_steps WHERE routine_id = ?", (routine_id,))
    for i, label in enumerate(steps):
        db.execute("INSERT INTO routine_steps (routine_id, owner_id, label, sort_order) VALUES (?, ?, ?, ?)",
                   (routine_id, owner, label, i))


@router.get("")
def list_routines(request: Request, day: Optional[date] = Query(None)):
    """Your routines with today's ticks; the starter ideas while you have none."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        mine = _routines(db, owner, (day or date.today()).isoformat())
        if mine:
            return {"routines": mine, "starters": []}
        return {"routines": [], "starters": [{"name": n, "when": w, "steps": s} for n, w, s in STARTERS]}
    finally:
        db.close()


@router.post("", status_code=201)
def create_routine(body: RoutineIn, request: Request):
    _check(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        order = db.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM routines WHERE owner_id = ?", (owner,)).fetchone()[0]
        cur = db.execute("INSERT INTO routines (owner_id, name, when_for, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                         (owner, body.name, body.when, order, _now(), _now()))
        _save_steps(db, owner, cur.lastrowid, body.steps)
        db.commit()
        return next(r for r in _routines(db, owner, date.today().isoformat()) if r["id"] == cur.lastrowid)
    finally:
        db.close()


@router.put("/{routine_id}")
def update_routine(routine_id: int, body: RoutineIn, request: Request):
    """Rename, retime, or change the steps (today's ticks on removed or changed steps go with them)."""
    _check(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _owned(db, owner, routine_id)
        db.execute("UPDATE routines SET name = ?, when_for = ?, updated_at = ? WHERE id = ?",
                   (body.name, body.when, _now(), routine_id))
        _save_steps(db, owner, routine_id, body.steps)
        db.commit()
        return next(r for r in _routines(db, owner, date.today().isoformat()) if r["id"] == routine_id)
    finally:
        db.close()


@router.delete("/{routine_id}", status_code=204)
def delete_routine(routine_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM routines WHERE id = ? AND owner_id = ?", (routine_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


class CheckIn(BaseModel):
    step_id: int
    done: bool = True
    day: Optional[date] = None


@router.post("/{routine_id}/check")
def tick(routine_id: int, body: CheckIn, request: Request):
    owner = request.state.user["id"]
    day = (body.day or date.today()).isoformat()
    db = _get_db()
    try:
        _owned(db, owner, routine_id)
        if not db.execute("SELECT 1 FROM routine_steps WHERE id = ? AND routine_id = ?", (body.step_id, routine_id)).fetchone():
            raise HTTPException(status_code=404, detail="Step not found")
        if body.done:
            db.execute("INSERT OR IGNORE INTO routine_checks (step_id, owner_id, day) VALUES (?, ?, ?)", (body.step_id, owner, day))
        else:
            db.execute("DELETE FROM routine_checks WHERE step_id = ? AND day = ?", (body.step_id, day))
        db.commit()
        return next(r for r in _routines(db, owner, day) if r["id"] == routine_id)
    finally:
        db.close()
