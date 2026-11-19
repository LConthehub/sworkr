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
    r = ok(api.put(f"/api/routines/{r['id']}", params={"day": "2044-01-01"},
                   json={"name": "Mornings", "when": "morning", "steps": ["Skincare", "Water"]}))
    assert r["name"] == "Mornings" and [(x["label"], x["done"]) for x in r["steps"]] == [("Skincare", False), ("Water", True)]   # Water keeps its tick
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


def test_wellness_days_line_up_with_money(api, admin):
    from datetime import timedelta as _td
    today = date.today()
    c = ok(api.post("/api/clients", json={"name": "Well client"}), 201)
    for i, (sleep, paid) in enumerate([(8, 600), (8, 400), (5, 100), (5, 0)]):
        day = today - _td(days=i + 1)
        ok(api.put("/api/wellness", json={"day": day.isoformat(), "sleep_hours": sleep, "water_glasses": 8, "energy": 4}))
        if paid:
            ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": "Dinner", "duration_minutes": 60,
                                                   "scheduled_date": f"{day.isoformat()}T15:00:00Z", "rate": paid, "amount_paid": paid}), 201)
    ok(api.put("/api/wellness", json={"day": (today - _td(days=1)).isoformat(), "sleep_hours": 9}))   # changing a day, not adding
    assert len(ok(api.get("/api/wellness", params={"days": 10}))) == 4
    r = ok(api.get("/api/wellness/vs-money"))
    sleep = next(x for x in r["comparisons"] if x["title"] == "Sleep")
    assert (sleep["better_days"], sleep["better_avg"], sleep["worse_days"], sleep["worse_avg"]) == (2, 500, 2, 50)
    assert api.put("/api/wellness", json={"day": today.isoformat(), "energy": 9}).status_code == 400
    assert ok(admin.get("/api/wellness/vs-money"))["days_logged"] == 0


HEALTH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" value="HKCategoryValueSleepAnalysisInBed" startDate="2044-03-01 22:00:00 -0800" endDate="2044-03-02 07:00:00 -0800"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" value="HKCategoryValueSleepAnalysisAsleepCore" startDate="2044-03-01 23:00:00 -0800" endDate="2044-03-02 03:00:00 -0800"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" value="HKCategoryValueSleepAnalysisAsleepREM" startDate="2044-03-02 03:00:00 -0800" endDate="2044-03-02 06:30:00 -0800"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="iPhone" value="HKCategoryValueSleepAnalysisAsleepUnspecified" startDate="2044-03-01 23:30:00 -0800" endDate="2044-03-02 06:00:00 -0800"/>
 <Record type="HKQuantityTypeIdentifierDietaryWater" sourceName="App" unit="mL" value="500" startDate="2044-03-02 09:00:00 -0800" endDate="2044-03-02 09:00:00 -0800"/>
 <Record type="HKQuantityTypeIdentifierDietaryWater" sourceName="App" unit="L" value="1" startDate="2044-03-02 15:00:00 -0800" endDate="2044-03-02 15:00:00 -0800"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count" value="900" startDate="2044-03-02 10:00:00 -0800" endDate="2044-03-02 10:10:00 -0800"/>
</HealthData>"""


def test_an_apple_health_export_fills_in_sleep_and_water(api):
    import io as _io
    import zipfile as _zip
    ok(api.put("/api/wellness", json={"day": "2044-03-02", "energy": 4}))
    buf = _io.BytesIO()
    with _zip.ZipFile(buf, "w") as z:
        z.writestr("apple_health_export/export.xml", HEALTH_XML)
    r = ok(api.post("/api/wellness/import-apple-health", content=buf.getvalue(), headers={"Content-Type": "application/zip"}))
    assert (r["days"], r["sleep_days"], r["water_days"]) == (1, 1, 1)
    db = main.get_db()
    row = db.execute("SELECT sleep_hours, water_glasses, energy FROM wellness_days WHERE day = '2044-03-02' AND owner_id = ?",
                     (ok(api.get("/api/auth/status"))["user"]["id"],)).fetchone()
    db.close()
    assert (row["sleep_hours"], row["water_glasses"], row["energy"]) == (7.5, 6, 4)   # the watch's 7.5 h, not both; energy kept
    assert api.post("/api/wellness/import-apple-health", content=b"not a zip or xml",
                    headers={"Content-Type": "application/octet-stream"}).status_code == 400


import base64 as _b64  # noqa: E402

import bank  # noqa: E402


class Bridge:
    """A pretend SimpleFIN Bridge: one claim, then accounts with transactions."""

    def __init__(self):
        self.claimed = False
        self.seen = []

    def __call__(self, req):
        self.seen.append(req)
        if req.url.path == "/claim/abc":
            if self.claimed:
                return httpx.Response(403)
            self.claimed = True
            return httpx.Response(200, text="https://user123:pass456@bridge.example/simplefin")
        if req.url.path == "/simplefin/accounts":
            assert req.headers["authorization"] == "Basic " + _b64.b64encode(b"user123:pass456").decode()
            return httpx.Response(200, json={"errors": [], "accounts": [{
                "org": {"name": "Credit Union"}, "id": "acct-1", "name": "Checking", "currency": "USD",
                "transactions": [
                    {"id": "t1", "posted": 2340000000, "amount": "-42.50", "description": "WIGS R US"},
                    {"id": "t2", "posted": 2340086400, "amount": "300.00", "description": "VENMO FROM X"},
                ]}]})
        return httpx.Response(404)


def test_bank_transactions_come_in_once_and_wait_to_be_reviewed(api, admin, monkeypatch):
    bridge = Bridge()
    monkeypatch.setattr(bank, "TRANSPORT", httpx.MockTransport(bridge))
    assert api.post("/api/bank/connect", json={"setup_token": "not base64!!"}).status_code == 400
    token = _b64.b64encode(b"https://bridge.example/claim/abc").decode()
    ok(api.post("/api/bank/connect", json={"setup_token": token}))
    assert api.post("/api/bank/connect", json={"setup_token": token}).status_code == 400    # a token works once
    db = main.get_db()
    stored = db.execute("SELECT value FROM user_settings WHERE key = 'simplefin_access' AND user_id = ?",
                        (ok(api.get("/api/auth/status"))["user"]["id"],)).fetchone()[0]
    db.close()
    assert "pass456" not in stored
    assert ok(api.post("/api/bank/fetch"))["added"] == 2
    assert ok(api.post("/api/bank/fetch"))["added"] == 0                                  # not twice
    new = ok(api.get("/api/bank/transactions"))
    spend = next(t for t in new if t["amount"] < 0)
    paid = next(t for t in new if t["amount"] > 0)
    r = ok(api.post(f"/api/bank/transactions/{spend['id']}", json={"action": "expense", "category": "other", "description": "Wig"}))
    assert r["status"] == "added" and r["expense_id"]
    e = next(x for x in ok(api.get("/api/expenses")) if x["id"] == r["expense_id"])
    assert (e["amount"], e["description"]) == (42.5, "Wig")
    ok(api.post(f"/api/bank/transactions/{paid['id']}", json={"action": "ignore"}))
    assert ok(api.get("/api/bank/transactions")) == []
    assert api.post(f"/api/bank/transactions/{spend['id']}", json={"action": "expense"}).status_code == 400   # already added
    assert admin.post(f"/api/bank/transactions/{paid['id']}", json={"action": "restore"}).status_code == 404
    assert ok(api.get("/api/bank/status"))["connected"] is True


import progress  # noqa: E402


def test_a_missed_day_pauses_a_streak_two_end_it():
    from datetime import date as _d, timedelta as _td
    today = _d(2044, 5, 10)
    day = lambda n: (today - _td(days=n)).isoformat()  # noqa: E731
    assert progress.streak({day(0), day(1), day(2)}, today)["days"] == 3
    assert progress.streak({day(1), day(2)}, today)["days"] == 2                 # today isn't over yet
    assert progress.streak({day(0), day(2), day(3)}, today)["days"] == 3         # one gap: paused, not lost
    assert progress.streak({day(2), day(3)}, today) == {"days": 2, "paused": True}    # yesterday missed: paused
    assert progress.streak({day(0), day(1)}, today)["paused"] is False
    assert progress.streak({day(0), day(3), day(4)}, today)["days"] == 1         # two gaps: a new streak
    assert progress.streak({day(0), day(2)}, today, skip={day(1)})["days"] == 2  # nothing planned that day
    assert progress.longest([day(9), day(8), day(6), day(1)]) == 3


def test_progress_has_goals_badges_and_one_switch(api):
    p = ok(api.get("/api/progress"))
    assert p["enabled"] and {s["id"] for s in p["streaks"]} == {"posting", "routines", "money"}
    assert {b["id"] for b in p["badges"]} >= {"backup", "two_step", "passkey", "checkin"}
    ok(api.post("/api/progress/goals", json={"kind": "money_days", "target": 5}), 201)
    ok(api.post("/api/expenses", json={"description": "Wipes", "amount": 9, "category": "other",
                                       "date": date.today().isoformat() + "T12:00:00Z"}), 201)
    g = ok(api.get("/api/progress"))["goals"][0]
    assert (g["kind"], g["target"], g["done"]) == ("money_days", 5, 1)
    assert next(s for s in ok(api.get("/api/progress"))["streaks"] if s["id"] == "money")["days"] == 1
    assert api.post("/api/progress/goals", json={"kind": "work_more", "target": 5}).status_code == 400
    assert api.delete("/api/progress/goals/money_days").status_code == 204
    ok(api.put("/api/progress/settings", json={"enabled": False}))
    assert ok(api.get("/api/progress")) == {"enabled": False}
    ok(api.put("/api/progress/settings", json={"enabled": True}))


def test_a_finished_tour_gets_a_wrap_up(api):
    from datetime import timedelta as _td
    end = date.today() - _td(days=2)
    start = end - _td(days=4)
    t = ok(api.post("/api/tours", json={"kind": "tour", "name": "Wrap stint", "start_date": start.isoformat(), "end_date": end.isoformat(),
                                        "starts_at": f"{start.isoformat()}T00:00:00Z", "ends_at": f"{(end + _td(days=1)).isoformat()}T00:00:00Z"}), 201)
    c = ok(api.post("/api/clients", json={"name": "Tour newbie"}), 201)
    ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": "Dinner", "duration_minutes": 60,
                                           "scheduled_date": f"{(start + _td(days=1)).isoformat()}T15:00:00Z", "rate": 500, "amount_paid": 500}), 201)
    w = ok(api.get("/api/progress"))["tour_wrapup"]
    assert w["name"] == "Wrap stint" and w["income"] == 500 and w["new_clients"] >= 1 and w["best_day"]["earned"] == 500
