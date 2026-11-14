"""
Authentication helpers: password hashing, sessions, and login throttling.

- Passwords are hashed with scrypt (Python standard library, no extra dependency).
- Session tokens are random; only their SHA-256 hash is stored in the database,
  so a copy of the database can't be used to log in.
- Repeated failed logins for a username are slowed down with an increasing lockout.
- Sessions that sit unused are logged out automatically.
"""

import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

SESSION_COOKIE = "sworkr_session"
SESSION_DAYS = 30
MIN_PASSWORD_LENGTH = 8
# Log out a session that hasn't been used for this long. Each user can change theirs on the Account page.
DEFAULT_IDLE_MINUTES = int(os.environ.get("SESSION_IDLE_MINUTES", "120"))
IDLE_CHOICES = (15, 30, 60, 120, 480, 0)   # minutes; 0 = stay logged in (up to 30 days)

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
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
        (_token_hash(token), user_id, now.isoformat(timespec="seconds"),
         (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
    )
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(timespec="seconds"),))
    db.commit()
    return token


def idle_minutes_for(db, user_id: int) -> int:
    """How long this user's session may sit unused before it is logged out. 0 means never."""
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = 'idle_minutes'", (user_id,)).fetchone()
    try:
        return max(0, int(row["value"])) if row and row["value"] is not None else DEFAULT_IDLE_MINUTES
    except ValueError:
        return DEFAULT_IDLE_MINUTES


def user_for_token(db, token: Optional[str], touch: bool = True) -> Optional[dict]:
    """
    The logged-in user for a session cookie, or None.
    A session ends 30 days after login, or sooner if it sits unused for longer than the user's
    auto-logout time. `touch=False` is for background requests (polling): they don't count as use.
    """
    if not token:
        return None
    token_hash = _token_hash(token)
    row = db.execute("""
        SELECT u.id, u.username, u.is_admin, s.expires_at, s.created_at, s.last_seen_at
        FROM sessions s JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ?
    """, (token_hash,)).fetchone()
    if not row:
        return None
    now = datetime.now(timezone.utc)
    last_seen = datetime.fromisoformat(row["last_seen_at"] or row["created_at"])
    idle = idle_minutes_for(db, row["id"])
    if datetime.fromisoformat(row["expires_at"]) < now or (idle and now - last_seen > timedelta(minutes=idle)):
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        db.commit()
        return None
    if touch and (row["last_seen_at"] is None or now - last_seen > timedelta(seconds=30)):
        db.execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                   (now.isoformat(timespec="seconds"), token_hash))
        db.commit()
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
    """After `free_attempts` failures for a key (a username, or a visitor's address), lock it for
    2, 4, 8 … seconds (max 15 min)."""

    MAX_LOCK_SECONDS = 15 * 60
    MAX_TRACKED = 10000   # so a flood of made-up usernames can't use up memory

    def __init__(self, free_attempts: int = 5):
        self.FREE_ATTEMPTS = free_attempts
        self._lock = threading.Lock()
        self._state = {}  # key -> (failures, locked_until)

    def seconds_locked(self, username: str) -> int:
        with self._lock:
            _, until = self._state.get(username, (0, 0.0))
            return max(0, int(until - time.time() + 0.999))

    def failure(self, username: str):
        with self._lock:
            if username not in self._state and len(self._state) >= self.MAX_TRACKED:
                now = time.time()
                for key in [k for k, (_, until) in self._state.items() if until < now][: self.MAX_TRACKED // 2]:
                    del self._state[key]
                if len(self._state) >= self.MAX_TRACKED:   # still full: forget the oldest entries
                    for key in list(self._state)[: self.MAX_TRACKED // 2]:
                        del self._state[key]
            failures, _ = self._state.get(username, (0, 0.0))
            failures += 1
            until = 0.0
            if failures >= self.FREE_ATTEMPTS:
                until = time.time() + min(2 ** (failures - self.FREE_ATTEMPTS + 1), self.MAX_LOCK_SECONDS)
            self._state[username] = (failures, until)

    def success(self, username: str):
        with self._lock:
            self._state.pop(username, None)


throttle = LoginThrottle()               # per username
ip_throttle = LoginThrottle(free_attempts=20)   # per visitor address: allows a household behind one address some typos
