"""Tests for what fits your work, quick logs, per-hour pay, steady pay, safety timers, supplies, incidents, privacy check-up.
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
    name = "ev-" + uuid.uuid4().hex[:8]
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

import httpx  # noqa: E402

import safety  # noqa: E402


def test_only_what_fits_your_work_is_shown(api):
    f = ok(api.get("/api/work-profile"))["features"]
    assert all(f.values())                                   # nothing chosen yet: everything
    ok(api.put("/api/work-profile", json={"work_types": ["cam"]}))
    f = ok(api.get("/api/work-profile"))["features"]
    assert f["log_stream"] and f["customs"] and not f["rates"] and not f["bookings"] and not f["log_shift"]
    ok(api.put("/api/work-profile", json={"work_types": ["cam", "dancer"]}))
    f = ok(api.get("/api/work-profile"))["features"]
    assert f["log_shift"] and f["tours"] and not f["rates"]
    assert all(ok(api.put("/api/work-profile/show-everything", json={"show_everything": True}))["features"].values())
    assert {"massage", "seller"} <= {o["key"] for o in ok(api.get("/api/work-profile"))["options"]}


def test_a_quick_log_makes_the_income_and_shows_what_an_hour_pays(api, admin):
    club = place(api, name="Log Club", kind="club")
    today = date.today().isoformat()
    log = ok(api.post("/api/worklog", json={"kind": "shift", "source_id": club["id"], "hours": 6, "gross": 700, "fees": 100,
                                            "units": 14, "day": today}), 201)
    assert (log["gross"], log["fees"], log["source_name"]) == (700, 100, "Log Club")
    assert any(i["id"] == log["income_id"] and i["gross"] == 700 for i in ok(api.get("/api/income")))
    ok(api.post("/api/worklog", json={"kind": "stream", "hours": 3, "gross": 150, "day": today}), 201)
    c = ok(api.post("/api/clients", json={"name": "Hour client"}), 201)
    ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": "Dinner", "duration_minutes": 120,
                                           "scheduled_date": today + "T12:00:00Z", "rate": 600, "amount_paid": 600, "status": "completed"}), 201)
    ok(api.put("/api/per-hour/prep", json={"prep_minutes": 60}))
    ok(api.post("/api/expenses", json={"description": "Ads", "amount": 200, "category": "marketing", "date": today + "T12:00:00Z"}), 201)
    r = ok(api.get("/api/per-hour"))
    rows = {x["label"]: x for x in r["rows"]}
    assert rows["Shift – Log Club"]["per_hour"] == 100 and rows["Stream"]["per_hour"] == 50
    assert (rows["Bookings"]["hours"], rows["Bookings"]["per_hour"]) == (3, 200)          # 2 hours + 1 getting ready
    assert r["overall"] == {"income": 1350, "costs": 200, "hours": 12, "per_hour": round(1150 / 12, 2)}
    assert api.post("/api/worklog", json={"kind": "shift", "gross": 10, "fees": 20}).status_code == 400
    assert admin.delete(f"/api/worklog/{log['id']}").status_code == 204                    # not theirs: nothing happens
    assert len(ok(api.get("/api/worklog"))) == 2
    assert api.delete(f"/api/worklog/{log['id']}").status_code == 204
    assert not any(i["id"] == log["income_id"] for i in ok(api.get("/api/income")))


def test_steady_pay_suggests_a_weekly_amount_and_counts_the_buffer(api):
    s = ok(api.get("/api/steady-pay"))
    assert len(s["months"]) == 6 and s["weekly"] is None and s["buffer"] is None
    env = ok(api.post("/api/goals", json={"name": "Buffer", "envelope": True}), 201)
    ok(api.post(f"/api/goals/{env['id']}/entries", json={"amount": 3000}), 201)
    s = ok(api.put("/api/steady-pay", json={"weekly": 500, "goal_id": env["id"]}))
    assert s["weekly"] == 500 and s["buffer"]["balance"] == 3000 and s["buffer"]["weeks"] == 6
    assert api.put("/api/steady-pay", json={"weekly": 500, "goal_id": 999999}).status_code == 404


def test_a_safety_timer_pushes_to_the_contact_and_all_clear_follows(api, monkeypatch):
    sent = []
    monkeypatch.setattr(safety, "PUSH_TRANSPORT", httpx.MockTransport(
        lambda req: (sent.append((str(req.url), req.headers["title"], req.content.decode())), httpx.Response(200))[1]))
    assert api.post("/api/safety/timer", json={"minutes": 20}).status_code == 409           # no contact yet
    assert api.put("/api/safety", json={"contact_name": "Jo", "contact_push": "https://ntfy.sh/short"}).status_code == 400
    s = ok(api.put("/api/safety", json={"contact_name": "Jo", "contact_push": "https://ntfy.example/a-long-random-topic-9f3k2"}))
    assert s["armed"] is True
    t = ok(api.post("/api/safety/timer", json={"minutes": 20, "note": "Walking home from the venue"}), 201)["timer"]
    assert safety.run_alerts(now=datetime.now(timezone.utc)) == 0                           # not due yet
    db = main.get_db()
    db.execute("UPDATE safety_timers SET due_at = '2020-01-01T00:00:00+00:00' WHERE id = ?", (t["id"],))
    db.commit()
    db.close()
    assert safety.run_alerts() >= 1 and safety.run_alerts() == 0                            # once only
    assert "hasn't checked in" in sent[0][1] and "Walking home" in sent[0][2] and "Jo" in sent[0][2]
    assert ok(api.post("/api/safety/timer/safe"))["timer"] is None
    assert "All clear" in sent[-1][1]
    assert ok(api.get("/api/safety/timer"))["timer"] is None


def test_supplies_run_low(api, admin):
    assert "Condoms" in ok(api.get("/api/supplies"))["starters"]
    rows = ok(api.post("/api/supplies", json={"name": "Condoms", "have": 3, "low_at": 2}), 201)
    assert rows[0]["low"] is False
    rows = ok(api.post(f"/api/supplies/{rows[0]['id']}/change", json={"by": -1}))
    assert rows[0]["have"] == 2 and rows[0]["low"] is True
    ok(api.post(f"/api/supplies/{rows[0]['id']}/change", json={"by": -10}))
    assert ok(api.get("/api/supplies"))["supplies"][0]["have"] == 0                         # never below zero
    assert admin.post(f"/api/supplies/{rows[0]['id']}/change", json={"by": 5}).status_code == 404


def test_the_incident_log_and_privacy_checkup_are_private(api, admin):
    rows = ok(api.post("/api/incidents", json={"happened_on": "2044-02-02", "title": "Pushy at the door",
                                               "what": "Wouldn't leave.", "evidence": "Screenshots in my vault folder"}), 201)
    assert rows[0]["title"] == "Pushy at the door"
    assert ok(admin.get("/api/incidents")) == [] or all(r["title"] != "Pushy at the door" for r in ok(admin.get("/api/incidents")))
    assert admin.put(f"/api/incidents/{rows[0]['id']}", json={"happened_on": "2044-02-02", "title": "x"}).status_code == 404
    c = ok(api.get("/api/privacy-checkup"))
    assert c["done"] == 0 and c["total"] >= 8
    c = ok(api.post("/api/privacy-checkup", json={"id": "work_phone", "done": True}))
    assert c["done"] == 1 and next(i for i in c["items"] if i["id"] == "work_phone")["done_on"]
    assert ok(admin.get("/api/privacy-checkup"))["done"] == 0
    assert api.post("/api/privacy-checkup", json={"id": "nope", "done": True}).status_code == 400
