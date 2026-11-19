"""
A workplace's own rules, and the bins it stores for you.

Houses and agencies each have their own way of doing things. This keeps the ones that change how you plan:

- outdates: whether the house lets you see a client away from it, and its rules for that (the minimum, the
  house's share, signing out). When a house allows them, each client's profile gets an "outdates" answer.
- shifts: none, the same every day (5am to 5pm), or several to choose from (days, nights, swing). A stay at the
  place remembers which shift you're on, and booking outside it is warned about.
- the doctor's day: kept on the place's doctor charge, so tests on a stay land on it.
- storage: whether the house keeps a bin for you while you're away, and its rules (how long, the fee, the size).
- anything else worth remembering.

A guide lists what hasn't been answered yet for each house or agency, so a place gets set up once, properly.

Bins: what's in each one, where it's kept, and a label to print with a QR code. The code opens that bin in
sworkr and needs your login, so the label itself gives nothing away.
"""

import json
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter()
_get_db: Optional[Callable] = None

HOUSE_KINDS = ("brothel", "agency", "club", "studio")
GUIDED_KINDS = ("brothel", "agency")
PATTERNS = ("none", "fixed", "varied")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text: Optional[str], limit: int = 2000) -> Optional[str]:
    return (text or "").strip()[:limit] or None


def _time(text: Optional[str]) -> Optional[str]:
    """"05:00" or None. Anything else is refused."""
    if not text:
        return None
    try:
        hours, minutes = text.strip().split(":")[:2]
        if 0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59:
            return f"{int(hours):02d}:{int(minutes):02d}"
    except ValueError:
        pass
    raise HTTPException(status_code=400, detail="Times look like 05:00 or 17:30")


# ==================== RULES ====================

class ShiftIn(BaseModel):
    label: Optional[str] = None       # "Days", "Nights"
    start: str                        # "05:00"
    end: str                          # "17:00" (an end before the start runs past midnight)


class RulesIn(BaseModel):
    outdates_allowed: Optional[bool] = None       # None: not answered yet
    outdate_rules: Optional[str] = None
    shift_pattern: Optional[str] = None           # none, fixed, varied; None: not answered yet
    shifts: List[ShiftIn] = []
    storage_allowed: Optional[bool] = None
    storage_rules: Optional[str] = None
    other_rules: Optional[str] = None
    doctor_weekday: Optional[int] = None          # 0 Monday .. 6 Sunday; goes on the place's doctor charge
    no_doctor: bool = False                       # this place has no doctor's day


def _place(db, owner: int, source_id: int) -> dict:
    r = db.execute("SELECT id, name, kind FROM income_sources WHERE id = ? AND owner_id = ?", (source_id, owner)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="That workplace doesn't exist")
    return dict(r)


def shift_text(s: dict) -> str:
    def nice(t: str) -> str:
        h, m = int(t[:2]), t[3:]
        return f"{h % 12 or 12}{'' if m == '00' else ':' + m}{'am' if h < 12 else 'pm'}"
    span = f"{nice(s['start'])} to {nice(s['end'])}"
    return f"{s['label']} ({span})" if s.get("label") else span


def get_rules(db, owner: int, place: dict) -> dict:
    r = db.execute("SELECT * FROM place_rules WHERE source_id = ? AND owner_id = ?", (place["id"], owner)).fetchone()
    d = dict(r) if r else {}
    as_bool = lambda v: None if v is None else bool(v)  # noqa: E731
    doctor = db.execute("SELECT id, weekday FROM place_charges WHERE source_id = ? AND owner_id = ? AND test_type IS NOT NULL "
                        "ORDER BY id LIMIT 1", (place["id"], owner)).fetchone()
    shifts = json.loads(d.get("shifts") or "[]")
    for s in shifts:
        s["text"] = shift_text(s)
    out = {
        "source_id": place["id"], "name": place["name"], "kind": place["kind"],
        "outdates_allowed": as_bool(d.get("outdates_allowed")), "outdate_rules": d.get("outdate_rules"),
        "shift_pattern": d.get("shift_pattern"), "shifts": shifts,
        "storage_allowed": as_bool(d.get("storage_allowed")), "storage_rules": d.get("storage_rules"),
        "other_rules": d.get("other_rules"), "no_doctor": bool(d.get("no_doctor")),
        "has_doctor_charge": bool(doctor), "doctor_weekday": doctor["weekday"] if doctor else None,
    }
    # What the guide still asks about. A club or studio isn't asked about a doctor or outdates.
    todo = []
    if place["kind"] in GUIDED_KINDS:
        if out["doctor_weekday"] is None and not out["no_doctor"]:
            todo.append("the doctor's day")
        if out["outdates_allowed"] is None:
            todo.append("outdates")
    if place["kind"] in HOUSE_KINDS:
        if out["shift_pattern"] is None:
            todo.append("shifts")
        if out["storage_allowed"] is None:
            todo.append("storage")
    out["todo"] = todo
    return out


@router.get("/api/house-rules")
def list_rules(request: Request):
    """Every house, agency, club and studio with its rules, and what's still to answer for each."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        marks = ", ".join("?" * len(HOUSE_KINDS))
        places = [dict(r) for r in db.execute(
            f"SELECT id, name, kind FROM income_sources WHERE owner_id = ? AND archived = 0 AND kind IN ({marks}) ORDER BY name",
            (owner, *HOUSE_KINDS))]
        rules = [get_rules(db, owner, p) for p in places]
        return {"places": rules, "to_set_up": [r for r in rules if r["todo"] and r["kind"] in GUIDED_KINDS]}
    finally:
        db.close()


@router.get("/api/income-sources/{source_id}/rules")
def read_rules(source_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return get_rules(db, owner, _place(db, owner, source_id))
    finally:
        db.close()


@router.put("/api/income-sources/{source_id}/rules")
def save_rules(source_id: int, body: RulesIn, request: Request):
    if body.shift_pattern is not None and body.shift_pattern not in PATTERNS:
        raise HTTPException(status_code=400, detail="Shifts are none, fixed or varied")
    if body.doctor_weekday is not None and not 0 <= body.doctor_weekday <= 6:
        raise HTTPException(status_code=400, detail="Choose a day of the week")
    shifts = [{"label": _clean(s.label, 40), "start": _time(s.start), "end": _time(s.end)} for s in body.shifts[:8]]
    if any(not s["start"] or not s["end"] for s in shifts):
        raise HTTPException(status_code=400, detail="Each shift needs a start and an end")
    if body.shift_pattern in (None, "none"):
        shifts = []
    elif not shifts:
        raise HTTPException(status_code=400, detail="Add at least one shift")
    elif body.shift_pattern == "fixed":
        shifts = shifts[:1]
    owner = request.state.user["id"]
    db = _get_db()
    try:
        place = _place(db, owner, source_id)
        to_int = lambda v: None if v is None else int(v)  # noqa: E731
        db.execute("""
            INSERT INTO place_rules (source_id, owner_id, outdates_allowed, outdate_rules, shift_pattern, shifts, storage_allowed,
                                     storage_rules, other_rules, no_doctor, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET outdates_allowed = excluded.outdates_allowed, outdate_rules = excluded.outdate_rules,
                shift_pattern = excluded.shift_pattern, shifts = excluded.shifts, storage_allowed = excluded.storage_allowed,
                storage_rules = excluded.storage_rules, other_rules = excluded.other_rules, no_doctor = excluded.no_doctor,
                updated_at = excluded.updated_at
        """, (source_id, owner, to_int(body.outdates_allowed), _clean(body.outdate_rules), body.shift_pattern, json.dumps(shifts),
              to_int(body.storage_allowed), _clean(body.storage_rules), _clean(body.other_rules, 5000),
              int(body.no_doctor and body.doctor_weekday is None), _now()))
        if body.doctor_weekday is not None:
            doctor = db.execute("SELECT id FROM place_charges WHERE source_id = ? AND owner_id = ? AND test_type IS NOT NULL "
                                "ORDER BY id LIMIT 1", (source_id, owner)).fetchone()
            if doctor:
                db.execute("UPDATE place_charges SET weekday = ?, updated_at = ? WHERE id = ?", (body.doctor_weekday, _now(), doctor["id"]))
            else:
                # No doctor charge yet: add one with no price, to be filled in on the place itself.
                order = db.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM place_charges WHERE source_id = ?", (source_id,)).fetchone()[0]
                db.execute("INSERT INTO place_charges (owner_id, source_id, label, amount, cadence, category, test_type, weekday, "
                           "sort_order, created_at, updated_at) VALUES (?, ?, 'Doctor', NULL, 'per_week', 'medical', 'weekly', ?, ?, ?, ?)",
                           (owner, source_id, body.doctor_weekday, order, _now(), _now()))
        db.commit()
        return get_rules(db, owner, place)
    finally:
        db.close()


def outdates_possible(db, owner: int) -> bool:
    return bool(db.execute("SELECT 1 FROM place_rules WHERE owner_id = ? AND outdates_allowed = 1 LIMIT 1", (owner,)).fetchone())


# ==================== THE SHIFT ON A STAY ====================

class StayShiftIn(BaseModel):
    label: Optional[str] = None
    start: Optional[str] = None       # both empty: no shift on this stay
    end: Optional[str] = None


def _tour(db, owner: int, tour_id: int) -> dict:
    r = db.execute("SELECT id, source_id, shift_label, shift_start, shift_end FROM tours WHERE id = ? AND owner_id = ?",
                   (tour_id, owner)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Tour not found")
    return dict(r)


def _stay_shift(t: dict) -> Optional[dict]:
    if not t["shift_start"] or not t["shift_end"]:
        return None
    s = {"label": t["shift_label"], "start": t["shift_start"], "end": t["shift_end"]}
    return {**s, "text": shift_text(s)}


@router.get("/api/tours/{tour_id}/shift")
def read_stay_shift(tour_id: int, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return {"shift": _stay_shift(_tour(db, owner, tour_id))}
    finally:
        db.close()


@router.put("/api/tours/{tour_id}/shift")
def save_stay_shift(tour_id: int, body: StayShiftIn, request: Request):
    start, end = _time(body.start), _time(body.end)
    if bool(start) != bool(end):
        raise HTTPException(status_code=400, detail="A shift needs a start and an end")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _tour(db, owner, tour_id)
        db.execute("UPDATE tours SET shift_label = ?, shift_start = ?, shift_end = ? WHERE id = ?",
                   (_clean(body.label, 40) if start else None, start, end, tour_id))
        db.commit()
        return {"shift": _stay_shift(_tour(db, owner, tour_id))}
    finally:
        db.close()


def in_shift(clock: str, start: str, end: str) -> bool:
    """Whether a wall-clock time ("14:30") falls in a shift. A shift whose end is before its start runs past midnight."""
    if start == end:
        return True
    return start <= clock < end if start < end else clock >= start or clock < end


def shift_warnings(db, owner: int, start_utc: datetime, tz_offset: int) -> List[str]:
    """Booking a client outside the shift you're on at the place you're staying."""
    local = start_utc - timedelta(minutes=tz_offset or 0)
    day, clock = local.date().isoformat(), local.strftime("%H:%M")
    yesterday = (local.date() - timedelta(days=1)).isoformat()
    out = []
    # A night shift's small hours belong to the day before, so a stay counts from its first day to the morning after its last.
    for t in db.execute("""
        SELECT t.shift_label, t.shift_start, t.shift_end, t.start_date, t.end_date, s.name AS place
        FROM tours t JOIN income_sources s ON s.id = t.source_id
        WHERE t.owner_id = ? AND t.kind = 'tour' AND t.shift_start IS NOT NULL AND t.shift_end IS NOT NULL
          AND t.start_date <= ? AND t.end_date >= ?
    """, (owner, day, yesterday)):
        overnight = t["shift_start"] > t["shift_end"]
        if t["end_date"] < day and not (overnight and clock < t["shift_end"]):
            continue
        if not in_shift(clock, t["shift_start"], t["shift_end"]):
            text = shift_text({"label": t["shift_label"], "start": t["shift_start"], "end": t["shift_end"]})
            out.append(f"This is outside your shift at {t['place']}: {text}")
    return out


# ==================== BINS ====================

class BinItemIn(BaseModel):
    label: str
    quantity: int = 1


class BinIn(BaseModel):
    label: str                           # "Bin 2", "The blue tote"
    source_id: Optional[int] = None      # the place that's keeping it
    where_kept: Optional[str] = None     # "Storage room, top shelf"
    stored_on: Optional[date] = None     # the day you left it
    notes: Optional[str] = None
    items: List[BinItemIn] = []


def _bin(db, owner: int, where: str, value) -> dict:
    r = db.execute(f"""
        SELECT b.*, s.name AS place FROM storage_bins b LEFT JOIN income_sources s ON s.id = b.source_id
        WHERE b.{where} = ? AND b.owner_id = ?
    """, (value, owner)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Bin not found")
    d = dict(r)
    d["items"] = [dict(i) for i in db.execute("SELECT id, label, quantity FROM bin_items WHERE bin_id = ? ORDER BY sort_order, id", (d["id"],))]
    d["pieces"] = sum(i["quantity"] for i in d["items"])
    d["days_stored"] = (date.today() - date.fromisoformat(d["stored_on"])).days if d["stored_on"] else None
    rules = db.execute("SELECT storage_rules FROM place_rules WHERE source_id = ? AND owner_id = ?", (d["source_id"], owner)).fetchone() \
        if d["source_id"] else None
    d["storage_rules"] = rules["storage_rules"] if rules else None
    return d


def _save_items(db, bin_id: int, items: List[BinItemIn]):
    db.execute("DELETE FROM bin_items WHERE bin_id = ?", (bin_id,))
    order = 0
    for item in items[:300]:
        label = _clean(item.label, 200)
        if label:
            order += 1
            db.execute("INSERT INTO bin_items (bin_id, label, quantity, sort_order) VALUES (?, ?, ?, ?)",
                       (bin_id, label, max(1, min(int(item.quantity or 1), 9999)), order))


def _bin_values(db, owner: int, body: BinIn) -> tuple:
    label = _clean(body.label, 80)
    if not label:
        raise HTTPException(status_code=400, detail="Give the bin a name")
    if body.source_id is not None:
        _place(db, owner, body.source_id)
    return (label, body.source_id, _clean(body.where_kept, 200), body.stored_on.isoformat() if body.stored_on else None,
            _clean(body.notes))


@router.get("/api/bins")
def list_bins(request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        ids = [r["id"] for r in db.execute("SELECT id FROM storage_bins WHERE owner_id = ? ORDER BY label, id", (owner,))]
        return [_bin(db, owner, "id", i) for i in ids]
    finally:
        db.close()


@router.get("/api/bins/find")
def find_in_bins(request: Request, q: str = Query(..., min_length=1, max_length=100)):
    """Which bin is it in? Matches part of an item's name."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return [dict(r) for r in db.execute("""
            SELECT i.label AS item, i.quantity, b.id AS bin_id, b.label AS bin, s.name AS place, b.where_kept
            FROM bin_items i JOIN storage_bins b ON b.id = i.bin_id LEFT JOIN income_sources s ON s.id = b.source_id
            WHERE b.owner_id = ? AND LOWER(i.label) LIKE ? ORDER BY i.label LIMIT 100
        """, (owner, f"%{q.strip().lower()}%"))]
    finally:
        db.close()


@router.get("/api/bins/code/{code}")
def bin_by_code(code: str, request: Request):
    """What a scanned label opens. Only for the person the bin belongs to."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return _bin(db, owner, "code", code)
    finally:
        db.close()


@router.post("/api/bins", status_code=201)
def add_bin(body: BinIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        cur = db.execute("INSERT INTO storage_bins (label, source_id, where_kept, stored_on, notes, owner_id, code, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (*_bin_values(db, owner, body), owner, secrets.token_urlsafe(9), _now(), _now()))
        _save_items(db, cur.lastrowid, body.items)
        db.commit()
        return _bin(db, owner, "id", cur.lastrowid)
    finally:
        db.close()


@router.put("/api/bins/{bin_id}")
def update_bin(bin_id: int, body: BinIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _bin(db, owner, "id", bin_id)
        db.execute("UPDATE storage_bins SET label = ?, source_id = ?, where_kept = ?, stored_on = ?, notes = ?, updated_at = ? WHERE id = ?",
                   (*_bin_values(db, owner, body), _now(), bin_id))
        _save_items(db, bin_id, body.items)
        db.commit()
        return _bin(db, owner, "id", bin_id)
    finally:
        db.close()


@router.delete("/api/bins/{bin_id}", status_code=204)
def delete_bin(bin_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM storage_bins WHERE id = ? AND owner_id = ?", (bin_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


@router.get("/api/bins/{bin_id}/label")
def bin_label(bin_id: int, request: Request, origin: str = Query(..., max_length=200)):
    """A QR code for the bin's label. `origin` is the address sworkr is open at (https://my.address), so the code
    opens the bin from that address. The code holds only the link: no names and no list."""
    if not origin.startswith(("http://", "https://")) or any(c in origin for c in " \"'<>"):
        raise HTTPException(status_code=400, detail="That address doesn't look right")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        b = _bin(db, owner, "id", bin_id)
    finally:
        db.close()
    url = f"{origin.rstrip('/')}/bins/{b['code']}"
    import segno
    return {"url": url, "qr": segno.make(url, error="m").svg_data_uri(scale=6, border=2), "label": b["label"]}
