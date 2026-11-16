"""
sworkr's pages, served by the API itself, for the desktop app (no separate web server).

In Docker, nginx serves the built pages and passes /api on (frontend/nginx.conf). The desktop app has no nginx,
so this does the same job: the built files from frontend/dist, index.html for every other address (the app
works out the page itself), and the same protective headers nginx adds. Only used when STATIC_DIR is set.
"""

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

# Exactly what nginx.conf sends with the pages: only sworkr's own scripts may run, the page can't be framed, and
# no address leaks to other sites.
PAGE_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                               "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
                               "frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


def mount(app: FastAPI, folder: str) -> None:
    root = os.path.realpath(folder)
    index = os.path.join(root, "index.html")
    if not os.path.isfile(index):
        raise RuntimeError(f"No built pages in {root}: run the frontend build first")

    def _file(path: str):
        """The file for `path` inside the pages folder, or None. Never anything outside it."""
        full = os.path.realpath(os.path.join(root, path))
        if os.path.commonpath([root, full]) == root and os.path.isfile(full):
            return full
        return None

    @app.get("/{path:path}", include_in_schema=False)
    def page(path: str, request: Request):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        found = _file(path) if path else None
        headers = dict(PAGE_HEADERS)
        if request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https":
            headers["Strict-Transport-Security"] = "max-age=31536000"
        if found and path.startswith("assets/"):
            headers["Cache-Control"] = "public, max-age=2592000, immutable"   # fingerprinted names: safe to keep
        else:
            headers["Cache-Control"] = "no-store"
        return FileResponse(found or index, headers=headers)
