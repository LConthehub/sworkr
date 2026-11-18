"""
Your data, in your hands: take all of it with you, or wipe all of it.

- Download everything: one zip with a readable JSON file per kind of record (contacts, bookings, money,
  notes, tasks, settings...). Nothing is left out except secrets nobody should carry around in a file:
  saved passwords, sign-in tokens and the like.
- Erase everything: deletes every record that belongs to the person and overwrites the freed space in the
  database file. The login itself stays (with its passkeys and two-step sign-in), so the person can start
  again, or have an admin remove the login too. It asks for the password and a typed word first.

What erasing can't reach, and the page says so: backup files already written, the copies saved before an
upgrade or a restore, and calendar entries already sent to another server.

Which tables hold a person's records is read from the database itself (every table with an owner_id
column), so a table added later is covered without touching this file.
"""

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

import auth
import vault

router = APIRouter()
_get_db: Optional[Callable] = None

ERASE_WORD = "ERASE"

# Rows that hang off an owned row instead of carrying owner_id themselves: table -> (column, parent table).
CHILD_TABLES = {"client_tags": ("client_id", "clients"), "agreement_parties": ("agreement_id", "split_agreements"),
                "post_stats": ("post_id", "posts")}
# Columns holding saved passwords: left out of the download, like the password settings.
SECRET_COLUMNS = {"social_accounts": ("secret",)}

# Settings that are part of how the person signs in. Erasing data must not weaken or lock the login.
SIGN_IN_SETTINGS = ("two_step", "two_step_method", "two_step_address", "webauthn_handle", "totp_secret", "totp_last_step",
                    "passkey_only_remote", "signin_alerts", "idle_minutes")
# Never written to an export, on top of the sealed secrets.
PRIVATE_SETTINGS = frozenset(vault.SECRET_KEYS) | {"totp_last_step"}


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def owned_tables(db) -> List[str]:
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return [t for t in tables if any(c[1] == "owner_id" for c in db.execute(f"PRAGMA table_info({t})"))]


def _rows(db, sql: str, args: tuple) -> List[dict]:
    cur = db.execute(sql, args)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def collect(db, user_id: int) -> Dict[str, List[dict]]:
    """Everything that belongs to the person, by table."""
    data = {t: _rows(db, f"SELECT * FROM {t} WHERE owner_id = ?", (user_id,)) for t in owned_tables(db)}
    for table, (column, parent) in CHILD_TABLES.items():
        data[table] = _rows(db, f"SELECT * FROM {table} WHERE {column} IN (SELECT id FROM {parent} WHERE owner_id = ?)", (user_id,))
    for table, columns in SECRET_COLUMNS.items():
        for row in data.get(table, []):
            for c in columns:
                row.pop(c, None)
    data["settings"] = [r for r in _rows(db, "SELECT key, value FROM user_settings WHERE user_id = ? ORDER BY key", (user_id,))
                        if r["key"] not in PRIVATE_SETTINGS]
    data["sign_ins"] = _rows(db, "SELECT outcome, method, ip, user_agent, at FROM signin_events WHERE user_id = ? ORDER BY id", (user_id,))
    return data


def counts(db, user_id: int) -> Dict[str, int]:
    return {t: db.execute(f"SELECT COUNT(*) FROM {t} WHERE owner_id = ?", (user_id,)).fetchone()[0] for t in owned_tables(db)}


README = """Everything sworkr holds for {username}, exported {when}.

One file per kind of record, in JSON (opens in any text editor; most spreadsheet programs can import it).
Times are in UTC. Saved passwords and sign-in secrets are not included.

This file is not encrypted. It contains names, notes and money. Keep it somewhere safe, or delete it when
you're done with it.
"""


def export_zip(db, user: dict) -> bytes:
    when = datetime.now(timezone.utc).isoformat(timespec="seconds")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(username=user["username"], when=when))
        for name, rows in collect(db, user["id"]).items():
            z.writestr(f"{name}.json", json.dumps(rows, indent=1, ensure_ascii=False, default=str))
    return buf.getvalue()


def erase(db, user_id: int) -> int:
    """Delete every record the person owns. Returns how many rows went. The login and how it signs in stay."""
    db.execute("PRAGMA secure_delete = ON")   # freed pages are overwritten with zeros, not just marked free
    gone = 0
    for table in owned_tables(db):            # links between these tables cascade or are set to null
        gone += db.execute(f"DELETE FROM {table} WHERE owner_id = ?", (user_id,)).rowcount
    marks = ",".join("?" * len(SIGN_IN_SETTINGS))
    gone += db.execute(f"DELETE FROM user_settings WHERE user_id = ? AND key NOT IN ({marks})",
                       (user_id, *SIGN_IN_SETTINGS)).rowcount
    db.execute("DELETE FROM signin_events WHERE user_id = ?", (user_id,))
    db.commit()
    try:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")   # the write-ahead file would otherwise still hold the old pages
    except Exception:
        pass
    return gone


class EraseRequest(BaseModel):
    password: str
    confirm: str


@router.get("/api/account/data")
def data_summary(request: Request):
    """How much there is, for the page that offers the download and the erase."""
    db = _get_db()
    try:
        by_table = counts(db, request.state.user["id"])
        return {"records": sum(by_table.values()), "by_kind": {k: v for k, v in by_table.items() if v}, "erase_word": ERASE_WORD}
    finally:
        db.close()


@router.get("/api/account/data/export")
def download_everything(request: Request):
    user = request.state.user
    db = _get_db()
    try:
        blob = export_zip(db, user)
    finally:
        db.close()
    name = f"sworkr-my-data-{datetime.now().strftime('%Y-%m-%d')}.zip"
    return Response(content=blob, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.post("/api/account/data/erase")
def erase_everything(body: EraseRequest, request: Request):
    import demo
    if demo.ENABLED:
        raise HTTPException(status_code=403, detail="This is turned off in the demo: everyone shares its login")
    user = request.state.user
    if body.confirm.strip() != ERASE_WORD:
        raise HTTPException(status_code=400, detail=f"Type {ERASE_WORD} to confirm")
    db = _get_db()
    try:
        if not auth.check_login(db, user["username"], body.password):
            raise HTTPException(status_code=403, detail="That password isn't right")
        gone = erase(db, user["id"])
        # Other devices are signed out: whoever holds them shouldn't keep a window into a wiped account.
        auth.delete_user_sessions(db, user["id"], keep_token=request.cookies.get(auth.SESSION_COOKIE))
        db.commit()
        return {"erased": gone}
    finally:
        db.close()
