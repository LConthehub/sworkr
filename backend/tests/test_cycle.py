"""Cycle tracking: opt-in, averages, predictions, calendar days, booking warnings and privacy.
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
TODAY = "2050-03-01"


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    name = "cy-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def log(api, start, end=None, **fields):
    return ok(api.post("/api/cycle/entries", json={"start_date": start, "end_date": end, **fields}), 201)


def history(api):
    log(api, "2050-01-01", "2050-01-05", flow="medium")
    log(api, "2050-01-29", "2050-02-02")
    log(api, "2050-02-26")                              # started, not ended yet


def test_off_until_turned_on(api):
    assert ok(api.get("/api/cycle/settings"))["enabled"] is False
    history(api)
    assert ok(api.get("/api/cycle/days", params={"start": "2050-03-01", "end": "2050-04-01"})) == []
    ok(api.put("/api/cycle/settings", json={"enabled": True}))
    assert ok(api.get("/api/cycle/days", params={"start": "2050-03-01", "end": "2050-04-01", "today": TODAY}))


def test_averages_today_and_predictions(api):
    ok(api.put("/api/cycle/settings", json={"enabled": True}))
    history(api)
    c = ok(api.get("/api/cycle", params={"today": TODAY}))
    assert (c["average_cycle"], c["average_period"], c["cycles_counted"], c["irregular"]) == (28, 5, 2, False)
    assert c["today"]["cycle_day"] == 4 and c["today"]["on_period"] and c["today"]["open_entry"]
    assert c["next_period"] == {"start": "2050-03-26", "end": "2050-03-30"} and c["days_until_next"] == 25
    assert len(c["predictions"]) == 6 and c["entries"][0]["start_date"] == "2050-02-26"

    days = {d["date"]: d["kind"] for d in ok(api.get("/api/cycle/days", params={"start": "2050-02-25", "end": "2050-04-01", "today": TODAY}))}
    assert days["2050-02-26"] == "period" and days["2050-03-01"] == "period" and "2050-03-02" not in days
    assert [d for d, k in days.items() if k == "predicted"] == ["2050-03-26", "2050-03-27", "2050-03-28", "2050-03-29", "2050-03-30"]
    assert "fertile" not in days.values()                # off unless turned on


def test_fertile_days_only_when_asked(api):
    ok(api.put("/api/cycle/settings", json={"enabled": True, "show_fertile": True}))
    history(api)
    days = {d["date"]: d["kind"] for d in ok(api.get("/api/cycle/days", params={"start": "2050-03-01", "end": "2050-04-01", "today": TODAY}))}
    assert [d for d, k in days.items() if k == "fertile"] == ["2050-03-07", "2050-03-08", "2050-03-09", "2050-03-10",
                                                             "2050-03-11", "2050-03-12", "2050-03-13"]


def test_without_history_the_usual_lengths_are_used(api):
    ok(api.put("/api/cycle/settings", json={"enabled": True, "typical_cycle": 30, "typical_period": 4}))
    log(api, "2050-02-20")
    c = ok(api.get("/api/cycle", params={"today": TODAY}))
    assert (c["average_cycle"], c["average_period"], c["next_period"]["start"]) == (30, 4, "2050-03-22")
    assert api.put("/api/cycle/settings", json={"enabled": True, "typical_cycle": 90}).status_code == 400


def test_irregular_cycles_are_flagged(api):
    ok(api.put("/api/cycle/settings", json={"enabled": True}))
    for start in ("2049-09-01", "2049-09-22", "2049-11-01", "2049-11-20", "2050-01-05"):
        log(api, start)
    assert ok(api.get("/api/cycle", params={"today": TODAY}))["irregular"] is True


def test_entry_rules(api):
    log(api, "2050-01-01", "2050-01-05")
    for body in ({"start_date": "2050-01-03"}, {"start_date": "2050-02-10", "end_date": "2050-02-01"},
                 {"start_date": "2050-02-10", "end_date": "2050-03-20"}, {"start_date": "2050-02-10", "flow": "flood"}):
        assert api.post("/api/cycle/entries", json=body).status_code == 400, body
    e = log(api, "2050-02-01")
    ok(api.put(f"/api/cycle/entries/{e['id']}", json={"start_date": "2050-02-01", "end_date": "2050-02-04", "flow": "light"}))
    api.delete(f"/api/cycle/entries/{e['id']}")
    assert len(ok(api.get("/api/cycle", params={"today": TODAY}))["entries"]) == 1


def test_booking_on_a_period_day_asks_first(api):
    ok(api.put("/api/cycle/settings", json={"enabled": True}))
    history(api)
    client = ok(api.post("/api/clients", json={"name": "C"}), 201)
    body = {"client_id": client["id"], "service_type": "S", "duration_minutes": 60, "scheduled_date": "2050-03-27T20:00:00Z"}
    r = api.post("/api/appointments", params={"warn": True, "tz_offset": 0}, json=body)
    assert r.status_code == 409 and r.json()["detail"]["warnings"][0]["type"] == "period"
    assert "predicted" in r.json()["detail"]["warnings"][0]["message"]
    # 2:00 UTC on the 26th is still the 25th in New York: not a period day there.
    early = {**body, "scheduled_date": "2050-03-26T02:00:00Z"}
    assert api.post("/api/appointments", params={"warn": True, "tz_offset": 300}, json=early).status_code == 201
    ok(api.put("/api/cycle/settings", json={"enabled": True, "warn_on_booking": False}))
    assert api.post("/api/appointments", params={"warn": True}, json=body).status_code == 201


def test_cycle_data_is_private(api, admin):
    e = log(api, "2050-01-01")
    assert admin.put(f"/api/cycle/entries/{e['id']}", json={"start_date": "2050-01-02"}).status_code == 404
    admin.delete(f"/api/cycle/entries/{e['id']}")
    assert len(ok(api.get("/api/cycle", params={"today": TODAY}))["entries"]) == 1
    assert all(x["id"] != e["id"] for x in ok(admin.get("/api/cycle", params={"today": TODAY}))["entries"])
