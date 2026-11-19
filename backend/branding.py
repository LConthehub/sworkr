"""
The home-screen name and icon, so sworkr doesn't have to look like sworkr on a phone.

When someone adds sworkr to their home screen, the phone takes the name and icon from the app manifest (Android)
and the apple-touch-icon (iPhone). Both are served here without a login, because the phone fetches them that way.

Everyone chooses their own: a plain name ("Notes", "Planner") and any picture. The page asks for them with a key
that belongs to that person (it opens nothing but their chosen name and icon), so two people sharing one sworkr
can each have a different one. An admin's choice is also what everyone gets until they choose their own, and what
the login page uses.

The picture is cut to a square and resized here (Pillow), and kept in the data folder. Nothing else is public.
"""

import base64
import io
import json
import os
import secrets
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/branding")
_get_db: Optional[Callable] = None
SIZES = (180, 192, 512)
MAX_UPLOAD = 8 * 1024 * 1024
DEFAULT_NAME = "Sworkr"


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _dir(user_id: Optional[int] = None, make: bool = True) -> str:
    """The folder a set of icons lives in: the install's own, or one person's."""
    d = os.path.join(os.environ.get("DATA_DIR", "data"), "branding")
    if user_id is not None:
        d = os.path.join(d, f"u{int(user_id)}")
    if make:
        os.makedirs(d, exist_ok=True)
    return d


def _static(name: str) -> Optional[str]:
    """The built-in icon of that name, wherever the pages are (Docker web image, or the desktop app's folder)."""
    for root in (os.environ.get("STATIC_DIR"), os.path.join(os.path.dirname(__file__), "..", "frontend", "public"),
                 os.path.join(os.path.dirname(__file__), "static")):
        if root and os.path.exists(os.path.join(root, name)):
            return os.path.join(root, name)
    return None


def _user_setting(db, user_id: int, key: str) -> Optional[str]:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return r["value"] if r else None


def _set_user(db, user_id: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, value))


def _has_icon(user_id: Optional[int]) -> bool:
    return os.path.exists(os.path.join(_dir(user_id, make=False), "icon-512.png"))


def _user_for_key(db, key: Optional[str]) -> Optional[int]:
    if not key or len(key) > 64:
        return None
    r = db.execute("SELECT user_id FROM user_settings WHERE key = 'brand_key' AND value = ?", (key,)).fetchone()
    return r["user_id"] if r else None


def current(user_id: Optional[int] = None) -> dict:
    """The name and icon one person gets (their own, else the install's), or the install's when nobody is named."""
    db = _get_db()
    try:
        own_name = _user_setting(db, user_id, "home_name") if user_id is not None else None
        r = db.execute("SELECT value FROM settings WHERE key = 'home_name'").fetchone()
        shared_name = r["value"] if r else None
    finally:
        db.close()
    own_icon = user_id is not None and _has_icon(user_id)
    return {"name": own_name or shared_name or DEFAULT_NAME, "custom_icon": own_icon or _has_icon(None),
            "own": bool(own_name) or own_icon}


def _who(k: Optional[str]) -> Optional[int]:
    db = _get_db()
    try:
        return _user_for_key(db, k)
    finally:
        db.close()


@router.get("/manifest.json")
def manifest(k: Optional[str] = Query(None)):
    user_id = _who(k)
    name = current(user_id)["name"]
    tail = f"?k={k}" if user_id is not None else ""
    body = {
        "name": name, "short_name": name[:12], "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#fc4c9c", "theme_color": "#a73178",
        "icons": [{"src": f"/api/branding/icon-{s}.png{tail}", "sizes": f"{s}x{s}", "type": "image/png"} for s in (192, 512)]
                 + [{"src": f"/api/branding/icon-512.png{tail}", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
        # Android: a long press on the home-screen icon offers these. Plain words, so they give nothing away.
        "shortcuts": [{"name": n, "url": u} for n, u in (("Calendar", "/calendar"), ("Money", "/money"), ("Contacts", "/contacts"))],
    }
    return Response(json.dumps(body), media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


def _icon(size: int, k: Optional[str]) -> Response:
    user_id = _who(k)
    path = None
    for owner in ((user_id, None) if user_id is not None else (None,)):
        candidate = os.path.join(_dir(owner, make=False), f"icon-{size}.png")
        if os.path.exists(candidate):
            path = candidate
            break
    if not path:
        path = _static("apple-touch-icon.png" if size == 180 else f"icon-{size}.png")
        if not path:
            raise HTTPException(status_code=404)
    with open(path, "rb") as f:
        return Response(f.read(), media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get("/icon-180.png")
def icon_180(k: Optional[str] = Query(None)):
    return _icon(180, k)


@router.get("/icon-192.png")
def icon_192(k: Optional[str] = Query(None)):
    return _icon(192, k)


@router.get("/icon-512.png")
def icon_512(k: Optional[str] = Query(None)):
    return _icon(512, k)


class BrandingIn(BaseModel):
    name: Optional[str] = None           # empty: back to the shared one, or Sworkr
    icon: Optional[str] = None           # a picture as base64 (data: URL or plain); empty: keep the current one
    reset_icon: bool = False


def make_icons(data: bytes, folder: Optional[str] = None) -> None:
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img.load()
    img = img.convert("RGBA")
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))
    for size in SIZES:
        out = img.resize((size, size), Image.LANCZOS)
        flat = Image.new("RGB", out.size, (255, 255, 255))   # phones show transparency as black on some screens
        flat.paste(out, mask=out.split()[3])
        flat.save(os.path.join(folder or _dir(), f"icon-{size}.png"), "PNG")


def _key(db, user_id: int) -> str:
    key = _user_setting(db, user_id, "brand_key")
    if not key:
        key = secrets.token_urlsafe(18)
        _set_user(db, user_id, "brand_key", key)
        db.commit()
    return key


def _view(user: dict) -> dict:
    db = _get_db()
    try:
        key = _key(db, user["id"])
    finally:
        db.close()
    # An admin's choice is the shared one, so for them "own" and shared are the same thing.
    return {**current(None if user.get("is_admin") else user["id"]), "key": key, "shared": bool(user.get("is_admin"))}


@router.put("")
def save(body: BrandingIn, request: Request):
    """Your own home-screen name and icon. An admin's is also what everyone else gets until they choose."""
    import demo
    if demo.ENABLED:
        raise HTTPException(status_code=403, detail="Some features are only available in the full version.")
    user = request.state.user
    shared = bool(user.get("is_admin"))
    name = (body.name or "").strip()[:30] or None
    db = _get_db()
    try:
        if shared:
            db.execute("INSERT INTO settings (key, value) VALUES ('home_name', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (name,))
        else:
            _set_user(db, user["id"], "home_name", name)
        db.commit()
    finally:
        db.close()
    folder = _dir(None if shared else user["id"])
    if body.reset_icon:
        for size in SIZES:
            try:
                os.remove(os.path.join(folder, f"icon-{size}.png"))
            except FileNotFoundError:
                pass
    elif body.icon:
        raw = body.icon.split(",", 1)[1] if body.icon.startswith("data:") else body.icon
        try:
            data = base64.b64decode(raw, validate=False)
        except ValueError:
            raise HTTPException(status_code=400, detail="That picture couldn't be read")
        if len(data) > MAX_UPLOAD:
            raise HTTPException(status_code=400, detail="That picture is too big (8 MB at most)")
        try:
            make_icons(data, folder)
        except Exception:
            raise HTTPException(status_code=400, detail="That doesn't look like a picture sworkr can use (try a PNG or JPEG)")
    return _view(user)


@router.get("")
def get(request: Request):
    return _view(request.state.user)
