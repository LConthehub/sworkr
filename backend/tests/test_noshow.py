"""Tests for deposits, cancellations and no-shows.
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
    name = "s-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)

from datetime import datetime, timezone  # noqa: E402


def booking(api, client_id, when, rate=400, paid=0):
    return ok(api.post("/api/appointments", json={"client_id": client_id, "service_type": "Dinner", "duration_minutes": 60,
                                                  "scheduled_date": when, "rate": rate, "amount_paid": paid}), 201)


def cancel(api, a, **params):
    return ok(api.put(f"/api/appointments/{a['id']}/status", params={"status": "cancelled", **params}))


def test_policy_suggests_fees_for_no_shows_and_late_cancellations(api):
    pol = ok(api.put("/api/booking-policy", json={"deposit_percent": 25, "late_cancel_hours": 48,
                                                  "late_cancel_fee_percent": 50, "no_show_fee_percent": 100}))
    assert pol["late_cancel_hours"] == 48
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    soon = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()

    late = cancel(api, booking(api, sam["id"], soon, paid=100), cancel_reason="client")
    assert (late["cancel_reason"], late["cancellation_fee"]) == ("late", 200)       # inside 48 hours
    in_time = cancel(api, booking(api, sam["id"], later), cancel_reason="client")
    assert (in_time["cancel_reason"], in_time["cancellation_fee"]) == ("client", None)
    gone = cancel(api, booking(api, sam["id"], "2044-01-01T20:00:00Z"), cancel_reason="no_show", cancellation_fee=300)
    assert (gone["cancel_reason"], gone["cancellation_fee"]) == ("no_show", 300)   # your own figure wins
    mine = cancel(api, booking(api, sam["id"], later), cancel_reason="me")
    assert mine["cancellation_fee"] is None
    assert api.put(f"/api/appointments/{mine['id']}/status", params={"status": "cancelled", "cancel_reason": "x"}).status_code == 400
    # Back on: the reason and fee go.
    back = ok(api.put(f"/api/appointments/{mine['id']}/status", params={"status": "scheduled"}))
    assert back["cancel_reason"] is None

    stats = ok(api.get(f"/api/clients/{sam['id']}/summary"))["stats"]
    assert (stats["no_shows"], stats["late_cancellations"]) == (1, 1)
    assert stats["fees_owed"] == 100 + 300 and stats["outstanding"] == 400     # fees less deposits paid
    assert api.put("/api/booking-policy", json={"no_show_fee_percent": 150}).status_code == 400


def test_a_clients_record_is_shown_and_warned_about(api):
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    cancel(api, booking(api, sam["id"], "2044-01-01T20:00:00Z", paid=100), cancel_reason="no_show", cancellation_fee=400)
    r = api.post("/api/appointments", params={"warn": True}, json={
        "client_id": sam["id"], "service_type": "Dinner", "duration_minutes": 60, "scheduled_date": "2044-02-01T20:00:00Z"})
    assert r.status_code == 409
    msg = next(w for w in r.json()["detail"]["warnings"] if w["type"] == "unreliable")["message"]
    assert msg == "Sam didn't turn up 1 time (of 1 bookings), and still owes $300.00 in cancellation fees"


def test_marking_a_cancellation_fee_paid(api):
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    a = cancel(api, booking(api, sam["id"], "2044-01-01T20:00:00Z", paid=100), cancel_reason="no_show", cancellation_fee=250)
    paid = ok(api.post(f"/api/appointments/{a['id']}/mark-paid"))
    assert paid["amount_paid"] == 250
    assert ok(api.get(f"/api/clients/{sam['id']}/summary"))["stats"]["fees_owed"] == 0
