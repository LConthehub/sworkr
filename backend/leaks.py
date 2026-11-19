"""
Stolen content: where it turned up, and how getting it taken down is going.

Each entry is one place your content was found without your say: the site, the link, what it is, and where the
original lives. It moves from found, to notice sent, to removed (or refused). A notice that has had no answer
for ten days is marked to chase.

sworkr writes the takedown notice for you to copy and send yourself: it never contacts anyone. The notice is
signed with whatever name you choose in the settings here. A takedown notice normally needs a real name or an
agent's; someone you trust, or a takedown service, can send it for you so your own name stays off it.
"""

from datetime import date, datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/leaks")
_get_db: Optional[Callable] = None

STATUSES = ("found", "sent", "removed", "refused")
CHASE_DAYS = 10


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(text: Optional[str], limit: int = 2000) -> Optional[str]:
    return (text or "").strip()[:limit] or None


class LeakIn(BaseModel):
    found_on: date
    site: str                             # the site or account it's on
    url: Optional[str] = None             # the exact link
    what: Optional[str] = None            # which set, clip or picture
    original_url: Optional[str] = None    # where the real one is sold or posted
    status: str = "found"
    sent_on: Optional[date] = None
    sent_to: Optional[str] = None         # the address or form the notice went to
    removed_on: Optional[date] = None
    notes: Optional[str] = None


class StatusIn(BaseModel):
    status: str
    on: Optional[date] = None
    sent_to: Optional[str] = None


class SettingsIn(BaseModel):
    sign_as: Optional[str] = None         # the name the notice is signed with
    contact: Optional[str] = None         # an email address for the reply


def _row(r, today: date) -> dict:
    d = dict(r)
    waiting = (today - date.fromisoformat(d["sent_on"])).days if d["status"] == "sent" and d["sent_on"] else None
    d["days_waiting"] = waiting
    d["chase"] = waiting is not None and waiting >= CHASE_DAYS
    return d


def _need(db, leak_id: int, owner: int) -> dict:
    r = db.execute("SELECT * FROM leaks WHERE id = ? AND owner_id = ?", (leak_id, owner)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Not found")
    return _row(r, date.today())


def _values(body: LeakIn) -> tuple:
    site = _clean(body.site, 200)
    if not site:
        raise HTTPException(status_code=400, detail="Say where you found it")
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")
    return (body.found_on.isoformat(), site, _clean(body.url), _clean(body.what, 500), _clean(body.original_url), body.status,
            body.sent_on.isoformat() if body.sent_on else None, _clean(body.sent_to, 300),
            body.removed_on.isoformat() if body.removed_on else None, _clean(body.notes, 5000))


def _settings(db, owner: int) -> dict:
    rows = {r["key"]: r["value"] for r in db.execute(
        "SELECT key, value FROM user_settings WHERE user_id = ? AND key IN ('leak_sign_as', 'leak_contact')", (owner,))}
    return {"sign_as": rows.get("leak_sign_as") or "", "contact": rows.get("leak_contact") or ""}


@router.get("")
def list_leaks(request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        today = date.today()
        rows = [_row(r, today) for r in db.execute(
            "SELECT * FROM leaks WHERE owner_id = ? ORDER BY CASE status WHEN 'found' THEN 0 WHEN 'sent' THEN 1 ELSE 2 END, "
            "found_on DESC, id DESC", (owner,))]
        return {"leaks": rows, "settings": _settings(db, owner), "chase_days": CHASE_DAYS,
                "counts": {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES},
                "to_chase": sum(1 for r in rows if r["chase"])}
    finally:
        db.close()


@router.put("/settings")
def save_settings(body: SettingsIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        for key, value in (("leak_sign_as", _clean(body.sign_as, 120)), ("leak_contact", _clean(body.contact, 200))):
            db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
                       "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, key, value))
        db.commit()
        return _settings(db, owner)
    finally:
        db.close()


@router.post("", status_code=201)
def add_leak(body: LeakIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        cur = db.execute("INSERT INTO leaks (found_on, site, url, what, original_url, status, sent_on, sent_to, removed_on, notes, "
                         "owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (*_values(body), owner, _now(), _now()))
        db.commit()
        return _need(db, cur.lastrowid, owner)
    finally:
        db.close()


@router.put("/{leak_id}")
def update_leak(leak_id: int, body: LeakIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _need(db, leak_id, owner)
        db.execute("UPDATE leaks SET found_on = ?, site = ?, url = ?, what = ?, original_url = ?, status = ?, sent_on = ?, sent_to = ?, "
                   "removed_on = ?, notes = ?, updated_at = ? WHERE id = ?", (*_values(body), _now(), leak_id))
        db.commit()
        return _need(db, leak_id, owner)
    finally:
        db.close()


@router.post("/{leak_id}/status")
def move_leak(leak_id: int, body: StatusIn, request: Request):
    """One tap: the notice went out, it came down, or they said no. A removed one that comes back goes to found again."""
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        leak = _need(db, leak_id, owner)
        on = (body.on or date.today()).isoformat()
        sent_on, removed_on, sent_to = leak["sent_on"], leak["removed_on"], leak["sent_to"]
        if body.status == "sent":
            sent_on, removed_on, sent_to = on, None, _clean(body.sent_to, 300) or sent_to
        elif body.status == "removed":
            removed_on = on
        elif body.status == "found":
            sent_on, removed_on = None, None
        db.execute("UPDATE leaks SET status = ?, sent_on = ?, removed_on = ?, sent_to = ?, updated_at = ? WHERE id = ?",
                   (body.status, sent_on, removed_on, sent_to, _now(), leak_id))
        db.commit()
        return _need(db, leak_id, owner)
    finally:
        db.close()


@router.delete("/{leak_id}", status_code=204)
def delete_leak(leak_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM leaks WHERE id = ? AND owner_id = ?", (leak_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()


def notice_text(leak: dict, settings: dict) -> dict:
    name = settings["sign_as"] or "[your name, or your agent's]"
    contact = settings["contact"] or "[an email address for the reply]"
    lines = [
        "To whom it may concern,",
        "",
        "I am the copyright owner of the material described below, or I am authorised to act for the owner. "
        "It has been posted on your service without permission.",
        "",
        f"The work: {leak['what'] or 'my photos and videos'}.",
    ]
    if leak["original_url"]:
        lines.append(f"Where the original is published: {leak['original_url']}")
    lines += [
        f"Where the copy is: {leak['url'] or leak['site']}",
        "",
        "I have a good faith belief that this use of the material is not authorised by the copyright owner, its agent, or the law.",
        "",
        "The information in this notice is accurate, and under penalty of perjury, I am the owner of the exclusive "
        "right that is being infringed, or authorised to act for the owner.",
        "",
        "Please remove the material or disable access to it, and confirm when that is done.",
        "",
        f"Signed: {name}",
        f"Contact: {contact}",
        f"Date: {date.today().isoformat()}",
    ]
    missing = [label for label, value in (("the name to sign with", settings["sign_as"]), ("a contact address", settings["contact"]),
                                          ("the exact link", leak["url"])) if not value]
    return {"subject": f"Copyright takedown notice: {leak['site']}", "body": "\n".join(lines), "missing": missing}


@router.get("/{leak_id}/notice")
def notice(leak_id: int, request: Request):
    """The takedown notice as text, to copy and send yourself."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return notice_text(_need(db, leak_id, owner), _settings(db, owner))
    finally:
        db.close()
