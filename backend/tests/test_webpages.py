"""The desktop app's pages, served by the API itself: the built files, index.html for app addresses, the same
protective headers as nginx, and never a file from outside the pages folder.
Run with:  docker compose run --rm tests"""
import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webpages  # noqa: E402


def make(tmp_path):
    pages = tmp_path / "web"
    (pages / "assets").mkdir(parents=True)
    (pages / "index.html").write_text("<html>sworkr</html>")
    (pages / "assets" / "index-abc.js").write_text("console.log(1)")
    (pages / "manifest.json").write_text("{}")
    (tmp_path / "secret.txt").write_text("not for the web")
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}
    webpages.mount(app, str(pages))
    return TestClient(app)


def test_pages_files_and_headers(tmp_path):
    c = make(tmp_path)
    home = c.get("/")
    assert home.status_code == 200 and "sworkr" in home.text
    assert home.headers["content-security-policy"].startswith("default-src 'self'; script-src 'self'")
    assert home.headers["x-frame-options"] == "DENY" and home.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in home.headers
    assert c.get("/money/rates").text == home.text                       # an app address gets the app
    script = c.get("/assets/index-abc.js")
    assert script.text == "console.log(1)" and "immutable" in script.headers["cache-control"]
    assert c.get("/manifest.json").headers["content-type"].startswith("application/json")
    assert c.get("/api/health").json() == {"status": "ok"}             # the API still answers
    assert c.get("/api/nothing-here").status_code == 404               # an unknown API address isn't the app
    assert "max-age" in c.get("/", headers={"X-Forwarded-Proto": "https"}).headers["strict-transport-security"]


def test_nothing_outside_the_pages_folder(tmp_path):
    c = make(tmp_path)
    for attempt in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt"):
        r = c.get(attempt)
        assert "not for the web" not in r.text, attempt
