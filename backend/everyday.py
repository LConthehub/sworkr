"""
Small everyday things: supplies that run low, an incident log, and a privacy check-up.

- Supplies: a short stock list (condoms, lube, test kits, wipes, lashes...). Each has how many you have and the
  number at which it counts as running low. Tap minus when you use one.
- Incident log: what happened, when, who, and what evidence you kept, written down the same day. For a lawyer,
  a platform appeal, the police if you choose, or just your own memory. Never sent anywhere.
- Privacy check-up: a checklist of things worth doing once (and again now and then). sworkr only remembers
  which ones you ticked.
"""

import json
from datetime import date, datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
_get_db: Optional[Callable] = None

STARTER_SUPPLIES = ["Condoms", "Lube", "Wipes", "Toy cleaner", "Hand sanitizer"]

CHECKUP = [
    ("work_phone", "A separate work phone or number", "A second SIM, an eSIM or a number app. Clients never get your personal number."),
    ("work_email", "A work email that isn't tied to your legal name", "Check its recovery phone and email aren't your personal ones either."),
    ("photos_location", "Location stripped from photos", "Phones store where a photo was taken inside the file. Turn off location for the camera, or remove it before posting."),
    ("face_search", "Searched for your own face and work name", "Try a reverse image search with your ad photos, and search your work name with your city."),
    ("data_brokers", "Asked people-search sites to remove your home address", "Search your legal name and address; most of these sites have an opt-out form."),
    ("social_split", "Personal and work accounts fully apart", "Different email, different phone number, no shared contacts upload, not logged in on the same browser profile."),
    ("payment_names", "Checked what name clients see when they pay you", "Payment apps often show your legal name. Look at what a payer sees, and change the display name if you can."),
    ("phone_lock", "A strong phone lock, with previews hidden", "A 6-digit code or longer, and message previews off on the lock screen."),
    ("two_step_everywhere", "Two-step sign-in on email and your main platforms", "An authenticator app is safer than text messages."),
    ("backup_plan", "Someone you trust knows what to do in an emergency", "Who to call, and where your important things are."),
]


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _owner(request: Request) -> int:
    return request.state.user["id"]


# ==================== SUPPLIES ====================

class SupplyIn(BaseModel):
    name: str
    have: int = 0
    low_at: int = 1
    note: Optional[str] = None


def _supplies(db, owner: int) -> List[dict]:
    return [{**dict(r), "low": r["have"] <= r["low_at"]} for r in db.execute(
        "SELECT id, name, have, low_at, note FROM supplies WHERE owner_id = ? ORDER BY name COLLATE NOCASE", (owner,))]


def _check_supply(body: SupplyIn):
    body.name = (body.name or "").strip()[:80]
    if not body.name:
        raise HTTPException(status_code=400, detail="What is it?")
    if not (0 <= body.have <= 100000 and 0 <= body.low_at <= 100000):
        raise HTTPException(status_code=400, detail="Counts are 0 or more")


@router.get("/api/supplies")
def list_supplies(request: Request):
    db = _get_db()
    try:
        rows = _supplies(db, _owner(request))
        return {"supplies": rows, "starters": [] if rows else STARTER_SUPPLIES}
    finally:
        db.close()


@router.post("/api/supplies", status_code=201)
def add_supply(body: SupplyIn, request: Request):
    _check_supply(body)
    db = _get_db()
    try:
        db.execute("INSERT INTO supplies (owner_id, name, have, low_at, note, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (_owner(request), body.name, body.have, body.low_at, (body.note or "").strip()[:200] or None, _now()))
        db.commit()
        return _supplies(db, _owner(request))
    finally:
        db.close()


@router.put("/api/supplies/{supply_id}")
def edit_supply(supply_id: int, body: SupplyIn, request: Request):
    _check_supply(body)
    db = _get_db()
    try:
        cur = db.execute("UPDATE supplies SET name = ?, have = ?, low_at = ?, note = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                         (body.name, body.have, body.low_at, (body.note or "").strip()[:200] or None, _now(), supply_id, _owner(request)))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Not found")
        db.commit()
        return _supplies(db, _owner(request))
    finally:
        db.close()


class Change(BaseModel):
    by: int        # +1 bought one, -1 used one


@router.post("/api/supplies/{supply_id}/change")
def change_supply(supply_id: int, body: Change, request: Request):
    db = _get_db()
    try:
        cur = db.execute("UPDATE supplies SET have = MAX(0, have + ?), updated_at = ? WHERE id = ? AND owner_id = ?",
                         (body.by, _now(), supply_id, _owner(request)))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Not found")
        db.commit()
        return _supplies(db, _owner(request))
    finally:
        db.close()


@router.delete("/api/supplies/{supply_id}", status_code=204)
def delete_supply(supply_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM supplies WHERE id = ? AND owner_id = ?", (supply_id, _owner(request)))
        db.commit()
    finally:
        db.close()


# ==================== INCIDENT LOG ====================

class IncidentIn(BaseModel):
    happened_on: date
    title: str
    what: Optional[str] = None
    who: Optional[str] = None
    evidence: Optional[str] = None      # what you kept and where: screenshots, messages, a plate number


def _clean(text: Optional[str], limit: int) -> Optional[str]:
    return (text or "").strip()[:limit] or None


def _incidents(db, owner: int) -> List[dict]:
    return [dict(r) for r in db.execute(
        "SELECT id, happened_on, title, what, who, evidence, created_at, updated_at FROM incidents WHERE owner_id = ? "
        "ORDER BY happened_on DESC, id DESC", (owner,))]


@router.get("/api/incidents")
def list_incidents(request: Request):
    db = _get_db()
    try:
        return _incidents(db, _owner(request))
    finally:
        db.close()


@router.post("/api/incidents", status_code=201)
def add_incident(body: IncidentIn, request: Request):
    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="A few words for what happened")
    db = _get_db()
    try:
        db.execute("INSERT INTO incidents (owner_id, happened_on, title, what, who, evidence, created_at, updated_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (_owner(request), body.happened_on.isoformat(), body.title.strip()[:120], _clean(body.what, 8000),
                    _clean(body.who, 500), _clean(body.evidence, 2000), _now(), _now()))
        db.commit()
        return _incidents(db, _owner(request))
    finally:
        db.close()


@router.put("/api/incidents/{incident_id}")
def edit_incident(incident_id: int, body: IncidentIn, request: Request):
    if not (body.title or "").strip():
        raise HTTPException(status_code=400, detail="A few words for what happened")
    db = _get_db()
    try:
        cur = db.execute("UPDATE incidents SET happened_on = ?, title = ?, what = ?, who = ?, evidence = ?, updated_at = ? "
                         "WHERE id = ? AND owner_id = ?",
                         (body.happened_on.isoformat(), body.title.strip()[:120], _clean(body.what, 8000), _clean(body.who, 500),
                          _clean(body.evidence, 2000), _now(), incident_id, _owner(request)))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Not found")
        db.commit()
        return _incidents(db, _owner(request))
    finally:
        db.close()


@router.delete("/api/incidents/{incident_id}", status_code=204)
def delete_incident(incident_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM incidents WHERE id = ? AND owner_id = ?", (incident_id, _owner(request)))
        db.commit()
    finally:
        db.close()


# ==================== PRIVACY CHECK-UP ====================

class Tick(BaseModel):
    id: str
    done: bool


def _ticks(db, owner: int) -> dict:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = 'privacy_checkup'", (owner,)).fetchone()
    try:
        return json.loads(r["value"]) if r and r["value"] else {}
    except ValueError:
        return {}


@router.get("/api/privacy-checkup")
def checkup(request: Request):
    db = _get_db()
    try:
        ticks = _ticks(db, _owner(request))
        items = [{"id": i, "title": t, "how": h, "done_on": ticks.get(i)} for i, t, h in CHECKUP]
        return {"items": items, "done": sum(1 for x in items if x["done_on"]), "total": len(items)}
    finally:
        db.close()


@router.post("/api/privacy-checkup")
def tick(body: Tick, request: Request):
    if body.id not in {i for i, _, _ in CHECKUP}:
        raise HTTPException(status_code=400, detail="Unknown item")
    owner = _owner(request)
    db = _get_db()
    try:
        ticks = _ticks(db, owner)
        if body.done:
            ticks[body.id] = date.today().isoformat()
        else:
            ticks.pop(body.id, None)
        db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, 'privacy_checkup', ?) "
                   "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, json.dumps(ticks)))
        db.commit()
    finally:
        db.close()
    return checkup(request)
