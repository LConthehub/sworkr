"""
Personas: the names you work under. Many people use a different name for each kind of work or each
platform, so a contact (who knows you by that name), a workplace or platform (an account under that name) and a
post can each say which persona it's for. Earnings can then be compared by persona.
"""

from datetime import datetime, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/personas")
_get_db: Optional[Callable] = None
TABLES = {"clients", "income_sources", "posts"}
COLORS = ["#db2777", "#7c3aed", "#0891b2", "#65a30d", "#d97706", "#4f46e5", "#059669", "#b45309"]


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PersonaIn(BaseModel):
    name: str
    color: Optional[str] = None
    notes: Optional[str] = None
    archived: bool = False


def check(db, owner_id: int, persona_id: Optional[int]) -> Optional[int]:
    """The persona id if it's this person's (or None); otherwise a 400."""
    if persona_id is None:
        return None
    if not db.execute("SELECT 1 FROM personas WHERE id = ? AND owner_id = ?", (persona_id, owner_id)).fetchone():
        raise HTTPException(status_code=400, detail="That persona doesn't exist")
    return persona_id


def assign(db, table: str, row_id: int, owner_id: int, body: BaseModel):
    """Save body.persona_id on a contact, place or post, but only if the request included it (so older apps
    and imports that don't know about personas leave it alone)."""
    assert table in TABLES
    if "persona_id" not in body.model_fields_set:
        return
    persona_id = check(db, owner_id, body.persona_id)
    db.execute(f"UPDATE {table} SET persona_id = ? WHERE id = ? AND owner_id = ?", (persona_id, row_id, owner_id))


def _rows(db, owner_id: int) -> List[dict]:
    return [{**dict(r), "archived": bool(r["archived"])} for r in db.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM clients c WHERE c.persona_id = p.id) AS contacts,
               (SELECT COUNT(*) FROM income_sources s WHERE s.persona_id = p.id) AS places,
               (SELECT COUNT(*) FROM posts x WHERE x.persona_id = p.id) AS posts
        FROM personas p WHERE p.owner_id = ? ORDER BY p.archived, p.name COLLATE NOCASE
    """, (owner_id,))]


def _validate(db, owner_id: int, body: PersonaIn, persona_id: Optional[int] = None) -> PersonaIn:
    body.name = (body.name or "").strip()
    if not body.name or len(body.name) > 60:
        raise HTTPException(status_code=400, detail="Give the persona a name (up to 60 characters)")
    if db.execute("SELECT 1 FROM personas WHERE owner_id = ? AND LOWER(name) = LOWER(?) AND id IS NOT ?",
                  (owner_id, body.name, persona_id)).fetchone():
        raise HTTPException(status_code=409, detail=f"You already have a persona called '{body.name}'")
    color = (body.color or "").strip()
    if color and not (len(color) == 7 and color[0] == "#" and all(ch in "0123456789abcdefABCDEF" for ch in color[1:])):
        raise HTTPException(status_code=400, detail="Colour must look like #a1b2c3")
    body.color = color or None
    body.notes = (body.notes or "").strip() or None
    return body


@router.get("")
def list_personas(request: Request):
    db = _get_db()
    try:
        return _rows(db, request.state.user["id"])
    finally:
        db.close()


@router.post("", status_code=201)
def create_persona(body: PersonaIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _validate(db, owner, body)
        count = db.execute("SELECT COUNT(*) FROM personas WHERE owner_id = ?", (owner,)).fetchone()[0]
        now = _now()
        cur = db.execute("INSERT INTO personas (owner_id, name, color, notes, archived, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (owner, body.name, body.color or COLORS[count % len(COLORS)], body.notes, int(body.archived), now, now))
        db.commit()
        return next(p for p in _rows(db, owner) if p["id"] == cur.lastrowid)
    finally:
        db.close()


@router.put("/{persona_id}")
def update_persona(persona_id: int, body: PersonaIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        check(db, owner, persona_id)
        _validate(db, owner, body, persona_id)
        db.execute("UPDATE personas SET name = ?, color = COALESCE(?, color), notes = ?, archived = ?, updated_at = ? "
                   "WHERE id = ? AND owner_id = ?",
                   (body.name, body.color, body.notes, int(body.archived), _now(), persona_id, owner))
        db.commit()
        return next(p for p in _rows(db, owner) if p["id"] == persona_id)
    except HTTPException as e:
        if e.status_code == 400 and e.detail == "That persona doesn't exist":
            raise HTTPException(status_code=404, detail="Persona not found")
        raise
    finally:
        db.close()


@router.delete("/{persona_id}", status_code=204)
def delete_persona(persona_id: int, request: Request):
    """Contacts, places and posts under it stay; they just have no persona."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        for table in sorted(TABLES):
            db.execute(f"UPDATE {table} SET persona_id = NULL WHERE persona_id = ? AND owner_id = ?", (persona_id, owner))
        db.execute("DELETE FROM personas WHERE id = ? AND owner_id = ?", (persona_id, owner))
        db.commit()
    finally:
        db.close()
