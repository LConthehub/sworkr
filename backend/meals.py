"""
Meals at home and a shopping list. (Meals on a tour live with the tour, in tourplan.py.)

- A meal plan by day: breakfast, lunch, dinner, snacks, each with what it is and its groceries.
- A shopping list: add items, tick them off, and fill it from a week's meals in one tap (each grocery once).
- Calories and macros: off unless the person turns them on (Settings > Health). Then a meal can carry calories,
  protein, carbs and fat, and each day shows its totals against targets the person sets. Nothing is suggested.
"""

import json
from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter()
_get_db: Optional[Callable] = None
MEALS = ("breakfast", "lunch", "dinner", "snack")
MACROS = ("calories", "protein", "carbs", "fat")


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _owner(request: Request) -> int:
    return request.state.user["id"]


def _setting(db, owner: int, key: str) -> Optional[str]:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (owner, key)).fetchone()
    return r["value"] if r else None


def _put(db, owner: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, key, value))


def nutrition(db, owner: int) -> dict:
    try:
        targets = json.loads(_setting(db, owner, "nutrition_targets") or "{}")
    except ValueError:
        targets = {}
    return {"enabled": _setting(db, owner, "nutrition_on") == "1", "targets": {k: targets.get(k) for k in MACROS}}


def _items(text: Optional[str]) -> List[str]:
    out, seen = [], set()
    for part in (text or "").split(","):
        item = part.strip()[:80]
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


# ==================== THE PLAN ====================

class MealIn(BaseModel):
    day: date
    meal: str = "dinner"
    what: str
    groceries: Optional[str] = None          # comma separated
    calories: Optional[float] = None
    protein: Optional[float] = None          # grams
    carbs: Optional[float] = None
    fat: Optional[float] = None


def _check(body: MealIn) -> MealIn:
    body.what = (body.what or "").strip()[:120]
    if not body.what:
        raise HTTPException(status_code=400, detail="What's the meal?")
    if body.meal not in MEALS:
        raise HTTPException(status_code=400, detail="Breakfast, lunch, dinner or snack")
    for k in MACROS:
        v = getattr(body, k)
        if v is not None and not 0 <= v < 20000:
            raise HTTPException(status_code=400, detail="Check the numbers")
    body.groceries = ", ".join(_items(body.groceries)) or None
    return body


def _week(db, owner: int, start: date) -> dict:
    end = start + timedelta(days=7)
    rows = [dict(r) for r in db.execute(
        "SELECT id, day, meal, what, groceries, calories, protein, carbs, fat FROM meal_plan "
        "WHERE owner_id = ? AND day >= ? AND day < ? ORDER BY day, "
        "CASE meal WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'dinner' THEN 2 ELSE 3 END, id",
        (owner, start.isoformat(), end.isoformat()))]
    days = []
    for i in range(7):
        d = (start + timedelta(days=i)).isoformat()
        meals = [m for m in rows if m["day"] == d]
        totals = {k: round(sum(m[k] or 0 for m in meals), 1) for k in MACROS}
        days.append({"day": d, "meals": meals, "totals": totals})
    return {"start": start.isoformat(), "days": days, "nutrition": nutrition(db, owner)}


@router.get("/api/meals")
def week(request: Request, start: Optional[date] = Query(None)):
    """A week of meals from `start` (default: this Monday)."""
    today = date.today()
    start = start or today - timedelta(days=today.weekday())
    db = _get_db()
    try:
        return _week(db, _owner(request), start)
    finally:
        db.close()


@router.post("/api/meals", status_code=201)
def add_meal(body: MealIn, request: Request, start: Optional[date] = Query(None)):
    _check(body)
    owner = _owner(request)
    db = _get_db()
    try:
        db.execute("INSERT INTO meal_plan (owner_id, day, meal, what, groceries, calories, protein, carbs, fat, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (owner, body.day.isoformat(), body.meal, body.what, body.groceries, body.calories, body.protein,
                    body.carbs, body.fat, _now()))
        db.commit()
        return _week(db, owner, start or body.day - timedelta(days=body.day.weekday()))
    finally:
        db.close()


@router.delete("/api/meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM meal_plan WHERE id = ? AND owner_id = ?", (meal_id, _owner(request)))
        db.commit()
    finally:
        db.close()


class NutritionIn(BaseModel):
    enabled: bool
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None


@router.put("/api/meals/nutrition")
def save_nutrition(body: NutritionIn, request: Request):
    owner = _owner(request)
    targets = {k: getattr(body, k) for k in MACROS if getattr(body, k) is not None and getattr(body, k) > 0}
    db = _get_db()
    try:
        _put(db, owner, "nutrition_on", "1" if body.enabled else "0")
        _put(db, owner, "nutrition_targets", json.dumps(targets))
        db.commit()
        return nutrition(db, owner)
    finally:
        db.close()


@router.get("/api/meals/nutrition")
def get_nutrition(request: Request):
    db = _get_db()
    try:
        return nutrition(db, _owner(request))
    finally:
        db.close()


# ==================== SHOPPING LIST ====================

class ShopIn(BaseModel):
    label: str


def _shopping(db, owner: int) -> List[dict]:
    return [{**dict(r), "done": bool(r["done"])} for r in db.execute(
        "SELECT id, label, done FROM shopping_items WHERE owner_id = ? ORDER BY done, sort_order, id", (owner,))]


def _add_items(db, owner: int, labels: List[str]) -> int:
    have = {r[0].lower() for r in db.execute("SELECT label FROM shopping_items WHERE owner_id = ? AND done = 0", (owner,))}
    order = db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM shopping_items WHERE owner_id = ?", (owner,)).fetchone()[0]
    added = 0
    for label in labels:
        if label.lower() not in have:
            order += 1
            added += 1
            have.add(label.lower())
            db.execute("INSERT INTO shopping_items (owner_id, label, done, sort_order, created_at) VALUES (?, ?, 0, ?, ?)",
                       (owner, label, order, _now()))
    return added


@router.get("/api/shopping")
def shopping(request: Request):
    db = _get_db()
    try:
        return _shopping(db, _owner(request))
    finally:
        db.close()


@router.post("/api/shopping", status_code=201)
def add_shopping(body: ShopIn, request: Request):
    labels = _items(body.label)
    if not labels:
        raise HTTPException(status_code=400, detail="What do you need?")
    owner = _owner(request)
    db = _get_db()
    try:
        _add_items(db, owner, labels)
        db.commit()
        return _shopping(db, owner)
    finally:
        db.close()


class Done(BaseModel):
    done: bool


@router.post("/api/shopping/{item_id}/done")
def tick_shopping(item_id: int, body: Done, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        if not db.execute("UPDATE shopping_items SET done = ? WHERE id = ? AND owner_id = ?", (int(body.done), item_id, owner)).rowcount:
            raise HTTPException(status_code=404, detail="Not found")
        db.commit()
        return _shopping(db, owner)
    finally:
        db.close()


@router.post("/api/shopping/clear-done")
def clear_done(request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        db.execute("DELETE FROM shopping_items WHERE owner_id = ? AND done = 1", (owner,))
        db.commit()
        return _shopping(db, owner)
    finally:
        db.close()


@router.post("/api/shopping/from-meals")
def from_meals(request: Request, start: date = Query(...)):
    """Every grocery from that week's meals onto the list, once each (skipping what's already on it)."""
    owner = _owner(request)
    db = _get_db()
    try:
        groceries = []
        for r in db.execute("SELECT groceries FROM meal_plan WHERE owner_id = ? AND day >= ? AND day < ?",
                            (owner, start.isoformat(), (start + timedelta(days=7)).isoformat())):
            groceries += _items(r["groceries"])
        added = _add_items(db, owner, _items(", ".join(groceries)))
        db.commit()
        return {"added": added, "items": _shopping(db, owner)}
    finally:
        db.close()
