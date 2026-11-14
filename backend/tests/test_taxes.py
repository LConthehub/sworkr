"""Tests for the year-end tax summary.
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
    name = "t-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)


def test_the_year_adds_up_by_kind_of_income_and_main_category(api):
    house = ok(api.post("/api/income-sources", json={"name": "The House", "kind": "brothel", "gift_share_percent": 50}), 201)
    ok(api.post("/api/income", json={"source_id": house["id"], "kind": "shift", "date": "2044-03-01T20:00:00Z", "gross": 1000, "fees": 500}), 201)
    ok(api.post("/api/income", json={"source_id": house["id"], "kind": "gift", "date": "2044-04-01T20:00:00Z", "gross": 2000, "fees": 1000}), 201)
    ok(api.post("/api/income", json={"kind": "tips", "date": "2044-05-01T20:00:00Z", "gross": 100, "status": "pending"}), 201)
    ok(api.post("/api/income", json={"kind": "tips", "date": "2045-01-01T20:00:00Z", "gross": 999}), 201)   # next year
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    ok(api.post("/api/appointments", json={"client_id": sam["id"], "service_type": "Dinner", "duration_minutes": 60,
                                           "scheduled_date": "2044-06-01T20:00:00Z", "status": "completed", "rate": 400, "amount_paid": 400}), 201)
    for cat, amount in (("room_rent", 300), ("workspace", 50), ("marketing", 120)):
        ok(api.post("/api/expenses", json={"description": "x", "amount": amount, "category": cat, "date": "2044-02-01T12:00:00Z"}), 201)

    t = ok(api.get("/api/tax-summary", params={"year": 2044, "set_aside_percent": 25}))
    by_kind = {i["key"]: i for i in t["income"]}
    assert (by_kind["gift"]["gross"], by_kind["gift"]["fees"]) == (2000, 1000)
    assert by_kind["calendar"]["gross"] == 400 and "tips" not in by_kind   # pending isn't income yet
    assert (t["gross_income"], t["fees"], t["total_expenses"]) == (3400, 1500, 470)
    assert t["profit"] == 3400 - 1500 - 470 and t["pending"] == 100
    work = next(g for g in t["expenses"] if g["key"] == "workspace")
    assert work["total"] == 350 and {l["label"] for l in work["lines"]} == {"Room & board", "General"}
    assert t["set_aside"] == {"percent": 25, "amount": round((3400 - 1500 - 470) * 0.25, 2)}


def test_the_year_follows_your_time_zone(api):
    # 1 Jan 2045 at 03:00 UTC is still New Year's Eve 2044 in Los Angeles (UTC-8, getTimezoneOffset 480).
    ok(api.post("/api/income", json={"kind": "tips", "date": "2045-01-01T03:00:00Z", "gross": 50}), 201)
    assert ok(api.get("/api/tax-summary", params={"year": 2044, "tz_offset": 480}))["gross_income"] == 50
    assert ok(api.get("/api/tax-summary", params={"year": 2044}))["gross_income"] == 0


def test_partners_shares_are_left_out(api, admin):
    pal = ok(api.post("/api/clients", json={"name": "Pal", "role": "partner"}), 201)
    inc = ok(api.post("/api/income", json={"kind": "sale", "date": "2044-03-01T20:00:00Z", "gross": 1000}), 201)
    ok(api.put(f"/api/splits/income/{inc['id']}", json={"parties": [{"partner_id": pal["id"], "share_type": "percent", "share_value": 40}]}))
    assert ok(api.get("/api/tax-summary", params={"year": 2044}))["gross_income"] == 600
    assert ok(admin.get("/api/tax-summary", params={"year": 2044}))["gross_income"] == 0
