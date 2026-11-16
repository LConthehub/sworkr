"""
Money beyond bookings: each user's own expense categories, the places they earn (venues, platforms,
agencies) with their fees, income that isn't a booking (payouts, tips, sales, shifts), savings goals, and
the "how I work" starter setups (presets.json).

Every amount has a currency (see currencies.py). Only USD is switched on for now.
"""

import json
import os
import secrets
import sqlite3
import datetime as dt
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import collab
import currencies
import personas

router = APIRouter()
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _db():
    return _get_db()


def _owner(request: Request) -> int:
    return request.state.user["id"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _clean(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip()
    return text or None


def _amount_ok(value: Optional[float]) -> bool:
    return value is None or 0 <= value < float("inf")


# ==================== EXPENSE CATEGORIES ====================

# Two levels. The main categories are the same for everyone (so totals line up from person to person and
# year to year), though anyone can rename, recolour or hide them, and add main categories of their own.
# Subcategories sit under a main one; a few are built in because sworkr fills them itself (room & board
# from tours, health tests from appointments). Kinds of work (presets.json) add more.
# (key, label, colour, parent key)
BUILTIN_CATEGORIES = [
    ("workspace", "Workspace", "#c2410c", None),
    ("fees", "Fees & licenses", "#b45309", None),
    ("health", "Health & safety", "#0f9488", None),
    ("wardrobe", "Look & wardrobe", "#fc4c9c", None),
    ("gear", "Gear & tech", "#7c3aed", None),
    ("marketing", "Marketing", "#e67eb6", None),
    ("travel", "Travel", "#a73178", None),
    ("fitness", "Fitness & training", "#65a30d", None),
    ("other", "Other", "#4b86a6", None),
    ("room_rent", "Room & board", None, "workspace"),
    ("cleaning", "Cleaning & laundry", None, "workspace"),
    ("medical", "Tests & doctor", None, "health"),
    ("equipment", "Equipment & toys", None, "gear"),
]
BUILTIN_KEYS = {c[0] for c in BUILTIN_CATEGORIES}
BUILTIN_TOPS = {c[0] for c in BUILTIN_CATEGORIES if c[3] is None}
NEVER_HIDDEN = {"other"}   # where expenses go when their category is deleted
EXTRA_COLORS = ["#7c3aed", "#0891b2", "#65a30d", "#d97706", "#db2777", "#4f46e5", "#059669", "#b45309", "#9333ea", "#0284c7"]


def ensure_categories(db, owner_id: int):
    """Every user has the built-in categories. Added the first time they're needed."""
    have = {r[0] for r in db.execute("SELECT key FROM expense_categories WHERE owner_id = ?", (owner_id,))}
    missing = [c for c in BUILTIN_CATEGORIES if c[0] not in have]
    for order, (key, label, color, parent) in enumerate(BUILTIN_CATEGORIES):
        if key not in have:
            db.execute("INSERT OR IGNORE INTO expense_categories (owner_id, key, label, color, parent_key, sort_order, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (owner_id, key, label, color, parent, order if parent is None else 100 + order, _now()))
    if missing:
        db.commit()


def check_category(db, owner_id: int, key: str) -> str:
    """The category key if this user has it; otherwise a 422 naming the problem."""
    ensure_categories(db, owner_id)
    key = (key or "other").strip()
    if not db.execute("SELECT 1 FROM expense_categories WHERE owner_id = ? AND key = ?", (owner_id, key)).fetchone():
        raise HTTPException(status_code=422, detail=f"There's no expense category '{key}'")
    return key


def category_lookup(db, owner_id: int) -> dict:
    """{key, lower-case name, or "main > sub": key}, for matching what people type (e.g. in a CSV) to a category."""
    ensure_categories(db, owner_id)
    rows = list(db.execute("SELECT key, label, parent_key FROM expense_categories WHERE owner_id = ?", (owner_id,)))
    labels = {r["key"]: r["label"].strip() for r in rows}
    out = {}
    for r in rows:
        out[r["key"].lower()] = r["key"]
        out[labels[r["key"]].lower()] = r["key"]
        if r["parent_key"] in labels:
            out[f"{labels[r['parent_key']]} > {labels[r['key']]}".lower()] = r["key"]
    return out


def _add_category(db, owner_id: int, label: str, color: Optional[str] = None, parent_key: Optional[str] = None) -> str:
    """A new category at the end of the list. A main one gets a colour; a subcategory shows its main one's unless given one."""
    count = db.execute("SELECT COUNT(*) FROM expense_categories WHERE owner_id = ?", (owner_id,)).fetchone()[0]
    last = db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM expense_categories WHERE owner_id = ?", (owner_id,)).fetchone()[0]
    if parent_key is None and not color:
        color = EXTRA_COLORS[count % len(EXTRA_COLORS)]
    key = "c" + secrets.token_hex(4)
    db.execute("INSERT INTO expense_categories (owner_id, key, label, color, parent_key, sort_order, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?)", (owner_id, key, label, color, parent_key, last + 1, _now()))
    return key


def _label_taken(db, owner_id: int, label: str, except_key: Optional[str] = None) -> bool:
    return bool(db.execute(
        "SELECT 1 FROM expense_categories WHERE owner_id = ? AND LOWER(label) = LOWER(?) AND key IS NOT ?",
        (owner_id, label, except_key)).fetchone())


class CategoryIn(BaseModel):
    label: str
    color: Optional[str] = None
    hidden: bool = False
    parent_key: Optional[str] = None   # None: a main category. Left out of an update: it stays where it is.


def _check_color(color: Optional[str]) -> Optional[str]:
    color = _clean(color)
    if color and not (len(color) == 7 and color[0] == "#" and all(ch in "0123456789abcdefABCDEF" for ch in color[1:])):
        raise HTTPException(status_code=400, detail="Colour must look like #a1b2c3")
    return color


def _check_label(label: Optional[str]) -> str:
    label = _clean(label)
    if not label or len(label) > 60:
        raise HTTPException(status_code=400, detail="Give the category a name (up to 60 characters)")
    return label


def _check_parent(db, owner_id: int, parent_key: Optional[str], key: Optional[str] = None):
    """A subcategory goes under a main category, only one level deep."""
    if parent_key is None:
        return
    parent = db.execute("SELECT parent_key FROM expense_categories WHERE owner_id = ? AND key = ?", (owner_id, parent_key)).fetchone()
    if not parent:
        raise HTTPException(status_code=400, detail="That main category doesn't exist")
    if parent["parent_key"] is not None or parent_key == key:
        raise HTTPException(status_code=400, detail="Subcategories can only go under a main category")
    if key is not None:
        if key in BUILTIN_TOPS:
            raise HTTPException(status_code=400, detail="The built-in main categories stay main categories")
        if db.execute("SELECT 1 FROM expense_categories WHERE owner_id = ? AND parent_key = ?", (owner_id, key)).fetchone():
            raise HTTPException(status_code=400, detail="Move this category's subcategories somewhere else first")


def _category_rows(db, owner_id: int) -> List[dict]:
    """Main categories in order, each followed by its subcategories. A subcategory without a colour of its
    own shows its main category's."""
    ensure_categories(db, owner_id)
    rows = [{**dict(r), "hidden": bool(r["hidden"]), "builtin": r["key"] in BUILTIN_KEYS} for r in db.execute("""
        SELECT c.key, c.label, c.color, c.parent_key, c.sort_order, c.hidden,
               (SELECT COUNT(*) FROM expenses e WHERE e.owner_id = c.owner_id AND e.category = c.key) AS used
        FROM expense_categories c WHERE c.owner_id = ? ORDER BY c.sort_order, c.id
    """, (owner_id,))]
    tops = [r for r in rows if r["parent_key"] is None]
    top_keys = {r["key"] for r in tops}
    out = []
    for top in tops:
        out.append(top)
        out += [{**sub, "color": sub["color"] or top["color"]} for sub in rows if sub["parent_key"] == top["key"]]
    return out + [r for r in rows if r["parent_key"] is not None and r["parent_key"] not in top_keys]


@router.get("/api/expense-categories")
def list_categories(request: Request):
    db = _db()
    try:
        return _category_rows(db, _owner(request))
    finally:
        db.close()


@router.post("/api/expense-categories", status_code=201)
def create_category(body: CategoryIn, request: Request):
    label = _check_label(body.label)
    color = _check_color(body.color)
    owner = _owner(request)
    db = _db()
    try:
        ensure_categories(db, owner)
        _check_parent(db, owner, body.parent_key)
        if _label_taken(db, owner, label):
            raise HTTPException(status_code=409, detail=f"You already have a category called '{label}'")
        key = _add_category(db, owner, label, color, body.parent_key)
        db.commit()
        return next(c for c in _category_rows(db, owner) if c["key"] == key)
    finally:
        db.close()


@router.put("/api/expense-categories/{key}")
def update_category(key: str, body: CategoryIn, request: Request):
    """Rename, recolour, hide or show a category, or move a subcategory (parent_key) to another main one,
    or make it a main category (parent_key: null)."""
    label = _check_label(body.label)
    color = _check_color(body.color)
    owner = _owner(request)
    db = _db()
    try:
        ensure_categories(db, owner)
        row = db.execute("SELECT parent_key, color FROM expense_categories WHERE owner_id = ? AND key = ?", (owner, key)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Category not found")
        if body.hidden and key in NEVER_HIDDEN:
            raise HTTPException(status_code=400, detail="'Other' can't be hidden: it's where uncategorised expenses go")
        if _label_taken(db, owner, label, except_key=key):
            raise HTTPException(status_code=409, detail=f"You already have a category called '{label}'")
        parent = row["parent_key"]
        if "parent_key" in body.model_fields_set and body.parent_key != parent:
            _check_parent(db, owner, body.parent_key, key)
            parent = body.parent_key
            if parent is None and not (color or row["color"]):   # a new main category needs a colour of its own
                color = EXTRA_COLORS[secrets.randbelow(len(EXTRA_COLORS))]
        if parent is not None and color and not row["color"]:
            # A subcategory is listed in its main category's colour; saving that colour back shouldn't pin it.
            top = db.execute("SELECT color FROM expense_categories WHERE owner_id = ? AND key = ?", (owner, parent)).fetchone()
            if top and (top["color"] or "").lower() == color.lower():
                color = None
        db.execute("UPDATE expense_categories SET label = ?, color = COALESCE(?, color), hidden = ?, parent_key = ? "
                   "WHERE owner_id = ? AND key = ?", (label, color, int(body.hidden), parent, owner, key))
        db.commit()
        return next(c for c in _category_rows(db, owner) if c["key"] == key)
    finally:
        db.close()


@router.delete("/api/expense-categories/{key}", status_code=204)
def delete_category(key: str, request: Request):
    """Delete one of your own categories. Its expenses move to 'Other', and so do its subcategories.
    Built-in ones can be renamed or hidden instead."""
    owner = _owner(request)
    if key in BUILTIN_KEYS:
        raise HTTPException(status_code=400, detail="Built-in categories can be renamed or hidden, but not deleted")
    db = _db()
    try:
        db.execute("UPDATE expenses SET category = 'other' WHERE owner_id = ? AND category = ?", (owner, key))
        db.execute("UPDATE expense_categories SET parent_key = 'other' WHERE owner_id = ? AND parent_key = ?", (owner, key))
        db.execute("DELETE FROM expense_categories WHERE owner_id = ? AND key = ?", (owner, key))
        db.commit()
    finally:
        db.close()


# ==================== PLACES YOU EARN ====================

class SourceKind(str, Enum):
    BROTHEL = "brothel"
    CLUB = "club"            # strip club, bar
    AGENCY = "agency"
    PLATFORM = "platform"    # OnlyFans, cam site, clip store
    PHONE = "phone"          # phone, text or chat line
    STUDIO = "studio"        # dungeon, studio or room you hire
    EVENT = "event"          # convention, party, event
    OTHER = "other"


class SourceIn(BaseModel):
    name: str
    kind: SourceKind = SourceKind.OTHER
    fee_percent: Optional[float] = None     # the share the venue or platform keeps
    fee_per_shift: Optional[float] = None   # a house fee or tip-out each time you work
    token_value: Optional[float] = None     # what one token pays you
    payout_note: Optional[str] = None
    notes: Optional[str] = None
    currency: str = currencies.DEFAULT
    archived: bool = False
    work_type: Optional[str] = None         # which kind of work it's for (a key of presets.json), for comparing
    persona_id: Optional[int] = None        # the name you work under there
    gift_share_percent: Optional[float] = None   # the share of a gift's value the place charges you (brothels: often 50)
    tip_share_percent: Optional[float] = None    # the share of your tips the place keeps (a house cut or tip-out)
    transport_cut_percent: Optional[float] = None  # (older: one Kelly cut. Use `cuts` instead)
    cuts: Optional[List["CutIn"]] = None     # the place's deductions; left out: they stay as they are
    holds_cash: bool = False                 # the office keeps what you earn until payout
    cash_limit: Optional[float] = None       # how much cash you may keep on you there


class CutIn(BaseModel):
    """One deduction a workplace makes: a Kelly cut for a cab, a different one for a limo, a runner's fee, a card fee…"""
    label: str
    kind: str = "percent"                    # percent, or a fixed amount
    value: float
    basis: str = "top"                       # top: off the whole amount before the house's share. mine: out of your share
    auto: bool = False                       # taken every time, rather than ticked when it applies


SourceIn.model_rebuild()


def _validate_source(s: SourceIn):
    if not _clean(s.name):
        raise HTTPException(status_code=400, detail="Give it a name")
    if s.fee_percent is not None and not (0 <= s.fee_percent <= 100):
        raise HTTPException(status_code=400, detail="The platform's share must be between 0 and 100%")
    if s.gift_share_percent is not None and not (0 <= s.gift_share_percent <= 100):
        raise HTTPException(status_code=400, detail="The share of gifts must be between 0 and 100%")
    if s.tip_share_percent is not None and not (0 <= s.tip_share_percent <= 100):
        raise HTTPException(status_code=400, detail="The share of tips must be between 0 and 100%")
    if s.transport_cut_percent is not None and not (0 <= s.transport_cut_percent <= 100):
        raise HTTPException(status_code=400, detail="The Kelly cut must be between 0 and 100%")
    if not (_amount_ok(s.fee_per_shift) and _amount_ok(s.token_value)):
        raise HTTPException(status_code=400, detail="Fees and token values must be 0 or more")
    s.currency = currencies.check(s.currency)
    s.work_type = _clean(s.work_type)
    if s.work_type and s.work_type not in PRESETS:
        raise HTTPException(status_code=400, detail="Unknown kind of work")


def _source_values(s: SourceIn) -> tuple:
    return (s.name.strip(), s.kind.value, s.fee_percent, s.fee_per_shift, s.token_value, _clean(s.payout_note),
            _clean(s.notes), s.currency, int(s.archived), s.work_type, s.gift_share_percent, s.tip_share_percent, s.transport_cut_percent)


def _source_row(r) -> dict:
    return {**dict(r), "archived": bool(r["archived"]), "holds_cash": bool(r["holds_cash"]), "cuts": []}


def _with_cuts(db, owner_id: int, sources: List[dict]) -> List[dict]:
    by_id = {s["id"]: s for s in sources}
    for c in db.execute("SELECT id, source_id, label, kind, value, basis, auto FROM source_cuts WHERE owner_id = ? ORDER BY sort_order, id", (owner_id,)):
        if c["source_id"] in by_id:
            by_id[c["source_id"]]["cuts"].append({**dict(c), "auto": bool(c["auto"])})
    return sources


def get_source(db, source_id: int, owner_id: int) -> Optional[dict]:
    r = db.execute("SELECT * FROM income_sources WHERE id = ? AND owner_id = ?", (source_id, owner_id)).fetchone()
    return _with_cuts(db, owner_id, [_source_row(r)])[0] if r else None


def _save_house_rules(db, source_id: int, owner_id: int, body: SourceIn):
    """The office-holds-cash setting, and (when the request has them) the place's cuts, replaced as a whole."""
    if body.cash_limit is not None and not (0 <= body.cash_limit < 1e9):
        raise HTTPException(status_code=400, detail="The cash you can keep must be 0 or more")
    db.execute("UPDATE income_sources SET holds_cash = ?, cash_limit = ? WHERE id = ? AND owner_id = ?",
               (int(body.holds_cash), body.cash_limit, source_id, owner_id))
    if body.cuts is None:
        return
    if len(body.cuts) > 20:
        raise HTTPException(status_code=400, detail="That's a lot of cuts: 20 at most")
    rows = []
    for order, c in enumerate(body.cuts):
        label = _clean(c.label)
        if not label or len(label) > 60:
            raise HTTPException(status_code=400, detail="Give each cut a name (up to 60 characters)")
        if c.kind not in ("percent", "amount") or c.basis not in ("top", "mine"):
            raise HTTPException(status_code=400, detail="A cut is a percentage or an amount, off the top or out of your share")
        if not (0 <= c.value < 1e9) or (c.kind == "percent" and c.value > 100):
            raise HTTPException(status_code=400, detail="A cut is 0 to 100%, or an amount of 0 or more")
        rows.append((owner_id, source_id, label, c.kind, c.value, c.basis, int(c.auto), order, _now()))
    db.execute("DELETE FROM source_cuts WHERE source_id = ? AND owner_id = ?", (source_id, owner_id))
    db.executemany("INSERT INTO source_cuts (owner_id, source_id, label, kind, value, basis, auto, sort_order, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


@router.get("/api/income-sources")
def list_sources(request: Request):
    db = _db()
    try:
        return _with_cuts(db, _owner(request), [_source_row(r) for r in db.execute(
            "SELECT * FROM income_sources WHERE owner_id = ? ORDER BY archived, name COLLATE NOCASE", (_owner(request),))])
    finally:
        db.close()


@router.post("/api/income-sources", status_code=201)
def create_source(body: SourceIn, request: Request):
    _validate_source(body)
    db = _db()
    try:
        now = _now()
        cur = db.execute("""
            INSERT INTO income_sources (name, kind, fee_percent, fee_per_shift, token_value, payout_note, notes,
                                        currency, archived, work_type, gift_share_percent, tip_share_percent,
                                        transport_cut_percent, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_source_values(body), _owner(request), now, now))
        personas.assign(db, "income_sources", cur.lastrowid, _owner(request), body)
        _save_house_rules(db, cur.lastrowid, _owner(request), body)
        db.commit()
        return get_source(db, cur.lastrowid, _owner(request))
    finally:
        db.close()


@router.put("/api/income-sources/{source_id}")
def update_source(source_id: int, body: SourceIn, request: Request):
    _validate_source(body)
    owner = _owner(request)
    db = _db()
    try:
        if not get_source(db, source_id, owner):
            raise HTTPException(status_code=404, detail="Not found")
        db.execute("""
            UPDATE income_sources SET name = ?, kind = ?, fee_percent = ?, fee_per_shift = ?, token_value = ?,
                   payout_note = ?, notes = ?, currency = ?, archived = ?, work_type = ?, gift_share_percent = ?,
                   tip_share_percent = ?, transport_cut_percent = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_source_values(body), _now(), source_id, owner))
        personas.assign(db, "income_sources", source_id, owner, body)
        _save_house_rules(db, source_id, owner, body)
        db.commit()
        return get_source(db, source_id, owner)
    finally:
        db.close()


@router.delete("/api/income-sources/{source_id}", status_code=204)
def delete_source(source_id: int, request: Request):
    """Its income stays, just no longer linked to it. (Archiving keeps the link and hides it from pickers.)"""
    owner = _owner(request)
    db = _db()
    try:
        db.execute("UPDATE income SET source_id = NULL WHERE source_id = ? AND owner_id = ?", (source_id, owner))
        # Its charges go with it (ON DELETE CASCADE), and so do their open renewal reminders.
        db.execute("DELETE FROM tasks WHERE owner_id = ? AND done_at IS NULL AND id IN "
                   "(SELECT task_id FROM place_charges WHERE source_id = ? AND owner_id = ?)", (owner, source_id, owner))
        db.execute("DELETE FROM income_sources WHERE id = ? AND owner_id = ?", (source_id, owner))
        db.commit()
    finally:
        db.close()


# ==================== INCOME ====================

class IncomeKind(str, Enum):
    SHIFT = "shift"
    PAYOUT = "payout"
    TIPS = "tips"
    SALE = "sale"                  # pay-per-view, customs, clips
    SUBSCRIPTION = "subscription"
    BOOKING = "booking"            # paid outside the calendar
    ALLOWANCE = "allowance"        # a sugar arrangement's regular allowance
    GIFT = "gift"                  # a present (gross: what it's worth). A brothel's share of it is the fees.
    OTHER = "other"


class IncomeStatus(str, Enum):
    RECEIVED = "received"
    PENDING = "pending"            # earned, not paid out yet


class IncomeIn(BaseModel):
    source_id: Optional[int] = None
    date: datetime                   # when it was earned
    description: Optional[str] = None
    kind: IncomeKind = IncomeKind.OTHER
    tokens: Optional[float] = None
    gross: float                     # before fees
    fees: float = 0                  # what the venue or platform kept, house fee, tip-out
    status: IncomeStatus = IncomeStatus.RECEIVED
    payout_date: Optional[date] = None
    notes: Optional[str] = None
    currency: str = currencies.DEFAULT
    client_id: Optional[int] = None  # who it came from (an allowance, a gift)
    payment_method: Optional[str] = None   # how it was paid: cash, bank transfer, a payment app…
    transport_cut: Optional[float] = None  # (older: the Kelly cut's amount. Use `cuts` instead)
    cuts: Optional[List[dict]] = None      # the place's cuts taken from this, as [{label, amount}]; they're part of the fees


INCOME_SELECT = """
    SELECT i.*, s.name AS source_name, (SELECT c.display_name FROM clients c WHERE c.id = i.client_id) AS client_name,
           ROUND(i.gross - i.fees, 2) AS net,
           ROUND((i.gross - i.fees) - """ + collab.partner_share_sql("income", "CASE WHEN i.status = 'received' THEN i.gross - i.fees ELSE 0 END", "i.id") + """, 2) AS my_net,
           """ + collab.partner_names_sql("income", "i.id") + """ AS partner_names
    FROM income i LEFT JOIN income_sources s ON i.source_id = s.id
"""


def _validate_income(db, body: IncomeIn, owner_id: int):
    if not (_amount_ok(body.gross) and _amount_ok(body.fees) and _amount_ok(body.tokens) and _amount_ok(body.transport_cut)):
        raise HTTPException(status_code=400, detail="Amounts must be 0 or more")
    body.currency = currencies.check(body.currency)
    if body.client_id is not None and not db.execute("SELECT 1 FROM clients WHERE id = ? AND owner_id = ?",
                                                     (body.client_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That contact doesn't exist")
    if body.source_id is not None and not get_source(db, body.source_id, owner_id):
        raise HTTPException(status_code=400, detail="That workplace or platform doesn't exist")


def _income_values(body: IncomeIn) -> tuple:
    return (body.source_id, _utc_iso(body.date), _clean(body.description), body.kind.value, body.tokens,
            round(body.gross, 2), round(body.fees, 2), body.status.value,
            body.payout_date.isoformat() if body.payout_date else None, _clean(body.notes), body.currency, body.client_id,
            (_clean(body.payment_method) or "")[:40] or None, body.transport_cut or None)


def _income_row(r) -> dict:
    d = dict(r)
    try:
        d["cuts"] = json.loads(d.get("cuts") or "[]")
    except ValueError:
        d["cuts"] = []
    return d


def _cuts_json(body: IncomeIn) -> Optional[str]:
    """The cuts taken from an income, tidied: a name and an amount each."""
    out = []
    for c in (body.cuts or [])[:20]:
        label, amount = _clean(str(c.get("label") or "")), c.get("amount")
        if not label or not isinstance(amount, (int, float)) or not (0 <= amount < 1e9):
            raise HTTPException(status_code=400, detail="Each cut needs a name and an amount of 0 or more")
        out.append({"label": label[:60], "amount": round(amount, 2)})
    return json.dumps(out) if out else None


def get_income(db, income_id: int, owner_id: int) -> Optional[dict]:
    r = db.execute(INCOME_SELECT + " WHERE i.id = ? AND i.owner_id = ?", (income_id, owner_id)).fetchone()
    return _income_row(r) if r else None


def income_between(db, owner_id: int, start_iso: str, end_iso: str, status: Optional[str] = "received") -> List[dict]:
    """Income earned in [start, end). Used by tour figures and the earnings comparison."""
    sql = INCOME_SELECT + " WHERE i.owner_id = ? AND i.date >= ? AND i.date < ?"
    params = [owner_id, start_iso, end_iso]
    if status:
        sql += " AND i.status = ?"
        params.append(status)
    return [dict(r) for r in db.execute(sql + " ORDER BY i.date, i.id", params)]


@router.get("/api/income")
def list_income(
    request: Request,
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    source_id: Optional[int] = None,
    status: Optional[IncomeStatus] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(200, ge=1, le=1000),
):
    conditions, params = ["i.owner_id = ?"], [_owner(request)]
    if start:
        conditions.append("i.date >= ?")
        params.append(_utc_iso(start))
    if end:
        conditions.append("i.date < ?")
        params.append(_utc_iso(end))
    if source_id is not None:
        conditions.append("i.source_id = ?")
        params.append(source_id)
    if status:
        conditions.append("i.status = ?")
        params.append(status.value)
    db = _db()
    try:
        return [_income_row(r) for r in db.execute(
            INCOME_SELECT + f" WHERE {' AND '.join(conditions)} ORDER BY i.date DESC, i.id DESC LIMIT ? OFFSET ?",
            (*params, limit, (page - 1) * limit))]
    finally:
        db.close()


@router.post("/api/income", status_code=201)
def create_income(body: IncomeIn, request: Request):
    owner = _owner(request)
    db = _db()
    try:
        _validate_income(db, body, owner)
        now = _now()
        cur = db.execute("""
            INSERT INTO income (source_id, date, description, kind, tokens, gross, fees, status, payout_date, notes,
                                currency, client_id, payment_method, transport_cut, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_income_values(body), owner, now, now))
        db.execute("UPDATE income SET cuts = ? WHERE id = ?", (_cuts_json(body), cur.lastrowid))
        db.commit()
        return get_income(db, cur.lastrowid, owner)
    finally:
        db.close()


@router.put("/api/income/{income_id}")
def update_income(income_id: int, body: IncomeIn, request: Request):
    owner = _owner(request)
    db = _db()
    try:
        if not get_income(db, income_id, owner):
            raise HTTPException(status_code=404, detail="Not found")
        _validate_income(db, body, owner)
        db.execute("""
            UPDATE income SET source_id = ?, date = ?, description = ?, kind = ?, tokens = ?, gross = ?, fees = ?,
                   status = ?, payout_date = ?, notes = ?, currency = ?, client_id = ?, payment_method = ?,
                   transport_cut = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_income_values(body), _now(), income_id, owner))
        db.execute("UPDATE income SET cuts = ? WHERE id = ?", (_cuts_json(body), income_id))
        db.commit()
        return get_income(db, income_id, owner)
    finally:
        db.close()


@router.post("/api/income/{income_id}/received")
def mark_received(income_id: int, request: Request):
    """A pending payout has arrived."""
    owner = _owner(request)
    db = _db()
    try:
        existing = get_income(db, income_id, owner)
        if not existing:
            raise HTTPException(status_code=404, detail="Not found")
        db.execute("UPDATE income SET status = 'received', payout_date = COALESCE(payout_date, ?), updated_at = ? "
                   "WHERE id = ? AND owner_id = ?", (date.today().isoformat(), _now(), income_id, owner))
        db.commit()
        return get_income(db, income_id, owner)
    finally:
        db.close()


@router.delete("/api/income/{income_id}", status_code=204)
def delete_income(income_id: int, request: Request):
    db = _db()
    try:
        if get_income(db, income_id, _owner(request)):
            collab.forget(db, "income", income_id)
        db.execute("DELETE FROM income WHERE id = ? AND owner_id = ?", (income_id, _owner(request)))
        db.commit()
    finally:
        db.close()


# ==================== SAVINGS GOALS ====================
# A goal is an envelope: its balance is what you've put in, minus what you've taken out. sworkr doesn't move
# real money. A rule says how much should go in (a % of what you earn, an amount each week, or an amount per
# booking); sworkr works out how much that comes to and suggests setting the difference aside.

class GoalKind(str, Enum):
    SAVINGS = "savings"
    TAX = "tax"


class RuleType(str, Enum):
    NONE = "none"
    PERCENT = "percent"          # rule_amount % of everything received
    WEEKLY = "weekly"            # rule_amount every week
    PER_BOOKING = "per_booking"  # rule_amount for each completed booking


class GoalIn(BaseModel):
    name: str
    kind: GoalKind = GoalKind.SAVINGS
    target_amount: Optional[float] = None
    target_date: Optional[date] = None
    rule_type: RuleType = RuleType.NONE
    rule_amount: Optional[float] = None
    starts_on: Optional[date] = None
    priority: int = 0
    color: Optional[str] = None
    notes: Optional[str] = None
    currency: str = currencies.DEFAULT
    archived: bool = False


class EntryIn(BaseModel):
    amount: float                # positive puts money in, negative takes it out
    date: Optional[dt.date] = None   # (dt.date: a field called `date` would hide the type)
    note: Optional[str] = None


def _validate_goal(body: GoalIn):
    if not _clean(body.name):
        raise HTTPException(status_code=400, detail="Give the goal a name")
    if body.target_amount is not None and not (0 < body.target_amount < float("inf")):
        raise HTTPException(status_code=400, detail="The target must be more than 0")
    if body.rule_type == RuleType.NONE:
        body.rule_amount = None
    elif body.rule_amount is None or not (0 < body.rule_amount < float("inf")):
        raise HTTPException(status_code=400, detail="Say how much the rule sets aside")
    elif body.rule_type == RuleType.PERCENT and body.rule_amount > 100:
        raise HTTPException(status_code=400, detail="A percentage can't be more than 100")
    body.color = _check_color(body.color)
    body.currency = currencies.check(body.currency)


def _goal_values(body: GoalIn) -> tuple:
    return (body.name.strip(), body.kind.value, body.target_amount,
            body.target_date.isoformat() if body.target_date else None, body.rule_type.value, body.rule_amount,
            (body.starts_on or date.today()).isoformat(), body.priority, body.color, _clean(body.notes),
            body.currency, int(body.archived))


def received_since(db, owner_id: int, since: date) -> float:
    """Everything received from `since` on: paid bookings plus other income, after fees."""
    start = f"{since.isoformat()}T00:00:00+00:00"
    # Your share only: what partners get from shared bookings and income isn't yours.
    bookings = db.execute("""
        SELECT COALESCE(SUM(a.amount_paid - """ + collab.partner_share_sql("appointment", "a.amount_paid", "a.id") + """), 0)
        FROM appointments a WHERE a.owner_id = ? AND a.kind = 'client' AND a.scheduled_date >= ?
    """, (owner_id, start)).fetchone()[0]
    other = db.execute("""
        SELECT COALESCE(SUM((i.gross - i.fees) - """ + collab.partner_share_sql("income", "i.gross - i.fees", "i.id") + """), 0)
        FROM income i WHERE i.owner_id = ? AND i.status = 'received' AND i.date >= ?
    """, (owner_id, start)).fetchone()[0]
    return round(bookings + other, 2)


def _completed_bookings_since(db, owner_id: int, since: date) -> int:
    return db.execute("""
        SELECT COUNT(*) FROM appointments
        WHERE owner_id = ? AND kind = 'client' AND status = 'completed' AND scheduled_date >= ?
    """, (owner_id, f"{since.isoformat()}T00:00:00+00:00")).fetchone()[0]


def goal_status(db, owner_id: int, goal: dict, today: Optional[date] = None) -> dict:
    today = today or date.today()
    entries = [dict(r) for r in db.execute(
        "SELECT id, date, amount, note, created_at FROM goal_entries WHERE goal_id = ? ORDER BY date DESC, id DESC",
        (goal["id"],))]
    balance = round(sum(e["amount"] for e in entries), 2)
    starts = date.fromisoformat(goal["starts_on"])
    put_in_since_start = sum(e["amount"] for e in entries if e["amount"] > 0 and e["date"] >= goal["starts_on"])

    # What the rule says should have gone in by now.
    rule, amount = goal["rule_type"], goal["rule_amount"] or 0
    basis = None
    if rule == "percent":
        basis = received_since(db, owner_id, starts)
        expected = basis * amount / 100
    elif rule == "weekly":
        expected = amount * ((today - starts).days // 7 + 1) if today >= starts else 0
    elif rule == "per_booking":
        basis = _completed_bookings_since(db, owner_id, starts)
        expected = amount * basis
    else:
        expected = None
    suggested = round(max(expected - put_in_since_start, 0), 2) if expected is not None else None

    target, target_date = goal["target_amount"], goal["target_date"]
    status = {
        "balance": balance,
        "progress": round(min(balance / target, 1), 4) if target else None,
        "remaining": round(max(target - balance, 0), 2) if target else None,
        "reached": bool(target and balance >= target),
        "rule_expected": round(expected, 2) if expected is not None else None,
        "rule_basis": basis,
        "suggested": suggested,
        "per_week_needed": None,
        "on_track": None,
        "entries": entries[:50],
    }
    if target and target_date and balance < target:
        end = date.fromisoformat(target_date)
        days_left = (end - today).days
        status["per_week_needed"] = round((target - balance) / max(days_left / 7, 1), 2) if days_left > 0 else round(target - balance, 2)
        total_days = max((end - starts).days, 1)
        elapsed = min(max((today - starts).days, 0), total_days)
        status["on_track"] = balance >= target * elapsed / total_days
    return status


def _goal_row(db, owner_id: int, r) -> dict:
    goal = {**dict(r), "archived": bool(r["archived"])}
    return {**goal, **goal_status(db, owner_id, goal)}


def _get_goal(db, goal_id: int, owner_id: int):
    return db.execute("SELECT * FROM goals WHERE id = ? AND owner_id = ?", (goal_id, owner_id)).fetchone()


@router.get("/api/goals")
def list_goals(request: Request):
    owner = _owner(request)
    db = _db()
    try:
        return [_goal_row(db, owner, r) for r in db.execute(
            "SELECT * FROM goals WHERE owner_id = ? ORDER BY archived, priority DESC, id", (owner,))]
    finally:
        db.close()


@router.post("/api/goals", status_code=201)
def create_goal(body: GoalIn, request: Request):
    _validate_goal(body)
    owner = _owner(request)
    db = _db()
    try:
        now = _now()
        cur = db.execute("""
            INSERT INTO goals (name, kind, target_amount, target_date, rule_type, rule_amount, starts_on, priority,
                               color, notes, currency, archived, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_goal_values(body), owner, now, now))
        db.commit()
        return _goal_row(db, owner, _get_goal(db, cur.lastrowid, owner))
    finally:
        db.close()


@router.put("/api/goals/{goal_id}")
def update_goal(goal_id: int, body: GoalIn, request: Request):
    _validate_goal(body)
    owner = _owner(request)
    db = _db()
    try:
        existing = _get_goal(db, goal_id, owner)
        if not existing:
            raise HTTPException(status_code=404, detail="Goal not found")
        if body.starts_on is None:
            body.starts_on = date.fromisoformat(existing["starts_on"])
        db.execute("""
            UPDATE goals SET name = ?, kind = ?, target_amount = ?, target_date = ?, rule_type = ?, rule_amount = ?,
                   starts_on = ?, priority = ?, color = ?, notes = ?, currency = ?, archived = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_goal_values(body), _now(), goal_id, owner))
        db.commit()
        return _goal_row(db, owner, _get_goal(db, goal_id, owner))
    finally:
        db.close()


@router.delete("/api/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: int, request: Request):
    owner = _owner(request)
    db = _db()
    try:
        db.execute("DELETE FROM goal_entries WHERE goal_id = ? AND owner_id = ?", (goal_id, owner))
        db.execute("DELETE FROM goals WHERE id = ? AND owner_id = ?", (goal_id, owner))
        db.commit()
    finally:
        db.close()


@router.post("/api/goals/{goal_id}/entries", status_code=201)
def add_entry(goal_id: int, body: EntryIn, request: Request):
    """Put money into a goal (a positive amount) or take it out (negative)."""
    owner = _owner(request)
    if body.amount == 0 or not (abs(body.amount) < float("inf")):
        raise HTTPException(status_code=400, detail="Enter an amount")
    db = _db()
    try:
        goal = _get_goal(db, goal_id, owner)
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")
        status = goal_status(db, owner, dict(goal))
        if body.amount < 0 and status["balance"] + body.amount < -0.005:
            raise HTTPException(status_code=400, detail=f"There's only {status['balance']:.2f} in this goal")
        db.execute("INSERT INTO goal_entries (goal_id, owner_id, date, amount, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (goal_id, owner, (body.date or date.today()).isoformat(), round(body.amount, 2), _clean(body.note), _now()))
        db.commit()
        return _goal_row(db, owner, goal)
    finally:
        db.close()


@router.delete("/api/goals/{goal_id}/entries/{entry_id}", status_code=204)
def delete_entry(goal_id: int, entry_id: int, request: Request):
    db = _db()
    try:
        db.execute("DELETE FROM goal_entries WHERE id = ? AND goal_id = ? AND owner_id = ?", (entry_id, goal_id, _owner(request)))
        db.commit()
    finally:
        db.close()


# ==================== HOW I WORK (starter setups) ====================

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json"), encoding="utf-8") as _f:
    PRESETS = json.load(_f)["work_types"]


class WorkProfile(BaseModel):
    work_types: List[str]


def _work_types(db, owner_id: int) -> Optional[List[str]]:
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = 'work_types'", (owner_id,)).fetchone()
    try:
        return json.loads(row[0]) if row and row[0] is not None else None
    except ValueError:
        return None


def apply_presets(db, owner_id: int, work_types: List[str]) -> dict:
    """Add the categories and workplaces and platforms for these kinds of work. Anything already there is skipped."""
    ensure_categories(db, owner_id)
    added = {"categories": [], "sources": []}
    for work_type in work_types:
        preset = PRESETS[work_type]   # (work_type is also stored on each place added below)
        for parent, labels in preset.get("categories", {}).items():
            for label in labels:
                if not _label_taken(db, owner_id, label):
                    _add_category(db, owner_id, label, parent_key=parent)
                    added["categories"].append(label)
        for source in preset.get("sources", []):
            if not db.execute("SELECT 1 FROM income_sources WHERE owner_id = ? AND LOWER(name) = LOWER(?)",
                              (owner_id, source["name"])).fetchone():
                now = _now()
                db.execute("""
                    INSERT INTO income_sources (name, kind, fee_percent, fee_per_shift, token_value, payout_note,
                                                gift_share_percent, work_type, owner_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (source["name"], source.get("kind", "other"), source.get("fee_percent"), source.get("fee_per_shift"),
                      source.get("token_value"), source.get("payout_note"), source.get("gift_share_percent"),
                      work_type, owner_id, now, now))
                source_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                categories = category_lookup(db, owner_id)
                for order, charge in enumerate(source.get("charges", [])):
                    # No amount: every place charges differently, so the person fills it in.
                    db.execute("""
                        INSERT INTO place_charges (owner_id, source_id, label, cadence, category, test_type, sort_order,
                                                   created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (owner_id, source_id, charge["label"], charge["cadence"],
                          categories.get(charge["category"].lower(), "other"), charge.get("test_type"), order, now, now))
                added["sources"].append(source["name"])
    return added


@router.get("/api/work-profile")
def get_work_profile(request: Request):
    db = _db()
    try:
        return {"work_types": _work_types(db, _owner(request)),
                "options": [{"key": k, "label": v["label"]} for k, v in PRESETS.items()]}
    finally:
        db.close()


@router.put("/api/work-profile")
def save_work_profile(body: WorkProfile, request: Request):
    """Save which kinds of work you do (an empty list means "skip"), and add their starter setups."""
    unknown = [t for t in body.work_types if t not in PRESETS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown kind of work: {', '.join(unknown)}")
    owner = _owner(request)
    types = list(dict.fromkeys(body.work_types))
    db = _db()
    try:
        added = apply_presets(db, owner, types)
        db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, 'work_types', ?) "
                   "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, json.dumps(types)))
        db.commit()
        return {"work_types": types, "added": added}
    except sqlite3.Error:
        db.rollback()
        raise
    finally:
        db.close()


# ==================== CASH THE OFFICE IS HOLDING ====================

class PaidOutIn(BaseModel):
    payment_method: Optional[str] = None
    paid_on: Optional[date] = None


@router.get("/api/held")
def held_by_the_office(request: Request):
    """For each workplace: what you've earned there that hasn't been paid out to you yet (income marked "not yet")."""
    owner = _owner(request)
    db = _db()
    try:
        return [dict(r) for r in db.execute("""
            SELECT s.id AS source_id, s.name, s.holds_cash, s.cash_limit, COUNT(i.id) AS entries,
                   ROUND(COALESCE(SUM(i.gross - i.fees), 0), 2) AS held, MIN(i.date) AS since
            FROM income_sources s JOIN income i ON i.source_id = s.id AND i.status = 'pending'
            WHERE s.owner_id = ? GROUP BY s.id ORDER BY held DESC
        """, (owner,))]
    finally:
        db.close()


@router.post("/api/income-sources/{source_id}/paid-out")
def paid_out(source_id: int, body: PaidOutIn, request: Request):
    """The office paid you what it was holding: everything pending at this workplace becomes received."""
    owner = _owner(request)
    db = _db()
    try:
        if not get_source(db, source_id, owner):
            raise HTTPException(status_code=404, detail="Not found")
        total = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(gross - fees), 0) AS held FROM income WHERE source_id = ? AND owner_id = ? "
                           "AND status = 'pending'", (source_id, owner)).fetchone()
        db.execute("UPDATE income SET status = 'received', payout_date = ?, payment_method = COALESCE(?, payment_method), updated_at = ? "
                   "WHERE source_id = ? AND owner_id = ? AND status = 'pending'",
                   ((body.paid_on or datetime.now(timezone.utc).date()).isoformat(), (_clean(body.payment_method) or "")[:40] or None,
                    _now(), source_id, owner))
        db.commit()
        return {"entries": total["n"], "paid": round(total["held"], 2)}
    finally:
        db.close()


# ==================== TIPS ====================

class TipIn(BaseModel):
    amount: float                         # 0 with a booking: take that booking's tip away
    source_id: Optional[int] = None       # the workplace it was earned at, if it keeps a share
    appointment_id: Optional[int] = None  # the booking it came with
    date: Optional[datetime] = None
    note: Optional[str] = None
    payment_method: Optional[str] = None


@router.post("/api/tips")
def log_tip(body: TipIn, request: Request):
    """
    A tip, on its own or with a booking. It's income of the kind "tips". When it was earned at a workplace that
    keeps a share of tips, that share is worked out here and saved as the fee, so what you kept is right
    everywhere. A booking has one tip: sending another replaces it, and 0 removes it.
    """
    owner = _owner(request)
    if not (0 <= body.amount < 1e9) or (body.amount == 0 and body.appointment_id is None):
        raise HTTPException(status_code=400, detail="The tip must be more than 0")
    db = _db()
    try:
        source = None
        if body.source_id is not None:
            source = get_source(db, body.source_id, owner)
            if not source:
                raise HTTPException(status_code=400, detail="That workplace or platform doesn't exist")
        booking = None
        if body.appointment_id is not None:
            booking = db.execute("""
                SELECT a.id, a.client_id, a.scheduled_date, c.display_name FROM appointments a LEFT JOIN clients c ON c.id = a.client_id
                WHERE a.id = ? AND a.owner_id = ? AND a.kind = 'client'
            """, (body.appointment_id, owner)).fetchone()
            if not booking:
                raise HTTPException(status_code=404, detail="Booking not found")
            db.execute("DELETE FROM income WHERE appointment_id = ? AND kind = 'tips' AND owner_id = ?", (body.appointment_id, owner))
        amount = round(body.amount, 2)
        share = round(amount * ((source or {}).get("tip_share_percent") or 0) / 100, 2)
        income_id = None
        if amount > 0:
            when = _utc_iso(body.date) if body.date else (booking["scheduled_date"] if booking else _now())
            what = _clean(body.note) or ("Tip from " + booking["display_name"] if booking and booking["display_name"] else "Tip")
            cur = db.execute("""
                INSERT INTO income (source_id, date, description, kind, gross, fees, status, currency, client_id, appointment_id,
                                    payment_method, owner_id, created_at, updated_at)
                VALUES (?, ?, ?, 'tips', ?, ?, 'received', ?, ?, ?, ?, ?, ?, ?)
            """, (body.source_id, when, what, amount, share, (source or {}).get("currency") or currencies.DEFAULT,
                  booking["client_id"] if booking else None, body.appointment_id, (_clean(body.payment_method) or "")[:40] or None,
                  owner, _now(), _now()))
            income_id = cur.lastrowid
        db.commit()
        return {"tip": amount, "house_share": share, "kept": round(amount - share, 2), "income_id": income_id}
    finally:
        db.close()


# ==================== COMPARING KINDS OF WORK ====================

BOOKINGS_GROUP = "bookings"
OTHER_GROUP = "other"


@router.get("/api/earnings/by-source")
def compare_sources(
    request: Request,
    start: datetime = Query(...),
    end: datetime = Query(...),
    group: str = Query("work_type", description="work_type (kind of work), source (workplace or platform) or persona"),
):
    """
    What each kind of work (or each workplace or platform) brought in between start and end: before fees, fees, what
    you kept, and its share. Bookings on the calendar are their own group ("In-person bookings"). Income that
    isn't from a place, or from a place without a kind of work, is "Other". Only money already received counts;
    pending payouts are shown separately.
    """
    if group not in ("work_type", "source", "persona"):
        raise HTTPException(status_code=400, detail="group must be work_type, source or persona")
    owner = _owner(request)
    start_iso, end_iso = _utc_iso(start), _utc_iso(end)
    db = _db()
    try:
        rows = {}

        def row(key, label):
            return rows.setdefault(key, {"key": key, "label": label, "gross": 0.0, "fees": 0.0, "net": 0.0,
                                         "partners": 0.0, "entries": 0, "pending": 0.0})

        names = {p["id"]: p["name"] for p in db.execute("SELECT id, name FROM personas WHERE owner_id = ?", (owner,))}

        def persona_row(persona_id):
            return row(f"persona:{persona_id}", names[persona_id]) if persona_id in names else row(OTHER_GROUP, "No persona")

        # Bookings: one group, or by the persona each client knows you by.
        for b in db.execute("""
            SELECT c.persona_id, COALESCE(SUM(a.amount_paid), 0) AS paid, COUNT(*) AS n,
                   COALESCE(SUM(a.amount_paid - """ + collab.partner_share_sql("appointment", "a.amount_paid", "a.id") + """), 0) AS mine
            FROM appointments a LEFT JOIN clients c ON c.id = a.client_id
            WHERE a.owner_id = ? AND a.kind = 'client' AND a.amount_paid > 0 AND a.scheduled_date >= ? AND a.scheduled_date < ?
            GROUP BY CASE WHEN ? = 'persona' THEN c.persona_id END
        """, (owner, start_iso, end_iso, group)).fetchall():
            if not b["n"]:
                continue
            r = persona_row(b["persona_id"]) if group == "persona" else row(BOOKINGS_GROUP, "In-person bookings")
            r["gross"] += round(b["paid"], 2)
            r["net"] += round(b["mine"], 2)
            r["partners"] += round(b["paid"] - b["mine"], 2)
            r["entries"] += b["n"]

        for i in db.execute("""
            SELECT i.gross, i.fees, i.status, i.source_id, s.name AS source_name, s.work_type, s.persona_id,
                   (i.gross - i.fees) - """ + collab.partner_share_sql("income", "i.gross - i.fees", "i.id") + """ AS mine
            FROM income i LEFT JOIN income_sources s ON i.source_id = s.id
            WHERE i.owner_id = ? AND i.date >= ? AND i.date < ?
        """, (owner, start_iso, end_iso)):
            if group == "work_type":
                key = i["work_type"] or OTHER_GROUP
                r = row(key, PRESETS[key]["label"] if key in PRESETS else "Other income")
            elif group == "persona":
                r = persona_row(i["persona_id"])
            else:
                key = f"source:{i['source_id']}" if i["source_id"] else OTHER_GROUP
                r = row(key, i["source_name"] or "Not from a saved place")
            if i["status"] == "pending":
                r["pending"] += i["gross"] - i["fees"]
                continue
            r["gross"] += i["gross"]
            r["fees"] += i["fees"]
            r["net"] += i["mine"]
            r["partners"] += (i["gross"] - i["fees"]) - i["mine"]
            r["entries"] += 1

        total = sum(r["net"] for r in rows.values())
        out = []
        for r in rows.values():
            for k in ("gross", "fees", "net", "partners", "pending"):
                r[k] = round(r[k], 2)
            r["share"] = round(r["net"] / total, 4) if total > 0 else None
            r["per_entry"] = round(r["net"] / r["entries"], 2) if r["entries"] else None
            out.append(r)
        out.sort(key=lambda r: r["net"], reverse=True)
        return {"group": group, "rows": out, "total": round(total, 2)}
    finally:
        db.close()
