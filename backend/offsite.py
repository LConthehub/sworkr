"""
Backups that survive losing this computer.

- Off-site copies: after each automatic backup, the same encrypted file is uploaded to a WebDAV folder
  (Nextcloud, or anything that speaks WebDAV). The file is encrypted before it leaves, so the other
  server only holds something it can't read. Old copies there are thinned out by which_to_delete().
- Restore test: about once a month the newest backup is opened with the saved passphrase into a
  throwaway database and checked. A backup nobody has ever opened is a hope, not a backup; this is what
  turns "a file exists" into "it restores".

A failure here never stops the local backup: it is recorded and shown on the Backups page.
"""

import logging
import os
import re
import dbfile as sqlite3
import tempfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from typing import Callable, List, Optional
from urllib.parse import unquote, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import backup

log = logging.getLogger("sworkr.offsite")
router = APIRouter(prefix="/api/backup")
_get_db: Optional[Callable] = None
_transport: Optional[httpx.BaseTransport] = None   # tests put a pretend server here

VERIFY_EVERY_DAYS = 30
NAME = re.compile(r"^sworkr-(\d{4})-(\d{2})-(\d{2})-\d{6}\.swbak$")


class OffsiteError(Exception):
    pass


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def backup_date(name: str) -> Optional[date]:
    """The day a backup file was made, from its name. None for anything that isn't one of ours."""
    m = NAME.match(name)
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    except ValueError:
        return None


# ==================== WHICH OFF-SITE COPIES TO KEEP ====================

def which_to_delete(names: List[str], today: date) -> List[str]:
    """Which of the off-site backup files to remove, given all of them.

    `names` are file names like "sworkr-2026-11-15-031502.swbak" (use backup_date(name) for the day);
    anything that isn't one of ours has already been filtered out. Return the names to delete.
    Whatever this returns, the caller never deletes the newest file.
    """
    # TODO(human): decide the retention policy. Until then nothing is ever deleted off-site.
    return []


# ==================== THE WEBDAV FOLDER ====================

class WebDavFolder:
    def __init__(self, url: str, username: str, password: str, transport: Optional[httpx.BaseTransport] = None):
        self.url = url.rstrip("/") + "/"
        self.http = httpx.Client(auth=(username, password), timeout=120, follow_redirects=True,
                                 transport=transport or _transport)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.http.close()

    def _request(self, method: str, url: str, ok=(200, 201, 204, 207), **kw) -> httpx.Response:
        try:
            r = self.http.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise OffsiteError(f"Couldn't reach the server ({type(e).__name__})") from None
        if r.status_code == 401:
            raise OffsiteError("The server refused the username or app password")
        if r.status_code == 507:
            raise OffsiteError("The server is out of space")
        if r.status_code not in ok:
            raise OffsiteError(f"The server answered {r.status_code} to {method}")
        return r

    def ensure(self):
        """Make the folder if it isn't there yet (405: it already is)."""
        self._request("MKCOL", self.url, ok=(201, 405))

    def names(self) -> List[str]:
        r = self._request("PROPFIND", self.url, headers={"Depth": "1"})
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            raise OffsiteError("The server's file list couldn't be read") from None
        found = []
        for href in root.iter("{DAV:}href"):
            name = unquote(urlparse(href.text or "").path).rstrip("/").rsplit("/", 1)[-1]
            if backup_date(name):
                found.append(name)
        return sorted(set(found))

    def put(self, name: str, blob: bytes):
        self._request("PUT", self.url + name, content=blob, headers={"Content-Type": "application/octet-stream"})

    def delete(self, name: str):
        self._request("DELETE", self.url + name, ok=(200, 204, 404))


def _config(db) -> Optional[dict]:
    url, user, password = (backup._setting(db, k) for k in ("offsite_url", "offsite_username", "offsite_password"))
    return {"url": url, "username": user, "password": password} if url and user and password else None


def _check_url(url: str) -> str:
    url = url.strip()
    parts = urlparse(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise HTTPException(status_code=400, detail="The address should look like https://cloud.example.com/remote.php/dav/files/you/sworkr-backups")
    return url


def send(db, name: str, blob: bytes) -> bool:
    """Upload one backup and thin out old copies. Records what happened; never raises."""
    cfg = _config(db)
    if not cfg:
        return False
    try:
        with WebDavFolder(**cfg) as folder:
            folder.ensure()
            folder.put(name, blob)
            there = folder.names()
            if name not in there:
                raise OffsiteError("The upload finished but the file isn't in the folder")
            newest = there[-1]
            for old in which_to_delete(list(there), datetime.now().date()):
                if old != newest and old in there:      # the newest copy is never removed, whatever the policy says
                    folder.delete(old)
        backup._set(db, "offsite_last_at", backup._now_iso())
        backup._set(db, "offsite_last_file", name)
        backup._set(db, "offsite_last_error", None)
        return True
    except Exception as e:
        log.warning("Off-site backup failed: %s", e)
        backup._set(db, "offsite_last_error", str(e)[:300])
        return False


# ==================== RESTORE TEST ====================

def verify_latest(db) -> Optional[dict]:
    """Open the newest local backup the way a restore would. Returns what was found, or None if there is nothing to test."""
    passphrase = backup._setting(db, "backup_passphrase")
    files = backup.list_backups()
    if not passphrase or not files:
        return None
    name = files[-1]["name"]
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    try:
        with open(os.path.join(backup.BACKUP_DIR, name), "rb") as f:
            backup.restore_into(path, f.read(), passphrase)      # decrypts, checks the pages, copies
        check = sqlite3.connect(path)
        try:
            tables = check.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
            users = check.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            check.close()
        if not users:
            raise backup.BackupError("The backup opens but holds no accounts")
        result = {"ok": True, "file": name, "tables": tables}
        backup._set(db, "backup_verify_error", None)
    except Exception as e:
        log.warning("Restore test failed for %s: %s", name, e)
        result = {"ok": False, "file": name, "error": str(e)[:300]}
        backup._set(db, "backup_verify_error", f"{name}: {str(e)[:250]}")
    finally:
        for leftover in (path, path + "-wal", path + "-shm"):
            if os.path.exists(leftover):
                os.remove(leftover)
    backup._set(db, "backup_verified_at", backup._now_iso())
    backup._set(db, "backup_verified_file", name)
    return result


def verify_if_due(db) -> Optional[dict]:
    last = backup._setting(db, "backup_verified_at")
    if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).days < VERIFY_EVERY_DAYS:
        return None
    return verify_latest(db)


# ==================== API (admin only) ====================

class OffsiteSettings(BaseModel):
    enabled: bool = True
    url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None      # blank or missing: keep the saved one


def status(db) -> dict:
    return {
        "enabled": bool(_config(db)),
        "url": backup._setting(db, "offsite_url"),
        "username": backup._setting(db, "offsite_username"),
        "has_password": bool(backup._setting(db, "offsite_password")),   # the password itself is never sent back
        "last_at": backup._setting(db, "offsite_last_at"),
        "last_file": backup._setting(db, "offsite_last_file"),
        "last_error": backup._setting(db, "offsite_last_error"),
        "verified_at": backup._setting(db, "backup_verified_at"),
        "verified_file": backup._setting(db, "backup_verified_file"),
        "verify_error": backup._setting(db, "backup_verify_error"),
        "verify_every_days": VERIFY_EVERY_DAYS,
    }


@router.get("/offsite")
def offsite_status(request: Request):
    backup._require_admin(request)
    db = _get_db()
    try:
        return status(db)
    finally:
        db.close()


@router.put("/offsite")
def save_offsite(body: OffsiteSettings, request: Request):
    """Turn off-site copies on (the folder is tried first, so a typo shows up now) or off."""
    backup._require_admin(request)
    db = _get_db()
    try:
        if not body.enabled:
            for key in ("offsite_url", "offsite_username", "offsite_password", "offsite_last_error"):
                backup._set(db, key, None)
            return status(db)
        url = _check_url(body.url or "")
        username = (body.username or "").strip()
        password = (body.password or "").strip() or backup._setting(db, "offsite_password")
        if not username or not password:
            raise HTTPException(status_code=400, detail="Enter the username and an app password for that server")
        try:
            with WebDavFolder(url, username, password) as folder:
                folder.ensure()
                folder.names()
        except OffsiteError as e:
            raise HTTPException(status_code=400, detail=str(e))
        for key, value in (("offsite_url", url), ("offsite_username", username), ("offsite_password", password),
                           ("offsite_last_error", None)):
            backup._set(db, key, value)
        # Send the newest backup we already have, so there is a copy off this computer from the first minute.
        files = backup.list_backups()
        if files:
            with open(os.path.join(backup.BACKUP_DIR, files[-1]["name"]), "rb") as f:
                send(db, files[-1]["name"], f.read())
        return status(db)
    finally:
        db.close()


@router.post("/verify")
def verify_now(request: Request):
    backup._require_admin(request)
    db = _get_db()
    try:
        result = verify_latest(db)
        if result is None:
            raise HTTPException(status_code=400, detail="Turn on automatic backups first: there is nothing to test yet")
        return {**status(db), "result": result}
    finally:
        db.close()
