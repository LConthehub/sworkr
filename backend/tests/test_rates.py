"""The rate card, deposits to collect, and clients on an old rate.
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
NOW = datetime.now(timezone.utc)
at = lambda days: (NOW + timedelta(days=days)).isoformat()   # noqa: E731


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "rt-" + uuid.uuid4().hex[:8]
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


def person(api, name, **more):
    return ok(api.post("/api/clients", json={"name": name, **more}), 201)


def book(api, client_id, days, service, minutes, rate, paid=0, status="scheduled"):
    return ok(api.post("/api/appointments", params={"warn": "false"}, json={
        "client_id": client_id, "service_type": service, "duration_minutes": minutes, "scheduled_date": at(days),
        "rate": rate, "amount_paid": paid, "status": status}), 201)


def test_the_rate_card(api):
    scarlett = ok(api.post("/api/personas", json={"name": "Scarlett"}), 201)
    ok(api.post("/api/rates", json={"label": "  Dinner   date ", "minutes": 120, "price": 700, "notes": "Outcall +$100"}), 201)
    hour = ok(api.post("/api/rates", json={"label": "One hour", "minutes": 60, "price": 400, "persona_id": scarlett["id"]}), 201)
    ok(api.post("/api/rates", json={"label": "Overnight", "price": 3000}), 201)
    rates = ok(api.get("/api/rates"))
    assert [(r["label"], r["minutes"], r["price"], r["persona_name"]) for r in rates] == [
        ("Dinner date", 120, 700, None), ("Overnight", None, 3000, None), ("One hour", 60, 400, "Scarlett")]
    raised = ok(api.put(f"/api/rates/{hour['id']}", json={"label": "One hour", "minutes": 60, "price": 450, "archived": True}))
    assert (raised["price"], raised["archived"], raised["persona_name"]) == (450, True, None)
    assert api.post("/api/rates", json={"label": " ", "price": 5}).status_code == 400
    assert api.post("/api/rates", json={"label": "x", "price": -5}).status_code == 400
    assert api.post("/api/rates", json={"label": "x", "price": 5, "minutes": 0}).status_code == 400
    assert api.post("/api/rates", json={"label": "x", "price": 5, "persona_id": 999999}).status_code == 400
    assert api.put("/api/rates/999999", json={"label": "x", "price": 5}).status_code == 404
    ok(api.delete(f"/api/rates/{hour['id']}"), 204)
    assert len(ok(api.get("/api/rates"))) == 2


def test_deposits_to_collect(api):
    a, b, c = person(api, "Avery"), person(api, "Blake"), person(api, "Casey")
    book(api, a["id"], 3, "Dinner date", 120, 800)                  # nothing in yet
    book(api, b["id"], 5, "Dinner date", 120, 800, paid=100)        # part of the deposit
    book(api, c["id"], 7, "Overnight", 600, 3000, paid=750)         # deposit paid
    book(api, a["id"], -2, "Dinner date", 120, 800, status="completed")
    none_set = ok(api.get("/api/rates/deposits"))
    assert (none_set["deposit_percent"], none_set["to_collect"], none_set["bookings_ahead"], none_set["held"]) == (0, [], 3, 850)

    ok(api.put("/api/booking-policy", json={"deposit_percent": 25, "late_cancel_hours": 24, "late_cancel_fee_percent": 50, "no_show_fee_percent": 100}))
    data = ok(api.get("/api/rates/deposits"))
    assert [(d["client_name"], d["deposit"], d["missing"]) for d in data["to_collect"]] == [("Avery", 200, 200), ("Blake", 200, 100)]
    assert (data["missing"], data["held"]) == (300, 850)


def test_clients_on_an_old_rate(api):
    ok(api.post("/api/rates", json={"label": "Dinner date", "minutes": 120, "price": 800}), 201)
    ok(api.post("/api/rates", json={"label": "One hour", "minutes": 60, "price": 450}), 201)
    old, current, mixed, gone = person(api, "Old rate"), person(api, "Current"), person(api, "Mixed"), person(api, "Blocked", do_not_see=True)
    book(api, old["id"], -90, "dinner date", 120, 600, status="completed")
    book(api, old["id"], -30, "Dinner date", 120, 650, status="completed")       # their latest is what counts
    book(api, current["id"], -10, "Dinner date", 120, 800, status="completed")
    book(api, mixed["id"], -20, "One hour", 60, 300, status="completed")
    book(api, mixed["id"], -5, "Dinner date", 180, 500, status="completed")      # a length that isn't on the card
    book(api, gone["id"], -5, "One hour", 60, 100, status="completed")
    rows = ok(api.get("/api/rates/behind"))
    assert [(r["client_name"], r["service"], r["their_rate"], r["card_rate"], r["gap"], r["bookings"]) for r in rows] == [
        ("Mixed", "One hour", 300, 450, 150, 2), ("Old rate", "Dinner date", 650, 800, 150, 2)]
    assert ok(api.get("/api/rates/behind"))[1]["last_booked"][:10] == at(-30)[:10]


def test_people_only_see_their_own(api, admin):
    rate = ok(api.post("/api/rates", json={"label": "Mine", "price": 1}), 201)
    other = new_user(admin)
    assert ok(other.get("/api/rates")) == [] and ok(other.get("/api/rates/behind")) == []
    assert other.put(f"/api/rates/{rate['id']}", json={"label": "Theirs", "price": 2}).status_code == 404
    other.delete(f"/api/rates/{rate['id']}")
    assert len(ok(api.get("/api/rates"))) == 1
    for path in ("/api/rates", "/api/rates/deposits", "/api/rates/behind"):
        assert TestClient(main.app).get(path).status_code == 401
