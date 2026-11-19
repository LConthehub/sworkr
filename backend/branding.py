"""
The home-screen name and icon, so sworkr doesn't have to look like sworkr on a phone.

When someone adds sworkr to their home screen, the phone takes the name and icon from the app manifest (Android)
and the apple-touch-icon (iPhone). Both are served here, before anyone signs in (the phone fetches them that way),
so they are set once for the whole install, by an admin: a plain name ("Notes", "Planner") and any picture.

The picture is cut to a square and resized here (Pillow), and kept in the data folder. Nothing else is public.
"""

import base64
import io
import json
import os
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/branding")
_get_db: Optional[Callable] = None
SIZES = (180, 192, 512)
MAX_UPLOAD = 8 * 1024 * 1024
DEFAULT_NAME = "Sworkr"


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _dir() -> str:
    d = os.path.join(os.environ.get("DATA_DIR", "data"), "branding")
    os.makedirs(d, exist_ok=True)
    return d


def _static(name: str) -> Optional[str]:
    """The built-in icon of that name, wherever the pages are (Docker web image, or the desktop app's folder)."""
    for root in (os.environ.get("STATIC_DIR"), os.path.join(os.path.dirname(__file__), "..", "frontend", "public"),
                 os.path.join(os.path.dirname(__file__), "static")):
        if root and os.path.exists(os.path.join(root, name)):
            return os.path.join(root, name)
    return None


def _setting(key: str) -> Optional[str]:
    db = _get_db()
    try:
        r = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else None
    finally:
        db.close()


def current() -> dict:
    return {"name": _setting("home_name") or DEFAULT_NAME, "custom_icon": os.path.exists(os.path.join(_dir(), "icon-512.png"))}


@router.get("/manifest.json")
def manifest():
    name = current()["name"]
    body = {
        "name": name, "short_name": name[:12], "start_url": "/", "scope": "/", "display": "standalone",
        "background_color": "#fc4c9c", "theme_color": "#a73178",
        "icons": [{"src": f"/api/branding/icon-{s}.png", "sizes": f"{s}x{s}", "type": "image/png"} for s in (192, 512)]
                 + [{"src": "/api/branding/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
        # Android: a long press on the home-screen icon offers these. Plain words, so they give nothing away.
        "shortcuts": [{"name": n, "url": u} for n, u in (("Calendar", "/calendar"), ("Money", "/money"), ("Contacts", "/contacts"))],
    }
    return Response(json.dumps(body), media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


def _icon(size: int) -> Response:
    custom = os.path.join(_dir(), f"icon-{size}.png")
    if os.path.exists(custom):
        path = custom
    else:
        path = _static("apple-touch-icon.png" if size == 180 else f"icon-{size}.png")
        if not path:
            raise HTTPException(status_code=404)
    with open(path, "rb") as f:
        return Response(f.read(), media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get("/icon-180.png")
def icon_180():
    return _icon(180)


@router.get("/icon-192.png")
def icon_192():
    return _icon(192)


@router.get("/icon-512.png")
def icon_512():
    return _icon(512)


class BrandingIn(BaseModel):
    name: Optional[str] = None           # empty: back to Sworkr
    icon: Optional[str] = None           # a picture as base64 (data: URL or plain); empty: keep the current one
    reset_icon: bool = False


def make_icons(data: bytes) -> None:
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
        flat.save(os.path.join(_dir(), f"icon-{size}.png"), "PNG")


@router.put("")
def save(body: BrandingIn, request: Request):
    import demo
    if demo.ENABLED:
        raise HTTPException(status_code=403, detail="Some features are only available in the full version.")
    if not request.state.user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Only the admin can change the home-screen name and icon")
    name = (body.name or "").strip()[:30] or None
    db = _get_db()
    try:
        db.execute("INSERT INTO settings (key, value) VALUES ('home_name', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (name,))
        db.commit()
    finally:
        db.close()
    if body.reset_icon:
        for size in SIZES:
            try:
                os.remove(os.path.join(_dir(), f"icon-{size}.png"))
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
            make_icons(data)
        except Exception:
            raise HTTPException(status_code=400, detail="That doesn't look like a picture sworkr can use (try a PNG or JPEG)")
    return current()


@router.get("")
def get(request: Request):
    return current()
