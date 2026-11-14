"""Tests for arrangements (allowances) and the mileage log.
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
    name = "a-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)

TODAY = date.today()


def test_an_allowance_reminds_and_moves_on_when_received(api):
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    due = TODAY + timedelta(days=3)
    a = ok(api.put(f"/api/clients/{sam['id']}/arrangement", json={"amount": 1500, "cadence": "monthly", "next_due": due.isoformat()}))
    task = next(t for t in ok(api.get("/api/tasks")) if t["id"] == a["task_id"])
    assert (task["title"], task["due_date"], task["client_id"]) == ("Allowance due from Sam", due.isoformat(), sam["id"])

    r = ok(api.post(f"/api/clients/{sam['id']}/arrangement/received", json={}), 201)
    income = next(i for i in ok(api.get("/api/income")) if i["id"] == r["income_id"])
    assert (income["kind"], income["gross"], income["client_id"]) == ("allowance", 1500, sam["id"])
    nxt = date.fromisoformat(r["arrangement"]["next_due"])
    assert nxt > due and (nxt - due).days in (28, 29, 30, 31)
    assert next(t for t in ok(api.get("/api/tasks")) if t["id"] == a["task_id"])["due_date"] == nxt.isoformat()


def test_per_meet_has_no_schedule_and_stopping_removes_the_reminder(api):
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    a = ok(api.put(f"/api/clients/{sam['id']}/arrangement", json={"amount": 500, "cadence": "per_meet", "next_due": TODAY.isoformat()}))
    assert a["next_due"] is None and a["task_id"] is None
    ok(api.post(f"/api/clients/{sam['id']}/arrangement/received", json={"amount": 600}), 201)
    b = ok(api.put(f"/api/clients/{sam['id']}/arrangement", json={"amount": 500, "cadence": "weekly", "next_due": TODAY.isoformat()}))
    assert b["task_id"]
    ok(api.put(f"/api/clients/{sam['id']}/arrangement", json={"amount": 500, "cadence": "weekly", "next_due": TODAY.isoformat(), "active": False}))
    assert b["task_id"] not in [t["id"] for t in ok(api.get("/api/tasks", params={"status": "all"}))]
    assert api.put(f"/api/clients/{sam['id']}/arrangement", json={"cadence": "yearly"}).status_code == 400


def test_arrangements_are_private(api, admin):
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    ok(api.put(f"/api/clients/{sam['id']}/arrangement", json={"amount": 1, "cadence": "weekly"}))
    assert admin.get(f"/api/clients/{sam['id']}/arrangement").status_code == 404
    assert admin.post(f"/api/clients/{sam['id']}/arrangement/received", json={}).status_code == 404
    assert all(a["client_id"] != sam["id"] for a in ok(admin.get("/api/arrangements")))


def test_mileage_adds_up_at_the_rate_you_set(api):
    ok(api.post("/api/tax-summary/mileage", json={"date": "2044-03-01", "miles": 12.5, "purpose": "Outcall"}), 201)
    ok(api.post("/api/tax-summary/mileage", json={"date": "2044-03-02", "miles": 30}), 201)
    ok(api.post("/api/tax-summary/mileage", json={"date": "2045-01-02", "miles": 99}), 201)
    m = ok(api.get("/api/tax-summary/mileage", params={"year": 2044}))
    assert (len(m["trips"]), m["miles"], m["rate"], m["deduction"]) == (2, 42.5, None, None)
    ok(api.put("/api/tax-summary/mileage/rate/2044", json={"rate": 0.7}))
    assert ok(api.get("/api/tax-summary", params={"year": 2044}))["mileage"]["deduction"] == round(42.5 * 0.7, 2)
    assert api.post("/api/tax-summary/mileage", json={"date": "2044-03-01", "miles": 0}).status_code == 400


def test_important_dates_show_on_the_calendar(api):
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    soon = TODAY + timedelta(days=10)
    ok(api.put(f"/api/clients/{sam['id']}/arrangement", json={"amount": 100, "cadence": "weekly", "next_due": soon.isoformat()}))
    ok(api.post("/api/documents", json={"name": "Work card", "expires_on": soon.isoformat()}), 201)
    ok(api.post("/api/meds", json={"name": "Depo", "method": "shot", "started_on": (soon - timedelta(days=84)).isoformat(), "discreet": True}), 201)
    ok(api.post("/api/meds", json={"name": "Patch", "method": "patch", "started_on": (soon - timedelta(days=7)).isoformat(), "discreet": False}), 201)
    dates = ok(api.get("/api/calendar/dates", params={"start": TODAY.isoformat(), "end": (TODAY + timedelta(days=30)).isoformat()}))
    on_day = {(d["kind"], d["label"]) for d in dates if d["date"] == soon.isoformat()}
    assert {("money", "Allowance due from Sam"), ("document", "Work card runs out"), ("health", "Health"),
            ("health", "Change the patch")} <= on_day
    assert api.get("/api/calendar/dates", params={"start": "2044-01-01", "end": "2046-01-01"}).status_code == 400
