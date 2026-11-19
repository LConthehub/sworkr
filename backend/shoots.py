"""
Planning a content shoot, from the idea to the release.

A shoot has a date, a place and a concept, and then the lists that make it happen:

- people: the photographer, co-stars, makeup, an assistant. Each with a role, a fee, what was agreed about
  the content, and whether their paperwork (ID, release) is done. A person can be one of your contacts.
- goals: what the shoot has to produce ("3 pay-per-view sets", "10 teasers", "a trailer").
- shots: the shot list.
- wardrobe: outfits and props, ticked off as they're packed.
- prep: things to do before the day.
- budget: what each thing is planned to cost and what it did cost. Paying a line or a person's fee writes it
  into expenses, linked to the shoot, so the shoot knows what it really cost.
- marketing: the plan for putting it out, with dates. A shoot can have a campaign in the post planner.

The pictures and videos stay in the person's own library; a shoot can only point at the folder.
"""

from datetime import date, datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import finance
import personas

router = APIRouter()
_get_db: Optional[Callable] = None

STATUSES = ("idea", "planning", "booked", "shot", "editing", "released", "cancelled")
AHEAD = ("idea", "planning", "booked")
ITEM_KINDS = ("goal", "shot", "wardrobe", "prep", "budget", "marketing")
ROLES = ("photographer", "videographer", "co-star", "makeup", "assistant", "other")


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _owner(request: Request) -> int:
    return request.state.user["id"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text: Optional[str], limit: int = 10000) -> Optional[str]:
    return (text or "").strip()[:limit] or None


def _money_ok(value: Optional[float]) -> bool:
    return value is None or 0 <= value < 1e9


class ShootIn(BaseModel):
    title: str
    status: str = "planning"
    shoot_date: Optional[date] = None
    start_time: Optional[str] = None      # "14:30", local
    hours: Optional[float] = None
    concept: Optional[str] = None
    location_name: Optional[str] = None
    location_address: Optional[str] = None
    location_notes: Optional[str] = None  # access, parking, light, what's allowed there
    set_path: Optional[str] = None        # the folder in your library the results go in
    campaign_id: Optional[int] = None
    tour_id: Optional[int] = None
    persona_id: Optional[int] = None
    notes: Optional[str] = None


class ItemIn(BaseModel):
    kind: str
    label: str
    notes: Optional[str] = None
    done: bool = False
    amount: Optional[float] = None        # budget: what it's planned to cost
    actual: Optional[float] = None        # budget: what it did cost
    due_date: Optional[date] = None       # prep and marketing: by when


class PersonIn(BaseModel):
    name: Optional[str] = None            # left out when it's one of your contacts
    contact_id: Optional[int] = None
    role: str = "other"
    fee: Optional[float] = None
    agreement: Optional[str] = None       # what was agreed about the content: who can post it, the split
    id_checked: bool = False
    release_signed: bool = False
    confirmed: bool = False
    notes: Optional[str] = None


class PayIn(BaseModel):
    amount: Optional[float] = None        # left out: the planned amount (or the fee)
    paid_on: Optional[date] = None


def _shoot_category(db, owner_id: int) -> str:
    """Shoot costs go under "Photographers & shoots" when the person has that category, otherwise Marketing."""
    finance.ensure_categories(db, owner_id)
    r = db.execute("SELECT key FROM expense_categories WHERE owner_id = ? AND LOWER(label) = 'photographers & shoots'", (owner_id,)).fetchone()
    return r["key"] if r else "marketing"


def _items(db, shoot_id: int) -> List[dict]:
    return [{**dict(r), "done": bool(r["done"])} for r in db.execute(
        "SELECT * FROM shoot_items WHERE shoot_id = ? ORDER BY kind, done, sort_order, id", (shoot_id,))]


def _people(db, shoot_id: int) -> List[dict]:
    out = []
    for r in db.execute("""
        SELECT p.*, c.display_name AS contact_name FROM shoot_people p LEFT JOIN clients c ON c.id = p.contact_id
        WHERE p.shoot_id = ? ORDER BY p.id
    """, (shoot_id,)):
        d = dict(r)
        for flag in ("id_checked", "release_signed", "confirmed"):
            d[flag] = bool(d[flag])
        d["display_name"] = d["contact_name"] or d["name"] or "Someone"
        out.append(d)
    return out


def _summary(shoot: dict, items: List[dict], people: List[dict], spent: float, today: date) -> dict:
    """The figures a list of shoots shows, and what still needs doing."""
    counts = {k: {"total": 0, "done": 0} for k in ITEM_KINDS}
    for i in items:
        counts[i["kind"]]["total"] += 1
        counts[i["kind"]]["done"] += i["done"]
    budget = [i for i in items if i["kind"] == "budget"]
    planned = sum(i["amount"] or 0 for i in budget) + sum(p["fee"] or 0 for p in people)
    days_left = (date.fromisoformat(shoot["shoot_date"]) - today).days if shoot["shoot_date"] else None
    warnings = []
    if shoot["status"] in AHEAD:
        if not shoot["shoot_date"]:
            warnings.append("No date yet")
        if days_left is not None and days_left < 0:
            warnings.append("The date has passed: mark it as shot, or move it")
        if days_left is not None and 0 <= days_left <= 7:
            if not shoot["location_name"]:
                warnings.append("No location yet")
            unconfirmed = [p["display_name"] for p in people if not p["confirmed"]]
            if unconfirmed:
                warnings.append("Not confirmed: " + ", ".join(unconfirmed))
            left = counts["prep"]["total"] - counts["prep"]["done"]
            if left:
                warnings.append(f"{left} thing{'' if left == 1 else 's'} still to prepare")
            unpacked = counts["wardrobe"]["total"] - counts["wardrobe"]["done"]
            if unpacked and days_left <= 1:
                warnings.append(f"{unpacked} wardrobe item{'' if unpacked == 1 else 's'} not packed")
    # Anyone else on camera needs their paperwork before the content can go out.
    paperwork = [p["display_name"] for p in people if p["role"] == "co-star" and not (p["id_checked"] and p["release_signed"])]
    if paperwork and shoot["status"] != "cancelled":
        warnings.append("ID or release still needed: " + ", ".join(paperwork))
    return {"counts": counts, "people": len(people), "planned": round(planned, 2), "spent": round(spent, 2),
            "left_to_spend": round(planned - spent, 2), "days_left": days_left, "warnings": warnings}


def _full(db, owner_id: int, shoot_id: int, detail: bool = True) -> Optional[dict]:
    r = db.execute("""
        SELECT s.*, c.name AS campaign_name, t.name AS tour_name,
               (SELECT COALESCE(SUM(e.amount), 0) FROM expenses e WHERE e.shoot_id = s.id) AS spent
        FROM shoots s LEFT JOIN campaigns c ON c.id = s.campaign_id LEFT JOIN tours t ON t.id = s.tour_id
        WHERE s.id = ? AND s.owner_id = ?
    """, (shoot_id, owner_id)).fetchone()
    if not r:
        return None
    shoot = dict(r)
    items, people = _items(db, shoot_id), _people(db, shoot_id)
    shoot["summary"] = _summary(shoot, items, people, shoot.pop("spent"), datetime.now(timezone.utc).date())
    if detail:
        shoot["items"], shoot["people"] = items, people
    return shoot


def _need(db, owner_id: int, shoot_id: int) -> dict:
    shoot = _full(db, owner_id, shoot_id)
    if not shoot:
        raise HTTPException(status_code=404, detail="Shoot not found")
    return shoot


def _values(db, owner_id: int, body: ShootIn) -> tuple:
    import content
    title = _clean(body.title, 160)
    if not title:
        raise HTTPException(status_code=400, detail="Give the shoot a name")
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")
    start = _clean(body.start_time, 5)
    if start:
        try:
            datetime.strptime(start, "%H:%M")
        except ValueError:
            raise HTTPException(status_code=400, detail="The start time looks like 14:30")
    if body.hours is not None and not (0 < body.hours <= 72):
        raise HTTPException(status_code=400, detail="How long is 0 to 72 hours")
    for table, value, what in (("campaigns", body.campaign_id, "campaign"), ("tours", body.tour_id, "tour")):
        if value is not None and not db.execute(f"SELECT 1 FROM {table} WHERE id = ? AND owner_id = ?", (value, owner_id)).fetchone():
            raise HTTPException(status_code=400, detail=f"That {what} doesn't exist")
    return (title, body.status, body.shoot_date.isoformat() if body.shoot_date else None, start, body.hours, _clean(body.concept),
            _clean(body.location_name, 160), _clean(body.location_address, 300), _clean(body.location_notes),
            content.clean_path(body.set_path) or None, body.campaign_id, body.tour_id, personas.check(db, owner_id, body.persona_id),
            _clean(body.notes))


# ==================== SHOOTS ====================

@router.get("/api/shoots")
def list_shoots(request: Request, show: str = Query("ahead", description="ahead, done or all")):
    """Shoots with their figures. Ahead: soonest first, undated last. Done: latest first."""
    wheres = {"ahead": f"status IN ({', '.join(repr(s) for s in AHEAD)})", "done": "status IN ('shot', 'editing', 'released')", "all": "1 = 1"}
    if show not in wheres:
        raise HTTPException(status_code=400, detail="show must be ahead, done or all")
    owner = _owner(request)
    order = "shoot_date DESC, id DESC" if show == "done" else "shoot_date IS NULL, shoot_date, id"
    db = _get_db()
    try:
        ids = [r[0] for r in db.execute(f"SELECT id FROM shoots WHERE owner_id = ? AND {wheres[show]} ORDER BY {order} LIMIT 500", (owner,))]
        return [_full(db, owner, i, detail=False) for i in ids]
    finally:
        db.close()


@router.get("/api/shoots/{shoot_id}")
def get_shoot(shoot_id: int, request: Request):
    db = _get_db()
    try:
        return _need(db, _owner(request), shoot_id)
    finally:
        db.close()


@router.post("/api/shoots", status_code=201)
def create_shoot(body: ShootIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        cur = db.execute("""
            INSERT INTO shoots (title, status, shoot_date, start_time, hours, concept, location_name, location_address, location_notes,
                                set_path, campaign_id, tour_id, persona_id, notes, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_values(db, owner, body), owner, _now(), _now()))
        db.commit()
        return _full(db, owner, cur.lastrowid)
    finally:
        db.close()


@router.put("/api/shoots/{shoot_id}")
def update_shoot(shoot_id: int, body: ShootIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        _need(db, owner, shoot_id)
        db.execute("""
            UPDATE shoots SET title = ?, status = ?, shoot_date = ?, start_time = ?, hours = ?, concept = ?, location_name = ?,
                   location_address = ?, location_notes = ?, set_path = ?, campaign_id = ?, tour_id = ?, persona_id = ?, notes = ?,
                   updated_at = ? WHERE id = ? AND owner_id = ?
        """, (*_values(db, owner, body), _now(), shoot_id, owner))
        db.commit()
        return _full(db, owner, shoot_id)
    finally:
        db.close()


@router.delete("/api/shoots/{shoot_id}", status_code=204)
def delete_shoot(shoot_id: int, request: Request):
    """The plan goes, with its lists. What was spent on it stays in expenses."""
    owner = _owner(request)
    db = _get_db()
    try:
        if _full(db, owner, shoot_id, detail=False):
            db.execute("DELETE FROM shoot_items WHERE shoot_id = ?", (shoot_id,))
            db.execute("DELETE FROM shoot_people WHERE shoot_id = ?", (shoot_id,))
            db.execute("DELETE FROM shoots WHERE id = ? AND owner_id = ?", (shoot_id, owner))
            db.commit()
    finally:
        db.close()


@router.post("/api/shoots/{shoot_id}/copy", status_code=201)
def copy_shoot(shoot_id: int, request: Request):
    """Start a new shoot from this one: the same place, people and lists, nothing ticked, no date."""
    owner = _owner(request)
    db = _get_db()
    try:
        old = _need(db, owner, shoot_id)
        cur = db.execute("""
            INSERT INTO shoots (title, status, start_time, hours, concept, location_name, location_address, location_notes,
                                persona_id, notes, owner_id, created_at, updated_at)
            VALUES (?, 'planning', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (f"{old['title']} (copy)"[:160], old["start_time"], old["hours"], old["concept"], old["location_name"],
              old["location_address"], old["location_notes"], old["persona_id"], old["notes"], owner, _now(), _now()))
        new_id = cur.lastrowid
        for i in old["items"]:
            db.execute("INSERT INTO shoot_items (shoot_id, owner_id, kind, label, notes, amount, sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (new_id, owner, i["kind"], i["label"], i["notes"], i["amount"], i["sort_order"], _now()))
        for p in old["people"]:
            db.execute("INSERT INTO shoot_people (shoot_id, owner_id, name, contact_id, role, fee, agreement, id_checked, notes, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (new_id, owner, p["name"], p["contact_id"], p["role"], p["fee"], p["agreement"], int(p["id_checked"]), p["notes"], _now()))
        db.commit()
        return _full(db, owner, new_id)
    finally:
        db.close()


@router.post("/api/shoots/{shoot_id}/campaign", status_code=201)
def make_campaign(shoot_id: int, request: Request):
    """Start a campaign in the post planner for what this shoot produces, and link the two."""
    owner = _owner(request)
    db = _get_db()
    try:
        shoot = _need(db, owner, shoot_id)
        if shoot["campaign_id"]:
            raise HTTPException(status_code=409, detail="This shoot already has a campaign")
        cur = db.execute("INSERT INTO campaigns (name, goal, start_date, set_path, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (shoot["title"][:120], "; ".join(i["label"] for i in shoot["items"] if i["kind"] == "goal")[:300] or None,
                          shoot["shoot_date"], shoot["set_path"], owner, _now(), _now()))
        db.execute("UPDATE shoots SET campaign_id = ?, updated_at = ? WHERE id = ?", (cur.lastrowid, _now(), shoot_id))
        db.commit()
        return _full(db, owner, shoot_id)
    finally:
        db.close()


# ==================== THE LISTS ====================

def _item_values(body: ItemIn) -> tuple:
    label = _clean(body.label, 300)
    if body.kind not in ITEM_KINDS:
        raise HTTPException(status_code=400, detail="Unknown list")
    if not label:
        raise HTTPException(status_code=400, detail="Say what it is")
    if not (_money_ok(body.amount) and _money_ok(body.actual)):
        raise HTTPException(status_code=400, detail="Amounts must be 0 or more")
    budget = body.kind == "budget"
    return (body.kind, label, _clean(body.notes, 2000), int(body.done), body.amount if budget else None,
            body.actual if budget else None, body.due_date.isoformat() if body.due_date else None)


def _item(db, owner_id: int, item_id: int) -> dict:
    r = db.execute("SELECT * FROM shoot_items WHERE id = ? AND owner_id = ?", (item_id, owner_id)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Not found")
    return dict(r)


@router.post("/api/shoots/{shoot_id}/items", status_code=201)
def add_item(shoot_id: int, body: ItemIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        _need(db, owner, shoot_id)
        last = db.execute("SELECT COALESCE(MAX(sort_order), 0) FROM shoot_items WHERE shoot_id = ?", (shoot_id,)).fetchone()[0]
        db.execute("INSERT INTO shoot_items (kind, label, notes, done, amount, actual, due_date, shoot_id, owner_id, sort_order, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (*_item_values(body), shoot_id, owner, last + 1, _now()))
        db.commit()
        return _full(db, owner, shoot_id)
    finally:
        db.close()


@router.put("/api/shoots/items/{item_id}")
def update_item(item_id: int, body: ItemIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        item = _item(db, owner, item_id)
        db.execute("UPDATE shoot_items SET kind = ?, label = ?, notes = ?, done = ?, amount = ?, actual = ?, due_date = ? WHERE id = ?",
                   (*_item_values(body), item_id))
        db.commit()
        return _full(db, owner, item["shoot_id"])
    finally:
        db.close()


@router.delete("/api/shoots/items/{item_id}")
def delete_item(item_id: int, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        item = _item(db, owner, item_id)
        db.execute("DELETE FROM shoot_items WHERE id = ?", (item_id,))
        db.commit()
        return _full(db, owner, item["shoot_id"])
    finally:
        db.close()


def _log_expense(db, owner_id: int, shoot: dict, description: str, amount: float, paid_on: Optional[date], contact_id: Optional[int] = None) -> int:
    when = (paid_on or datetime.now(timezone.utc).date()).isoformat()
    cur = db.execute("""
        INSERT INTO expenses (description, amount, category, date, client_id, tour_id, owner_id, created_at, source, shoot_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'shoot', ?)
    """, (description[:300], round(amount, 2), _shoot_category(db, owner_id), f"{when}T12:00:00+00:00", contact_id, shoot["tour_id"],
          owner_id, _now(), shoot["id"]))
    return cur.lastrowid


@router.post("/api/shoots/items/{item_id}/pay")
def pay_item(item_id: int, body: PayIn, request: Request):
    """A budget line was paid: its real cost is saved, it's ticked, and the cost is written into expenses."""
    owner = _owner(request)
    db = _get_db()
    try:
        item = _item(db, owner, item_id)
        if item["kind"] != "budget":
            raise HTTPException(status_code=400, detail="Only budget lines are paid")
        if item["expense_id"]:
            raise HTTPException(status_code=409, detail="This is already in your expenses. Change it there.")
        amount = body.amount if body.amount is not None else item["amount"]
        if not amount or not (0 < amount < 1e9):
            raise HTTPException(status_code=400, detail="Say how much it cost")
        shoot = _need(db, owner, item["shoot_id"])
        expense_id = _log_expense(db, owner, shoot, f"{shoot['title']}: {item['label']}", amount, body.paid_on)
        db.execute("UPDATE shoot_items SET actual = ?, done = 1, expense_id = ? WHERE id = ?", (round(amount, 2), expense_id, item_id))
        db.commit()
        return _full(db, owner, item["shoot_id"])
    finally:
        db.close()


# ==================== PEOPLE ====================

def _person_values(db, owner_id: int, body: PersonIn) -> tuple:
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail="Unknown role")
    name = _clean(body.name, 120)
    if body.contact_id is not None and not db.execute("SELECT 1 FROM clients WHERE id = ? AND owner_id = ?", (body.contact_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That contact doesn't exist")
    if not name and body.contact_id is None:
        raise HTTPException(status_code=400, detail="Say who it is, or choose a contact")
    if not _money_ok(body.fee):
        raise HTTPException(status_code=400, detail="The fee must be 0 or more")
    return (name, body.contact_id, body.role, body.fee, _clean(body.agreement, 2000), int(body.id_checked), int(body.release_signed),
            int(body.confirmed), _clean(body.notes, 2000))


def _person(db, owner_id: int, person_id: int) -> dict:
    r = db.execute("SELECT * FROM shoot_people WHERE id = ? AND owner_id = ?", (person_id, owner_id)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Not found")
    return dict(r)


@router.post("/api/shoots/{shoot_id}/people", status_code=201)
def add_person(shoot_id: int, body: PersonIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        _need(db, owner, shoot_id)
        db.execute("INSERT INTO shoot_people (name, contact_id, role, fee, agreement, id_checked, release_signed, confirmed, notes, "
                   "shoot_id, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (*_person_values(db, owner, body), shoot_id, owner, _now()))
        db.commit()
        return _full(db, owner, shoot_id)
    finally:
        db.close()


@router.put("/api/shoots/people/{person_id}")
def update_person(person_id: int, body: PersonIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        person = _person(db, owner, person_id)
        db.execute("UPDATE shoot_people SET name = ?, contact_id = ?, role = ?, fee = ?, agreement = ?, id_checked = ?, release_signed = ?, "
                   "confirmed = ?, notes = ? WHERE id = ?", (*_person_values(db, owner, body), person_id))
        # Unticking takes the date with it.
        db.execute("UPDATE shoot_people SET id_checked_on = CASE WHEN id_checked = 1 THEN id_checked_on END, "
                   "release_signed_on = CASE WHEN release_signed = 1 THEN release_signed_on END WHERE id = ?", (person_id,))
        db.commit()
        return _full(db, owner, person["shoot_id"])
    finally:
        db.close()


@router.delete("/api/shoots/people/{person_id}")
def delete_person(person_id: int, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        person = _person(db, owner, person_id)
        db.execute("DELETE FROM shoot_people WHERE id = ?", (person_id,))
        db.commit()
        return _full(db, owner, person["shoot_id"])
    finally:
        db.close()


@router.post("/api/shoots/people/{person_id}/pay")
def pay_person(person_id: int, body: PayIn, request: Request):
    """Their fee was paid: it's written into expenses against the shoot (and against them, if they're a contact)."""
    owner = _owner(request)
    db = _get_db()
    try:
        person = _person(db, owner, person_id)
        if person["expense_id"]:
            raise HTTPException(status_code=409, detail="This fee is already in your expenses. Change it there.")
        amount = body.amount if body.amount is not None else person["fee"]
        if not amount or not (0 < amount < 1e9):
            raise HTTPException(status_code=400, detail="Say how much you paid")
        shoot = _need(db, owner, person["shoot_id"])
        who = next(p["display_name"] for p in shoot["people"] if p["id"] == person_id)
        expense_id = _log_expense(db, owner, shoot, f"{shoot['title']}: {who} ({person['role']})", amount, body.paid_on, person["contact_id"])
        db.execute("UPDATE shoot_people SET fee = ?, expense_id = ? WHERE id = ?", (round(amount, 2), expense_id, person_id))
        db.commit()
        return _full(db, owner, person["shoot_id"])
    finally:
        db.close()


# ==================== PAPERWORK ====================
# Who needs what: anyone on camera needs their ID checked (that they're an adult) and a signed release; whoever
# held the camera needs a release too, because the pictures are theirs until they sign them over.

ON_CAMERA = ("co-star",)
NEEDS_RELEASE = ("co-star", "photographer", "videographer")

RELEASE_TEXT = """MODEL RELEASE

Date of the shoot: ____________     Place: ____________

I, ____________ (legal name), also known as ____________ (stage name), confirm that:

1. I am 18 or older, and I showed a government photo ID today to prove it.
2. I took part in this shoot freely, and agreed beforehand to everything that was filmed or photographed.
3. I agree that ____________ may publish and sell the photos and videos from this shoot on these sites:
   ____________________________________________
4. We agreed to share the money like this: ____________________________________________
5. If I ask for a piece to be taken down later, this is what we agreed: ____________________________________________

Signed: ____________        Date: ____________
Signed (the other person): ____________        Date: ____________

A copy of each person's ID is kept with this release."""


class PaperworkIn(BaseModel):
    id_checked_on: Optional[date] = None        # the day you saw their ID
    release_signed_on: Optional[date] = None    # the day the release was signed
    records_kept: Optional[str] = None          # where the copies are, in your own words


def _missing(p: dict) -> List[str]:
    out = []
    if p["role"] in ON_CAMERA and not p["id_checked"]:
        out.append("ID check")
    if p["role"] in NEEDS_RELEASE and not p["release_signed"]:
        out.append("release")
    if p["role"] in NEEDS_RELEASE and (p["id_checked"] or p["release_signed"]) and not p["records_kept"]:
        out.append("where the copies are")
    return out


@router.put("/api/shoots/people/{person_id}/paperwork")
def save_paperwork(person_id: int, body: PaperworkIn, request: Request):
    """The dates and where the records are. A date ticks the box; no date unticks it."""
    owner = _owner(request)
    db = _get_db()
    try:
        person = _person(db, owner, person_id)
        db.execute("UPDATE shoot_people SET id_checked_on = ?, id_checked = ?, release_signed_on = ?, release_signed = ?, records_kept = ? "
                   "WHERE id = ?",
                   (body.id_checked_on.isoformat() if body.id_checked_on else None, int(bool(body.id_checked_on)),
                    body.release_signed_on.isoformat() if body.release_signed_on else None, int(bool(body.release_signed_on)),
                    _clean(body.records_kept, 500), person_id))
        db.commit()
        return _full(db, owner, person["shoot_id"])
    finally:
        db.close()


@router.get("/api/paperwork")
def paperwork(request: Request):
    """Everyone from every shoot who needs paperwork, the ones with something missing first."""
    owner = _owner(request)
    db = _get_db()
    try:
        people = []
        for r in db.execute("""
            SELECT p.*, c.display_name AS contact_name, s.title AS shoot_title, s.shoot_date, s.status AS shoot_status
            FROM shoot_people p JOIN shoots s ON s.id = p.shoot_id LEFT JOIN clients c ON c.id = p.contact_id
            WHERE p.owner_id = ? AND s.status != 'cancelled' ORDER BY s.shoot_date DESC, p.id
        """, (owner,)):
            d = dict(r)
            if d["role"] not in NEEDS_RELEASE:
                continue
            people.append({
                "id": d["id"], "shoot_id": d["shoot_id"], "shoot_title": d["shoot_title"], "shoot_date": d["shoot_date"],
                "released": d["shoot_status"] == "released", "name": d["contact_name"] or d["name"] or "Someone", "role": d["role"],
                "id_checked": bool(d["id_checked"]), "id_checked_on": d["id_checked_on"],
                "release_signed": bool(d["release_signed"]), "release_signed_on": d["release_signed_on"],
                "records_kept": d["records_kept"], "missing": _missing(d)})
        people.sort(key=lambda p: (not p["missing"], not p["released"]))
        return {"people": people, "incomplete": sum(1 for p in people if p["missing"]),
                # Already out, with paperwork missing: the ones to fix first.
                "released_incomplete": sum(1 for p in people if p["missing"] and p["released"]),
                "release_text": RELEASE_TEXT}
    finally:
        db.close()
