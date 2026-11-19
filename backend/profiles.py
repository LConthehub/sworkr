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
    outdates: Optional[str] = None        # yes or no: whether they see you away from the house; empty: not asked
    outdate_notes: Optional[str] = None   # where they like to go, what they book


EMPTY = {"languages": None, "translator": False, "culture": None, "talk_about": None, "avoid": None,
         "deceased": False, "deceased_on": None, "outdates": None, "outdate_notes": None}


def _clean(text: Optional[str]) -> Optional[str]:
    return (text or "").strip()[:TEXT_LIMIT] or None


def _client(db, owner: int, client_id: int):
    r = db.execute("SELECT id FROM clients WHERE id = ? AND owner_id = ?", (client_id, owner)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Contact not found")


def get_profile(db, owner: int, client_id: int) -> dict:
    r = db.execute("SELECT * FROM client_profiles WHERE client_id = ? AND owner_id = ?", (client_id, owner)).fetchone()
    import house
    # The outdates answer only shows when one of your houses allows them.
    possible = house.outdates_possible(db, owner)
    if not r:
        return {**EMPTY, "outdates_possible": possible}
    d = dict(r)
    return {**{k: (bool(d[k]) if k in ("translator", "deceased") else d[k]) for k in EMPTY}, "outdates_possible": possible}


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
                                         deceased, deceased_on, outdates, outdate_notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET languages = excluded.languages, translator = excluded.translator,
                culture = excluded.culture, talk_about = excluded.talk_about, avoid = excluded.avoid,
                deceased = excluded.deceased, deceased_on = excluded.deceased_on, outdates = excluded.outdates,
                outdate_notes = excluded.outdate_notes, updated_at = excluded.updated_at
        """, (client_id, owner, _clean(body.languages), int(body.translator), _clean(body.culture),
              _clean(body.talk_about), _clean(body.avoid), int(body.deceased),
              body.deceased_on.isoformat() if body.deceased and body.deceased_on else None,
              body.outdates if body.outdates in ("yes", "no") else None, _clean(body.outdate_notes),
              datetime.now(timezone.utc).isoformat(timespec="seconds")))
        if body.deceased:
            db.execute("UPDATE clients SET is_active = 0 WHERE id = ? AND owner_id = ?", (client_id, owner))
        db.commit()
        return get_profile(db, owner, client_id)
    finally:
        db.close()


# ==================== AFTER A BOOKING ====================

RATINGS = ("great", "fine", "bad")
AGAIN = ("yes", "maybe", "no")


class ReviewIn(BaseModel):
    rating: Optional[str] = None          # great, fine, bad
    again: Optional[str] = None           # would see them again: yes, maybe, no
    talked_about: Optional[str] = None
    notes: Optional[str] = None


def _review_row(r) -> dict:
    d = dict(r)
    d.pop("owner_id", None)
    return d


@router.get("/api/appointments/{appointment_id}/review")
def read_review(appointment_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        r = db.execute("SELECT * FROM booking_reviews WHERE appointment_id = ? AND owner_id = ?", (appointment_id, owner)).fetchone()
        return _review_row(r) if r else None
    finally:
        db.close()


@router.put("/api/appointments/{appointment_id}/review")
def save_review(appointment_id: int, body: ReviewIn, request: Request):
    """A few quick answers about how a booking went, kept with the client."""
    if body.rating is not None and body.rating not in RATINGS:
        raise HTTPException(status_code=400, detail="Great, fine or not good")
    if body.again is not None and body.again not in AGAIN:
        raise HTTPException(status_code=400, detail="Yes, maybe or no")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        a = db.execute("SELECT client_id FROM appointments WHERE id = ? AND owner_id = ? AND kind = 'client'",
                       (appointment_id, owner)).fetchone()
        if not a:
            raise HTTPException(status_code=404, detail="Booking not found")
        db.execute("""
            INSERT INTO booking_reviews (appointment_id, owner_id, client_id, rating, again, talked_about, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(appointment_id) DO UPDATE SET rating = excluded.rating, again = excluded.again,
                talked_about = excluded.talked_about, notes = excluded.notes
        """, (appointment_id, owner, a["client_id"], body.rating, body.again, _clean(body.talked_about), _clean(body.notes),
              datetime.now(timezone.utc).isoformat(timespec="seconds")))
        db.commit()
        return _review_row(db.execute("SELECT * FROM booking_reviews WHERE appointment_id = ?", (appointment_id,)).fetchone())
    finally:
        db.close()


@router.get("/api/clients/{client_id}/reviews")
def client_reviews(client_id: int, request: Request):
    """How bookings with this person have gone, newest first, with a count of each answer."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _client(db, owner, client_id)
        rows = [_review_row(r) for r in db.execute("""
            SELECT r.*, a.scheduled_date FROM booking_reviews r JOIN appointments a ON a.id = r.appointment_id
            WHERE r.owner_id = ? AND r.client_id = ? ORDER BY a.scheduled_date DESC LIMIT 50
        """, (owner, client_id))]
        return {"reviews": rows,
                "ratings": {k: sum(1 for r in rows if r["rating"] == k) for k in RATINGS},
                "again": {k: sum(1 for r in rows if r["again"] == k) for k in AGAIN}}
    finally:
        db.close()


# ==================== CLIENT BASE ====================

def _bucket(counts: dict, key: str):
    counts[key] = counts.get(key, 0) + 1


def _top(counts: dict, n: int = 8) -> list:
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top, rest = items[:n], sum(v for _, v in items[n:])
    return [{"label": k, "count": v} for k, v in top] + ([{"label": "Others", "count": rest}] if rest else [])


def _ordered(counts: dict, order: list) -> list:
    return [{"label": k, "count": counts.get(k, 0)} for k in order if counts.get(k)]


AGES = ["Under 25", "25–34", "35–44", "45–54", "55–64", "65 and over", "Not known"]
BOOKINGS = ["Never booked", "Once", "2–4 times", "5–9 times", "10 or more"]
SPEND = ["Nothing yet", "Under $500", "$500–$2,000", "$2,000–$5,000", "$5,000 and over"]


@router.get("/api/client-base")
def demographics(request: Request):
    """Who the client base is, from what's in the profiles: counts only, nothing leaves sworkr."""
    owner = request.state.user["id"]
    today = date.today()
    db = _get_db()
    try:
        rows = db.execute("""
            SELECT c.id, c.birthday, c.found_via, c.industry, p.languages,
                   (SELECT COUNT(*) FROM appointments a WHERE a.client_id = c.id AND a.kind = 'client'
                      AND (a.status = 'completed' OR (a.status != 'cancelled' AND a.amount_paid > 0))) AS bookings,
                   (SELECT COALESCE(SUM(a.amount_paid), 0) FROM appointments a WHERE a.client_id = c.id AND a.kind = 'client') AS spent,
                   (SELECT r.again FROM booking_reviews r JOIN appointments a ON a.id = r.appointment_id
                      WHERE r.client_id = c.id AND r.again IS NOT NULL ORDER BY a.scheduled_date DESC LIMIT 1) AS again
            FROM clients c LEFT JOIN client_profiles p ON p.client_id = c.id
            WHERE c.owner_id = ? AND c.role = 'client' AND COALESCE(p.deceased, 0) = 0
        """, (owner,)).fetchall()
        age, found, work, langs, booked, spend, again = {}, {}, {}, {}, {}, {}, {}
        for r in rows:
            if r["birthday"]:
                b = date.fromisoformat(r["birthday"][:10])
                years = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
                _bucket(age, AGES[0] if years < 25 else AGES[1] if years < 35 else AGES[2] if years < 45
                        else AGES[3] if years < 55 else AGES[4] if years < 65 else AGES[5])
            else:
                _bucket(age, AGES[6])
            _bucket(found, (r["found_via"] or "Not noted").strip())
            _bucket(work, (r["industry"] or "Not noted").strip())
            for lang in [x.strip() for x in (r["languages"] or "").split(",") if x.strip()]:
                _bucket(langs, lang[:1].upper() + lang[1:])
            n = r["bookings"]
            _bucket(booked, BOOKINGS[0] if n == 0 else BOOKINGS[1] if n == 1 else BOOKINGS[2] if n < 5 else BOOKINGS[3] if n < 10 else BOOKINGS[4])
            s = r["spent"] or 0
            _bucket(spend, SPEND[0] if s <= 0 else SPEND[1] if s < 500 else SPEND[2] if s < 2000 else SPEND[3] if s < 5000 else SPEND[4])
            if r["again"]:
                _bucket(again, {"yes": "Yes", "maybe": "Maybe", "no": "No"}[r["again"]])
        return {"clients": len(rows), "groups": [
            {"title": "Age", "bars": _ordered(age, AGES)},
            {"title": "How they found you", "bars": _top(found)},
            {"title": "Line of work", "bars": _top(work)},
            {"title": "Languages", "bars": _top(langs)},
            {"title": "How often they've booked", "bars": _ordered(booked, BOOKINGS)},
            {"title": "What they've spent in all", "bars": _ordered(spend, SPEND)},
            {"title": "Would see again (last answer)", "bars": _ordered(again, ["Yes", "Maybe", "No"])},
        ]}
    finally:
        db.close()
