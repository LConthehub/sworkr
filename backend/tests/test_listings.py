"""Ad listings: an ad that runs, expires and is renewed, with the cost logged as an expense.
Run with:  docker compose run --rm tests"""
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

PASSWORD = "correct-horse-battery"
TODAY = datetime.now(timezone.utc).date()
day = lambda n: (TODAY + timedelta(days=n)).isoformat()   # noqa: E731


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "ls-" + uuid.uuid4().hex[:8]
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


def listing(api, site, **more):
    return ok(api.post("/api/listings", json={"site": site, **more}), 201)


def test_listings_are_sorted_by_what_needs_attention(api):
    listing(api, "Slixa", end_date=day(20), cost=90, renew_days=30)
    listing(api, "Tryst", title="Chicago", end_date=day(2), cost=60, renew_days=30)
    listing(api, "Eros", end_date=day(-1), cost=250, renew_days=30)
    listing(api, "Leolist", end_date=day(10), cost=300, renew_days=30, paused=True)
    listing(api, "My website")
    data = ok(api.get("/api/listings"))
    assert [(r["site"], r["state"]) for r in data["listings"]] == [
        ("Eros", "expired"), ("Tryst", "soon"), ("Slixa", "live"), ("My website", "live"), ("Leolist", "paused")]
    assert data["need_attention"] == 2
    assert data["per_month"] == 150                     # Slixa + Tryst: the expired and paused ones aren't running
    tryst = data["listings"][1]
    assert (tryst["days_left"], tryst["per_month"], tryst["spent"], tryst["payments"]) == (2, 60, 0, 0)

    assert api.post("/api/listings", json={"site": " "}).status_code == 400
    assert api.post("/api/listings", json={"site": "X", "cost": -1}).status_code == 400
    assert api.post("/api/listings", json={"site": "X", "renew_days": 0}).status_code == 400
    assert api.post("/api/listings", json={"site": "X", "start_date": day(5), "end_date": day(1)}).status_code == 400
    assert api.post("/api/listings", json={"site": "X", "link": "javascript:alert(1)"}).status_code == 400
    assert api.post("/api/listings", json={"site": "X", "tour_id": 999999}).status_code == 400
    assert api.post("/api/listings", json={"site": "X", "persona_id": 999999}).status_code == 400


def test_renewing_moves_the_end_date_and_logs_the_cost(api):
    ad = listing(api, "Tryst", city="Chicago", end_date=day(2), cost=60, renew_days=30)
    renewed = ok(api.post(f"/api/listings/{ad['id']}/renew", json={}))
    assert renewed["end_date"] == day(32) and renewed["state"] == "live"          # added on to what was left
    assert (renewed["spent"], renewed["payments"]) == (60, 1)
    [expense] = ok(api.get("/api/expenses"))
    assert expense["description"] == "Tryst ad (Chicago): 30 days" and expense["amount"] == 60 and expense["category"] == "marketing"
    assert expense["notes"] == f"Runs until {day(32)}"

    late = listing(api, "Eros", end_date=day(-10), cost=250, renew_days=30, paused=True)
    back = ok(api.post(f"/api/listings/{late['id']}/renew", json={"cost": 200, "days": 7}))
    assert back["end_date"] == day(7) and back["paused"] is False and back["spent"] == 200   # expired: counted from today
    quiet = ok(api.post(f"/api/listings/{late['id']}/renew", json={"log_expense": False}))
    assert quiet["end_date"] == day(37) and quiet["payments"] == 1
    assert len(ok(api.get("/api/expenses"))) == 2

    nothing_set = listing(api, "My website")
    assert api.post(f"/api/listings/{nothing_set['id']}/renew", json={}).status_code == 400    # how long for?
    first = ok(api.post(f"/api/listings/{nothing_set['id']}/renew", json={"days": 365, "cost": 20}))
    assert first["start_date"] == day(0) and first["end_date"] == day(365)
    assert api.post("/api/listings/999999/renew", json={}).status_code == 404

    # the expense is an ordinary one: it can be changed, and it outlives the ad
    ok(api.put(f"/api/expenses/{expense['id']}", json={"description": "Tryst ad", "amount": 55, "category": "marketing"}))
    assert {r["id"]: r["spent"] for r in ok(api.get("/api/listings"))["listings"]}[ad["id"]] == 55
    ok(api.delete(f"/api/listings/{ad['id']}"), 204)
    assert len(ok(api.get("/api/expenses"))) == 3


def test_ad_spend_shows_against_the_clients_it_brought(api):
    ad = listing(api, "Tryst", cost=120, renew_days=30)
    ok(api.post(f"/api/listings/{ad['id']}/renew", json={}))
    c = ok(api.post("/api/clients", json={"name": "Avery", "found_via": "tryst"}), 201)
    ok(api.post("/api/appointments", params={"warn": "false"}, json={
        "client_id": c["id"], "service_type": "Dinner", "duration_minutes": 60,
        "scheduled_date": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), "rate": 500, "amount_paid": 500}), 201)
    start, end = (TODAY - timedelta(days=30)).isoformat() + "T00:00:00Z", (TODAY + timedelta(days=30)).isoformat() + "T00:00:00Z"
    [row] = ok(api.get("/api/marketing/found-via", params={"start": start, "end": end}))["rows"]
    assert (row["income"], row["spend"], row["profit"]) == (500, 120, 380)


def test_edit_and_people_only_see_their_own(api, admin):
    ad = listing(api, "Tryst", cost=60, renew_days=30, ad_text="Hello")
    changed = ok(api.put(f"/api/listings/{ad['id']}", json={"site": "Tryst", "title": "Main", "paused": True}))
    assert (changed["title"], changed["state"], changed["cost"], changed["ad_text"]) == ("Main", "paused", None, None)
    other = new_user(admin)
    assert ok(other.get("/api/listings"))["listings"] == []
    assert other.put(f"/api/listings/{ad['id']}", json={"site": "Theirs"}).status_code == 404
    assert other.post(f"/api/listings/{ad['id']}/renew", json={"days": 5}).status_code == 404
    other.delete(f"/api/listings/{ad['id']}")
    assert len(ok(api.get("/api/listings"))["listings"]) == 1
    assert TestClient(main.app).get("/api/listings").status_code == 401
