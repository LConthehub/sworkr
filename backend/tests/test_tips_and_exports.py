"""Tips (with the house's share), the tax summary as a CSV, and co-workers and crew as one group.
Run with:  docker compose run --rm tests"""
import csv
import io
import os
import sqlite3
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
import migrations  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "tp-" + uuid.uuid4().hex[:8]
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


def test_a_tip_on_a_booking_and_the_houses_share(api):
    house = ok(api.post("/api/income-sources", json={"name": "The Ranch", "kind": "brothel", "tip_share_percent": 50}), 201)
    assert house["tip_share_percent"] == 50
    avery = ok(api.post("/api/clients", json={"name": "Avery"}), 201)
    booking = ok(api.post("/api/appointments", params={"warn": "false"}, json={
        "client_id": avery["id"], "service_type": "One hour", "duration_minutes": 60, "scheduled_date": "2026-03-10T19:00:00Z",
        "rate": 400, "amount_paid": 400}), 201)
    assert booking["tip"] is None

    tip = ok(api.post("/api/tips", json={"amount": 100, "appointment_id": booking["id"], "source_id": house["id"]}))
    assert (tip["tip"], tip["house_share"], tip["kept"]) == (100, 50, 50)
    seen = ok(api.get(f"/api/appointments/{booking['id']}"))
    assert (seen["tip"], seen["tip_source_id"], seen["amount_paid"]) == (100, house["id"], 400)      # the tip is on top of what was paid
    [income] = ok(api.get("/api/income"))
    assert (income["kind"], income["gross"], income["fees"], income["client_name"], income["description"]) == ("tips", 100, 50, "Avery", "Tip from Avery")
    assert income["date"].startswith("2026-03-10")

    ok(api.post("/api/tips", json={"amount": 60, "appointment_id": booking["id"]}))                  # changed: all mine this time
    [income] = ok(api.get("/api/income"))
    assert (income["gross"], income["fees"]) == (60, 0)
    ok(api.post("/api/tips", json={"amount": 0, "appointment_id": booking["id"]}))                   # taken away
    assert ok(api.get("/api/income")) == [] and ok(api.get(f"/api/appointments/{booking['id']}"))["tip"] is None

    ok(api.post("/api/tips", json={"amount": 40, "appointment_id": booking["id"]}))
    ok(api.delete(f"/api/appointments/{booking['id']}"), 204)
    assert [i["gross"] for i in ok(api.get("/api/income"))] == [40]                                   # the money was still received

    assert api.post("/api/tips", json={"amount": 0}).status_code == 400
    assert api.post("/api/tips", json={"amount": -5, "appointment_id": 1}).status_code == 400
    assert api.post("/api/tips", json={"amount": 5, "source_id": 999999}).status_code == 400
    assert api.post("/api/tips", json={"amount": 5, "appointment_id": 999999}).status_code == 404
    assert api.post("/api/income-sources", json={"name": "x", "tip_share_percent": 150}).status_code == 400


def test_a_tip_from_quick_add_and_in_the_years_figures(api):
    club = ok(api.post("/api/income-sources", json={"name": "Club", "kind": "club", "tip_share_percent": 20}), 201)
    ok(api.post("/api/tips", json={"amount": 250, "source_id": club["id"], "date": "2026-05-01T03:00:00Z", "note": "Friday night"}))
    ok(api.post("/api/tips", json={"amount": 30, "date": "2026-05-02T03:00:00Z"}))
    year = ok(api.get("/api/tax-summary", params={"year": 2026}))
    tips = next(i for i in year["income"] if i["key"] == "tips")
    assert (tips["gross"], tips["fees"], tips["entries"]) == (280, 50, 2)

    r = api.get("/api/tax-summary/csv", params={"year": 2026})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "tax-summary-2026" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert {"section": "Income", "item": "Tips", "detail": "2 entries", "amount": "280.0"} in rows
    assert {"section": "Totals", "item": "Profit", "detail": "", "amount": "230.0"} in rows
    assert any(row["section"].startswith("Fees") and row["amount"] == "-50.0" for row in rows)
    assert TestClient(main.app).get("/api/tax-summary/csv", params={"year": 2026}).status_code == 401


def test_people_only_tip_their_own_bookings(api, admin):
    avery = ok(api.post("/api/clients", json={"name": "Avery"}), 201)
    booking = ok(api.post("/api/appointments", params={"warn": "false"}, json={
        "client_id": avery["id"], "service_type": "One hour", "duration_minutes": 60, "scheduled_date": "2026-03-10T19:00:00Z", "rate": 400}), 201)
    place = ok(api.post("/api/income-sources", json={"name": "Mine", "tip_share_percent": 10}), 201)
    other = new_user(admin)
    assert other.post("/api/tips", json={"amount": 5, "appointment_id": booking["id"]}).status_code == 404
    assert other.post("/api/tips", json={"amount": 5, "source_id": place["id"]}).status_code == 400
    assert TestClient(main.app).post("/api/tips", json={"amount": 5}).status_code == 401


def test_co_workers_and_crew_are_collaborators(api):
    for role in ("partner", "crew", "co-worker", "collaborator"):
        made = ok(api.post("/api/clients", json={"name": f"A {role}", "role": role}), 201)
        assert made["role"] == "partner"
    assert api.post("/api/clients", json={"name": "x", "role": "boss"}).status_code == 400
    assert len(ok(api.get("/api/clients", params={"role": "partner"}))) == 4
    exported = list(csv.DictReader(io.StringIO(api.get("/api/csv/clients").content.decode("utf-8-sig"))))
    assert {row["role"] for row in exported} == {"collaborator"}
    r = api.post("/api/csv/clients", content=b"name,role\nNew crew,crew\nOld word,co-worker\n", headers={"Content-Type": "text/csv"})
    assert r.status_code == 200, r.text
    assert len(ok(api.get("/api/clients", params={"role": "partner"}))) == 6


def test_upgrading_turns_crew_into_collaborators(tmp_path, monkeypatch):
    path = str(tmp_path / "sworkr.db")
    monkeypatch.setattr(migrations, "LATEST", 31)
    monkeypatch.setattr(migrations, "MIGRATIONS", [m for m in migrations.MIGRATIONS if m[0] <= 31])
    assert migrations.run(path) == 31
    db = sqlite3.connect(path)
    db.execute("INSERT INTO users (id, username, password_hash, is_admin, created_at) VALUES (1, 'u', 'x', 1, 'now')")
    for name, role, industry in (("Photo", "crew", None), ("Driver", "crew", "Driver"), ("Jade", "partner", None), ("Client", "client", "Law")):
        db.execute("INSERT INTO clients (name, display_name, role, industry, owner_id, created_at, updated_at) VALUES (?, ?, ?, ?, 1, 'now', 'now')",
                   (name, name, role, industry))
    db.commit()
    db.close()
    monkeypatch.undo()
    assert migrations.run(path) == migrations.LATEST
    db = sqlite3.connect(path)
    assert db.execute("SELECT name, role, industry FROM clients ORDER BY id").fetchall() == [
        ("Photo", "partner", "Crew"), ("Driver", "partner", "Driver"), ("Jade", "partner", None), ("Client", "client", "Law")]
    db.close()


def test_income_says_how_it_was_paid_and_keeps_a_kelly_cut(api):
    house = ok(api.post("/api/income-sources", json={"name": "The Ranch", "kind": "brothel", "fee_percent": 50, "transport_cut_percent": 20}), 201)
    assert house["transport_cut_percent"] == 20
    # $1,000 booking a driver brought in: 20% off the top ($200), then half of the remaining $800 to the house ($400).
    made = ok(api.post("/api/income", json={"source_id": house["id"], "date": "2026-03-01T12:00:00Z", "kind": "booking", "gross": 1000,
                                            "fees": 600, "transport_cut": 200, "payment_method": "  Cash "}), 201)
    assert (made["fees"], made["transport_cut"], made["payment_method"]) == (600, 200, "Cash")
    changed = ok(api.put(f"/api/income/{made['id']}", json={"source_id": house["id"], "date": "2026-03-01T12:00:00Z", "kind": "booking",
                                                            "gross": 1000, "fees": 500, "payment_method": "Bank transfer"}))
    assert (changed["fees"], changed["transport_cut"], changed["payment_method"]) == (500, None, "Bank transfer")
    tip = ok(api.post("/api/tips", json={"amount": 20, "payment_method": "Cash"}))
    assert [i["payment_method"] for i in ok(api.get("/api/income")) if i["id"] == tip["income_id"]] == ["Cash"]
    assert api.post("/api/income-sources", json={"name": "x", "transport_cut_percent": 101}).status_code == 400
    assert api.post("/api/income", json={"date": "2026-03-01T12:00:00Z", "gross": 10, "transport_cut": -1}).status_code == 400
