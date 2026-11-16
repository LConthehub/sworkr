"""
The content library and the post planner.

The library is a folder the person already keeps their photos and videos in. sworkr only ever reads it:
- Nextcloud (over WebDAV, with an app password),
- a Synology NAS or any other WebDAV server,
- or a folder mounted into sworkr's container (a NAS share, an external drive...; see docker-compose.yml).

Each subfolder is a "set". sworkr lists files and makes thumbnails on request; nothing from the library is
stored in sworkr's database or on its disk. Thumbnails are made in memory (Nextcloud's own previews when the
library is in Nextcloud), with a small in-memory cache that's lost on restart.

Posts are planned against files and sets: platform, account, when, caption, price, status. sworkr never posts
anything itself: it reminds you, copies the caption, and keeps track of what went where and when.
"""

import io
import vault
import json
import mimetypes
import os
import posixpath
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, unquote, urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

import campaigns
import personas

router = APIRouter()
_get_db: Optional[Callable] = None

CONTENT_ROOT = os.environ.get("CONTENT_ROOT", "/content")   # where mounted folders appear inside the container
TIMEOUT = 30
MAX_THUMB_SOURCE = 40 * 1024 * 1024     # don't download images bigger than this just to make a thumbnail
MAX_FILES = 2000
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif", "image/avif", "image/bmp", "image/tiff")


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


class LibraryError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _demo() -> bool:
    import demo
    return demo.ENABLED


# ==================== PATHS ====================

def clean_path(path: Optional[str]) -> str:
    """A path inside the library, as 'Set/sub/file.jpg'. Anything that tries to leave the library is refused."""
    path = (path or "").replace("\\", "/").strip("/")
    if not path:
        return ""
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts) or any(ord(ch) < 32 for ch in path):
        raise HTTPException(status_code=400, detail="That isn't a path inside your library")
    return "/".join(parts)


def kind_of(name: str) -> str:
    mime = mimetypes.guess_type(name)[0] or ""
    if mime.startswith("image/") or name.lower().endswith((".heic", ".heif", ".avif", ".webp")):
        return "image"
    if mime.startswith("video/") or name.lower().endswith((".mov", ".mkv", ".m4v")):
        return "video"
    return "other"


# ==================== LIBRARIES ====================

class Library:
    """Lists a folder (`list`) and reads a file (`read`, for thumbnails)."""
    can_preview_videos = False

    def list(self, path: str) -> List[dict]:
        raise NotImplementedError

    def read(self, path: str) -> bytes:
        raise NotImplementedError

    def thumbnail(self, path: str, size: int) -> Optional[bytes]:
        if kind_of(path) != "image":
            return None
        return make_thumbnail(self.read(path), size)

    def web_link(self, path: str) -> Optional[str]:
        return None

    def close(self):
        pass


class FolderLibrary(Library):
    """A folder mounted into the container, under CONTENT_ROOT."""

    def __init__(self, folder: str):
        root = os.path.realpath(CONTENT_ROOT)
        base = os.path.realpath(os.path.join(root, clean_path(folder)))
        if os.path.commonpath([root, base]) != root:
            raise LibraryError("That folder isn't inside the content folder")
        if not os.path.isdir(base):
            raise LibraryError(f"There's no folder at {base}. Check that it's mounted into sworkr's container.")
        self.base = base

    def _real(self, path: str) -> str:
        full = os.path.realpath(os.path.join(self.base, path))
        if os.path.commonpath([self.base, full]) != self.base:     # a symlink pointing outside the library
            raise LibraryError("That file is outside your library")
        return full

    def list(self, path: str) -> List[dict]:
        folder = self._real(path)
        if not os.path.isdir(folder):
            raise LibraryError("That folder isn't there any more")
        out = []
        for entry in sorted(os.scandir(folder), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            rel = f"{path}/{entry.name}" if path else entry.name
            out.append({"name": entry.name, "path": rel, "folder": entry.is_dir(),
                        "size": None if entry.is_dir() else stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")})
        return out

    def read(self, path: str) -> bytes:
        full = self._real(path)
        if os.path.getsize(full) > MAX_THUMB_SOURCE:
            raise LibraryError("Too big to preview")
        with open(full, "rb") as f:
            return f.read()


DAV = {"d": "DAV:", "oc": "http://owncloud.org/ns"}


class WebDavLibrary(Library):
    """A folder on a WebDAV server (Nextcloud, Synology's WebDAV Server package, and others)."""

    def __init__(self, url: str, username: str, password: str, nextcloud: bool = False,
                 transport: Optional[httpx.BaseTransport] = None):
        self.root = url.rstrip("/") + "/"
        self.nextcloud = nextcloud
        self.http = httpx.Client(auth=(username, password), timeout=TIMEOUT, follow_redirects=True, transport=transport,
                                 headers={"User-Agent": "sworkr-content"})

    def close(self):
        self.http.close()

    def _url(self, path: str) -> str:
        return self.root + "/".join(quote(p) for p in path.split("/") if p) + ("/" if path == "" else "")

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            r = self.http.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise LibraryError(f"Couldn't reach the server: {e}") from e
        if r.status_code == 401:
            raise LibraryError("The server rejected the username or app password")
        return r

    def list(self, path: str) -> List[dict]:
        url = self._url(path)
        if path and not url.endswith("/"):
            url += "/"
        r = self._request("PROPFIND", url, headers={"Depth": "1", "Content-Type": "application/xml"}, content=(
            '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:prop>'
            '<d:resourcetype/><d:getcontentlength/><d:getlastmodified/><oc:fileid/></d:prop></d:propfind>'))
        if r.status_code == 404:
            raise LibraryError("That folder isn't there. Check the folder address.")
        if r.status_code != 207:
            raise LibraryError(f"The server didn't list the folder (HTTP {r.status_code})")
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as e:
            raise LibraryError("Couldn't read the server's answer") from e
        here = urlsplit(url).path.rstrip("/")
        out = []
        for resp in root.iterfind("d:response", DAV):
            href = unquote(urlsplit(urljoin(url, resp.findtext("d:href", "", DAV))).path).rstrip("/")
            if href == unquote(here):
                continue
            name = href.rsplit("/", 1)[-1]
            if not name or name.startswith("."):
                continue
            folder = resp.find(".//d:resourcetype/d:collection", DAV) is not None
            size = resp.findtext(".//d:getcontentlength", None, DAV)
            modified = resp.findtext(".//d:getlastmodified", None, DAV)
            try:
                modified = datetime.strptime(modified, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc).isoformat() if modified else None
            except ValueError:
                modified = None
            out.append({"name": name, "path": f"{path}/{name}" if path else name, "folder": folder,
                        "size": int(size) if size and size.isdigit() else None, "modified": modified,
                        "fileid": resp.findtext(".//oc:fileid", None, DAV)})
        out.sort(key=lambda e: (not e["folder"], e["name"].lower()))
        return out

    def read(self, path: str) -> bytes:
        with self.http.stream("GET", self._url(path)) as r:
            if r.status_code == 401:
                raise LibraryError("The server rejected the username or app password")
            if r.status_code != 200:
                raise LibraryError(f"Couldn't read the file (HTTP {r.status_code})")
            data = bytearray()
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > MAX_THUMB_SOURCE:
                    raise LibraryError("Too big to preview")
            return bytes(data)

    def _nextcloud_base(self) -> Optional[str]:
        m = re.match(r"(.*?)/remote\.php/(?:dav/files/[^/]+|webdav)/", self.root)
        return m.group(1) if m else None

    def thumbnail(self, path: str, size: int) -> Optional[bytes]:
        # Nextcloud makes previews itself (videos too, when it's set up to): ask it first.
        base = self._nextcloud_base() if self.nextcloud else None
        if base:
            folder, _, name = path.rpartition("/")
            fileid = next((e.get("fileid") for e in self.list(folder) if e["name"] == name), None)
            if fileid:
                r = self._request("GET", f"{base}/index.php/core/preview",
                                  params={"fileId": fileid, "x": size, "y": size, "a": "true", "forceIcon": "0"})
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                    return r.content
        return super().thumbnail(path, size)

    def web_link(self, path: str) -> Optional[str]:
        base = self._nextcloud_base() if self.nextcloud else None
        m = re.match(r".*?/remote\.php/dav/files/[^/]+/(.*)$", self.root)
        if not (base and m):
            return None
        folder = posixpath.dirname("/" + unquote(m.group(1)).strip("/") + "/" + path)
        return f"{base}/index.php/apps/files/?dir={quote(folder)}"


def make_thumbnail(data: bytes, size: int) -> Optional[bytes]:
    """A small JPEG of an image, made in memory. Needs Pillow; returns None when it can't."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    Image.MAX_IMAGE_PIXELS = 80_000_000      # refuse "decompression bomb" images
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((size, size))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, "JPEG", quality=80)
            return out.getvalue()
    except Exception:
        return None


# ==================== THE DEMO'S MADE-UP LIBRARY ====================

class DemoLibrary(Library):
    SETS = {"2026-10 Red lace": 8, "2026-10 Beach day": 6, "2026-11 Collab with Jade": 5, "2026-11 Office roleplay": 7,
            "Teasers": 4}
    COLORS = {"2026-10 Red lace": (196, 30, 58), "2026-10 Beach day": (20, 140, 180), "2026-11 Collab with Jade": (124, 58, 237),
              "2026-11 Office roleplay": (80, 80, 90), "Teasers": (252, 76, 156)}

    def list(self, path: str) -> List[dict]:
        now = datetime.now(timezone.utc)
        if path == "":
            return [{"name": s, "path": s, "folder": True, "size": None,
                     "modified": (now - timedelta(days=5 * i)).isoformat(timespec="seconds")} for i, s in enumerate(self.SETS)]
        if path not in self.SETS:
            raise LibraryError("That folder isn't there any more")
        out = []
        for i in range(self.SETS[path]):
            name = f"{i + 1:02d}.mp4" if i == self.SETS[path] - 1 else f"{i + 1:02d}.jpg"
            out.append({"name": name, "path": f"{path}/{name}", "folder": False, "size": 2_400_000 + i * 31_337,
                        "modified": (now - timedelta(days=3)).isoformat(timespec="seconds")})
        return out

    def thumbnail(self, path: str, size: int) -> Optional[bytes]:
        """A coloured placeholder: the demo has no real content."""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return None
        folder, _, name = path.rpartition("/")
        r, g, b = self.COLORS.get(folder, (150, 150, 150))
        shade = (int(name[:2]) if name[:2].isdigit() else 1) * 9
        img = Image.new("RGB", (size, size), (min(r + shade, 255), min(g + shade, 255), min(b + shade, 255)))
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), "DEMO", fill=(255, 255, 255))
        draw.text((10, size - 22), ("▶ " if name.endswith(".mp4") else "") + name, fill=(255, 255, 255))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=80)
        return out.getvalue()


# ==================== SETTINGS (per person) ====================

KINDS = ("nextcloud", "webdav", "folder")


def _get(db, user_id: int, key: str) -> Optional[str]:
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return vault.unseal(key, row["value"]) if row else None


def _set(db, user_id: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, vault.seal(key, value)))


def load_settings(db, user_id: int) -> dict:
    s = {k: _get(db, user_id, f"content_{k}") for k in ("kind", "url", "username", "password", "folder", "use_calendar_login")}
    s["use_calendar_login"] = s["use_calendar_login"] == "1"
    if s["use_calendar_login"]:
        s["username"] = _get(db, user_id, "cal_username")
        s["password"] = _get(db, user_id, "cal_password")
    try:
        s["repost_days"] = json.loads(_get(db, user_id, "content_repost_days") or "{}")
    except ValueError:
        s["repost_days"] = {}
    return s


def open_library(s: dict) -> Library:
    if _demo():
        return DemoLibrary()
    kind = s.get("kind")
    if kind == "folder":
        return FolderLibrary(s.get("folder") or "")
    if kind in ("nextcloud", "webdav"):
        if not (s.get("url") and s.get("username") and s.get("password")):
            raise LibraryError("Fill in the folder address, username and app password")
        return WebDavLibrary(s["url"], s["username"], s["password"], nextcloud=kind == "nextcloud")
    raise LibraryError("Connect your content library first")


def nextcloud_folder_url(server: str, username: str, folder: str) -> str:
    """'https://cloud.example.com' + 'me' + 'Content' → the WebDAV address of that folder."""
    server = server.strip().rstrip("/")
    if "://" not in server:
        server = "https://" + server
    server = re.split(r"/(?:index\.php|apps|remote\.php|login)(?:/|$)", server, maxsplit=1)[0]
    parts = [quote(p) for p in clean_path(folder).split("/") if p]
    return f"{server}/remote.php/dav/files/{quote(username)}/" + "/".join(parts) + ("/" if parts else "")


class ContentSettings(BaseModel):
    kind: str
    url: Optional[str] = None            # WebDAV folder address (for Nextcloud: the server address)
    folder: Optional[str] = None         # Nextcloud folder, or the mounted folder's path under CONTENT_ROOT
    username: Optional[str] = None
    password: Optional[str] = None       # blank or missing: keep the saved one
    use_calendar_login: bool = False     # Nextcloud: use the account from calendar sync
    repost_days: Dict[str, int] = {}     # wait this many days before reposting the same file to a platform


def _settings_from(db, user_id: int, body: ContentSettings) -> dict:
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail="Choose Nextcloud, WebDAV (Synology and others) or a mounted folder")
    s = {"kind": body.kind, "folder": None, "url": None, "username": None, "password": None,
         "use_calendar_login": body.use_calendar_login and body.kind == "nextcloud"}
    if body.kind == "folder":
        s["folder"] = clean_path(body.folder)
        return s
    from calendar_sync import same_server
    if s["use_calendar_login"]:
        s["username"], s["password"] = _get(db, user_id, "cal_username"), _get(db, user_id, "cal_password")
        if not (s["username"] and s["password"]):
            raise HTTPException(status_code=400, detail="Set up calendar sync first, or enter a username and app password here")
    else:
        s["username"] = (body.username or "").strip()
    raw = (body.url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Enter the server or folder address")
    if body.kind == "nextcloud":
        s["url"] = nextcloud_folder_url(raw, s["username"] or "", body.folder or "")
        s["folder"] = clean_path(body.folder)
    else:
        s["url"] = raw if "://" in raw else "https://" + raw
        if urlsplit(s["url"]).scheme not in ("http", "https"):
            raise HTTPException(status_code=400, detail="That doesn't look like a web address")
    # A saved password only ever goes back to the server (and username) it was saved for. Otherwise anyone with a
    # logged-in session could point this at their own server and have sworkr send them the password.
    if s["use_calendar_login"]:
        if not same_server(s["url"], _get(db, user_id, "cal_url")):
            raise HTTPException(status_code=400, detail="Your calendar login is for a different server. "
                                                        "Enter a username and app password for this one.")
    elif (body.password or "").strip():
        s["password"] = body.password.strip()
    elif _get(db, user_id, "content_password"):
        if not same_server(s["url"], _get(db, user_id, "content_url")) or \
                s["username"].lower() != (_get(db, user_id, "content_username") or "").lower():
            raise HTTPException(status_code=400, detail="The server or username changed, so enter the app password again")
        s["password"] = _get(db, user_id, "content_password")
    return s


def _refuse_in_demo():
    if _demo():
        raise HTTPException(status_code=403, detail="The content library is a made-up sample in the demo. "
                                                    "Never enter real account details in a demo.")


@router.get("/api/content/settings")
def get_settings(request: Request):
    db = _get_db()
    try:
        s = load_settings(db, request.state.user["id"])
        return {"kind": s["kind"], "url": s["url"], "folder": s["folder"], "username": s["username"],
                "has_password": bool(s["password"]), "use_calendar_login": s["use_calendar_login"],
                "repost_days": s["repost_days"], "content_root": CONTENT_ROOT, "demo": _demo(),
                "connected": _demo() or bool(s["kind"])}
    finally:
        db.close()


@router.post("/api/content/test")
def test_settings(body: ContentSettings, request: Request):
    _refuse_in_demo()
    db = _get_db()
    try:
        s = _settings_from(db, request.state.user["id"], body)
    finally:
        db.close()
    try:
        lib = open_library(s)
        try:
            entries = lib.list("")
        finally:
            lib.close()
    except LibraryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "sets": sum(1 for e in entries if e["folder"]), "files": sum(1 for e in entries if not e["folder"])}


@router.put("/api/content/settings")
def save_settings(body: ContentSettings, request: Request):
    _refuse_in_demo()
    user_id = request.state.user["id"]
    for platform, days in body.repost_days.items():
        if not (0 <= days <= 3650) or len(platform) > 60:
            raise HTTPException(status_code=400, detail="Repost waits are 0 to 3650 days")
    db = _get_db()
    try:
        s = _settings_from(db, user_id, body)
        for key in ("kind", "url", "folder", "username"):
            _set(db, user_id, f"content_{key}", s[key])
        _set(db, user_id, "content_use_calendar_login", "1" if s["use_calendar_login"] else "0")
        _set(db, user_id, "content_password", None if s["use_calendar_login"] else s["password"])
        _set(db, user_id, "content_repost_days", json.dumps({k.strip(): int(v) for k, v in body.repost_days.items() if k.strip()}))
        db.commit()
        _thumbs.forget(user_id)
    finally:
        db.close()
    return get_settings(request)


# ==================== BROWSING ====================

def _library_for(request: Request) -> Library:
    db = _get_db()
    try:
        s = load_settings(db, request.state.user["id"])
    finally:
        db.close()
    if not s["kind"] and not _demo():
        raise HTTPException(status_code=409, detail={"code": "not_set_up", "message": "Connect your content library first"})
    try:
        return open_library(s)
    except LibraryError as e:
        raise HTTPException(status_code=502, detail=str(e))


def _history(db, owner_id: int) -> Dict[str, List[dict]]:
    """For each file and set: the posts that used it."""
    out: Dict[str, List[dict]] = {}
    for p in db.execute("SELECT id, platform, account, status, scheduled_at, posted_at, set_path, file_paths, price "
                        "FROM posts WHERE owner_id = ? AND status != 'skipped'", (owner_id,)):
        brief = {"post_id": p["id"], "platform": p["platform"], "account": p["account"], "status": p["status"],
                 "when": p["posted_at"] or p["scheduled_at"], "price": p["price"]}
        for path in {*json.loads(p["file_paths"] or "[]"), *([p["set_path"]] if p["set_path"] else [])}:
            out.setdefault(path, []).append(brief)
    for items in out.values():
        items.sort(key=lambda b: b["when"] or "", reverse=True)
    return out


@router.get("/api/content/browse")
def browse(request: Request, path: str = Query("", description="A folder in the library; empty for the top")):
    """A folder's sets (subfolders) and files, each with where it's been posted or planned."""
    path = clean_path(path)
    lib = _library_for(request)
    try:
        entries = lib.list(path)[:MAX_FILES]
        link = lib.web_link(path + "/x") if path else lib.web_link("x")
    except LibraryError as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        lib.close()
    db = _get_db()
    try:
        history = _history(db, request.state.user["id"])
    finally:
        db.close()
    for e in entries:
        e.pop("fileid", None)
        e["kind"] = "folder" if e["folder"] else kind_of(e["name"])
        e["posts"] = history.get(e["path"], [])
        if e["folder"]:   # a set: also count posts of the files inside it
            inside = [b for p, items in history.items() if p.startswith(e["path"] + "/") for b in items]
            e["file_posts"] = len(inside)
            e["platforms"] = sorted({b["platform"] for b in e["posts"] + inside if b["status"] == "posted"})
    return {"path": path, "entries": entries, "web_link": link, "demo": _demo()}


class ThumbCache:
    """Recent thumbnails in memory only (lost on restart), so scrolling a set doesn't fetch everything again."""

    def __init__(self, limit=400):
        self.limit = limit
        self.items: "OrderedDict[tuple, bytes]" = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        return None

    def put(self, key, value):
        with self.lock:
            self.items[key] = value
            while len(self.items) > self.limit:
                self.items.popitem(last=False)

    def forget(self, user_id):
        with self.lock:
            for key in [k for k in self.items if k[0] == user_id]:
                del self.items[key]


_thumbs = ThumbCache()


@router.get("/api/content/thumbnail")
def thumbnail(request: Request, path: str = Query(...), size: int = Query(256, ge=64, le=640)):
    path = clean_path(path)
    if not path:
        raise HTTPException(status_code=400, detail="Which file?")
    key = (request.state.user["id"], path, size)
    data = _thumbs.get(key)
    if data is None:
        lib = _library_for(request)
        try:
            data = lib.thumbnail(path, size)
        except LibraryError as e:
            raise HTTPException(status_code=502, detail=str(e))
        finally:
            lib.close()
        if not data:
            raise HTTPException(status_code=404, detail="No preview for this file")
        _thumbs.put(key, data)
    # The browser may keep it briefly; nothing is kept on sworkr's disk.
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


# ==================== POSTS ====================

STATUSES = ("idea", "ready", "scheduled", "posted", "skipped")


class PostIn(BaseModel):
    platform: str
    account: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: str = "idea"
    caption: Optional[str] = None
    price: Optional[float] = None
    set_path: Optional[str] = None
    file_paths: List[str] = []
    posted_at: Optional[datetime] = None
    post_url: Optional[str] = None
    notes: Optional[str] = None
    repeat_dates: List[datetime] = []     # more times for the same post ("every Tuesday"), worked out by the browser
    persona_id: Optional[int] = None      # which of your names it's posted under
    campaign_id: Optional[int] = None     # the push it's part of
    place: Optional[str] = None           # where on the platform: a subreddit, a channel, a group
    inquiries: Optional[int] = None       # how many inquiries or sales it brought, once you know
    also: List["PostTarget"] = []         # the same post on other platforms: one more row each (new posts only)


class PostTarget(BaseModel):
    """One more place the same post goes. Anything left out is taken from the main post."""
    platform: str
    account: Optional[str] = None
    place: Optional[str] = None
    caption: Optional[str] = None
    scheduled_at: Optional[datetime] = None


PostIn.model_rebuild()


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _check_post(body: PostIn):
    body.platform = (body.platform or "").strip()
    if not body.platform or len(body.platform) > 60:
        raise HTTPException(status_code=400, detail="Which platform is it for?")
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")
    if body.price is not None and not (0 <= body.price < float("inf")):
        raise HTTPException(status_code=400, detail="The price must be 0 or more")
    if len(body.caption or "") > 10000:
        raise HTTPException(status_code=400, detail="That caption is too long")
    if body.post_url and not re.match(r"https?://", body.post_url.strip()):
        raise HTTPException(status_code=400, detail="The link to the post must start with https://")
    if len(body.file_paths) > 200 or len(body.repeat_dates) > 52 or len(body.also) > 20:
        raise HTTPException(status_code=400, detail="Too many files, repeats or platforms")
    if body.inquiries is not None and not (0 <= body.inquiries <= 1_000_000):
        raise HTTPException(status_code=400, detail="Inquiries must be 0 or more")
    body.place = (body.place or "").strip()[:120] or None
    body.set_path = clean_path(body.set_path) or None
    body.file_paths = list(dict.fromkeys(clean_path(p) for p in body.file_paths if p))
    if body.status == "posted" and body.posted_at is None:
        body.posted_at = datetime.now(timezone.utc)


def _post_row(r) -> dict:
    d = dict(r)
    d["file_paths"] = json.loads(d["file_paths"] or "[]")
    return d


def get_post(db, post_id: int, owner_id: int) -> Optional[dict]:
    r = db.execute("SELECT * FROM posts WHERE id = ? AND owner_id = ?", (post_id, owner_id)).fetchone()
    return _post_row(r) if r else None


def _warnings(db, owner_id: int, body: PostIn, exclude_id: Optional[int] = None) -> List[str]:
    """Files or a set already posted to this platform, and repost waits that haven't passed."""
    settings = load_settings(db, owner_id)
    wait = settings["repost_days"].get(body.platform) or settings["repost_days"].get(body.platform.lower())
    paths = set(body.file_paths) | ({body.set_path} if body.set_path else set())
    out = []
    for p in db.execute("SELECT * FROM posts WHERE owner_id = ? AND id IS NOT ? AND status = 'posted' AND LOWER(platform) = LOWER(?)",
                        (owner_id, exclude_id, body.platform)):
        used = paths & ({*json.loads(p["file_paths"] or "[]"), *([p["set_path"]] if p["set_path"] else [])})
        if not used:
            continue
        when = p["posted_at"] or p["scheduled_at"]
        label = ", ".join(sorted(used)[:3]) + (f" and {len(used) - 3} more" if len(used) > 3 else "")
        note = f"Already posted to {p['platform']}{' on ' + when[:10] if when else ''}: {label}"
        if wait and when:
            ready = datetime.fromisoformat(when) + timedelta(days=wait)
            planned = body.scheduled_at or datetime.now(timezone.utc)
            planned = planned if planned.tzinfo else planned.replace(tzinfo=timezone.utc)
            if planned < ready:
                note += f" (your {wait}-day wait for {p['platform']} ends {ready.date().isoformat()})"
        out.append(note)
    out += campaigns.place_warnings(db, owner_id, body.platform, body.place, body.scheduled_at, exclude_id)
    return out


@router.get("/api/posts")
def list_posts(request: Request, start: Optional[datetime] = None, end: Optional[datetime] = None,
               status: Optional[str] = None, campaign_id: Optional[int] = None, limit: int = Query(500, ge=1, le=2000)):
    conditions, params = ["owner_id = ?"], [request.state.user["id"]]
    if campaign_id is not None:
        conditions.append("campaign_id = ?")
        params.append(campaign_id)
    if start:
        conditions.append("COALESCE(posted_at, scheduled_at) >= ?")
        params.append(_iso(start))
    if end:
        conditions.append("COALESCE(posted_at, scheduled_at) < ?")
        params.append(_iso(end))
    if status == "open":
        conditions.append("status IN ('idea', 'ready', 'scheduled')")
    elif status:
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status")
        conditions.append("status = ?")
        params.append(status)
    db = _get_db()
    try:
        return [_post_row(r) for r in db.execute(
            f"SELECT * FROM posts WHERE {' AND '.join(conditions)} "
            "ORDER BY COALESCE(posted_at, scheduled_at) IS NULL, COALESCE(posted_at, scheduled_at), id LIMIT ?", (*params, limit))]
    finally:
        db.close()


def _values(body: PostIn, scheduled: Optional[datetime]) -> tuple:
    return (body.platform, (body.account or "").strip() or None, _iso(scheduled), body.status, (body.caption or "").strip() or None,
            body.price, body.set_path, json.dumps(body.file_paths), _iso(body.posted_at), (body.post_url or "").strip() or None,
            (body.notes or "").strip() or None, body.campaign_id, body.place, body.inquiries)


def _queue_sync(post_ids, owner_id):
    import calendar_sync
    for post_id in post_ids:
        calendar_sync.queue_item("post", post_id, owner_id)


@router.post("/api/posts", status_code=201)
def create_post(body: PostIn, request: Request):
    """Plan a post (or a repeating series). Answers with the post and any warnings about reposting."""
    _check_post(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        campaigns.check_campaign(db, owner, body.campaign_id)
        # The post itself, then the same post for each other platform it also goes to.
        versions = [body]
        for target in body.also:
            copy = body.model_copy(update={
                "platform": target.platform, "account": target.account or None, "place": target.place,
                "caption": target.caption if (target.caption or "").strip() else body.caption,
                "scheduled_at": target.scheduled_at or body.scheduled_at, "also": [], "repeat_dates": [],
                "post_url": None, "inquiries": None})
            _check_post(copy)
            versions.append(copy)
        warnings = [w for v in versions for w in _warnings(db, owner, v)]
        now = _now()
        series = uuid.uuid4().hex if body.repeat_dates else None
        ids = []
        for version in versions:
            for when in [version.scheduled_at, *version.repeat_dates]:
                cur = db.execute("""
                    INSERT INTO posts (platform, account, scheduled_at, status, caption, price, set_path, file_paths, posted_at,
                                       post_url, notes, campaign_id, place, inquiries, series_id, owner_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (*_values(version, when), series if version is body else None, owner, now, now))
                ids.append(cur.lastrowid)
                personas.assign(db, "posts", cur.lastrowid, owner, body)
        db.commit()
        _queue_sync(ids, owner)
        return {**get_post(db, ids[0], owner), "warnings": warnings, "created": len(ids)}
    finally:
        db.close()


@router.put("/api/posts/{post_id}")
def update_post(post_id: int, body: PostIn, request: Request):
    _check_post(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        if not get_post(db, post_id, owner):
            raise HTTPException(status_code=404, detail="Post not found")
        campaigns.check_campaign(db, owner, body.campaign_id)
        warnings = _warnings(db, owner, body, exclude_id=post_id)
        db.execute("""
            UPDATE posts SET platform = ?, account = ?, scheduled_at = ?, status = ?, caption = ?, price = ?, set_path = ?,
                   file_paths = ?, posted_at = ?, post_url = ?, notes = ?, campaign_id = ?, place = ?, inquiries = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_values(body, body.scheduled_at), _now(), post_id, owner))
        personas.assign(db, "posts", post_id, owner, body)
        db.commit()
        _queue_sync([post_id], owner)
        return {**get_post(db, post_id, owner), "warnings": warnings}
    finally:
        db.close()


class Posted(BaseModel):
    post_url: Optional[str] = None
    posted_at: Optional[datetime] = None
    inquiries: Optional[int] = None


@router.post("/api/posts/{post_id}/posted")
def mark_posted(post_id: int, body: Posted, request: Request):
    """It went up: when, and (optionally) the link to it."""
    owner = request.state.user["id"]
    if body.post_url and not re.match(r"https?://", body.post_url.strip()):
        raise HTTPException(status_code=400, detail="The link to the post must start with https://")
    db = _get_db()
    try:
        if not get_post(db, post_id, owner):
            raise HTTPException(status_code=404, detail="Post not found")
        if body.inquiries is not None and not (0 <= body.inquiries <= 1_000_000):
            raise HTTPException(status_code=400, detail="Inquiries must be 0 or more")
        db.execute("UPDATE posts SET status = 'posted', posted_at = ?, post_url = COALESCE(?, post_url), "
                   "inquiries = COALESCE(?, inquiries), updated_at = ? WHERE id = ? AND owner_id = ?",
                   (_iso(body.posted_at or datetime.now(timezone.utc)), (body.post_url or "").strip() or None, body.inquiries,
                    _now(), post_id, owner))
        db.commit()
        _queue_sync([post_id], owner)
        return get_post(db, post_id, owner)
    finally:
        db.close()


@router.delete("/api/posts/{post_id}", status_code=204)
def delete_post(post_id: int, request: Request, scope: str = Query("one")):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        post = get_post(db, post_id, owner)
        if not post:
            return
        ids = [post_id]
        if scope == "following" and post["series_id"]:
            ids = [r[0] for r in db.execute("SELECT id FROM posts WHERE owner_id = ? AND series_id = ? AND id >= ?",
                                            (owner, post["series_id"], post_id))]
        for one in ids:
            db.execute("DELETE FROM posts WHERE id = ? AND owner_id = ?", (one, owner))
        db.commit()
        _queue_sync(ids, owner)
    finally:
        db.close()
