"""
A decoy password: a second password that opens a separate, harmless account under the same username.

It's for the moment someone makes you unlock sworkr: a border check, a search, a partner standing over you.
Type the decoy password instead of the real one and sworkr opens an account with none of your records in it.
You can sign in with the decoy password beforehand and put a few plain things in, so it doesn't look unused.

How it works:
- The decoy is an ordinary, separate login with a hidden internal name. Nobody can sign in to it by that name,
  and it isn't shown in the list of users.
- Signing in always checks the typed password against both, so the time it takes says nothing.
- When the decoy password is used, the real account's sign-in history notes it, so you know afterwards.

What it doesn't do: it protects against someone looking at the screen, not against someone who copies the
database file and has its key. Both accounts are in the same file. An admin's decoy isn't an admin, so the admin
pages aren't there.
"""

import secrets
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import auth

router = APIRouter(prefix="/api/account/decoy")
_get_db: Optional[Callable] = None
_remove_user: Optional[Callable] = None
_demo: Callable = lambda: False


def setup(get_db: Callable, remove_user: Callable, demo: Callable):
    global _get_db, _remove_user, _demo
    _get_db, _remove_user, _demo = get_db, remove_user, demo


class DecoyIn(BaseModel):
    current_password: str
    decoy_password: str


class RemoveIn(BaseModel):
    current_password: str


def _own_password_ok(db, user: dict, password: str) -> bool:
    found = auth.check_login(db, user["username"], password)
    return bool(found) and found["id"] == user["id"]


@router.get("")
def status(request: Request):
    db = _get_db()
    try:
        return {"enabled": bool(db.execute("SELECT 1 FROM decoys WHERE user_id = ?", (request.state.user["id"],)).fetchone())}
    finally:
        db.close()


@router.put("")
def set_decoy(body: DecoyIn, request: Request):
    """Set the decoy password, or change it. The decoy account and what's in it are kept when it changes."""
    if _demo():
        raise HTTPException(status_code=403, detail="This is turned off in the demo.")
    user = request.state.user
    if len(body.decoy_password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"The decoy password must be at least {auth.MIN_PASSWORD_LENGTH} characters")
    if body.decoy_password == body.current_password:
        raise HTTPException(status_code=400, detail="The decoy password has to be different from your real one")
    db = _get_db()
    try:
        if not _own_password_ok(db, user, body.current_password):
            raise HTTPException(status_code=400, detail="Current password is wrong")
        hashed = auth.hash_password(body.decoy_password)
        row = db.execute("SELECT decoy_user_id FROM decoys WHERE user_id = ?", (user["id"],)).fetchone()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if row:
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hashed, row["decoy_user_id"]))
            auth.delete_user_sessions(db, row["decoy_user_id"])
        else:
            cur = db.execute("INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 0, ?)",
                             (auth.DECOY_PREFIX + secrets.token_hex(12), hashed, now))
            db.execute("INSERT INTO decoys (user_id, decoy_user_id, created_at) VALUES (?, ?, ?)", (user["id"], cur.lastrowid, now))
        db.commit()
        return {"enabled": True}
    finally:
        db.close()


@router.post("/remove")
def remove_decoy(body: RemoveIn, request: Request):
    """Take the decoy away, with everything that was put in it."""
    user = request.state.user
    db = _get_db()
    try:
        if not _own_password_ok(db, user, body.current_password):
            raise HTTPException(status_code=400, detail="Current password is wrong")
        row = db.execute("SELECT decoy_user_id FROM decoys WHERE user_id = ?", (user["id"],)).fetchone()
        if row:
            _remove_user(db, row["decoy_user_id"])
            db.commit()
        return {"enabled": False}
    finally:
        db.close()
