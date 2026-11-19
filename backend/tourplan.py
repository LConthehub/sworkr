"""
Planning a tour: a pack list and a budget.

Pack lists: reusable templates ("Tour basics", "Outcall bag") and each tour's own checklist. Adding a template to
a tour copies its items in, skipping any already on the list, and each item is ticked off as it's packed.

Budget: an amount planned for each expense category (main categories, as in Money). Next to each, what was
actually spent: expenses put on the tour or dated during it, your part after partners' shares.
"""

import json
from datetime import date, datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import collab

router = APIRouter()
_get_db: Optional[Callable] = None
STARTER = ["ID", "Phone + charger", "Work phone + charger", "Lingerie & outfits", "Heels", "Makeup bag", "Toiletries",
           "Condoms & lube", "Toy cleaner", "Wipes & towels", "Sheets / linen", "Cash float", "Card reader", "Meds & health papers", "VPN on the phone and laptop",
           "Snacks & water"]


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tour(db, owner: int, tour_id: int) -> dict:
    t = db.execute("SELECT * FROM tours WHERE id = ? AND owner_id = ?", (tour_id, owner)).fetchone()
    if not t:
        raise HTTPException(status_code=404, detail="Tour not found")
    return dict(t)


def _clean_items(items: List[str]) -> List[str]:
    out, seen = [], set()
    for item in items or []:
        label = (item or "").strip()[:80]
        if label and label.lower() not in seen:
            seen.add(label.lower())
            out.append(label)
    return out[:200]


# ==================== TEMPLATES ====================

class TemplateIn(BaseModel):
    name: str
    items: List[str] = []


def _templates(db, owner: int) -> List[dict]:
    return [{"id": r["id"], "name": r["name"], "items": json.loads(r["items"] or "[]")}
            for r in db.execute("SELECT * FROM pack_templates WHERE owner_id = ? ORDER BY name COLLATE NOCASE", (owner,))]


@router.get("/api/pack-templates")
def list_templates(request: Request):
    """Your templates. With none yet, a starter one is offered (not saved until you save it)."""
    db = _get_db()
    try:
        found = _templates(db, request.state.user["id"])
        return found or [{"id": None, "name": "Tour basics", "items": STARTER, "starter": True}]
    finally:
        db.close()


def _check_template(body: TemplateIn) -> TemplateIn:
    body.name = (body.name or "").strip()[:60]
    if not body.name:
        raise HTTPException(status_code=400, detail="Give the list a name")
    body.items = _clean_items(body.items)
    return body


@router.post("/api/pack-templates", status_code=201)
def create_template(body: TemplateIn, request: Request):
    _check_template(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        cur = db.execute("INSERT INTO pack_templates (owner_id, name, items, created_at) VALUES (?, ?, ?, ?)",
                         (owner, body.name, json.dumps(body.items), _now()))
        db.commit()
        return next(t for t in _templates(db, owner) if t["id"] == cur.lastrowid)
    finally:
        db.close()


@router.put("/api/pack-templates/{template_id}")
def update_template(template_id: int, body: TemplateIn, request: Request):
    _check_template(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        if not db.execute("UPDATE pack_templates SET name = ?, items = ? WHERE id = ? AND owner_id = ?",
                          (body.name, json.dumps(body.items), template_id, owner)).rowcount:
            raise HTTPException(status_code=404, detail="Not found")
        db.commit()
        return next(t for t in _templates(db, owner) if t["id"] == template_id)
    finally:
        db.close()


@router.delete("/api/pack-templates/{template_id}", status_code=204)
def delete_template(template_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM pack_templates WHERE id = ? AND owner_id = ?", (template_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


# ==================== A TOUR'S PACK LIST ====================

class PackAdd(BaseModel):
    label: Optional[str] = None          # one item
    template_id: Optional[int] = None    # or every item of a template
    items: Optional[List[str]] = None    # or these items (e.g. the starter list)


class PackItemIn(BaseModel):
    label: Optional[str] = None
    packed: Optional[bool] = None


def _pack(db, owner: int, tour_id: int) -> List[dict]:
    return [{**dict(r), "packed": bool(r["packed"])} for r in db.execute(
        "SELECT id, label, packed, sort_order FROM tour_pack WHERE owner_id = ? AND tour_id = ? ORDER BY sort_order, id",
        (owner, tour_id))]


@router.get("/api/tours/{tour_id}/pack")
def get_pack(tour_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _tour(db, owner, tour_id)
        return _pack(db, owner, tour_id)
    finally:
        db.close()


@router.post("/api/tours/{tour_id}/pack", status_code=201)
def add_to_pack(tour_id: int, body: PackAdd, request: Request):
    """Add one item, a template's items, or a list of items. Items already on the list aren't added twice."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _tour(db, owner, tour_id)
        if body.template_id is not None:
            t = db.execute("SELECT items FROM pack_templates WHERE id = ? AND owner_id = ?", (body.template_id, owner)).fetchone()
            if not t:
                raise HTTPException(status_code=404, detail="Template not found")
            labels = json.loads(t["items"] or "[]")
        elif body.items is not None:
            labels = body.items
        else:
            labels = [body.label or ""]
        labels = _clean_items(labels)
        if not labels:
            raise HTTPException(status_code=400, detail="Nothing to add")
        have = {i["label"].lower() for i in _pack(db, owner, tour_id)}
        order = db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM tour_pack WHERE tour_id = ?", (tour_id,)).fetchone()[0]
        for label in labels:
            if label.lower() in have:
                continue
            order += 1
            db.execute("INSERT INTO tour_pack (owner_id, tour_id, label, packed, sort_order) VALUES (?, ?, ?, 0, ?)",
                       (owner, tour_id, label, order))
        db.commit()
        return _pack(db, owner, tour_id)
    finally:
        db.close()


@router.put("/api/tour-pack/{item_id}")
def update_pack_item(item_id: int, body: PackItemIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        row = db.execute("SELECT * FROM tour_pack WHERE id = ? AND owner_id = ?", (item_id, owner)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        label = (body.label or "").strip()[:80] or row["label"] if body.label is not None else row["label"]
        packed = int(body.packed) if body.packed is not None else row["packed"]
        db.execute("UPDATE tour_pack SET label = ?, packed = ? WHERE id = ?", (label, packed, item_id))
        db.commit()
        return _pack(db, owner, row["tour_id"])
    finally:
        db.close()


@router.delete("/api/tour-pack/{item_id}", status_code=204)
def delete_pack_item(item_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM tour_pack WHERE id = ? AND owner_id = ?", (item_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


# ==================== A TOUR'S BUDGET ====================

class BudgetLine(BaseModel):
    category: str                        # a main expense category key
    planned: float


class BudgetIn(BaseModel):
    lines: List[BudgetLine]


def budget(db, owner: int, tour: dict) -> dict:
    """Planned and actual per main category, plus totals. Actual: your part of the tour's expenses."""
    cats = {r["key"]: dict(r) for r in db.execute(
        "SELECT key, label, parent_key, color, sort_order FROM expense_categories WHERE owner_id = ?", (owner,))}
    planned = {r["category"]: r["planned"] for r in db.execute(
        "SELECT category, planned FROM tour_budget WHERE owner_id = ? AND tour_id = ?", (owner, tour["id"]))}
    actual = {}
    for r in db.execute("""
        SELECT e.category, SUM(e.amount - """ + collab.partner_share_sql("expense", "e.amount", "e.id") + """) AS mine
        FROM expenses e
        WHERE e.owner_id = ? AND (e.tour_id = ? OR (e.tour_id IS NULL AND e.date >= ? AND e.date < ?))
        GROUP BY e.category
    """, (owner, tour["id"], tour["starts_at"], tour["ends_at"])):
        cat = cats.get(r["category"])
        top = (cat["parent_key"] or cat["key"]) if cat else "other"
        actual[top] = actual.get(top, 0) + (r["mine"] or 0)
    keys = sorted(set(planned) | set(actual), key=lambda k: (cats.get(k, {}).get("sort_order", 999), k))
    lines = [{"category": k, "label": cats.get(k, {}).get("label", k), "color": cats.get(k, {}).get("color"),
              "planned": round(planned[k], 2) if k in planned else None, "actual": round(actual.get(k, 0), 2)}
             for k in keys]
    # Meals planned for the tour count as the food plan, unless a food amount was set by hand.
    meals_cost = db.execute("SELECT COALESCE(SUM(cost), 0) FROM tour_meals WHERE owner_id = ? AND tour_id = ?",
                            (owner, tour["id"])).fetchone()[0]
    if meals_cost and "food" not in planned:
        planned["food"] = meals_cost
        if "food" not in keys:
            keys = sorted(set(keys) | {"food"}, key=lambda k: (cats.get(k, {}).get("sort_order", 999), k))
        lines = [{"category": k, "label": cats.get(k, {}).get("label", k), "color": cats.get(k, {}).get("color"),
                  "planned": round(planned[k], 2) if k in planned else None, "actual": round(actual.get(k, 0), 2),
                  "from_meals": k == "food"} for k in keys]
    total_planned = round(sum(v for v in planned.values()), 2)
    total_actual = round(sum(actual.values()), 2)
    return {"lines": lines, "planned": total_planned, "actual": total_actual,
            "left": round(total_planned - total_actual, 2) if planned else None}


@router.get("/api/tours/{tour_id}/budget")
def get_budget(tour_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return budget(db, owner, _tour(db, owner, tour_id))
    finally:
        db.close()


@router.put("/api/tours/{tour_id}/budget")
def save_budget(tour_id: int, body: BudgetIn, request: Request):
    """Replace the tour's planned amounts. A category left out, or planned at 0, has no plan."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        tour = _tour(db, owner, tour_id)
        known = {r[0] for r in db.execute("SELECT key FROM expense_categories WHERE owner_id = ? AND parent_key IS NULL", (owner,))}
        db.execute("DELETE FROM tour_budget WHERE owner_id = ? AND tour_id = ?", (owner, tour_id))
        for line in body.lines:
            if line.category not in known:
                raise HTTPException(status_code=400, detail=f"There's no main expense category '{line.category}'")
            if not 0 <= line.planned < 1e8:
                raise HTTPException(status_code=400, detail="Planned amounts must be 0 or more")
            if line.planned > 0:
                db.execute("INSERT INTO tour_budget (owner_id, tour_id, category, planned) VALUES (?, ?, ?, ?) "
                           "ON CONFLICT(tour_id, category) DO UPDATE SET planned = excluded.planned",
                           (owner, tour_id, line.category, round(line.planned, 2)))
        db.commit()
        return budget(db, owner, tour)
    finally:
        db.close()


# ==================== MEALS AND SNACKS ====================

MEALS = ("breakfast", "lunch", "dinner", "snack")


class MealIn(BaseModel):
    day: Optional[str] = None            # "YYYY-MM-DD", or empty for "any day"
    meal: str = "snack"
    what: str
    groceries: Optional[str] = None      # comma separated
    cost: Optional[float] = None


def _meals(db, owner: int, tour_id: int) -> List[dict]:
    return [dict(r) for r in db.execute(
        "SELECT id, day, meal, what, groceries, cost FROM tour_meals WHERE owner_id = ? AND tour_id = ? "
        "ORDER BY day IS NULL, day, CASE meal WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 WHEN 'dinner' THEN 2 ELSE 3 END, id",
        (owner, tour_id))]


def _check_meal(body: MealIn) -> MealIn:
    body.what = (body.what or "").strip()[:120]
    if not body.what:
        raise HTTPException(status_code=400, detail="What's the meal or snack?")
    if body.meal not in MEALS:
        raise HTTPException(status_code=400, detail="Breakfast, lunch, dinner or snack")
    if body.day:
        try:
            datetime.strptime(body.day, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="The day looks like 2026-06-01")
    else:
        body.day = None
    if body.cost is not None and not 0 <= body.cost < 1e6:
        raise HTTPException(status_code=400, detail="The cost must be 0 or more")
    body.groceries = ", ".join(_clean_items((body.groceries or "").split(","))) or None
    return body


@router.get("/api/tours/{tour_id}/meals")
def get_meals(tour_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _tour(db, owner, tour_id)
        return _meals(db, owner, tour_id)
    finally:
        db.close()


@router.post("/api/tours/{tour_id}/meals", status_code=201)
def add_meal(tour_id: int, body: MealIn, request: Request):
    _check_meal(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _tour(db, owner, tour_id)
        db.execute("INSERT INTO tour_meals (owner_id, tour_id, day, meal, what, groceries, cost) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (owner, tour_id, body.day, body.meal, body.what, body.groceries, body.cost))
        db.commit()
        return _meals(db, owner, tour_id)
    finally:
        db.close()


@router.delete("/api/tour-meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM tour_meals WHERE id = ? AND owner_id = ?", (meal_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


@router.post("/api/tours/{tour_id}/meals/to-pack")
def groceries_to_pack(tour_id: int, request: Request):
    """Every grocery from the tour's meals onto its pack list (once each)."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _tour(db, owner, tour_id)
        wanted = _clean_items([g for m in _meals(db, owner, tour_id) for g in (m["groceries"] or "").split(",")])
        have = {i["label"].lower() for i in _pack(db, owner, tour_id)}
        order = db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM tour_pack WHERE tour_id = ?", (tour_id,)).fetchone()[0]
        added = 0
        for label in wanted:
            if label.lower() not in have:
                order += 1
                added += 1
                db.execute("INSERT INTO tour_pack (owner_id, tour_id, label, packed, sort_order) VALUES (?, ?, ?, 0, ?)",
                           (owner, tour_id, label, order))
        db.commit()
        return {"added": added, "pack": _pack(db, owner, tour_id)}
    finally:
        db.close()


# ==================== CONVENTIONS: BOOTH AND PROMO ====================
# A convention is a tour whose purpose is "convention": its list has the booth fee, prints and cards, banners,
# merch to sell, outfits. Marking one bought logs it as an expense on the trip, so the trip's budget is whole.

CONVENTION_KINDS = {"booth": ("Booth & table", "marketing"), "promo": ("Promo materials", "marketing"),
                    "merch": ("Merch to sell", "marketing"), "outfit": ("Outfits & costumes", "wardrobe"),
                    "other": ("Other", "other")}
CONVENTION_STARTER = [("booth", "Booth or table fee"), ("promo", "Business cards"), ("promo", "Prints to sign"),
                      ("promo", "Banner"), ("merch", "Merch stock"), ("outfit", "Outfits"), ("other", "Card reader")]


class ConventionItemIn(BaseModel):
    kind: str = "promo"
    label: str
    qty: float = 1
    unit_cost: Optional[float] = None


def _convention(db, owner: int, tour_id: int) -> dict:
    t = _tour(db, owner, tour_id)
    if dict(t).get("purpose") != "convention":
        raise HTTPException(status_code=400, detail="This trip isn't a convention: change its purpose first")
    return t


def _items(db, owner: int, tour_id: int) -> dict:
    rows = [{**dict(r), "bought": r["expense_id"] is not None,
             "total": round(r["qty"] * r["unit_cost"], 2) if r["unit_cost"] is not None else None}
            for r in db.execute("SELECT id, kind, label, qty, unit_cost, expense_id FROM convention_items "
                                "WHERE owner_id = ? AND tour_id = ? ORDER BY sort_order, id", (owner, tour_id))]
    return {"items": rows, "kinds": {k: v[0] for k, v in CONVENTION_KINDS.items()},
            "planned": round(sum(r["total"] or 0 for r in rows), 2),
            "bought": round(sum(r["total"] or 0 for r in rows if r["bought"]), 2),
            "starter": [] if rows else [{"kind": k, "label": label} for k, label in CONVENTION_STARTER]}


def _check_item(body: ConventionItemIn) -> ConventionItemIn:
    body.label = (body.label or "").strip()[:120]
    if not body.label:
        raise HTTPException(status_code=400, detail="What is it?")
    if body.kind not in CONVENTION_KINDS:
        raise HTTPException(status_code=400, detail="Booth, promo, merch, outfit or other")
    if not 0 <= body.qty < 100000 or (body.unit_cost is not None and not 0 <= body.unit_cost < 1e7):
        raise HTTPException(status_code=400, detail="Check the amounts")
    return body


@router.get("/api/tours/{tour_id}/convention")
def get_convention(tour_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _convention(db, owner, tour_id)
        return _items(db, owner, tour_id)
    finally:
        db.close()


@router.post("/api/tours/{tour_id}/convention", status_code=201)
def add_convention_item(tour_id: int, body: ConventionItemIn, request: Request):
    _check_item(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _convention(db, owner, tour_id)
        order = db.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM convention_items WHERE tour_id = ?", (tour_id,)).fetchone()[0]
        db.execute("INSERT INTO convention_items (owner_id, tour_id, kind, label, qty, unit_cost, sort_order, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (owner, tour_id, body.kind, body.label, body.qty, body.unit_cost, order,
                                                       datetime.now(timezone.utc).isoformat(timespec="seconds")))
        db.commit()
        return _items(db, owner, tour_id)
    finally:
        db.close()


@router.delete("/api/convention-items/{item_id}", status_code=204)
def delete_convention_item(item_id: int, request: Request):
    """Remove it from the list. An expense it logged stays (the money was spent)."""
    db = _get_db()
    try:
        db.execute("DELETE FROM convention_items WHERE id = ? AND owner_id = ?", (item_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


@router.post("/api/convention-items/{item_id}/bought")
def buy_convention_item(item_id: int, request: Request):
    """Bought it: log the cost as an expense on the trip, in a fitting category."""
    import finance
    owner = request.state.user["id"]
    db = _get_db()
    try:
        r = db.execute("SELECT * FROM convention_items WHERE id = ? AND owner_id = ?", (item_id, owner)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Not found")
        if r["expense_id"] is not None:
            raise HTTPException(status_code=400, detail="Already marked bought")
        if r["unit_cost"] is None:
            raise HTTPException(status_code=400, detail="Add what it cost first")
        t = _tour(db, owner, r["tour_id"])
        lookup = finance.category_lookup(db, owner)
        category = {"merch": lookup.get("prints & merch"), "promo": lookup.get("prints & merch"),
                    "outfit": lookup.get("costumes & props")}.get(r["kind"]) or CONVENTION_KINDS[r["kind"]][1]
        day = date.today().isoformat()        # the day it was bought; it belongs to the trip either way (tour_id)
        cur = db.execute("INSERT INTO expenses (description, amount, category, date, owner_id, created_at, currency, tour_id) "
                         "VALUES (?, ?, ?, ?, ?, ?, 'USD', ?)",
                         (f"{r['label']} – {t['name']}", round(r["qty"] * r["unit_cost"], 2), category, f"{day}T12:00:00+00:00",
                          owner, datetime.now(timezone.utc).isoformat(timespec="seconds"), r["tour_id"]))
        db.execute("UPDATE convention_items SET expense_id = ? WHERE id = ?", (cur.lastrowid, item_id))
        db.commit()
        return _items(db, owner, r["tour_id"])
    finally:
        db.close()
