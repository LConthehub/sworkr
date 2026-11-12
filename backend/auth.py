"""
Authentication helpers: password hashing, sessions, and login throttling.

- Passwords are hashed with scrypt (Python standard library, no extra dependency).
- Session tokens are random; only their SHA-256 hash is stored in the database,
  so a copy of the database can't be used to log in.
- Repeated failed logins for a username are slowed down with an increasing lockout.
"""

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

SESSION_COOKIE = "sworkr_session"
SESSION_DAYS = 30
MIN_PASSWORD_LENGTH = 8

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


# ---------- passwords ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(hash_hex)))
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# A real hash to compare against when the username doesn't exist,
# so response time doesn't reveal whether a username is valid.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def check_login(db, username: str, password: str) -> Optional[dict]:
    row = db.execute("SELECT * FROM users WHERE username = ?", (username.strip().lower(),)).fetchone()
    if not row:
        verify_password(password, _DUMMY_HASH)
        return None
    return dict(row) if verify_password(password, row["password_hash"]) else None


# ---------- sessions ----------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), user_id, now.isoformat(timespec="seconds"),
         (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")),
    )
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(timespec="seconds"),))
    db.commit()
    return token


def user_for_token(db, token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    row = db.execute("""
        SELECT u.id, u.username, u.is_admin, s.expires_at
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ?
    """, (_token_hash(token),)).fetchone()
    if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return None
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


def delete_session(db, token: Optional[str]):
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        db.commit()


def delete_user_sessions(db, user_id: int, keep_token: Optional[str] = None):
    if keep_token:
        db.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, _token_hash(keep_token)))
    else:
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.commit()


# ---------- login throttling ----------

class LoginThrottle:
    """After 5 failures for a username, lock it for 2, 4, 8 … seconds (max 15 min)."""

    FREE_ATTEMPTS = 5
    MAX_LOCK_SECONDS = 15 * 60

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {}  # username -> (failures, locked_until)

    def seconds_locked(self, username: str) -> int:
        with self._lock:
            _, until = self._state.get(username, (0, 0.0))
            return max(0, int(until - time.time() + 0.999))

    def failure(self, username: str):
        with self._lock:
            failures, _ = self._state.get(username, (0, 0.0))
            failures += 1
            until = 0.0
            if failures >= self.FREE_ATTEMPTS:
                until = time.time() + min(2 ** (failures - self.FREE_ATTEMPTS + 1), self.MAX_LOCK_SECONDS)
            self._state[username] = (failures, until)

    def success(self, username: str):
        with self._lock:
            self._state.pop(username, None)


throttle = LoginThrottle()
