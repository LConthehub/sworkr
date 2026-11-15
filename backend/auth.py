"""
Authentication helpers: password hashing, sessions, and login throttling.

- Passwords are hashed with scrypt (Python standard library, no extra dependency).
- Session tokens are random; only their SHA-256 hash is stored in the database,
  so a copy of the database can't be used to log in.
- Repeated failed logins are slowed down with an increasing lockout, kept in the database so a restart
  doesn't forget it.
- Sessions that sit unused are logged out automatically.
"""

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

SESSION_COOKIE = "sworkr_session"
SESSION_DAYS = 30
MIN_PASSWORD_LENGTH = 12
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


def create_session(db, user_id: int, method: Optional[str] = None, ip: Optional[str] = None,
                   user_agent: Optional[str] = None, device_hash: Optional[str] = None) -> str:
    """A new session. How and from where it was opened is kept, so the person can see their signed-in devices."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen_at, method, ip, user_agent, device_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (_token_hash(token), user_id, now.isoformat(timespec="seconds"),
         (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds"), now.isoformat(timespec="seconds"),
         method, ip, (user_agent or "")[:300] or None, device_hash),
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

_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


class LoginThrottle:
    """After `free_attempts` failures for a key, lock it for 2, 4, 8 … seconds (max 15 min). Kept in the
    database (table login_throttle), so restarting sworkr doesn't give a guesser a fresh start. A key that
    has had no failure for a day is forgotten."""

    MAX_LOCK_SECONDS = 15 * 60
    MAX_TRACKED = 10000   # so a flood of made-up usernames can't fill the database
    FORGET_AFTER = 24 * 3600

    def __init__(self, prefix: str, free_attempts: int = 5):
        self.prefix = prefix
        self.FREE_ATTEMPTS = free_attempts

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}"[:200]

    def seconds_locked(self, key: str) -> int:
        db = _get_db()
        try:
            row = db.execute("SELECT locked_until FROM login_throttle WHERE key = ?", (self._key(key),)).fetchone()
        finally:
            db.close()
        return max(0, int(row["locked_until"] - time.time() + 0.999)) if row else 0

    def failure(self, key: str):
        now = time.time()
        db = _get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_throttle WHERE updated_at < ?", (now - self.FORGET_AFTER,))
            if db.execute("SELECT COUNT(*) FROM login_throttle").fetchone()[0] >= self.MAX_TRACKED:
                # Still full: forget the entries that failed longest ago.
                db.execute("DELETE FROM login_throttle WHERE key IN (SELECT key FROM login_throttle "
                           "ORDER BY updated_at LIMIT ?)", (self.MAX_TRACKED // 2,))
            row = db.execute("SELECT failures FROM login_throttle WHERE key = ?", (self._key(key),)).fetchone()
            failures = (row["failures"] if row else 0) + 1
            until = 0.0
            if failures >= self.FREE_ATTEMPTS:
                until = now + min(2 ** min(failures - self.FREE_ATTEMPTS + 1, 20), self.MAX_LOCK_SECONDS)
            db.execute("INSERT INTO login_throttle (key, failures, locked_until, updated_at) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET failures = excluded.failures, locked_until = excluded.locked_until, "
                       "updated_at = excluded.updated_at", (self._key(key), failures, until, now))
            db.commit()
        finally:
            db.close()

    def success(self, key: str):
        db = _get_db()
        try:
            db.execute("DELETE FROM login_throttle WHERE key = ?", (self._key(key),))
            db.commit()
        finally:
            db.close()


# Failures are counted three ways. A username from one address gets 5 tries. One address gets 20 across all
# usernames (a household behind one address is allowed some typos). And a username gets 30 across all addresses:
# high enough that a stranger who knows your username can't easily lock you out, low enough to stop a botnet.
pair_throttle = LoginThrottle("pair")
ip_throttle = LoginThrottle("ip", free_attempts=20)
throttle = LoginThrottle("user", free_attempts=30)
