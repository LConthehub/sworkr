"""
Bad-date list: people to warn about or refuse. Entries come from local warning lists (uploaded as CSV, each
list with its own name, which can be replaced by uploading a newer copy) or are added by hand.

A contact or a booking is checked against it by phone number (digits only, so "+1 (555) 123-4567" matches
"5551234567"), email and social media handle (ignoring case and "@"). Names alone never match: too many
people share them. A match is a warning shown on the contact and before booking; nothing is blocked silently.
"""

import csv
import io
import json
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/blocklist")
_get_db: Optional[Callable] = None
MAX_UPLOAD = 2_000_000
MAX_ROWS = 20_000
FIELDS = ["phone", "email", "handle", "name", "description", "area", "reported_on", "severity"]
# Column headings that usually mean each field, for guessing the mapping of an uploaded list.
GUESSES = {
    "phone": ["phone", "number", "mobile", "cell", "tel", "telephone", "phone number"],
    "email": ["email", "e-mail", "mail", "email address"],
    "handle": ["handle", "username", "user", "screen name", "instagram", "twitter", "social", "account", "@"],
    "name": ["name", "alias", "aka", "names", "client"],
    "description": ["description", "details", "what happened", "notes", "note", "report", "warning", "comments"],
    "area": ["area", "city", "location", "region", "where", "state"],
    "reported_on": ["date", "reported", "reported on", "when", "date reported"],
    "severity": ["severity", "level", "type", "status"],
}


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text) -> Optional[str]:
    text = str(text or "").strip()
    return text or None


def phone_key(phone: Optional[str]) -> Optional[str]:
    """Digits only, and at most the last 10, so a country code doesn't stop a match."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 7 else None


def handle_key(handle: Optional[str]) -> Optional[str]:
    h = (handle or "").strip().lower().lstrip("@")
    h = re.sub(r"^https?://(www\.)?[^/]+/", "", h).strip("/")   # a profile link: just the name
    return h or None


def email_key(email: Optional[str]) -> Optional[str]:
    e = (email or "").strip().lower()
    return e if "@" in e else None


class Severity(str, Enum):
    WARN = "warn"
    BLOCK = "block"


class EntryIn(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None
    handle: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    area: Optional[str] = None
    reported_on: Optional[date] = None
    severity: Severity = Severity.WARN
    list_name: Optional[str] = None      # which list it came from; "Added by me" when left empty


class ImportIn(BaseModel):
    csv: str
    list_name: str
    mapping: Dict[str, Optional[str]]    # field -> column heading
    replace: bool = True                 # drop this list's old entries first (a newer copy of the same list)


def _entry_values(e: EntryIn) -> tuple:
    return (_clean(e.phone), phone_key(e.phone), email_key(e.email), handle_key(e.handle), _clean(e.name),
            _clean(e.description), _clean(e.area), e.reported_on.isoformat() if e.reported_on else None,
            e.severity.value, _clean(e.list_name) or "Added by me")


def _no_demo():
    import demo
    if demo.ENABLED:
        raise HTTPException(status_code=403, detail="The bad-date list is turned off in the demo: everyone shares its "
                            "login, so never put real people's details here")


def _check_entry(e: EntryIn):
    _no_demo()
    if not (phone_key(e.phone) or email_key(e.email) or handle_key(e.handle)):
        raise HTTPException(status_code=400, detail="Give a phone number, email or handle: a name alone can't be matched")
    for field in ("description", "name", "area", "list_name"):
        if len(getattr(e, field) or "") > 2000:
            raise HTTPException(status_code=400, detail=f"The {field.replace('_', ' ')} is too long")


def _insert(db, owner_id: int, e: EntryIn) -> int:
    now = _now()
    cur = db.execute("""
        INSERT INTO blocklist (owner_id, phone, phone_key, email, handle, name, description, area, reported_on,
                               severity, list_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (owner_id, *_entry_values(e), now, now))
    return cur.lastrowid


def matches(db, owner_id: int, phones=(), emails=(), handles=()) -> List[dict]:
    """Entries matching any of these phone numbers, emails or handles."""
    keys = {
        "phone_key": {k for k in map(phone_key, phones) if k},
        "email": {k for k in map(email_key, emails) if k},
        "handle": {k for k in map(handle_key, handles) if k},
    }
    found = {}
    for column, values in keys.items():
        if not values:
            continue
        marks = ",".join("?" * len(values))
        for r in db.execute(f"SELECT * FROM blocklist WHERE owner_id = ? AND {column} IN ({marks})", (owner_id, *values)):
            found[r["id"]] = {**dict(r), "matched_on": column.replace("_key", "")}
    return sorted(found.values(), key=lambda r: (r["severity"] != "block", r["id"]))


def matches_for_client(db, owner_id: int, client: dict) -> List[dict]:
    handles = [h.get("handle") if isinstance(h, dict) else h for h in (client.get("handles") or [])]
    return matches(db, owner_id, [client.get("contact_phone")], [client.get("email")], handles)


def warning_text(who: str, found: List[dict]) -> str:
    first = found[0]
    what = "is BLOCKED on" if first["severity"] == "block" else "matches"
    detail = f": {first['description']}" if first.get("description") else ""
    more = f" (and {len(found) - 1} more)" if len(found) > 1 else ""
    return f"{who} {what} your bad-date list ({first['list_name']}, by {first['matched_on']}){detail}{more}"


# ==================== API ====================

@router.get("")
def list_entries(request: Request, q: Optional[str] = None, list_name: Optional[str] = None,
                 limit: int = Query(100, ge=1, le=500)):
    """Entries (newest first), optionally searched, plus each list's name and size."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        conditions, params = ["owner_id = ?"], [owner]
        if list_name:
            conditions.append("list_name = ?")
            params.append(list_name)
        if q and q.strip():
            like = f"%{q.strip().lower()}%"
            conditions.append("(LOWER(COALESCE(name, '')) LIKE ? OR LOWER(COALESCE(description, '')) LIKE ? OR "
                              "COALESCE(email, '') LIKE ? OR COALESCE(handle, '') LIKE ? OR COALESCE(phone_key, '') LIKE ?)")
            digits = re.sub(r"\D", "", q)
            params += [like, like, like, like, f"%{digits}%" if digits else like]
        entries = [dict(r) for r in db.execute(
            f"SELECT * FROM blocklist WHERE {' AND '.join(conditions)} ORDER BY id DESC LIMIT ?", (*params, limit))]
        lists = [dict(r) for r in db.execute(
            "SELECT list_name, COUNT(*) AS entries, MAX(updated_at) AS updated_at FROM blocklist WHERE owner_id = ? "
            "GROUP BY list_name ORDER BY list_name COLLATE NOCASE", (owner,))]
        return {"entries": entries, "lists": lists}
    finally:
        db.close()


@router.post("", status_code=201)
def add_entry(body: EntryIn, request: Request):
    _check_entry(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        entry_id = _insert(db, owner, body)
        db.commit()
        return dict(db.execute("SELECT * FROM blocklist WHERE id = ?", (entry_id,)).fetchone())
    finally:
        db.close()


@router.put("/{entry_id}")
def update_entry(entry_id: int, body: EntryIn, request: Request):
    _check_entry(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        cur = db.execute("""
            UPDATE blocklist SET phone = ?, phone_key = ?, email = ?, handle = ?, name = ?, description = ?, area = ?,
                   reported_on = ?, severity = ?, list_name = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_entry_values(body), _now(), entry_id, owner))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="Not found")
        db.commit()
        return dict(db.execute("SELECT * FROM blocklist WHERE id = ?", (entry_id,)).fetchone())
    finally:
        db.close()


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM blocklist WHERE id = ? AND owner_id = ?", (entry_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


@router.delete("", status_code=204)
def delete_list(request: Request, list_name: str = Query(...)):
    """Remove a whole list."""
    db = _get_db()
    try:
        db.execute("DELETE FROM blocklist WHERE owner_id = ? AND list_name = ?", (request.state.user["id"], list_name))
        db.commit()
    finally:
        db.close()


def _read_csv(text: str) -> csv.DictReader:
    if len(text) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="That file is too big (2 MB at most)")
    text = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="The file is empty, or has no heading row")
    return reader


class PreviewIn(BaseModel):
    csv: str


@router.post("/preview")
def preview(body: PreviewIn):
    """The file's column headings, a guess at which is which, and its first few rows."""
    reader = _read_csv(body.csv)
    headings = [h for h in reader.fieldnames if h is not None]
    guess = {}
    for field, words in GUESSES.items():
        for h in headings:
            if h.strip().lower() in words and h not in guess.values():
                guess[field] = h
                break
    rows = []
    for i, row in enumerate(reader):
        if i >= 5:
            break
        rows.append({h: (row.get(h) or "")[:200] for h in headings})
    return {"headings": headings, "mapping": guess, "rows": rows}


def _severity(value: Optional[str]) -> Severity:
    v = (value or "").strip().lower()
    return Severity.BLOCK if v in ("block", "blocked", "banned", "ban", "dangerous", "danger", "violent", "high") else Severity.WARN


def _date(value: Optional[str]) -> Optional[date]:
    v = (value or "").strip()
    # Month first for an ambiguous 03/02: sworkr is in US dollars for now.
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%b %d %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


@router.post("/import")
def import_list(body: ImportIn, request: Request):
    """Add a list from a CSV file, using `mapping` to say which column is which. With replace, a newer copy of the
    same list (same name) replaces the old one instead of doubling it. Rows with no phone, email or handle are
    skipped (a name alone can't be matched)."""
    _no_demo()
    list_name = _clean(body.list_name)
    if not list_name or len(list_name) > 80:
        raise HTTPException(status_code=400, detail="Give the list a name, like where it came from")
    unknown = [f for f in body.mapping if f not in FIELDS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown field: {', '.join(unknown)}")
    if not any(body.mapping.get(f) for f in ("phone", "email", "handle")):
        raise HTTPException(status_code=400, detail="Choose the column with phone numbers, emails or handles")
    reader = _read_csv(body.csv)
    missing = [c for c in body.mapping.values() if c and c not in reader.fieldnames]
    if missing:
        raise HTTPException(status_code=400, detail=f"The file has no column called {missing[0]!r}")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        removed = 0
        if body.replace:
            removed = db.execute("DELETE FROM blocklist WHERE owner_id = ? AND list_name = ?", (owner, list_name)).rowcount
        added = skipped = 0
        for i, row in enumerate(reader):
            if i >= MAX_ROWS:
                raise HTTPException(status_code=413, detail=f"That list has more than {MAX_ROWS} rows")
            get = lambda f: (row.get(body.mapping[f]) or "").strip() if body.mapping.get(f) else None  # noqa: E731
            entry = EntryIn(phone=get("phone"), email=get("email"), handle=get("handle"), name=(get("name") or "")[:200],
                            description=(get("description") or "")[:2000], area=(get("area") or "")[:200],
                            reported_on=_date(get("reported_on")), severity=_severity(get("severity")), list_name=list_name)
            if not (phone_key(entry.phone) or email_key(entry.email) or handle_key(entry.handle)):
                skipped += 1
                continue
            _insert(db, owner, entry)
            added += 1
        db.commit()
        return {"added": added, "skipped": skipped, "replaced": removed}
    finally:
        db.close()


@router.get("/check")
def check(request: Request, phone: Optional[str] = None, email: Optional[str] = None,
          handle: List[str] = Query([]), client_id: Optional[int] = None):
    """Does this phone, email or handle (or this contact's) match the list?"""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        phones, emails, handles = [phone], [email], list(handle)
        if client_id is not None:
            c = db.execute("SELECT contact_phone, email, handles FROM clients WHERE id = ? AND owner_id = ?",
                           (client_id, owner)).fetchone()
            if not c:
                raise HTTPException(status_code=404, detail="Contact not found")
            phones.append(c["contact_phone"])
            emails.append(c["email"])
            try:
                handles += [h.get("handle") for h in json.loads(c["handles"] or "[]") if isinstance(h, dict)]
            except ValueError:
                pass
        return matches(db, owner, phones, emails, handles)
    finally:
        db.close()
