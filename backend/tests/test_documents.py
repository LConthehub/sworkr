"""Tests for documents that expire.
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
    name = "d-" + uuid.uuid4().hex[:8]
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


def test_a_document_gets_a_reminder_before_it_runs_out(api):
    expires = TODAY + timedelta(days=100)
    doc = ok(api.post("/api/documents", json={"name": "Work card", "kind": "work_card", "expires_on": expires.isoformat()}), 201)
    task = next(t for t in ok(api.get("/api/tasks")) if t["id"] == doc["task_id"])
    assert (task["title"], task["due_date"]) == ("Renew Work card", (expires - timedelta(days=30)).isoformat())
    # A new date moves the reminder; no date removes it.
    ok(api.put(f"/api/documents/{doc['id']}", json={"name": "Work card", "expires_on": expires.isoformat(), "remind_days_before": 7}))
    assert next(t for t in ok(api.get("/api/tasks")) if t["id"] == doc["task_id"])["due_date"] == (expires - timedelta(days=7)).isoformat()
    ok(api.put(f"/api/documents/{doc['id']}", json={"name": "Work card"}))
    assert doc["task_id"] not in [t["id"] for t in ok(api.get("/api/tasks", params={"status": "all"}))]


def test_one_running_out_soon_is_reminded_today(api):
    doc = ok(api.post("/api/documents", json={"name": "ID check", "kind": "verification",
                                              "expires_on": (TODAY + timedelta(days=5)).isoformat()}), 201)
    assert next(t for t in ok(api.get("/api/tasks")) if t["id"] == doc["task_id"])["due_date"] == TODAY.isoformat()


def test_the_list_includes_renewals_from_places_charges(api):
    house = ok(api.post("/api/income-sources", json={"name": "The House", "kind": "brothel"}), 201)
    ok(api.post(f"/api/income-sources/{house['id']}/charges", json={
        "label": "License", "cadence": "per_quarter", "renews_on": (TODAY + timedelta(days=40)).isoformat()}), 201)
    ok(api.post("/api/documents", json={"name": "Passport", "kind": "passport", "expires_on": (TODAY + timedelta(days=900)).isoformat(),
                                        "source_id": house["id"]}), 201)
    data = ok(api.get("/api/documents"))
    assert [d["name"] for d in data["documents"]] == ["Passport"] and data["documents"][0]["place_name"] == "The House"
    assert [(c["name"], c["days_left"]) for c in data["from_places"]] == [("License", 40)]


def test_documents_are_checked_and_private(api, admin):
    assert api.post("/api/documents", json={"name": "x", "issued_on": "2030-01-02", "expires_on": "2030-01-01"}).status_code == 400
    assert api.post("/api/documents", json={"name": "x", "source_id": 999999}).status_code == 400
    doc = ok(api.post("/api/documents", json={"name": "Mine"}), 201)
    assert admin.put(f"/api/documents/{doc['id']}", json={"name": "Theirs"}).status_code == 404
    assert ok(admin.get("/api/documents"))["documents"] == []
