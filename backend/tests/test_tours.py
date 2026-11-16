"""Tests for tours, time off, health tests, room rent, earnings comparison and client preferences.
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


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    """A brand-new user for each test, so tours and time off from other tests never get in the way."""
    name = "t-" + uuid.uuid4().hex[:8]
    r = admin.post("/api/users", json={"username": name, "password": PASSWORD})
    assert r.status_code == 201, r.text
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


# All times are UTC (time zone offset 0), so a local day runs from midnight to midnight UTC.
def period(first, last, kind="tour", **fields):
    from datetime import date, timedelta
    end = date.fromisoformat(last) + timedelta(days=1)
    body = {"kind": kind, "start_date": first, "end_date": last,
            "starts_at": f"{first}T00:00:00Z", "ends_at": f"{end.isoformat()}T00:00:00Z", **fields}
    if kind == "tour":
        body.setdefault("name", "Chicago")
    return body


def add_tour(api, first, last, expect=201, **fields):
    r = api.post("/api/tours", json=period(first, last, **fields))
    assert r.status_code == expect, r.text
    return r.json()


def add_client(api, **fields):
    r = api.post("/api/clients", json={"name": "C " + uuid.uuid4().hex[:6], **fields})
    assert r.status_code == 201, r.text
    return r.json()


def book(api, client, when, expect=201, params=None, **fields):
    body = {"client_id": client["id"], "service_type": "Session", "duration_minutes": 60, "scheduled_date": when, **fields}
    r = api.post("/api/appointments", json=body, params=params or {})
    assert r.status_code == expect, r.text
    return r.json()


def add_test(api, when, test_type="weekly", cost=80, expect=201, **fields):
    body = {"kind": "test", "test_type": test_type, "cost": cost, "duration_minutes": 30, "scheduled_date": when, **fields}
    r = api.post("/api/appointments", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def expenses(api, **params):
    r = api.get("/api/expenses", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def summary(api, tour):
    r = api.get(f"/api/tours/{tour['id']}/summary")
    assert r.status_code == 200, r.text
    return r.json()


# ---------- room rent ----------

def test_a_tour_makes_one_room_rent_expense_per_day_and_keeps_them_in_step(api):
    tour = add_tour(api, "2041-03-03", "2041-03-07", room_rent_per_day=150)
    rent = [e for e in expenses(api) if e["category"] == "room_rent"]
    assert len(rent) == 5 and {e["amount"] for e in rent} == {150}
    assert sorted(e["date"][:10] for e in rent) == ["2041-03-03", "2041-03-04", "2041-03-05", "2041-03-06", "2041-03-07"]
    assert all(e["tour_id"] == tour["id"] and e["source"] == "tour_room" and e["tour_name"] == "Chicago" for e in rent)

    r = api.put(f"/api/tours/{tour['id']}", json=period("2041-03-03", "2041-03-04", room_rent_per_day=200))
    assert r.status_code == 200, r.text
    rent = [e for e in expenses(api) if e["category"] == "room_rent"]
    assert len(rent) == 2 and {e["amount"] for e in rent} == {200}

    # Generated room rent is changed on the tour, not by hand.
    assert api.put(f"/api/expenses/{rent[0]['id']}", json={"description": "x", "amount": 1}).status_code == 400
    assert api.delete(f"/api/expenses/{rent[0]['id']}").status_code == 400

    assert api.delete(f"/api/tours/{tour['id']}").status_code == 204
    assert [e for e in expenses(api) if e["category"] == "room_rent"] == []


def test_no_room_rent_without_a_rate(api):
    add_tour(api, "2041-04-01", "2041-04-03")
    assert expenses(api) == []


# ---------- tours and time off ----------

def test_tours_cannot_overlap_but_time_off_can_sit_inside_a_tour(api):
    add_tour(api, "2041-05-01", "2041-05-10")
    add_tour(api, "2041-05-10", "2041-05-12", name="Denver", expect=400)
    add_tour(api, "2041-05-11", "2041-05-12", name="Denver")                       # the next day is fine
    add_tour(api, "2041-05-04", "2041-05-04", kind="time_off", time_off_type="day_off")
    add_tour(api, "2041-05-04", "2041-05-05", kind="time_off", expect=400)         # time off overlapping time off
    add_tour(api, "2041-05-09", "2041-05-01", expect=400)                           # ends before it starts
    add_tour(api, "2041-06-01", "2041-06-02", name="  ", expect=400)               # a tour needs a name


def test_time_off_defaults_to_a_day_off_and_never_has_room_rent(api):
    off = add_tour(api, "2041-07-01", "2041-07-02", kind="time_off", room_rent_per_day=100)
    assert off["time_off_type"] == "day_off" and off["room_rent_per_day"] is None
    assert expenses(api) == []


def test_booking_a_client_during_time_off_asks_first(api):
    add_tour(api, "2041-08-01", "2041-08-07", kind="time_off", time_off_type="vacation", name="Mexico")
    c = add_client(api)
    r = api.post("/api/appointments", params={"warn": True}, json={
        "client_id": c["id"], "service_type": "Session", "duration_minutes": 60, "scheduled_date": "2041-08-03T20:00:00Z"})
    assert r.status_code == 409, r.text
    warnings = r.json()["detail"]["warnings"]
    assert [w["type"] for w in warnings] == ["time_off"]
    assert "vacation" in warnings[0]["message"] and "Mexico" in warnings[0]["message"]
    book(api, c, "2041-08-03T20:00:00Z")                         # "Save anyway"
    book(api, c, "2041-08-09T20:00:00Z", params={"warn": True})  # after the vacation: no question


def test_tours_are_private(api, admin):
    tour = add_tour(api, "2041-09-01", "2041-09-02")
    assert admin.get(f"/api/tours/{tour['id']}").status_code == 404
    assert admin.get(f"/api/tours/{tour['id']}/summary").status_code == 404
    assert tour["id"] not in [t["id"] for t in admin.get("/api/tours").json()]
    assert admin.put(f"/api/tours/{tour['id']}", json=period("2041-09-01", "2041-09-02")).status_code == 404


def test_listing_tours_by_range_for_the_calendar(api):
    a = add_tour(api, "2041-10-01", "2041-10-05")
    b = add_tour(api, "2041-10-20", "2041-10-22", name="Austin")
    ids = lambda **p: [t["id"] for t in api.get("/api/tours", params=p).json()]  # noqa: E731
    assert ids(start="2041-10-04T00:00:00Z", end="2041-10-10T00:00:00Z") == [a["id"]]
    assert ids(start="2041-10-01T00:00:00Z", end="2041-11-01T00:00:00Z") == [a["id"], b["id"]]


# ---------- money per tour ----------

def test_tour_figures_count_what_happens_during_the_tour(api):
    tour = add_tour(api, "2041-11-03", "2041-11-06", room_rent_per_day=100)
    c = add_client(api)
    book(api, c, "2041-11-03T20:00:00Z", rate=500, amount_paid=500, status="completed")
    book(api, c, "2041-11-05T20:00:00Z", rate=300, amount_paid=100, status="completed")
    book(api, c, "2041-11-06T23:00:00Z", rate=400, status="cancelled")
    book(api, c, "2041-11-07T01:00:00Z", rate=999, amount_paid=999)        # the day after: not this tour
    api.post("/api/expenses", json={"description": "Flight", "amount": 250, "category": "travel",
                                    "date": "2041-11-03T09:00:00Z"})      # on no tour, but during it
    api.post("/api/expenses", json={"description": "Ads", "amount": 40, "category": "marketing",
                                    "date": "2041-11-10T09:00:00Z", "tour_id": tour["id"]})  # put on the tour
    api.post("/api/expenses", json={"description": "Unrelated", "amount": 70, "date": "2041-11-20T09:00:00Z"})
    add_tour(api, "2041-11-05", "2041-11-05", kind="time_off")

    data = summary(api, tour)
    f = data["figures"]
    assert f["income"] == 600 and f["booked"] == 800 and f["owed"] == 200
    assert f["appointments"] == 2 and f["completed"] == 2
    assert f["room_rent"] == 400 and f["tests"] == 0 and f["other_expenses"] == 290 and f["expenses"] == 690
    assert f["profit"] == -90
    assert (f["days"], f["days_off"], f["working_days"]) == (4, 1, 3)
    assert f["profit_per_day"] == -30
    assert len(data["appointments"]) == 3

    listed = {t["id"]: t["figures"]["profit"] for t in api.get("/api/tours/summary").json()}
    assert listed == {tour["id"]: -90}


# ---------- health tests ----------

def test_a_health_test_with_a_cost_is_a_medical_expense(api):
    tour = add_tour(api, "2042-01-10", "2042-01-14")
    t = add_test(api, "2042-01-09T15:00:00Z", "weekly", 80, tour_id=tour["id"])   # the day before the tour
    assert (t["service_type"], t["client_id"], t["kind"], t["tour_id"]) == ("Weekly test", None, "test", tour["id"])
    medical = expenses(api, category="medical")
    assert [(e["amount"], e["test_type"], e["appointment_id"], e["tour_id"]) for e in medical] == [
        (80, "weekly", t["id"], tour["id"])]

    # It counts toward the tour it was put on, even though it's the day before.
    f = summary(api, tour)["figures"]
    assert f["tests"] == 80 and f["tests_by_type"] == {"weekly": 80}   # only the kinds that cost something

    # The expense follows the test, and is changed there, not by hand.
    assert api.delete(f"/api/expenses/{medical[0]['id']}").status_code == 400
    r = api.put(f"/api/appointments/{t['id']}", json={
        "kind": "test", "test_type": "monthly", "cost": 120, "duration_minutes": 30,
        "scheduled_date": "2042-01-11T15:00:00Z", "tour_id": tour["id"]})
    assert r.status_code == 200, r.text
    assert [(e["amount"], e["test_type"], e["description"]) for e in expenses(api, category="medical")] == [
        (120, "monthly", "Monthly test")]

    # Cancelling removes the cost; marking it scheduled again brings it back on the same tour.
    api.put(f"/api/appointments/{t['id']}/status", params={"status": "cancelled"})
    assert expenses(api, category="medical") == []
    api.put(f"/api/appointments/{t['id']}/status", params={"status": "scheduled"})
    assert [e["amount"] for e in expenses(api, category="medical")] == [120]

    assert api.delete(f"/api/appointments/{t['id']}").status_code == 204
    assert expenses(api, category="medical") == []


def test_health_tests_remember_their_last_cost(api):
    assert api.get("/api/appointments/test-costs").json() == {"weekly": None, "monthly": None, "yearly": None}
    add_test(api, "2042-02-01T15:00:00Z", "weekly", 75)
    add_test(api, "2042-02-02T15:00:00Z", "yearly", 300)
    assert api.get("/api/appointments/test-costs").json() == {"weekly": 75, "monthly": None, "yearly": 300}


def test_health_test_rules(api):
    add_test(api, "2042-03-01T15:00:00Z", test_type=None, expect=400)
    add_test(api, "2042-03-01T15:00:00Z", cost=-5, expect=400)
    add_test(api, "2042-03-01T15:00:00Z", repeat_dates=["2042-03-08T15:00:00Z"], expect=400)
    add_test(api, "2042-03-01T15:00:00Z", tour_id=999999, expect=400)
    # A test never carries client details or income, whatever is sent.
    c = add_client(api)
    t = add_test(api, "2042-03-02T15:00:00Z", client_id=c["id"], rate=500, amount_paid=500, safety_checkin=True)
    assert (t["client_id"], t["rate"], t["amount_paid"], t["safety_checkin"]) == (None, None, 0, False)
    # A test without a cost is fine, and has no expense.
    add_test(api, "2042-03-03T15:00:00Z", cost=None)
    assert [e["amount"] for e in expenses(api, category="medical")] == [80]


def test_a_client_appointment_still_needs_a_client(api):
    r = api.post("/api/appointments", json={"service_type": "Session", "duration_minutes": 60,
                                            "scheduled_date": "2042-04-01T15:00:00Z"})
    assert r.status_code == 400 and "client" in r.json()["detail"].lower()


# ---------- earnings by month or week ----------

def test_compare_by_month_counts_days_off(api):
    c = add_client(api)
    book(api, c, "2042-05-10T20:00:00Z", rate=400, amount_paid=400, status="completed")
    book(api, c, "2042-06-02T20:00:00Z", rate=300, amount_paid=300, status="completed")
    api.post("/api/expenses", json={"description": "Ads", "amount": 100, "date": "2042-05-15T12:00:00Z"})
    add_tour(api, "2042-05-30", "2042-06-02", kind="time_off", time_off_type="vacation")

    r = api.get("/api/earnings/compare", params={"by": "month", "start": "2042-05-01T00:00:00Z",
                                                 "end": "2042-07-01T00:00:00Z", "tz_offset": 0})
    assert r.status_code == 200, r.text
    may, june = r.json()["rows"]
    assert may["key"] == "2042-05" and june["key"] == "2042-06"
    assert (may["figures"]["income"], may["figures"]["expenses"], may["figures"]["profit"]) == (400, 100, 300)
    assert (may["figures"]["days"], may["figures"]["days_off"], may["figures"]["working_days"]) == (31, 2, 29)
    assert (june["figures"]["days_off"], june["figures"]["working_days"], june["figures"]["profit_per_day"]) == (2, 28, 10.71)


def test_compare_uses_the_viewers_time_zone_and_weeks_start_on_sunday(api):
    c = add_client(api)
    # 02:00 UTC on Sunday 2042-06-08 is still Saturday evening in New York (UTC-4 in June).
    book(api, c, "2042-06-08T02:00:00Z", rate=200, amount_paid=200)
    params = {"by": "week", "start": "2042-06-01T04:00:00Z", "end": "2042-06-15T04:00:00Z", "tz_offset": 240}
    rows = api.get("/api/earnings/compare", params=params).json()["rows"]
    assert [(r["key"], r["figures"]["income"]) for r in rows] == [("2042-06-01", 200), ("2042-06-08", 0)]
    assert api.get("/api/earnings/compare", params={**params, "by": "year"}).status_code == 400


# ---------- client birthday and preferences ----------

def test_client_birthday_and_preferences(api):
    c = add_client(api, birthday="1990-04-23", drink_preferences="Dry martini", food_preferences="No shellfish")
    assert (c["birthday"], c["drink_preferences"], c["food_preferences"]) == ("1990-04-23", "Dry martini", "No shellfish")
    r = api.put(f"/api/clients/{c['id']}", json={"name": c["name"], "birthday": None, "drink_preferences": "  "})
    assert r.status_code == 200
    assert (r.json()["birthday"], r.json()["drink_preferences"], r.json()["food_preferences"]) == (None, None, None)
    assert api.post("/api/clients", json={"name": "X", "birthday": "not a date"}).status_code == 422


# ---------- account ----------

def test_work_style_setting(api):
    assert api.get("/api/account/settings").json()["work_style"] == "both"
    r = api.put("/api/account/settings", json={"work_style": "full_time"})
    assert r.status_code == 200 and r.json()["work_style"] == "full_time"
    assert api.get("/api/account/settings").json()["work_style"] == "full_time"
    assert api.put("/api/account/settings", json={"work_style": "sometimes"}).status_code == 422
