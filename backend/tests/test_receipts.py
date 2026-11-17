"""Tests for discreet receipts: neutral wording, numbering, reprints as issued, privacy.
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
    name = "rc-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()




def booking(api, when="2044-03-02T19:00:00Z", rate=400, paid=400, method="Cash"):
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    return ok(api.post("/api/appointments", json={"client_id": sam["id"], "service_type": "Dinner", "duration_minutes": 60,
                                                  "scheduled_date": when, "rate": rate, "amount_paid": paid,
                                                  "payment_method": method}), 201)


def test_settings_have_discreet_defaults_and_can_change(api):
    s = ok(api.get("/api/receipts/settings"))
    assert s["service"] == "Consulting services" and s["business"] == "" and s["prefix"] == "R"
    s = ok(api.put("/api/receipts/settings", json={"business": "Lake Street Wellness", "service": "Coaching session",
                                                   "contact": "hello@example.com", "footer": "Thanks!", "prefix": "lsw-1"}))
    assert (s["business"], s["prefix"]) == ("Lake Street Wellness", "LSW1")


def test_a_receipt_from_a_booking_uses_its_amount_date_and_method(api):
    ok(api.put("/api/receipts/settings", json={"business": "Lake Street Wellness", "service": "Coaching session",
                                               "contact": "", "footer": "Thanks!", "prefix": "R"}))
    a = booking(api)
    r = ok(api.post("/api/receipts", json={"appointment_id": a["id"], "billed_to": "S. Smith"}), 201)
    assert (r["number"], r["issued_on"], r["amount"], r["method"]) == ("R-2044-001", "2044-03-02", 400, "Cash")
    assert (r["description"], r["business"], r["footer"], r["billed_to"]) == ("Coaching session", "Lake Street Wellness", "Thanks!", "S. Smith")
    assert "Dinner" not in str(r) and "Sam" not in str(r)       # nothing about the booking itself
    second = ok(api.post("/api/receipts", json={"appointment_id": a["id"], "amount": 50, "description": "Extra time"}), 201)
    assert second["number"] == "R-2044-002" and second["description"] == "Extra time"
    assert [x["number"] for x in ok(api.get("/api/receipts", params={"appointment_id": a["id"]}))] == ["R-2044-002", "R-2044-001"]


def test_reprints_keep_the_wording_they_were_issued_with(api):
    ok(api.put("/api/receipts/settings", json={"business": "Old Name", "service": "Services", "contact": "", "footer": "", "prefix": "R"}))
    r = ok(api.post("/api/receipts", json={"amount": 120, "date": "2045-01-05"}), 201)
    ok(api.put("/api/receipts/settings", json={"business": "New Name", "service": "Services", "contact": "", "footer": "", "prefix": "R"}))
    assert ok(api.get(f"/api/receipts/{r['id']}"))["business"] == "Old Name"
    assert ok(api.post("/api/receipts", json={"amount": 5, "date": "2046-01-01"}), 201)["number"] == "R-2046-001"   # new year, new count


def test_bad_receipts_are_refused_and_others_cant_see_them(api, admin):
    assert api.post("/api/receipts", json={"amount": 0}).status_code == 400
    assert api.post("/api/receipts", json={"amount": 10, "date": "soon"}).status_code == 400
    assert api.post("/api/receipts", json={"appointment_id": 999999}).status_code == 404
    r = ok(api.post("/api/receipts", json={"amount": 10}), 201)
    assert admin.get(f"/api/receipts/{r['id']}").status_code == 404
    assert api.delete(f"/api/receipts/{r['id']}").status_code == 204
    assert api.get(f"/api/receipts/{r['id']}").status_code == 404
