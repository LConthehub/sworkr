"""Campaigns, the places you post in and their rules, saved text, and one post going to several platforms.
Run with:  docker compose run --rm tests"""
import os
import sys
import tempfile
import uuid

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


def new_user(admin):
    name = "pr-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    return new_user(admin)


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def test_a_campaign_groups_posts_and_shows_progress(api):
    tour = ok(api.post("/api/tours", json={"name": "Chicago", "start_date": "2030-12-03", "end_date": "2030-12-07",
                                           "starts_at": "2030-12-03T00:00:00Z", "ends_at": "2030-12-08T00:00:00Z"}), 201)
    camp = ok(api.post("/api/campaigns", json={"name": " Chicago tour ", "goal": "Fill 6 bookings", "start_date": "2030-11-20",
                                               "end_date": "2030-12-07", "tour_id": tour["id"]}), 201)
    assert camp["name"] == "Chicago tour" and camp["tour_name"] == "Chicago" and camp["posts"] == 0

    first = ok(api.post("/api/posts", json={"platform": "X", "caption": "Chicago, Dec 3-7", "status": "scheduled",
                                            "scheduled_at": "2030-11-21T18:00:00Z", "campaign_id": camp["id"]}), 201)
    ok(api.post("/api/posts", json={"platform": "Reddit", "status": "scheduled", "scheduled_at": "2020-01-01T18:00:00Z",
                                    "campaign_id": camp["id"]}), 201)
    ok(api.post("/api/posts", json={"platform": "Bluesky", "status": "skipped", "campaign_id": camp["id"]}), 201)
    ok(api.post("/api/posts", json={"platform": "X", "caption": "Not part of it"}), 201)
    ok(api.post(f"/api/posts/{first['id']}/posted", json={"inquiries": 4}))

    [row] = ok(api.get("/api/campaigns"))
    assert (row["posts"], row["posted"], row["overdue"], row["inquiries"]) == (2, 1, 1, 4)
    assert row["platforms"] == ["Reddit", "X"]
    assert len(ok(api.get("/api/posts", params={"campaign_id": camp["id"]}))) == 3
    assert ok(api.get(f"/api/posts", params={"status": "posted"}))[0]["inquiries"] == 4

    changed = ok(api.put(f"/api/campaigns/{camp['id']}", json={"name": "Chicago", "archived": True}))
    assert changed["archived"] is True and changed["tour_name"] is None
    assert api.post("/api/campaigns", json={"name": " "}).status_code == 400
    assert api.post("/api/campaigns", json={"name": "Back to front", "start_date": "2030-02-01", "end_date": "2030-01-01"}).status_code == 400
    assert api.post("/api/campaigns", json={"name": "No such tour", "tour_id": 999999}).status_code == 400

    ok(api.delete(f"/api/campaigns/{camp['id']}"), 204)
    assert ok(api.get("/api/campaigns")) == []
    posts = ok(api.get("/api/posts"))
    assert len(posts) == 4 and all(p["campaign_id"] is None for p in posts)      # the posts stay


def test_one_post_goes_to_several_platforms(api):
    camp = ok(api.post("/api/campaigns", json={"name": "Red lace launch"}), 201)
    made = ok(api.post("/api/posts", json={
        "platform": "X", "account": "@me", "caption": "New set out now", "status": "scheduled", "scheduled_at": "2030-05-01T18:00:00Z",
        "campaign_id": camp["id"], "set_path": "Red lace", "file_paths": ["Red lace/01.jpg"],
        "also": [{"platform": "Reddit", "account": "u/me", "place": "r/example", "caption": "[F] New set", "scheduled_at": "2030-05-01T20:00:00Z"},
                 {"platform": "Bluesky"}]}), 201)
    assert made["created"] == 3 and made["platform"] == "X"
    posts = {p["platform"]: p for p in ok(api.get("/api/posts", params={"campaign_id": camp["id"]}))}
    assert set(posts) == {"X", "Reddit", "Bluesky"}
    assert posts["Reddit"]["caption"] == "[F] New set" and posts["Reddit"]["place"] == "r/example"
    assert posts["Reddit"]["scheduled_at"].startswith("2030-05-01T20:00") and posts["Reddit"]["account"] == "u/me"
    assert posts["Bluesky"]["caption"] == "New set out now" and posts["Bluesky"]["account"] is None      # taken from the main post
    assert posts["Bluesky"]["scheduled_at"] == posts["X"]["scheduled_at"]
    assert all(p["file_paths"] == ["Red lace/01.jpg"] and p["status"] == "scheduled" for p in posts.values())
    # each one is its own row afterwards
    ok(api.post(f"/api/posts/{posts['Reddit']['id']}/posted", json={}))
    assert ok(api.get("/api/campaigns"))[0]["posted"] == 1

    assert api.post("/api/posts", json={"platform": "X", "also": [{"platform": " "}]}).status_code == 400
    assert api.post("/api/posts", json={"platform": "X", "campaign_id": 999999}).status_code == 400
    assert api.post("/api/posts", json={"platform": "X", "inquiries": -1}).status_code == 400


def test_places_keep_their_rules_and_warn_when_posting_too_soon(api):
    place = ok(api.post("/api/post-places", json={"platform": "Reddit", "name": "r/example", "wait_days": 3,
                                                  "rules": "Title starts with [F]. Verify first.", "link": "https://example.com/r/example"}), 201)
    assert place["posted"] == 0 and place["free_from"] is None
    assert api.post("/api/post-places", json={"platform": "reddit", "name": "R/Example"}).status_code == 409
    assert api.post("/api/post-places", json={"platform": "Reddit", "name": ""}).status_code == 400
    assert api.post("/api/post-places", json={"platform": "Reddit", "name": "r/other", "link": "javascript:alert(1)"}).status_code == 400
    assert api.post("/api/post-places", json={"platform": "Reddit", "name": "r/other", "wait_days": -1}).status_code == 400

    first = ok(api.post("/api/posts", json={"platform": "Reddit", "place": "r/example", "status": "scheduled",
                                            "scheduled_at": "2030-06-01T18:00:00Z"}), 201)
    assert first["warnings"] == []
    ok(api.post(f"/api/posts/{first['id']}/posted", json={"posted_at": "2030-06-01T18:00:00Z"}))
    [row] = ok(api.get("/api/post-places"))
    assert row["posted"] == 1 and row["last_posted"].startswith("2030-06-01") and row["free_from"].startswith("2030-06-04")

    soon = ok(api.post("/api/posts", json={"platform": "reddit", "place": "R/EXAMPLE", "status": "scheduled",
                                           "scheduled_at": "2030-06-03T12:00:00Z"}), 201)
    assert len(soon["warnings"]) == 1 and "every 3 days" in soon["warnings"][0] and "2030-06-01" in soon["warnings"][0]
    later = ok(api.post("/api/posts", json={"platform": "Reddit", "place": "r/example", "status": "idea",
                                            "scheduled_at": "2030-06-10T12:00:00Z"}), 201)
    assert later["warnings"] == []
    elsewhere = ok(api.post("/api/posts", json={"platform": "Reddit", "place": "r/somewhere", "scheduled_at": "2030-06-02T12:00:00Z"}), 201)
    assert elsewhere["warnings"] == []

    renamed = ok(api.put(f"/api/post-places/{place['id']}", json={"platform": "Reddit", "name": "r/example", "wait_days": None, "archived": True}))
    assert renamed["archived"] is True and renamed["wait_days"] is None and renamed["rules"] is None
    ok(api.delete(f"/api/post-places/{place['id']}"), 204)
    assert ok(api.get("/api/post-places")) == []


def test_saved_text(api):
    s = ok(api.post("/api/snippets", json={"label": " Links ", "body": "Booking: example.com/book\n#tag"}), 201)
    assert s["label"] == "Links"
    ok(api.post("/api/snippets", json={"label": "Sign-off", "body": "xo"}), 201)
    assert [x["label"] for x in ok(api.get("/api/snippets"))] == ["Links", "Sign-off"]
    assert ok(api.put(f"/api/snippets/{s['id']}", json={"label": "Links", "body": "new"}))["body"] == "new"
    assert api.post("/api/snippets", json={"label": "Empty", "body": " "}).status_code == 400
    assert api.put("/api/snippets/999999", json={"label": "x", "body": "y"}).status_code == 404
    ok(api.delete(f"/api/snippets/{s['id']}"), 204)
    assert len(ok(api.get("/api/snippets"))) == 1


def test_people_only_see_and_use_their_own(api, admin):
    camp = ok(api.post("/api/campaigns", json={"name": "Mine"}), 201)
    place = ok(api.post("/api/post-places", json={"platform": "X", "name": "main"}), 201)
    snippet = ok(api.post("/api/snippets", json={"label": "a", "body": "b"}), 201)
    other = new_user(admin)
    assert ok(other.get("/api/campaigns")) == [] and ok(other.get("/api/post-places")) == [] and ok(other.get("/api/snippets")) == []
    assert other.post("/api/posts", json={"platform": "X", "campaign_id": camp["id"]}).status_code == 400
    assert other.put(f"/api/campaigns/{camp['id']}", json={"name": "Theirs"}).status_code == 404
    assert other.put(f"/api/post-places/{place['id']}", json={"platform": "X", "name": "x"}).status_code == 404
    assert other.put(f"/api/snippets/{snippet['id']}", json={"label": "x", "body": "y"}).status_code == 404
    other.delete(f"/api/campaigns/{camp['id']}")
    other.delete(f"/api/post-places/{place['id']}")
    other.delete(f"/api/snippets/{snippet['id']}")
    assert len(ok(api.get("/api/campaigns"))) == 1 and len(ok(api.get("/api/post-places"))) == 1 and len(ok(api.get("/api/snippets"))) == 1
    for path in ("/api/campaigns", "/api/post-places", "/api/snippets"):
        assert TestClient(main.app).get(path).status_code == 401
