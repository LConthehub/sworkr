"""Tests for the bad-date list: uploading lists, matching and warnings.
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
    name = "b-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)

LIST = """Phone Number,Name,What happened,City,Date,Level
+1 (555) 123-4567,Dave,Refused to pay,Reno,2026-03-01,
555.987.6543,Rick,Violent,Vegas,03/02/2026,dangerous
,No contact details,Skipped,,,
"""


def test_a_list_is_previewed_imported_and_replaced(api):
    p = ok(api.post("/api/blocklist/preview", json={"csv": LIST}))
    assert p["mapping"] == {"phone": "Phone Number", "name": "Name", "description": "What happened", "area": "City",
                            "reported_on": "Date", "severity": "Level"}
    assert len(p["rows"]) == 3
    r = ok(api.post("/api/blocklist/import", json={"csv": LIST, "list_name": "Reno list", "mapping": p["mapping"]}))
    assert (r["added"], r["skipped"]) == (2, 1)
    entries = {e["name"]: e for e in ok(api.get("/api/blocklist"))["entries"]}
    assert entries["Rick"]["severity"] == "block" and entries["Dave"]["severity"] == "warn"
    assert entries["Rick"]["reported_on"] == "2026-03-02" and entries["Dave"]["phone_key"] == "5551234567"
    # A newer copy of the same list replaces it instead of doubling it.
    r = ok(api.post("/api/blocklist/import", json={"csv": LIST, "list_name": "Reno list", "mapping": p["mapping"]}))
    assert r["replaced"] == 2
    assert ok(api.get("/api/blocklist"))["lists"] == [
        {"list_name": "Reno list", "entries": 2, "updated_at": ok(api.get("/api/blocklist"))["lists"][0]["updated_at"]}]
    assert api.post("/api/blocklist/import", json={"csv": LIST, "list_name": "x", "mapping": {"name": "Name"}}).status_code == 400
    assert api.delete("/api/blocklist", params={"list_name": "Reno list"}).status_code == 204
    assert ok(api.get("/api/blocklist"))["entries"] == []


def test_matching_by_phone_email_and_handle_but_never_name(api):
    ok(api.post("/api/blocklist", json={"phone": "555-123-4567", "description": "Robbed a friend"}), 201)
    ok(api.post("/api/blocklist", json={"handle": "@BadGuy", "severity": "block"}), 201)
    ok(api.post("/api/blocklist", json={"email": "Creep@Example.com"}), 201)
    assert api.post("/api/blocklist", json={"name": "Just a name"}).status_code == 400

    assert len(ok(api.get("/api/blocklist/check", params={"phone": "+1 (555) 123 4567"}))) == 1
    assert len(ok(api.get("/api/blocklist/check", params={"handle": "https://instagram.com/badguy"}))) == 1
    assert len(ok(api.get("/api/blocklist/check", params={"email": "creep@example.com"}))) == 1
    assert ok(api.get("/api/blocklist/check", params={"phone": "555-000-0000"})) == []

    c = ok(api.post("/api/clients", json={"name": "New guy", "handles": [{"platform": "X", "handle": "badguy"}]}), 201)
    found = ok(api.get("/api/blocklist/check", params={"client_id": c["id"]}))
    assert [f["matched_on"] for f in found] == ["handle"] and found[0]["severity"] == "block"


def test_booking_a_matching_contact_warns_first(api):
    ok(api.post("/api/blocklist", json={"phone": "5551234567", "description": "Refused to pay", "list_name": "Reno list"}), 201)
    c = ok(api.post("/api/clients", json={"name": "Dave", "contact_phone": "(555) 123-4567"}), 201)
    booking = {"client_id": c["id"], "service_type": "Dinner", "duration_minutes": 60, "scheduled_date": "2044-05-01T20:00:00Z"}
    r = api.post("/api/appointments", params={"warn": True}, json=booking)
    assert r.status_code == 409
    warning = next(w for w in r.json()["detail"]["warnings"] if w["type"] == "bad_date")
    assert "Reno list" in warning["message"] and "Refused to pay" in warning["message"]
    assert api.post("/api/appointments", json=booking).status_code == 201     # still yours to decide


def test_the_list_is_private(api, admin):
    e = ok(api.post("/api/blocklist", json={"phone": "5551112222"}), 201)
    assert ok(admin.get("/api/blocklist/check", params={"phone": "5551112222"})) == []
    assert admin.put(f"/api/blocklist/{e['id']}", json={"phone": "1"}).status_code in (400, 404)
    admin.delete(f"/api/blocklist/{e['id']}")
    assert len(ok(api.get("/api/blocklist"))["entries"]) == 1


def test_my_list_exports_as_csv_that_imports_back(api, admin):
    ok(api.post("/api/blocklist", json={"phone": "+1 555 222 3333", "name": "=HYPERLINK(1)", "description": "Pushy",
                                        "severity": "block"}), 201)
    r = api.get("/api/blocklist/export")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.text
    assert text.splitlines()[0] == "phone,email,handle,name,description,area,reported_on,severity,list"
    assert "+1 555 222 3333" in text and "'=HYPERLINK(1)" in text      # phone kept, formula defused
    assert "Pushy" not in admin.get("/api/blocklist/export").text      # only your own list
    p = ok(api.post("/api/blocklist/preview", json={"csv": text}))
    assert p["mapping"]["phone"] == "phone" and p["mapping"]["severity"] == "severity"
