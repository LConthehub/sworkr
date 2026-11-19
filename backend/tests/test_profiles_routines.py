"""Tests for client profiles (getting to know them, deceased) and routines.
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
    name = "pr-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def test_a_client_profile_remembers_the_person(api):
    c = ok(api.post("/api/clients", json={"name": "Ana"}), 201)
    assert ok(api.get(f"/api/clients/{c['id']}/profile"))["languages"] is None
    p = ok(api.put(f"/api/clients/{c['id']}/profile", json={
        "languages": "Spanish, a little English", "translator": True, "culture": "Takes shoes off indoors",
        "talk_about": "Football, her dog", "avoid": "Work"}))
    assert (p["languages"], p["translator"], p["avoid"], p["deceased"]) == ("Spanish, a little English", True, "Work", False)


def test_a_deceased_client_is_made_inactive_and_drops_out_of_ghosts(api):
    c = ok(api.post("/api/clients", json={"name": "Old regular"}), 201)
    for day in ("2025-01-05", "2025-02-05"):
        ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": "Dinner", "duration_minutes": 60,
                                               "scheduled_date": f"{day}T19:00:00Z", "rate": 300, "amount_paid": 300,
                                               "status": "completed"}), 201)
    ghosts = lambda: [x["id"] for x in ok(api.get("/api/marketing/lapsed", params={"days": 30}))]
    assert c["id"] in ghosts()
    p = ok(api.put(f"/api/clients/{c['id']}/profile", json={"deceased": True, "deceased_on": "2026-01-01"}))
    assert p["deceased"] and p["deceased_on"] == "2026-01-01"
    assert ok(api.get(f"/api/clients/{c['id']}"))["is_active"] is False
    assert c["id"] not in ghosts()


def test_profiles_are_private(api, admin):
    c = ok(api.post("/api/clients", json={"name": "Ana"}), 201)
    assert admin.get(f"/api/clients/{c['id']}/profile").status_code == 404
    assert admin.put(f"/api/clients/{c['id']}/profile", json={"avoid": "x"}).status_code == 404


def test_routines_start_with_ideas_then_tick_off_day_by_day(api):
    first = ok(api.get("/api/routines"))
    assert first["routines"] == [] and {s["when"] for s in first["starters"]} >= {"morning", "night", "before_booking", "after_booking"}
    r = ok(api.post("/api/routines", json={"name": "Morning", "when": "morning", "steps": ["Water", " ", "Stretch"]}), 201)
    assert [s["label"] for s in r["steps"]] == ["Water", "Stretch"] and r["done"] == 0
    step = r["steps"][0]["id"]
    r = ok(api.post(f"/api/routines/{r['id']}/check", json={"step_id": step, "day": "2044-01-01"}))
    assert ok(api.get("/api/routines", params={"day": "2044-01-01"}))["routines"][0]["done"] == 1
    assert ok(api.get("/api/routines", params={"day": "2044-01-02"}))["routines"][0]["done"] == 0      # a new day starts fresh
    assert ok(api.get("/api/routines"))["starters"] == []
    r = ok(api.put(f"/api/routines/{r['id']}", json={"name": "Mornings", "when": "morning", "steps": ["Water", "Skincare"]}))
    assert r["name"] == "Mornings" and len(r["steps"]) == 2
    assert api.post("/api/routines", json={"name": "Empty", "steps": []}).status_code == 400
    assert api.post("/api/routines", json={"name": "x", "when": "lunch", "steps": ["a"]}).status_code == 400
    assert api.delete(f"/api/routines/{r['id']}").status_code == 204


def test_routines_are_private(api, admin):
    r = ok(api.post("/api/routines", json={"name": "Night", "when": "night", "steps": ["Charge phone"]}), 201)
    assert admin.post(f"/api/routines/{r['id']}/check", json={"step_id": r["steps"][0]["id"]}).status_code == 404
    assert admin.put(f"/api/routines/{r['id']}", json={"name": "x", "steps": ["y"]}).status_code == 404


def test_the_quick_note_is_kept(api, admin):
    assert ok(api.get("/api/quick-note"))["text"] == ""
    ok(api.put("/api/quick-note", json={"text": "Buy more wipes\nCall the landlord"}))
    assert ok(api.get("/api/quick-note"))["text"].startswith("Buy more wipes")
    assert "wipes" not in ok(admin.get("/api/quick-note"))["text"]
    assert api.put("/api/quick-note", json={"text": "x" * 20001}).status_code == 400


def booked(api, name="Ana", when="2025-03-01T19:00:00Z", paid=400, **client):
    c = ok(api.post("/api/clients", json={"name": name, **client}), 201)
    a = ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": "Dinner", "duration_minutes": 60,
                                               "scheduled_date": when, "rate": paid, "amount_paid": paid, "status": "completed"}), 201)
    return c, a


def test_after_a_booking_the_answers_go_to_the_client(api, admin):
    c, a = booked(api)
    assert ok(api.get(f"/api/appointments/{a['id']}/review")) is None
    ok(api.put(f"/api/appointments/{a['id']}/review", json={"rating": "great", "again": "yes", "talked_about": "Her new job"}))
    ok(api.put(f"/api/appointments/{a['id']}/review", json={"rating": "fine", "again": "maybe"}))     # changing it, not adding
    h = ok(api.get(f"/api/clients/{c['id']}/reviews"))
    assert len(h["reviews"]) == 1 and h["ratings"]["fine"] == 1 and h["again"]["maybe"] == 1
    assert api.put(f"/api/appointments/{a['id']}/review", json={"rating": "meh"}).status_code == 400
    assert admin.put(f"/api/appointments/{a['id']}/review", json={"rating": "bad"}).status_code == 404


def test_the_client_base_counts_who_your_clients_are(api):
    c1, a1 = booked(api, "One", found_via="Tryst", industry="Tech", birthday="1990-05-01")
    booked(api, "Two", found_via="Tryst", industry="Law")
    ok(api.put(f"/api/clients/{c1['id']}/profile", json={"languages": "spanish, English"}))
    ok(api.put(f"/api/appointments/{a1['id']}/review", json={"again": "yes"}))
    gone = ok(api.post("/api/clients", json={"name": "Gone", "found_via": "Tryst"}), 201)
    ok(api.put(f"/api/clients/{gone['id']}/profile", json={"deceased": True}))
    d = ok(api.get("/api/client-base"))
    assert d["clients"] == 2                                            # the one who passed away isn't counted
    groups = {g["title"]: {b["label"]: b["count"] for b in g["bars"]} for g in d["groups"]}
    assert groups["How they found you"] == {"Tryst": 2}
    assert groups["Languages"] == {"Spanish": 1, "English": 1}
    assert groups["Age"].get("Not known") == 1 and sum(groups["Age"].values()) == 2
    assert groups["How often they've booked"] == {"Once": 2}
    assert groups["Would see again (last answer)"] == {"Yes": 1}


def test_holidays_show_on_the_calendar_for_the_chosen_country(api):
    assert not [m for m in ok(api.get("/api/calendar/dates", params={"start": "2044-12-20", "end": "2044-12-31"})) if m["kind"] == "holiday"]
    s = ok(api.get("/api/holidays/settings"))
    assert s["country"] is None and any(c["code"] == "US" for c in s["countries"])
    ok(api.put("/api/holidays/settings", json={"country": "us", "subdivision": "ca"}))
    marks = [m for m in ok(api.get("/api/calendar/dates", params={"start": "2044-12-20", "end": "2044-12-31"})) if m["kind"] == "holiday"]
    assert any(m["date"] == "2044-12-25" for m in marks)
    assert api.put("/api/holidays/settings", json={"country": "XX"}).status_code == 400
    assert api.put("/api/holidays/settings", json={"country": "US", "subdivision": "ZZ"}).status_code == 400
    ok(api.put("/api/holidays/settings", json={"country": None}))
    assert not [m for m in ok(api.get("/api/calendar/dates", params={"start": "2044-12-20", "end": "2044-12-31"})) if m["kind"] == "holiday"]


def test_a_driver_keeps_rates_and_a_ride_becomes_a_travel_expense(api, admin):
    driver = ok(api.post("/api/clients", json={"name": "Dee Driver", "role": "partner", "industry": "Driver"}), 201)
    ok(api.post(f"/api/clients/{driver['id']}/rates", json={"label": "Airport run", "amount": 60}), 201)
    rates = ok(api.post(f"/api/clients/{driver['id']}/rates", json={"label": "Waiting", "amount": 30, "unit": "hour"}), 201)
    assert [r["label"] for r in rates] == ["Airport run", "Waiting"]
    assert api.post(f"/api/clients/{driver['id']}/rates", json={"label": "x", "amount": 5, "unit": "furlong"}).status_code == 400
    assert [d["name"] for d in ok(api.get("/api/drivers"))] == ["Dee Driver"]
    c = ok(api.post("/api/clients", json={"name": "Rider client"}), 201)
    a = ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": "Dinner", "duration_minutes": 60,
                                               "scheduled_date": "2045-02-02T19:00:00Z", "rate": 400}), 201)
    r = ok(api.post(f"/api/appointments/{a['id']}/ride", json={"rate_id": rates[1]["id"], "quantity": 2}), 201)
    assert r["amount"] == 60
    e = next(x for x in ok(api.get("/api/expenses")) if x["id"] == r["expense_id"])
    assert e["description"] == "Ride: Waiting (2 hours) – Dee Driver" and e["appointment_id"] == a["id"]
    assert admin.post(f"/api/appointments/{a['id']}/ride", json={"rate_id": rates[1]["id"]}).status_code == 404
    assert admin.get(f"/api/clients/{driver['id']}/rates").status_code == 404


import json as _json  # noqa: E402

import httpx  # noqa: E402

import assistant  # noqa: E402


class Model:
    def __init__(self):
        self.seen = []

    def __call__(self, req):
        self.seen.append(req)
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen-local"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "October was your best month."}}]})


def test_local_and_cloud_addresses():
    for url in ("http://localhost:1234/v1", "http://127.0.0.1:11434/v1", "http://host.docker.internal:1234/v1",
                "http://192.168.1.20:8080/v1", "http://pc.tail1234.ts.net:1234/v1", "http://100.101.102.103:1234/v1"):
        assert assistant.is_local(url), url
    for url in ("https://api.openai.com/v1", "https://8.8.8.8/v1", "https://example.com/v1"):
        assert not assistant.is_local(url), url


def test_a_cloud_ai_needs_an_explicit_yes(api):
    assert api.put("/api/assistant/settings", json={"enabled": True, "url": "https://api.example.com/v1"}).status_code == 400
    s = ok(api.put("/api/assistant/settings", json={"enabled": True, "url": "https://api.example.com/v1", "cloud_ok": True, "key": "sk-1"}))
    assert s["cloud_ok"] and s["key_saved"] and "sk-1" not in _json.dumps(s)


def test_asking_sends_totals_only_never_names(api, monkeypatch):
    m = Model()
    monkeypatch.setattr(assistant, "TRANSPORT", httpx.MockTransport(m))
    assert api.post("/api/assistant/ask", json={"question": "Best month?"}).status_code == 409     # not on yet
    ok(api.put("/api/assistant/settings", json={"enabled": True, "url": "http://localhost:1234/v1", "model": "qwen-local"}))
    assert ok(api.post("/api/assistant/test"))["models"] == ["qwen-local"]
    c = ok(api.post("/api/clients", json={"name": "Secret Sam", "found_via": "Tryst", "contact_phone": "555-0100"}), 201)
    ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": "Dinner", "duration_minutes": 60,
                                           "scheduled_date": date.today().isoformat() + "T19:00:00Z", "rate": 400, "amount_paid": 400}), 201)
    r = ok(api.post("/api/assistant/ask", json={"question": "Best month?"}))
    assert r["answer"] == "October was your best month."
    sent = next(x for x in m.seen if x.url.path.endswith("/chat/completions")).content.decode()
    assert "Secret Sam" not in sent and "555-0100" not in sent
    assert "Tryst" in sent and "Dinner" in sent and _json.loads(sent)["model"] == "qwen-local"
