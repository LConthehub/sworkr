"""
Getting to know a client: the things worth remembering about a person beyond bookings and money.

Languages they speak and whether a translator is needed, cultural practices to respect, topics to talk about
and topics to avoid. A client can be marked deceased: they're then made inactive, so they drop out of Ghosts
and birthday reminders, but their history stays.

Kept in its own table (one row per client), so the profile can grow without touching the main client record.
"""

from datetime import date, datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
_get_db: Optional[Callable] = None
TEXT_LIMIT = 4000


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


class ProfileIn(BaseModel):
    languages: Optional[str] = None       # "Spanish, some English"
    translator: bool = False              # a translator is needed
    culture: Optional[str] = None         # practices to remember and respect
    talk_about: Optional[str] = None
    avoid: Optional[str] = None           # topics to stay away from
    deceased: bool = False
    deceased_on: Optional[date] = None


EMPTY = {"languages": None, "translator": False, "culture": None, "talk_about": None, "avoid": None,
         "deceased": False, "deceased_on": None}


def _clean(text: Optional[str]) -> Optional[str]:
    return (text or "").strip()[:TEXT_LIMIT] or None


def _client(db, owner: int, client_id: int):
    r = db.execute("SELECT id FROM clients WHERE id = ? AND owner_id = ?", (client_id, owner)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Contact not found")


def get_profile(db, owner: int, client_id: int) -> dict:
    r = db.execute("SELECT * FROM client_profiles WHERE client_id = ? AND owner_id = ?", (client_id, owner)).fetchone()
    if not r:
        return dict(EMPTY)
    d = dict(r)
    return {k: (bool(d[k]) if k in ("translator", "deceased") else d[k]) for k in EMPTY}


@router.get("/api/clients/{client_id}/profile")
def read_profile(client_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _client(db, owner, client_id)
        return get_profile(db, owner, client_id)
    finally:
        db.close()


@router.put("/api/clients/{client_id}/profile")
def save_profile(client_id: int, body: ProfileIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _client(db, owner, client_id)
        db.execute("""
            INSERT INTO client_profiles (client_id, owner_id, languages, translator, culture, talk_about, avoid,
                                         deceased, deceased_on, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET languages = excluded.languages, translator = excluded.translator,
                culture = excluded.culture, talk_about = excluded.talk_about, avoid = excluded.avoid,
                deceased = excluded.deceased, deceased_on = excluded.deceased_on, updated_at = excluded.updated_at
        """, (client_id, owner, _clean(body.languages), int(body.translator), _clean(body.culture),
              _clean(body.talk_about), _clean(body.avoid), int(body.deceased),
              body.deceased_on.isoformat() if body.deceased and body.deceased_on else None,
              datetime.now(timezone.utc).isoformat(timespec="seconds")))
        if body.deceased:
            db.execute("UPDATE clients SET is_active = 0 WHERE id = ? AND owner_id = ?", (client_id, owner))
        db.commit()
        return get_profile(db, owner, client_id)
    finally:
        db.close()
