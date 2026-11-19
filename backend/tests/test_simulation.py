"""A simulation: four pretend workers use sworkr for three months, then every screen is checked.
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
    name = "simp-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


# ==================== FOUR PRETEND WORKERS, 90 DAYS EACH ====================
# Each persona uses sworkr the way that kind of worker would, day by day, with a fixed random seed. Then every
# screen's data is opened for each of them: nothing may fail, and the numbers must hang together.

import random  # noqa: E402

DAYS = 90
START = date.today() - timedelta(days=DAYS)


def persona(admin, name):
    username = f"sim-{name}-" + uuid.uuid4().hex[:6]
    assert admin.post("/api/users", json={"username": username, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": username, "password": PASSWORD}).status_code == 200
    return c


def iso(d, hour=12):
    return f"{d.isoformat()}T{hour:02d}:00:00Z"


def make_clients(api, rnd, n, sources):
    out = []
    for i in range(n):
        c = ok(api.post("/api/clients", json={"name": f"Client {i}", "found_via": rnd.choice(sources),
                                              "industry": rnd.choice(["Tech", "Law", "Finance", None]),
                                              "birthday": f"{rnd.randint(1960, 2000)}-0{rnd.randint(1, 9)}-1{rnd.randint(0, 9)}"}), 201)
        out.append(c)
    return out


def sim_house_worker(api, rnd):
    ok(api.put("/api/work-profile", json={"work_types": ["brothel"]}))
    house = ok(api.post("/api/income-sources", json={"name": "Sim Ranch", "kind": "brothel", "fee_percent": 50}), 201)
    ok(api.post(f"/api/income-sources/{house['id']}/charges", json={"label": "Doctor", "cadence": "per_week", "amount": 75,
                                                                    "test_type": "weekly", "weekday": 2}), 201)
    ok(api.post(f"/api/income-sources/{house['id']}/charges", json={"label": "Room & board", "cadence": "per_day", "amount": 40,
                                                                    "category": "room_rent"}), 201)
    ok(api.post("/api/documents", json={"name": "Work card", "kind": "work_card", "expires_on": (START + timedelta(days=200)).isoformat(),
                                        "source_id": house["id"]}), 201)
    clients = make_clients(api, rnd, 12, ["House", "Regular"])
    for stay in range(3):
        first = START + timedelta(days=stay * 28 + 3)
        last = first + timedelta(days=13)
        t = ok(api.post("/api/tours", json={"kind": "tour", "name": f"Stay {stay}", "start_date": first.isoformat(), "end_date": last.isoformat(),
                                            "starts_at": iso(first, 0), "ends_at": iso(last + timedelta(days=1), 0), "source_id": house["id"]}), 201)
        for test in [a for a in ok(api.get(f"/api/tours/{t['id']}/summary"))["appointments"] if a["kind"] == "test"]:
            ok(api.put(f"/api/appointments/{test['id']}/test-result", json={"result": "clear"}))
        for d in range(4, 14):
            for _ in range(rnd.randint(0, 3)):
                c = rnd.choice(clients)
                rate = rnd.choice([300, 500, 800, 1200])
                ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": "Party", "duration_minutes": rnd.choice([30, 60, 120]),
                                                       "scheduled_date": iso(first + timedelta(days=d), rnd.randint(14, 23)),
                                                       "rate": rate, "amount_paid": rate, "status": "completed"}), 201)
    ok(api.post("/api/supplies", json={"name": "Condoms", "have": 40, "low_at": 10}), 201)


def sim_independent(api, rnd):
    ok(api.put("/api/work-profile", json={"work_types": ["independent"]}))
    clients = make_clients(api, rnd, 25, ["Tryst", "Eros", "Referral", "X"])
    for c in clients[:8]:
        ok(api.put(f"/api/clients/{c['id']}/profile", json={"languages": rnd.choice(["English", "Spanish, English"]), "talk_about": "Travel"}))
    tour_first = START + timedelta(days=40)
    ok(api.post("/api/tours", json={"kind": "tour", "name": "Chicago", "start_date": tour_first.isoformat(),
                                    "end_date": (tour_first + timedelta(days=4)).isoformat(), "starts_at": iso(tour_first, 0),
                                    "ends_at": iso(tour_first + timedelta(days=5), 0)}), 201)
    for d in range(DAYS):
        day = START + timedelta(days=d)
        if rnd.random() < 0.35:
            c = rnd.choice(clients)
            rate = rnd.choice([400, 600, 1000])
            done = day < date.today()
            a = ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": rnd.choice(["Dinner date", "One hour", "Overnight"]),
                                                       "duration_minutes": rnd.choice([60, 120, 720]), "scheduled_date": iso(day, 20),
                                                       "rate": rate, "amount_paid": rate if done else rate * 0.25,
                                                       "status": "completed" if done else "scheduled"}), 201)
            if done and rnd.random() < 0.5:
                ok(api.put(f"/api/appointments/{a['id']}/review", json={"rating": rnd.choice(["great", "fine"]), "again": "yes"}))
        if rnd.random() < 0.1:
            ok(api.post("/api/expenses", json={"description": "Ad renewal", "amount": rnd.choice([60, 120, 200]), "category": "marketing",
                                               "date": iso(day)}), 201)
        if rnd.random() < 0.08:
            ok(api.post("/api/inquiries", json={"name": f"Inquiry {d}", "found_via": "Tryst", "received_at": iso(day), "stage": "new"}), 201)


def sim_cam_creator(api, rnd):
    ok(api.put("/api/work-profile", json={"work_types": ["cam", "content"]}))
    site = ok(api.post("/api/income-sources", json={"name": "Cam site", "kind": "platform", "fee_percent": 40}), 201)
    env = ok(api.post("/api/goals", json={"name": "Buffer", "envelope": True}), 201)
    ok(api.put("/api/steady-pay", json={"weekly": 400, "goal_id": env["id"]}))
    for d in range(DAYS):
        day = START + timedelta(days=d)
        if rnd.random() < 0.6:
            gross = rnd.randint(80, 500)
            ok(api.post("/api/worklog", json={"kind": "stream", "source_id": site["id"], "day": day.isoformat(), "hours": rnd.choice([2, 3, 4]),
                                              "gross": gross, "fees": round(gross * 0.4), "units": gross * 20}), 201)
        if rnd.random() < 0.3:
            ok(api.post("/api/worklog", json={"kind": "sale", "day": day.isoformat(), "hours": 0.5, "gross": rnd.choice([15, 25, 40])}), 201)
        if rnd.random() < 0.4:
            status = "posted" if day < date.today() else "scheduled"
            ok(api.post("/api/posts", json={"platform": rnd.choice(["X", "Bluesky", "OF"]), "status": status, "caption": f"Post {d}",
                                            "scheduled_at": iso(day, 18), **({"posted_at": iso(day, 18)} if status == "posted" else {})}), 201)
        if d % 7 == 0:
            ok(api.post(f"/api/goals/{env['id']}/entries", json={"amount": 300, "date": day.isoformat()}), 201)
    ok(api.post("/api/progress/goals", json={"kind": "posts", "target": 3}), 201)


def sim_dancer(api, rnd):
    ok(api.put("/api/work-profile", json={"work_types": ["dancer"]}))
    club = ok(api.post("/api/income-sources", json={"name": "Club Sim", "kind": "club", "fee_per_shift": 60}), 201)
    r = ok(api.post("/api/routines", json={"name": "Before a shift", "when": "any", "steps": ["Bag packed", "Lashes on", "Cash for house fee"]}), 201)
    ok(api.put("/api/wellness/settings", json={"enabled": True}))
    for d in range(DAYS):
        day = START + timedelta(days=d)
        if day.weekday() in (3, 4, 5, 6) and rnd.random() < 0.85:
            gross = rnd.randint(200, 1400)
            ok(api.post("/api/worklog", json={"kind": "shift", "source_id": club["id"], "day": day.isoformat(), "hours": rnd.choice([6, 7, 8]),
                                              "gross": gross, "fees": rnd.choice([60, 80, 120]), "units": rnd.randint(5, 30)}), 201)
            for step in r["steps"]:
                ok(api.post(f"/api/routines/{r['id']}/check", json={"step_id": step["id"], "day": day.isoformat()}))
        ok(api.put("/api/wellness", json={"day": day.isoformat(), "sleep_hours": rnd.choice([5, 6, 7, 8, 9]), "energy": rnd.randint(1, 5)}))
        if rnd.random() < 0.15:
            ok(api.post("/api/expenses", json={"description": "Costume", "amount": rnd.randint(20, 150), "category": "wardrobe", "date": iso(day)}), 201)
    ok(api.post("/api/meals", json={"day": date.today().isoformat(), "meal": "dinner", "what": "Pasta", "groceries": "Pasta, sauce"}), 201)


# Addresses that need dates or a search word to answer.
PARAMS = {
    "/api/earnings/compare": {"start": iso(START, 0), "end": iso(date.today() + timedelta(days=1), 0)},
    "/api/marketing/found-via": {"start": iso(START, 0), "end": iso(date.today() + timedelta(days=1), 0)},
    "/api/marketing/busy": {"start": iso(START, 0), "end": iso(date.today() + timedelta(days=1), 0)},
    "/api/calendar/dates": {"start": START.isoformat(), "end": date.today().isoformat()},
    "/api/search": {"q": "Client"},
}
SKIP = {"/api/content/thumbnail", "/api/rates/quote", "/api/blocklist/check"}     # need a file or a specific thing to look up


def check_every_screen(api, who):
    paths = main.app.openapi()["paths"]
    for path, methods in paths.items():
        if "get" not in methods or "{" in path or path in SKIP:
            continue
        r = api.get(path, params=PARAMS.get(path, {}))
        assert r.status_code < 500, f"{who}: GET {path} failed with {r.status_code}: {r.text[:300]}"


def test_four_workers_use_sworkr_for_three_months(admin):
    rnd = random.Random(20261119)
    people = {}
    for name, play in (("house", sim_house_worker), ("independent", sim_independent), ("cam", sim_cam_creator), ("dancer", sim_dancer)):
        api = persona(admin, name)
        play(api, rnd)
        people[name] = api

    for name, api in people.items():
        check_every_screen(api, name)
        # The numbers hang together.
        ph = ok(api.get("/api/per-hour", params={"days": 365}))
        assert all(r["per_hour"] is None or r["per_hour"] >= 0 for r in ph["rows"]), (name, ph)
        p = ok(api.get("/api/progress"))
        assert p["enabled"] and len(p["streaks"]) == 3
        clients = [c for c in ok(api.get("/api/clients", params={"limit": 200})) if c["role"] == "client"]
        assert ok(api.get("/api/client-base"))["clients"] == len(clients), name
        export = api.get("/api/account/data/export")
        assert export.status_code == 200 and export.content[:2] == b"PK", name     # a zip

    if os.environ.get("SIM_REPORT"):
        for name, api in people.items():
            ph = ok(api.get("/api/per-hour", params={"days": 365}))
            sp = ok(api.get("/api/steady-pay"))
            pr = ok(api.get("/api/progress"))
            tx = api.get("/api/tax-summary").json()
            print(f"== {name} ==")
            print(" per hour:", [(r["label"], r["hours"], r["per_hour"]) for r in ph["rows"]], "overall", ph["overall"])
            print(" steady pay: months", sp["months"], "suggested", sp["suggested_weekly"], "buffer", sp["buffer"])
            print(" streaks:", [(s["id"], s["days"], s["paused"]) for s in pr["streaks"]], "bests", [(b["title"], b["value"]) for b in pr["bests"]])
            print(" badges earned:", [b["id"] for b in pr["badges"] if b["earned"]], "wallet", pr["wallet"], "wrapup", bool(pr["tour_wrapup"]))
            print(" tax keys:", list(tx)[:8] if isinstance(tx, dict) else tx)
    # Each persona's own story shows up.
    dancer = ok(people["dancer"].get("/api/per-hour", params={"days": 365}))
    assert any(r["label"].startswith("Shift") and r["per_hour"] for r in dancer["rows"])
    assert next(s for s in ok(people["dancer"].get("/api/progress"))["streaks"] if s["id"] == "routines")["days"] >= 0
    # Found by this simulation: months before someone started aren't counted as empty months,
    # a routine streak isn't broken by days off, and parties at a house don't add getting-ready time.
    house_pay = ok(people["house"].get("/api/steady-pay"))
    assert 0 not in house_pay["months"] and house_pay["suggested_weekly"] > 1000
    assert next(s for s in ok(people["dancer"].get("/api/progress"))["streaks"] if s["id"] == "routines")["days"] >= 2
    house_hour = ok(people["house"].get("/api/per-hour", params={"days": 365}))["rows"][0]
    assert house_hour["per_hour"] > 400
    cam = ok(people["cam"].get("/api/steady-pay"))
    assert cam["buffer"]["balance"] > 0 and cam["buffer"]["weeks"] > 0
    assert ok(people["cam"].get("/api/work-profile"))["features"]["rates"] is False      # cam doesn't see the rate card
    house_tours = ok(people["house"].get("/api/tours"))
    assert len(house_tours) == 3
    indep = ok(people["independent"].get("/api/client-base"))
    assert any(g["title"] == "Languages" and g["bars"] for g in indep["groups"])
    # Nobody sees anybody else's records.
    ids = {name: {c["id"] for c in ok(api.get("/api/clients", params={"limit": 200}))} for name, api in people.items()}
    names = list(ids)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert not ids[a] & ids[b], (a, b)
