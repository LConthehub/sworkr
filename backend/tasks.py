"""
Tasks: a simple to-do list. A task can have a due day (and optionally a time), notes, and a link to a contact
or a tour. Tasks show on the calendar on their due day, and sync to the person's calendar app as to-dos.
"""

from datetime import date, datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import calendar_sync

router = APIRouter(prefix="/api/tasks")
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip()
    return text or None


class TaskIn(BaseModel):
    title: str
    notes: Optional[str] = None
    due_date: Optional[date] = None      # the day it's due, in the person's own time zone
    due_at: Optional[datetime] = None    # the exact time, when it has one (the same day as due_date)
    done: bool = False
    client_id: Optional[int] = None
    tour_id: Optional[int] = None


TASK_SELECT = """
    SELECT t.*, c.display_name AS client_name, r.name AS tour_name
    FROM tasks t LEFT JOIN clients c ON t.client_id = c.id LEFT JOIN tours r ON t.tour_id = r.id
"""


def _row(r) -> dict:
    return {**dict(r), "done": r["done_at"] is not None}


def get_task(db, task_id: int, owner_id: int) -> Optional[dict]:
    r = db.execute(TASK_SELECT + " WHERE t.id = ? AND t.owner_id = ?", (task_id, owner_id)).fetchone()
    return _row(r) if r else None


def _validate(db, body: TaskIn, owner_id: int):
    title = _clean(body.title)
    if not title or len(title) > 300:
        raise HTTPException(status_code=400, detail="Give the task a title (up to 300 characters)")
    if body.due_at is not None and body.due_date is None:
        raise HTTPException(status_code=400, detail="A task with a time needs a day too")
    if body.client_id is not None and not db.execute(
            "SELECT 1 FROM clients WHERE id = ? AND owner_id = ?", (body.client_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That contact doesn't exist")
    if body.tour_id is not None and not db.execute(
            "SELECT 1 FROM tours WHERE id = ? AND owner_id = ? AND kind = 'tour'", (body.tour_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That tour doesn't exist")


def _due_at(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


@router.get("")
def list_tasks(
    request: Request,
    status: str = Query("open", description="open, done or all"),
    start: Optional[date] = Query(None, description="Only tasks due on or after this day"),
    end: Optional[date] = Query(None, description="Only tasks due before this day"),
    limit: int = Query(500, ge=1, le=2000),
):
    if status not in ("open", "done", "all"):
        raise HTTPException(status_code=400, detail="status must be open, done or all")
    conditions, params = ["t.owner_id = ?"], [request.state.user["id"]]
    if status == "open":
        conditions.append("t.done_at IS NULL")
    elif status == "done":
        conditions.append("t.done_at IS NOT NULL")
    if start:
        conditions.append("t.due_date >= ?")
        params.append(start.isoformat())
    if end:
        conditions.append("t.due_date < ?")
        params.append(end.isoformat())
    db = _get_db()
    try:
        # Tasks with a day first (soonest first), then those without one, newest first.
        return [_row(r) for r in db.execute(
            TASK_SELECT + f" WHERE {' AND '.join(conditions)} "
            "ORDER BY t.due_date IS NULL, t.due_date, t.due_at IS NULL, t.due_at, t.id DESC LIMIT ?",
            (*params, limit))]
    finally:
        db.close()


@router.post("", status_code=201)
def create_task(body: TaskIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _validate(db, body, owner)
        now = _now()
        cur = db.execute("""
            INSERT INTO tasks (title, notes, due_date, due_at, done_at, client_id, tour_id, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (body.title.strip(), _clean(body.notes), body.due_date.isoformat() if body.due_date else None,
              _due_at(body.due_at), now if body.done else None, body.client_id, body.tour_id, owner, now, now))
        db.commit()
        calendar_sync.queue_item("task", cur.lastrowid, owner)
        return get_task(db, cur.lastrowid, owner)
    finally:
        db.close()


@router.put("/{task_id}")
def update_task(task_id: int, body: TaskIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        existing = get_task(db, task_id, owner)
        if not existing:
            raise HTTPException(status_code=404, detail="Task not found")
        _validate(db, body, owner)
        done_at = (existing["done_at"] or _now()) if body.done else None
        db.execute("""
            UPDATE tasks SET title = ?, notes = ?, due_date = ?, due_at = ?, done_at = ?, client_id = ?, tour_id = ?,
                   updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (body.title.strip(), _clean(body.notes), body.due_date.isoformat() if body.due_date else None,
              _due_at(body.due_at), done_at, body.client_id, body.tour_id, _now(), task_id, owner))
        db.commit()
        calendar_sync.queue_item("task", task_id, owner)
        return get_task(db, task_id, owner)
    finally:
        db.close()


class Done(BaseModel):
    done: bool = True


@router.post("/{task_id}/done")
def set_done(task_id: int, body: Done, request: Request):
    """Tick a task off (or un-tick it)."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        existing = get_task(db, task_id, owner)
        if not existing:
            raise HTTPException(status_code=404, detail="Task not found")
        done_at = (existing["done_at"] or _now()) if body.done else None
        db.execute("UPDATE tasks SET done_at = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                   (done_at, _now(), task_id, owner))
        db.commit()
        calendar_sync.queue_item("task", task_id, owner)
        return get_task(db, task_id, owner)
    finally:
        db.close()


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        if not get_task(db, task_id, owner):
            return
        db.execute("DELETE FROM tasks WHERE id = ? AND owner_id = ?", (task_id, owner))
        db.commit()
        calendar_sync.queue_item("task", task_id, owner)
    finally:
        db.close()


def tasks_for_sync(db, owner_id: int) -> List[dict]:
    return [_row(r) for r in db.execute(TASK_SELECT + " WHERE t.owner_id = ?", (owner_id,))]
