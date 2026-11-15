"""
Encrypted backups of the whole database.

A backup file (.swbak) is the SQLite database, compressed, then encrypted with a passphrase
(AES-256-GCM, key derived with scrypt). Without the passphrase the file is unreadable, so it is
safe to keep on a USB stick or in cloud storage.

- Download one any time from the Account page (admin only).
- Automatic: once a passphrase is saved on the Account page, a backup is written to BACKUP_DIR
  every day and the newest BACKUP_KEEP files are kept.
- Restore with:  docker compose exec api python manage.py restore-backup /backups/<file>

File layout:  b"SWBAK1\\n" | 16-byte salt | 12-byte nonce | ciphertext (gzip of the database) + tag
"""

import gzip
import vault
import hashlib
import logging
import os
import secrets
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

MAGIC = b"SWBAK1\n"
MIN_PASSPHRASE_LENGTH = 10
BACKUP_DIR = os.environ.get("BACKUP_DIR", "/backups")
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))
AUTO_EVERY = 24 * 3600          # seconds between automatic backups
CHECK_EVERY = 15 * 60           # how often the worker looks whether one is due

log = logging.getLogger("sworkr.backup")
_get_db: Optional[Callable] = None


class BackupError(Exception):
    pass


# ==================== ENCRYPTION ====================

def _key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 15, r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024)


def encrypt(data: bytes, passphrase: str) -> bytes:
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, gzip.compress(data), MAGIC)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 28 + 16:
        raise BackupError("This isn't a sworkr backup file")
    body = blob[len(MAGIC):]
    salt, nonce, ciphertext = body[:16], body[16:28], body[28:]
    try:
        return gzip.decompress(AESGCM(_key(passphrase, salt)).decrypt(nonce, ciphertext, MAGIC))
    except InvalidTag:
        raise BackupError("Wrong passphrase, or the file is damaged") from None


# ==================== SNAPSHOT / RESTORE ====================

def snapshot(db) -> bytes:
    """A consistent copy of the live database, as bytes. Safe while the app is in use."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        dest = sqlite3.connect(path)
        try:
            db.backup(dest)
        finally:
            dest.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.remove(path)


def make_backup(db, passphrase: str) -> bytes:
    return encrypt(snapshot(db), passphrase)


def restore_into(db_path: str, blob: bytes, passphrase: str) -> None:
    """Replace the database at db_path with the one inside a backup file."""
    data = decrypt(blob, passphrase)
    if not data.startswith(b"SQLite format 3\x00"):
        raise BackupError("The backup doesn't contain a database")
    fd, path = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        source = sqlite3.connect(path)
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("The database inside the backup is damaged")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            dest = sqlite3.connect(db_path, timeout=30)
            try:
                source.backup(dest)   # copies page by page, so it also works while the app is running
            finally:
                dest.close()
        finally:
            source.close()
    finally:
        os.remove(path)


def backup_filename(now: Optional[datetime] = None) -> str:
    return f"sworkr-{(now or datetime.now()).strftime('%Y-%m-%d-%H%M%S')}.swbak"


# ==================== AUTOMATIC BACKUPS ====================

def _setting(db, key: str) -> Optional[str]:
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return vault.unseal(key, row[0]) if row else None


def _set(db, key: str, value: Optional[str]):
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, vault.seal(key, value)))
    db.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_backups() -> list:
    try:
        names = sorted(n for n in os.listdir(BACKUP_DIR) if n.startswith("sworkr-") and n.endswith(".swbak"))
    except OSError:
        return []
    return [{"name": n, "bytes": os.path.getsize(os.path.join(BACKUP_DIR, n))} for n in names]


def run_auto_backup(force: bool = False) -> Optional[str]:
    """Write a backup to BACKUP_DIR if one is due. Returns the file name, or None if nothing was written."""
    db = _get_db()
    try:
        passphrase = _setting(db, "backup_passphrase")
        if not passphrase:
            return None
        last = _setting(db, "backup_last_at")
        if not force and last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < AUTO_EVERY:
            return None
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            name = backup_filename()
            blob = make_backup(db, passphrase)
            tmp = os.path.join(BACKUP_DIR, name + ".part")
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, os.path.join(BACKUP_DIR, name))
            for old in list_backups()[:-BACKUP_KEEP]:
                os.remove(os.path.join(BACKUP_DIR, old["name"]))
            _set(db, "backup_last_at", _now_iso())
            _set(db, "backup_last_error", None)
            return name
        except Exception as e:  # keep the worker alive whatever happens
            log.warning("Automatic backup failed: %s", e)
            _set(db, "backup_last_error", str(e)[:300])
            return None
    finally:
        db.close()


def _worker():
    while True:
        try:
            run_auto_backup()
        except Exception as e:
            log.warning("Backup worker: %s", e)
        time.sleep(CHECK_EVERY)


def start(get_db: Callable, background: bool = True):
    global _get_db
    _get_db = get_db
    if background:
        threading.Thread(target=_worker, name="auto-backup", daemon=True).start()


# ==================== API (admin only) ====================

router = APIRouter(prefix="/api/backup")


class Passphrase(BaseModel):
    passphrase: str


class AutoBackup(BaseModel):
    passphrase: Optional[str] = None   # blank or missing: keep the saved one
    enabled: bool = True


def _require_admin(request: Request):
    if not request.state.user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Only an admin account can manage backups")


def _check(passphrase: str) -> str:
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise HTTPException(status_code=400, detail=f"The passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters")
    return passphrase


def _status(db) -> dict:
    files = list_backups()
    return {
        "auto_enabled": bool(_setting(db, "backup_passphrase")),
        "last_backup_at": _setting(db, "backup_last_at"),
        "last_error": _setting(db, "backup_last_error"),
        "folder": BACKUP_DIR,
        "keep": BACKUP_KEEP,
        "files": len(files),
        "newest_file": files[-1]["name"] if files else None,
    }


@router.get("")
def backup_status(request: Request):
    _require_admin(request)
    db = _get_db()
    try:
        return _status(db)
    finally:
        db.close()


@router.post("/download")
def download_backup(body: Passphrase, request: Request):
    """An encrypted copy of the whole database, to save somewhere safe."""
    _require_admin(request)
    db = _get_db()
    try:
        blob = make_backup(db, _check(body.passphrase))
    finally:
        db.close()
    return Response(content=blob, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{backup_filename()}"'})


@router.put("/auto")
def save_auto_backup(body: AutoBackup, request: Request):
    """Turn daily automatic backups on (with a passphrase) or off."""
    _require_admin(request)
    db = _get_db()
    try:
        if not body.enabled:
            _set(db, "backup_passphrase", None)
            return _status(db)
        passphrase = (body.passphrase or "").strip() or _setting(db, "backup_passphrase")
        if not passphrase:
            raise HTTPException(status_code=400, detail="Choose a passphrase for the backups")
        _set(db, "backup_passphrase", _check(passphrase))
    finally:
        db.close()
    run_auto_backup(force=True)   # make the first one right away, so problems show up now
    db = _get_db()
    try:
        return _status(db)
    finally:
        db.close()
