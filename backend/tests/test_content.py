"""Content library (mounted folder, a real WebDAV server, a pretend Nextcloud, the demo) and the post planner.
Run with:  docker compose run --rm tests"""
import io
import os
import sys
import tempfile
import threading
import uuid

import httpx
import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import calendar_sync  # noqa: E402
import content  # noqa: E402
import demo  # noqa: E402
import main  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    name = "ct-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def png(color=(200, 30, 60), size=(800, 600)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


@pytest.fixture
def library(monkeypatch):
    """A content folder like a mounted NAS share: two sets, an image and a video, and a secret file outside it."""
    root = tempfile.mkdtemp(prefix="sworkr-content-")
    os.makedirs(os.path.join(root, "Content", "2026-11 Red lace"))
    os.makedirs(os.path.join(root, "Content", "Teasers"))
    with open(os.path.join(root, "Content", "2026-11 Red lace", "01.png"), "wb") as f:
        f.write(png())
    with open(os.path.join(root, "Content", "2026-11 Red lace", "02.mp4"), "wb") as f:
        f.write(b"\x00" * 100)
    with open(os.path.join(root, "secret.txt"), "w") as f:
        f.write("not yours")
    monkeypatch.setattr(content, "CONTENT_ROOT", root)
    content._thumbs.items.clear()
    return root


# ---------- paths ----------

@pytest.mark.parametrize("bad", ["../etc/passwd", "a/../../b", "a/./b", "a//b", "a/\x00b"])
def test_paths_cannot_leave_the_library(bad):
    with pytest.raises(Exception):
        content.clean_path(bad)


def test_clean_paths():
    assert content.clean_path("/Set/sub/file.jpg/") == "Set/sub/file.jpg"
    assert content.clean_path("Set\\file.jpg") == "Set/file.jpg"
    assert content.clean_path("") == ""


# ---------- a mounted folder ----------

def test_a_mounted_folder(api, library):
    ok(api.put("/api/content/settings", json={"kind": "folder", "folder": "Content"}))
    top = ok(api.get("/api/content/browse"))
    assert [e["name"] for e in top["entries"]] == ["2026-11 Red lace", "Teasers"] and all(e["folder"] for e in top["entries"])
    inside = ok(api.get("/api/content/browse", params={"path": "2026-11 Red lace"}))["entries"]
    assert [(e["name"], e["kind"]) for e in inside] == [("01.png", "image"), ("02.mp4", "video")]
    thumb = api.get("/api/content/thumbnail", params={"path": "2026-11 Red lace/01.png", "size": 128})
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(thumb.content)).size) == 128
    assert api.get("/api/content/thumbnail", params={"path": "2026-11 Red lace/02.mp4"}).status_code == 404
    assert api.get("/api/content/browse", params={"path": "../"}).status_code == 400
    assert ok(api.post("/api/content/test", json={"kind": "folder", "folder": "Content"}))["sets"] == 2
    assert api.post("/api/content/test", json={"kind": "folder", "folder": "Nowhere"}).status_code == 400


def test_a_link_out_of_the_library_is_refused(api, library):
    os.symlink(os.path.join(library, "secret.txt"), os.path.join(library, "Content", "Teasers", "sneaky.png"))
    ok(api.put("/api/content/settings", json={"kind": "folder", "folder": "Content"}))
    r = api.get("/api/content/thumbnail", params={"path": "Teasers/sneaky.png"})
    assert r.status_code == 502 and "outside" in r.json()["detail"]


def test_not_connected_yet(api):
    r = api.get("/api/content/browse")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_set_up"


def test_settings_never_send_the_password_back(api):
    s = ok(api.put("/api/content/settings", json={"kind": "webdav", "url": "https://nas.example.com:5006/Content",
                                                  "username": "me", "password": "nas-app-pw"}))
    assert s["has_password"] and "nas-app-pw" not in str(s) and s["url"] == "https://nas.example.com:5006/Content"
    assert api.put("/api/content/settings", json={"kind": "dropbox"}).status_code == 400
    assert api.put("/api/content/settings", json={"kind": "webdav", "url": "ftp://x", "username": "a", "password": "b"}).status_code == 400


# ---------- a real WebDAV server (like a Synology with the WebDAV Server package) ----------

@pytest.fixture
def webdav():
    from cheroot import wsgi
    from wsgidav.wsgidav_app import WsgiDAVApp
    root = tempfile.mkdtemp(prefix="sworkr-dav-")
    os.makedirs(os.path.join(root, "Content", "Beach day"))
    with open(os.path.join(root, "Content", "Beach day", "sun & sea.jpg"), "wb") as f:
        out = io.BytesIO()
        Image.new("RGB", (640, 480), (20, 140, 180)).save(out, "JPEG")
        f.write(out.getvalue())
    app = WsgiDAVApp({
        "host": "127.0.0.1", "port": 0, "provider_mapping": {"/dav": root}, "verbose": 0, "logging": {"enable": False},
        "http_authenticator": {"accept_basic": True, "accept_digest": False, "default_to_digest": False},
        "simple_dc": {"user_mapping": {"*": {"me": {"password": "secret"}}}},
    })
    server = wsgi.Server(("127.0.0.1", 0), app)
    server.prepare()
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=server.serve, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/dav/Content"
    server.stop()


def test_a_real_webdav_server(api, webdav):
    settings = {"kind": "webdav", "url": webdav, "username": "me", "password": "secret"}
    assert ok(api.post("/api/content/test", json=settings))["sets"] == 1
    ok(api.put("/api/content/settings", json=settings))
    assert [e["name"] for e in ok(api.get("/api/content/browse"))["entries"]] == ["Beach day"]
    files = ok(api.get("/api/content/browse", params={"path": "Beach day"}))["entries"]
    assert [f["name"] for f in files] == ["sun & sea.jpg"] and files[0]["size"] > 0
    thumb = api.get("/api/content/thumbnail", params={"path": "Beach day/sun & sea.jpg"})
    assert thumb.status_code == 200 and Image.open(io.BytesIO(thumb.content)).size[0] == 256
    bad = api.post("/api/content/test", json={**settings, "password": "wrong"})
    assert bad.status_code == 400 and "rejected" in bad.json()["detail"]


# ---------- Nextcloud ----------

def test_nextcloud_folder_address_and_links():
    url = content.nextcloud_folder_url("cloud.example.com/index.php/apps/files", "lc", "Work/Content sets")
    assert url == "https://cloud.example.com/remote.php/dav/files/lc/Work/Content%20sets/"
    lib = content.WebDavLibrary(url, "lc", "pw", nextcloud=True)
    assert lib.web_link("Red lace/01.jpg") == "https://cloud.example.com/index.php/apps/files/?dir=/Work/Content%20sets/Red%20lace"


def test_nextcloud_previews_are_used_for_thumbnails():
    seen = []

    def server(request: httpx.Request):
        seen.append(request.url.path)
        if request.method == "PROPFIND":
            body = ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
                    '<d:response><d:href>/remote.php/dav/files/lc/Content/Set/</d:href><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>'
                    '<d:response><d:href>/remote.php/dav/files/lc/Content/Set/clip.mp4</d:href><d:propstat><d:prop><d:resourcetype/>'
                    '<d:getcontentlength>99</d:getcontentlength><oc:fileid>4242</oc:fileid></d:prop></d:propstat></d:response></d:multistatus>')
            return httpx.Response(207, content=body.encode())
        if request.url.path == "/index.php/core/preview":
            assert request.url.params["fileId"] == "4242"
            return httpx.Response(200, content=b"JPEGDATA", headers={"content-type": "image/jpeg"})
        return httpx.Response(404)

    lib = content.WebDavLibrary("https://cloud.example.com/remote.php/dav/files/lc/Content/", "lc", "pw", nextcloud=True,
                                transport=httpx.MockTransport(server))
    assert lib.thumbnail("Set/clip.mp4", 256) == b"JPEGDATA"     # Nextcloud can preview videos; sworkr can't
    assert "/index.php/core/preview" in seen


def test_nextcloud_can_use_the_calendar_login(api):
    r = api.put("/api/content/settings", json={"kind": "nextcloud", "url": "cloud.example.com", "folder": "Content",
                                               "use_calendar_login": True})
    assert r.status_code == 400 and "calendar" in r.json()["detail"]
    ok(api.put("/api/calendar-sync", json={"enabled": False, "url": "cloud.example.com", "username": "lc", "app_password": "cal-pw"}))
    s = ok(api.put("/api/content/settings", json={"kind": "nextcloud", "url": "cloud.example.com", "folder": "Content",
                                                  "use_calendar_login": True}))
    assert s["url"] == "https://cloud.example.com/remote.php/dav/files/lc/Content/" and s["has_password"]


# ---------- posts ----------

def post(api, expect=201, **fields):
    body = {"platform": "OnlyFans", "scheduled_at": "2049-01-10T18:00:00Z", **fields}
    return ok(api.post("/api/posts", json=body), expect)


def test_planning_and_posting(api, library):
    ok(api.put("/api/content/settings", json={"kind": "folder", "folder": "Content", "repost_days": {"X": 30}}))
    p = post(api, set_path="2026-11 Red lace", file_paths=["2026-11 Red lace/01.png"], caption="New set! 🔥", price=15,
             status="scheduled", account="@sunny")
    assert (p["status"], p["file_paths"], p["warnings"]) == ("scheduled", ["2026-11 Red lace/01.png"], [])
    done = ok(api.post(f"/api/posts/{p['id']}/posted", json={"post_url": "https://onlyfans.example/post/1"}))
    assert done["status"] == "posted" and done["posted_at"]

    # The library shows where things went.
    sets = {e["name"]: e for e in ok(api.get("/api/content/browse"))["entries"]}
    assert sets["2026-11 Red lace"]["platforms"] == ["OnlyFans"]
    files = {e["name"]: e for e in ok(api.get("/api/content/browse", params={"path": "2026-11 Red lace"}))["entries"]}
    assert files["01.png"]["posts"][0]["platform"] == "OnlyFans" and files["02.mp4"]["posts"] == []

    again = post(api, file_paths=["2026-11 Red lace/01.png"])
    assert "Already posted to OnlyFans" in again["warnings"][0]
    assert post(api, platform="Fansly", file_paths=["2026-11 Red lace/01.png"])["warnings"] == []

    x1 = post(api, platform="X", file_paths=["Teasers/a.jpg"], status="posted", posted_at="2049-01-01T12:00:00Z")
    soon = post(api, platform="X", file_paths=["Teasers/a.jpg"], scheduled_at="2049-01-15T12:00:00Z")
    assert "30-day wait for X ends 2049-01-31" in soon["warnings"][0]
    later = post(api, platform="x", file_paths=["Teasers/a.jpg"], scheduled_at="2049-03-01T12:00:00Z")
    assert "wait" not in later["warnings"][0]
    assert x1["id"]


def test_post_rules_and_listing(api):
    for body in ({"platform": " "}, {"platform": "X", "status": "maybe"}, {"platform": "X", "price": -1},
                 {"platform": "X", "post_url": "javascript:alert(1)"}, {"platform": "X", "file_paths": ["../x"]}):
        assert api.post("/api/posts", json=body).status_code == 400, body
    series = post(api, platform="Reddit", repeat_dates=["2049-02-17T18:00:00Z", "2049-02-24T18:00:00Z"])
    assert series["created"] == 3
    idea = post(api, platform="TikTok", scheduled_at=None, status="idea")
    listed = ok(api.get("/api/posts", params={"start": "2049-02-01T00:00:00Z", "end": "2049-03-01T00:00:00Z"}))
    assert [p["platform"] for p in listed] == ["Reddit", "Reddit"]
    assert idea["id"] in [p["id"] for p in ok(api.get("/api/posts", params={"status": "open"}))]
    api.delete(f"/api/posts/{series['id']}", params={"scope": "following"})
    assert [p for p in ok(api.get("/api/posts")) if p["platform"] == "Reddit"] == []


def test_posts_are_private(api, admin):
    p = post(api, caption="mine")
    assert p["id"] not in [x["id"] for x in ok(admin.get("/api/posts"))]
    assert admin.put(f"/api/posts/{p['id']}", json={"platform": "X"}).status_code == 404
    assert admin.post(f"/api/posts/{p['id']}/posted", json={}).status_code == 404
    admin.delete(f"/api/posts/{p['id']}")
    assert ok(api.get("/api/posts"))[0]["caption"] == "mine"


def test_posts_go_to_the_calendar():
    ics = calendar_sync.post_ics({"id": 5, "platform": "OnlyFans", "account": "@sunny", "status": "scheduled",
                                  "scheduled_at": "2049-01-10T18:00:00+00:00", "posted_at": None,
                                  "updated_at": "2049-01-01T00:00:00+00:00", "caption": "New set"}, discreet=False).decode()
    assert "SUMMARY:Post: OnlyFans (@sunny)" in ics and "DTSTART:20490110T180000Z" in ics and "New set" in ics
    discreet = calendar_sync.post_ics({"id": 5, "platform": "OnlyFans", "account": None, "status": "posted",
                                       "scheduled_at": None, "posted_at": "2049-01-10T18:00:00+00:00",
                                       "updated_at": "2049-01-01T00:00:00+00:00", "caption": "x"}, discreet=True).decode()
    assert "SUMMARY:Posted" in discreet and "OnlyFans" not in discreet


# ---------- the demo ----------

def test_the_demo_has_a_made_up_library(api, monkeypatch):
    monkeypatch.setattr(demo, "ENABLED", True)
    assert api.put("/api/content/settings", json={"kind": "folder", "folder": "x"}).status_code == 403
    sets = ok(api.get("/api/content/browse"))["entries"]
    assert len(sets) >= 3
    files = ok(api.get("/api/content/browse", params={"path": sets[0]["path"]}))["entries"]
    thumb = api.get("/api/content/thumbnail", params={"path": files[0]["path"]})
    assert thumb.status_code == 200 and thumb.content[:2] == b"\xff\xd8"


def test_saved_password_is_never_sent_to_a_different_server(api):
    ok(api.put("/api/content/settings", json={"kind": "webdav", "url": "https://nas.example.com:5006/Content",
                                              "username": "me", "password": "nas-app-pw"}))
    for change in ({"url": "https://attacker.example/Content"}, {"url": "https://nas.example.com:6000/Content"},
                   {"username": "you"}):
        for method, url in (("put", "/api/content/settings"), ("post", "/api/content/test")):
            r = getattr(api, method)(url, json={"kind": "webdav", "url": "https://nas.example.com:5006/Content",
                                                "username": "me", **change})
            assert r.status_code == 400 and "password again" in r.json()["detail"], (change, url)
    # Another folder on the same server keeps the saved password.
    assert ok(api.put("/api/content/settings", json={"kind": "webdav", "url": "https://nas.example.com:5006/Other",
                                                     "username": "me"}))["has_password"]


def test_calendar_login_only_goes_to_the_calendar_server(api):
    ok(api.put("/api/calendar-sync", json={"enabled": False, "url": "cloud.example.com", "username": "lc", "app_password": "cal-pw"}))
    for method, url in (("put", "/api/content/settings"), ("post", "/api/content/test")):
        r = getattr(api, method)(url, json={"kind": "nextcloud", "url": "attacker.example", "folder": "Content",
                                            "use_calendar_login": True})
        assert r.status_code == 400 and "different server" in r.json()["detail"]
