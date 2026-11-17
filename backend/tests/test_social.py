"""Tests for posting to Bluesky, Mastodon and Reddit (a fake network), auto-posting and post numbers.
Run with:  docker compose run --rm tests"""
import os
import sys
import tempfile
import uuid
from datetime import date, timedelta

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

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
    name = "so-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)


import json  # noqa: E402

import httpx  # noqa: E402

import content  # noqa: E402
import social  # noqa: E402


class Net:
    """A pretend Bluesky, Mastodon and Reddit. Records every request."""

    def __init__(self):
        self.seen = []
        self.fail_post = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.seen.append(req)
        host, path = req.url.host, req.url.path
        if path == "/xrpc/com.atproto.server.createSession":
            body = json.loads(req.content)
            if body["password"] != "app-pass":
                return httpx.Response(401, json={"message": "Invalid identifier or password"})
            return httpx.Response(200, json={"accessJwt": "jwt", "did": "did:plc:me", "handle": body["identifier"]})
        if path == "/xrpc/com.atproto.repo.uploadBlob":
            return httpx.Response(200, json={"blob": {"$type": "blob", "ref": {"$link": "cid"}, "size": len(req.content)}})
        if path == "/xrpc/com.atproto.repo.createRecord":
            if self.fail_post:
                return httpx.Response(500, json={"message": "down"})
            return httpx.Response(200, json={"uri": "at://did:plc:me/app.bsky.feed.post/3abc", "cid": "x"})
        if path == "/xrpc/app.bsky.feed.getPosts":
            return httpx.Response(200, json={"posts": [{"uri": "at://did:plc:me/app.bsky.feed.post/3abc",
                                                        "likeCount": 7, "repostCount": 2, "quoteCount": 1, "replyCount": 3}]})
        if host == "masto.example" and path == "/api/v1/accounts/verify_credentials":
            return httpx.Response(200, json={"acct": "me"})
        if host == "masto.example" and path == "/api/v1/statuses":
            return httpx.Response(200, json={"id": "111", "url": "https://masto.example/@me/111"})
        if host == "masto.example" and path == "/api/v1/statuses/111":
            return httpx.Response(200, json={"favourites_count": 4, "reblogs_count": 1, "replies_count": 0})
        if host == "www.reddit.com":
            return httpx.Response(200, json={"access_token": "tok"})
        if host == "oauth.reddit.com" and path == "/api/submit":
            return httpx.Response(200, json={"json": {"errors": [], "data": {
                "name": "t3_zz", "url": "https://www.reddit.com/r/example/comments/zz/"}}})
        return httpx.Response(404, json={"error": "not here"})


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(social, "TRANSPORT", httpx.MockTransport(n))
    return n


def post(api, **body):
    body.setdefault("platform", "Bluesky")
    p = ok(api.post("/api/posts", json=body), 201)
    return p[0] if isinstance(p, list) else p


def owner_of(api):
    return ok(api.get("/api/auth/status"))["user"]["id"]


def bluesky(api, label="none"):
    return ok(api.post("/api/social/accounts", json={"network": "bluesky", "handle": "@me.bsky.social",
                                                     "password": "app-pass", "label": label}), 201)


def test_facets_mark_links_and_tags_by_byte_position():
    text = "Café ✨ https://example.com/x. #tour"
    link, tag = social.bluesky_facets(text)
    assert text.encode()[link["index"]["byteStart"]:link["index"]["byteEnd"]] == b"https://example.com/x"
    assert tag["features"][0]["tag"] == "tour"


def test_connect_bluesky_checks_the_password_and_never_shows_it(api, net):
    bad = api.post("/api/social/accounts", json={"network": "bluesky", "handle": "me.bsky.social", "password": "nope"})
    assert bad.status_code == 400
    a = bluesky(api, "suggestive")
    assert a["display"] == "me.bsky.social" and a["server"] == "https://bsky.social" and "secret" not in a
    assert "app-pass" not in json.dumps(ok(api.get("/api/social/accounts")))
    db = main.get_db()
    stored = db.execute("SELECT secret FROM social_accounts WHERE id = ?", (a["id"],)).fetchone()[0]
    db.close()
    assert "app-pass" not in stored and stored.startswith("sealed:")


def test_post_now_to_bluesky_with_label_then_numbers(api, net):
    a = bluesky(api, "porn")
    p = post(api, caption="New set is up #tour https://example.com")
    done = ok(api.post(f"/api/posts/{p['id']}/publish", json={"account_id": a["id"]}))
    assert done["status"] == "posted" and done["post_url"] == "https://bsky.app/profile/me.bsky.social/post/3abc"
    record = json.loads(next(r for r in net.seen if r.url.path.endswith("createRecord")).content)["record"]
    assert record["labels"]["values"] == [{"val": "porn"}] and len(record["facets"]) == 2
    assert api.post(f"/api/posts/{p['id']}/publish", json={"account_id": a["id"]}).status_code == 400   # not twice
    assert ok(api.post("/api/social/stats/refresh"))["updated"] == 1
    s = ok(api.get("/api/social/stats"))
    row = next(x for x in s["posts"] if x["id"] == p["id"])
    assert (row["likes"], row["reposts"], row["replies"]) == (7, 3, 3)
    assert s["platforms"][0]["platform"] == "Bluesky"


def test_a_failed_post_keeps_the_reason_and_stays_unposted(api, net):
    a = bluesky(api)
    p = post(api, caption="x" * 301)
    r = api.post(f"/api/posts/{p['id']}/publish", json={"account_id": a["id"]})
    assert r.status_code == 400 and "300" in r.json()["detail"]
    p2 = post(api, caption="Hello")
    net.fail_post = True
    assert api.post(f"/api/posts/{p2['id']}/publish", json={"account_id": a["id"]}).status_code == 400
    db = main.get_db()
    got = content.get_post(db, p2["id"], owner_of(api))
    db.close()
    assert got["status"] != "posted" and "500" in got["post_error"]


def test_mastodon_posts_marked_sensitive_and_once_only(api, net):
    a = ok(api.post("/api/social/accounts", json={"network": "mastodon", "server": "masto.example", "token": "t",
                                                  "label": "nudity"}), 201)
    assert a["display"] == "@me@masto.example"
    p = post(api, platform="Mastodon", caption="Hi")
    done = ok(api.post(f"/api/posts/{p['id']}/publish", json={"account_id": a["id"]}))
    assert done["post_url"] == "https://masto.example/@me/111"
    req = next(r for r in net.seen if r.url.path == "/api/v1/statuses")
    assert b"sensitive=true" in req.content and req.headers["Idempotency-Key"].startswith("sworkr-")
    assert ok(api.post("/api/social/stats/refresh"))["updated"] == 1


def test_reddit_needs_a_subreddit_and_uses_the_first_line_as_title(api, net):
    a = ok(api.post("/api/social/accounts", json={"network": "reddit", "handle": "u/me", "password": "pw",
                                                  "client_id": "cid", "client_secret": "cs", "label": "porn"}), 201)
    p = post(api, platform="Reddit", caption="Visiting Chicago\nDetails in profile")
    assert api.post(f"/api/posts/{p['id']}/publish", json={"account_id": a["id"]}).status_code == 400
    p = post(api, platform="Reddit", place="r/example", caption="Visiting Chicago\nDetails in profile")
    ok(api.post(f"/api/posts/{p['id']}/publish", json={"account_id": a["id"]}))
    sent = next(r for r in net.seen if r.url.path == "/api/submit").content.decode()
    assert "title=Visiting+Chicago" in sent and "sr=example" in sent and "nsfw=true" in sent


def test_scheduled_posts_post_themselves_and_failures_stop(api, net):
    a = bluesky(api)
    due = post(api, caption="Due", scheduled_at="2020-01-01T10:00:00Z", status="scheduled")
    later = post(api, caption="Later", scheduled_at="2099-01-01T10:00:00Z", status="scheduled")
    bad = post(api, caption="y" * 400, scheduled_at="2020-01-01T09:00:00Z", status="scheduled")
    for p in (due, later, bad):
        assert ok(api.post(f"/api/posts/{p['id']}/publish", json={"account_id": a["id"], "when": "scheduled"}))["auto_post"] == 1
    social.run_due(main.get_db)
    owner = owner_of(api)
    db = main.get_db()
    assert content.get_post(db, due["id"], owner)["status"] == "posted"
    assert content.get_post(db, later["id"], owner)["status"] == "scheduled"
    b = content.get_post(db, bad["id"], owner)
    db.close()
    assert b["auto_post"] == 0 and "300" in b["post_error"]


def test_csv_numbers_match_posts_by_link(api):
    p = post(api, platform="X", status="posted", post_url="https://x.com/me/status/42")
    text = "Post Link,Impressions,Likes,Replies\nhttps://www.x.com/me/status/42?s=1,1.2k,30,4\nhttps://x.com/other/1,5,1,0\n"
    r = ok(api.post("/api/social/stats/import", content=text.encode(), headers={"Content-Type": "text/csv"}))
    assert (r["matched"], r["unmatched"]) == (1, 1)
    row = next(x for x in ok(api.get("/api/social/stats"))["posts"] if x["id"] == p["id"])
    assert (row["views"], row["likes"], row["replies"]) == (1200, 30, 4)


def test_accounts_are_private(api, admin, net):
    a = bluesky(api)
    assert all(x["id"] != a["id"] for x in ok(admin.get("/api/social/accounts")))
    p = post(admin, caption="hi")
    assert admin.post(f"/api/posts/{p['id']}/publish", json={"account_id": a["id"]}).status_code == 404
