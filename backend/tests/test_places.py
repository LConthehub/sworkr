"""Tests for kinds of place and the charges a place makes (room & board, doctor, license, room hire).
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
    name = "p-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)


def test_kinds_of_place(api):
    for kind in ("brothel", "club", "agency", "platform", "phone", "studio", "event", "other"):
        assert place(api, f"P {kind}", kind)["kind"] == kind
    assert api.post("/api/income-sources", json={"name": "x", "kind": "venue"}).status_code == 422


def test_brothel_starter_comes_with_its_charges(api):
    ok(api.put("/api/work-profile", json={"work_types": ["brothel"]}))
    house = next(s for s in ok(api.get("/api/income-sources")) if s["name"] == "My brothel")
    assert house["kind"] == "brothel"
    charges = {c["label"]: c for c in ok(api.get("/api/place-charges")) if c["source_id"] == house["id"]}
    assert set(charges) == {"Room & board", "Doctor"}      # a license is paid to the government, not the house
    assert (charges["Room & board"]["cadence"], charges["Room & board"]["category"]) == ("per_day", "room_rent")
    assert (charges["Doctor"]["test_type"], charges["Doctor"]["category"]) == ("weekly", "medical")
    licence_cat = next(c for c in ok(api.get("/api/expense-categories")) if c["label"] == "Licenses & permits")
    assert licence_cat["parent_key"] == "fees"                  # the category is still there, for what's paid to the authority
    assert all(c["amount"] is None for c in charges.values())   # left for the person to fill in


def test_logging_a_charge_adds_an_expense(api):
    house = place(api)
    room = ok(api.post(f"/api/income-sources/{house['id']}/charges",
                       json={"label": "Room & board", "cadence": "per_day", "category": "room_rent"}), 201)
    assert api.post(f"/api/place-charges/{room['id']}/log", json={}).status_code == 400    # no amount yet
    ok(api.put(f"/api/place-charges/{room['id']}", json={"label": "Room & board", "cadence": "per_day",
                                                          "category": "room_rent", "amount": 120}))
    r = ok(api.post(f"/api/place-charges/{room['id']}/log", json={"date": "2044-05-02T12:00:00Z"}), 201)
    r2 = ok(api.post(f"/api/place-charges/{room['id']}/log", json={"date": "2044-05-03T12:00:00Z", "amount": 90}), 201)
    spent = {e["id"]: e for e in ok(api.get("/api/expenses"))}
    assert spent[r["expense_id"]]["amount"] == 120 and spent[r2["expense_id"]]["amount"] == 90
    assert spent[r["expense_id"]]["category"] == "room_rent"
    assert spent[r["expense_id"]]["description"] == "Room & board – The House"
    assert api.post(f"/api/income-sources/{house['id']}/charges",
                    json={"label": "x", "cadence": "per_day", "category": "yachts"}).status_code == 422


def test_a_house_doctor_is_logged_as_a_health_test(api):
    house = place(api)
    doctor = ok(api.post(f"/api/income-sources/{house['id']}/charges",
                         json={"label": "Doctor", "cadence": "per_week", "amount": 60, "test_type": "weekly",
                               "category": "travel"}), 201)
    assert doctor["category"] == "medical"      # always under Tests & doctor
    r = ok(api.post(f"/api/place-charges/{doctor['id']}/log", json={"date": "2044-05-04T10:00:00Z"}), 201)
    test = ok(api.get(f"/api/appointments/{r['appointment_id']}"))
    assert (test["kind"], test["test_type"], test["cost"]) == ("test", "weekly", 60)
    expenses = [e for e in ok(api.get("/api/expenses")) if e["category"] == "medical"]
    assert [e["amount"] for e in expenses] == [60]


def test_a_license_gets_a_renewal_reminder_that_moves_when_paid(api):
    house = place(api)
    renews = date.today() + timedelta(days=40)
    lic = ok(api.post(f"/api/income-sources/{house['id']}/charges", json={
        "label": "Work card", "cadence": "per_year", "amount": 275, "category": "fees", "renews_on": renews.isoformat()}), 201)
    task = next(t for t in ok(api.get("/api/tasks")) if t["id"] == lic["task_id"])
    assert task["title"] == "Renew Work card – The House"
    assert task["due_date"] == (renews - timedelta(days=14)).isoformat()

    # Paying it for the coming year moves the date on a year, and the reminder with it.
    r = ok(api.post(f"/api/place-charges/{lic['id']}/log", json={}), 201)
    assert r["charge"]["renews_on"] == renews.replace(year=renews.year + 1).isoformat()
    task = next(t for t in ok(api.get("/api/tasks", params={"status": "all"})) if t["id"] == lic["task_id"])
    assert task["due_date"] == (renews.replace(year=renews.year + 1) - timedelta(days=14)).isoformat()

    # A daily charge can't have a renewal date; clearing the date removes the reminder.
    daily = ok(api.post(f"/api/income-sources/{house['id']}/charges", json={
        "label": "Linen", "cadence": "per_day", "renews_on": renews.isoformat()}), 201)
    assert daily["renews_on"] is None and daily["task_id"] is None
    ok(api.put(f"/api/place-charges/{lic['id']}", json={"label": "Work card", "cadence": "per_year", "category": "fees"}))
    assert lic["task_id"] not in [t["id"] for t in ok(api.get("/api/tasks", params={"status": "all"}))]


def test_deleting_a_place_takes_its_charges_and_reminders(api):
    house = place(api)
    lic = ok(api.post(f"/api/income-sources/{house['id']}/charges", json={
        "label": "License", "cadence": "once", "renews_on": (date.today() + timedelta(days=300)).isoformat()}), 201)
    assert lic["task_id"]
    assert api.delete(f"/api/income-sources/{house['id']}").status_code == 204
    assert ok(api.get("/api/place-charges")) == []
    assert lic["task_id"] not in [t["id"] for t in ok(api.get("/api/tasks", params={"status": "all"}))]


def test_charges_are_private(api, admin):
    house = place(api)
    mine = ok(api.post(f"/api/income-sources/{house['id']}/charges", json={"label": "Room", "amount": 5}), 201)
    assert admin.put(f"/api/place-charges/{mine['id']}", json={"label": "Mine"}).status_code == 404
    assert admin.post(f"/api/place-charges/{mine['id']}/log", json={}).status_code == 404
    assert admin.delete(f"/api/place-charges/{mine['id']}").status_code == 404
    assert admin.post(f"/api/income-sources/{house['id']}/charges", json={"label": "x"}).status_code == 404
    assert mine["id"] not in [c["id"] for c in ok(admin.get("/api/place-charges"))]


# ---------- stays: a tour at one of your places ----------

def stay(api, first, last, source_id, name="Spring stint", expect=201, **fields):
    end = date.fromisoformat(last) + timedelta(days=1)
    r = api.post("/api/tours", json={"kind": "tour", "name": name, "start_date": first, "end_date": last,
                                     "starts_at": f"{first}T00:00:00Z", "ends_at": f"{end.isoformat()}T00:00:00Z",
                                     "source_id": source_id, **fields})
    assert r.status_code == expect, r.text
    return r.json()


def charge(api, source_id, **fields):
    return ok(api.post(f"/api/income-sources/{source_id}/charges", json=fields), 201)


def test_a_stay_logs_the_places_daily_weekly_and_per_stay_charges(api):
    house = place(api)
    charge(api, house["id"], label="Room & board", cadence="per_day", amount=100, category="room_rent")
    charge(api, house["id"], label="Doctor", cadence="per_week", amount=60, test_type="weekly")
    charge(api, house["id"], label="Linen", cadence="per_stay", amount=25, category="cleaning")
    charge(api, house["id"], label="Booking fee", cadence="per_booking", amount=10)    # not by the day: left alone
    charge(api, house["id"], label="Parking", cadence="per_day")                       # no amount yet: left alone

    s = stay(api, "2044-06-01", "2044-06-10", house["id"])      # 10 days
    summary = ok(api.get(f"/api/tours/{s['id']}/summary"))
    by_label = {}
    for e in summary["expenses"]:
        by_label.setdefault(e["description"].rsplit(" – ", 1)[0], []).append(e)
    assert len(by_label["Room & board"]) == 10 and len(by_label["Linen"]) == 1
    assert len(by_label["Doctor"]) == 2 and all(e["category"] == "medical" for e in by_label["Doctor"])   # days 1 and 8
    assert "Booking fee" not in by_label and "Parking" not in by_label
    tests = [a for a in summary["appointments"] if a["kind"] == "test"]
    assert sorted(a["scheduled_date"][:10] for a in tests) == ["2044-06-01", "2044-06-08"]

    st = summary["statement"]
    assert st["place"]["name"] == "The House" and st["charges_total"] == 10 * 100 + 2 * 60 + 25
    assert {c["label"]: c["count"] for c in st["charges"]} == {"Room & board": 10, "Doctor": 2, "Linen": 1}

    # Shorter stay: logged again, nothing doubled.
    end = "2044-06-04"
    ok(api.put(f"/api/tours/{s['id']}", json={"kind": "tour", "name": "Spring stint", "start_date": "2044-06-01",
                                              "end_date": end, "starts_at": "2044-06-01T00:00:00Z",
                                              "ends_at": "2044-06-05T00:00:00Z", "source_id": house["id"]}))
    st = ok(api.get(f"/api/tours/{s['id']}/summary"))["statement"]
    assert {c["label"]: c["count"] for c in st["charges"]} == {"Room & board": 4, "Doctor": 1, "Linen": 1}

    # Changing a charge's amount changes the stays at that place.
    room = next(c for c in ok(api.get("/api/place-charges")) if c["label"] == "Room & board")
    ok(api.put(f"/api/place-charges/{room['id']}", json={"label": "Room & board", "cadence": "per_day",
                                                         "category": "room_rent", "amount": 80}))
    st = ok(api.get(f"/api/tours/{s['id']}/summary"))["statement"]
    assert next(c for c in st["charges"] if c["label"] == "Room & board")["total"] == 320

    # Deleting the stay takes what it logged, health tests included.
    assert api.delete(f"/api/tours/{s['id']}").status_code == 204
    assert [e for e in ok(api.get("/api/expenses")) if e.get("source") == "stay_charge"] == []
    assert [a for a in ok(api.get("/api/appointments")) if a.get("kind") == "test"] == []


def test_a_stay_statement_shows_what_you_should_be_paid(api):
    house = ok(api.post("/api/income-sources", json={"name": "The House", "kind": "brothel", "fee_percent": 50}), 201)
    charge(api, house["id"], label="Room & board", cadence="per_day", amount=100, category="room_rent")
    s = stay(api, "2044-07-01", "2044-07-03", house["id"])
    for day, gross in (("2044-07-01", 1000), ("2044-07-02", 600)):
        ok(api.post("/api/income", json={"source_id": house["id"], "date": f"{day}T20:00:00Z", "kind": "shift",
                                         "gross": gross, "fees": gross / 2}), 201)
    st = ok(api.get(f"/api/tours/{s['id']}/summary"))["statement"]
    assert (st["gross"], st["house_share"], st["charges_total"], st["take_home"]) == (1600, 800, 300, 500)

    # A tour that isn't at a place has no statement; a place that isn't yours is refused.
    other = stay(api, "2044-08-01", "2044-08-02", None, name="Chicago")
    assert ok(api.get(f"/api/tours/{other['id']}/summary"))["statement"] is None
    assert api.post("/api/tours", json={"kind": "tour", "name": "x", "start_date": "2044-09-01", "end_date": "2044-09-01",
                                        "starts_at": "2044-09-01T00:00:00Z", "ends_at": "2044-09-02T00:00:00Z",
                                        "source_id": 999999}).status_code == 400


# ---------- gifts, allowances, sugaring ----------

def test_a_brothel_gift_counts_at_its_value_minus_the_house_share(api):
    house = ok(api.post("/api/income-sources", json={"name": "The House", "kind": "brothel", "gift_share_percent": 50}), 201)
    assert house["gift_share_percent"] == 50
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    gift = ok(api.post("/api/income", json={"source_id": house["id"], "kind": "gift", "date": "2044-05-01T20:00:00Z",
                                            "description": "Designer bag", "gross": 2000, "fees": 1000,
                                            "client_id": sam["id"]}), 201)
    assert (gift["kind"], gift["net"], gift["client_name"]) == ("gift", 1000, "Sam")
    assert api.post("/api/income-sources", json={"name": "x", "gift_share_percent": 150}).status_code == 400


def test_allowance_names_who_it_is_from_and_only_your_contacts(api, admin):
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    a = ok(api.post("/api/income", json={"kind": "allowance", "date": "2044-05-01T20:00:00Z", "gross": 1500,
                                         "client_id": sam["id"]}), 201)
    assert a["client_id"] == sam["id"]
    assert admin.post("/api/income", json={"kind": "allowance", "date": "2044-05-01T20:00:00Z", "gross": 1,
                                           "client_id": sam["id"]}).status_code == 400
    assert api.delete(f"/api/clients/{sam['id']}").status_code == 204
    assert next(i for i in ok(api.get("/api/income")) if i["id"] == a["id"])["client_id"] is None


def test_sugar_dating_is_a_kind_of_work(api):
    options = {o["key"]: o["label"] for o in ok(api.get("/api/work-profile"))["options"]}
    assert options["sugar"].startswith("Sugar")
    ok(api.put("/api/work-profile", json={"work_types": ["sugar", "brothel"]}))
    places = {s["name"]: s for s in ok(api.get("/api/income-sources"))}
    assert places["My brothel"]["gift_share_percent"] == 50
    site = places["My sugar site"]
    membership = next(c for c in ok(api.get("/api/place-charges")) if c["source_id"] == site["id"])
    assert membership["cadence"] == "per_month"
    cat = next(c for c in ok(api.get("/api/expense-categories")) if c["key"] == membership["category"])
    assert (cat["label"], cat["parent_key"]) == ("Sugar-site memberships", "fees")


def test_a_quarterly_license_renews_three_months_on(api):
    house = place(api)
    renews = date.today() + timedelta(days=20)
    lic = ok(api.post(f"/api/income-sources/{house['id']}/charges", json={
        "label": "Quarterly license", "cadence": "per_quarter", "amount": 90, "category": "fees",
        "renews_on": renews.isoformat()}), 201)
    assert lic["renews_on"] == renews.isoformat() and lic["task_id"]
    r = ok(api.post(f"/api/place-charges/{lic['id']}/log", json={}), 201)
    month = renews.month + 2
    later = date(renews.year + month // 12, month % 12 + 1, 1)
    assert date.fromisoformat(r["charge"]["renews_on"]).replace(day=1) == later
    # Paying an old quarter well before the date doesn't move it again.
    r = ok(api.post(f"/api/place-charges/{lic['id']}/log", json={}), 201)
    assert date.fromisoformat(r["charge"]["renews_on"]).replace(day=1) == later


def test_renewing_a_license_moves_its_date_and_logs_what_was_paid_to_the_authority(api):
    ok(api.put("/api/work-profile", json={"work_types": ["brothel"]}))
    doc = ok(api.post("/api/documents", json={"name": "County work card", "kind": "work_card", "expires_on": (date.today() + timedelta(days=20)).isoformat()}), 201)
    new = (date.today() + timedelta(days=365)).isoformat()
    done = ok(api.post(f"/api/documents/{doc['id']}/renewed", json={"expires_on": new, "paid": 275, "paid_to": "County sheriff"}))
    assert (done["expires_on"], done["issued_on"]) == (new, date.today().isoformat())
    [expense] = [e for e in ok(api.get("/api/expenses")) if e["description"] == "County work card renewal"]
    assert (expense["amount"], expense["notes"]) == (275, "Paid to County sheriff")
    category = next(c for c in ok(api.get("/api/expense-categories")) if c["key"] == expense["category"])
    assert category["label"] == "Licenses & permits"
    task = next(t for t in ok(api.get("/api/tasks")) if t["id"] == done["task_id"])
    assert task["due_date"] == (date.today() + timedelta(days=365 - 30)).isoformat()      # the reminder moved with it
    assert ok(api.post(f"/api/documents/{doc['id']}/renewed", json={"expires_on": (date.today() + timedelta(days=400)).isoformat()}))["expires_on"]
    assert len([e for e in ok(api.get("/api/expenses")) if "renewal" in e["description"]]) == 1      # no cost, no expense
    assert api.post(f"/api/documents/{doc['id']}/renewed", json={"expires_on": date.today().isoformat()}).status_code == 400
    assert api.post(f"/api/documents/{doc['id']}/renewed", json={"expires_on": new, "paid": -5}).status_code == 400
    assert api.post("/api/documents/999999/renewed", json={"expires_on": new}).status_code == 404


def test_the_doctor_comes_on_their_own_day(api):
    house = place(api)
    doc = charge(api, house["id"], label="Doctor", cadence="per_week", amount=60, test_type="weekly", weekday=2)   # Wednesdays
    assert doc["weekday"] == 2
    s = stay(api, "2044-06-01", "2044-06-14", house["id"])
    tests = sorted(a["scheduled_date"][:10] for a in ok(api.get(f"/api/tours/{s['id']}/summary"))["appointments"] if a["kind"] == "test")
    assert tests and all(date.fromisoformat(d).weekday() == 2 for d in tests)
    expected = [d for d in (date(2044, 6, 1) + timedelta(days=i) for i in range(14)) if d.weekday() == 2]
    assert tests == [d.isoformat() for d in expected]
    # A stay that ends before the doctor's day gets no test.
    first_wed = expected[0]
    short_end = first_wed - timedelta(days=1)
    if short_end >= date(2044, 6, 1):
        s2 = stay(api, "2044-06-01", short_end.isoformat(), house["id"])
        assert not [a for a in ok(api.get(f"/api/tours/{s2['id']}/summary"))["appointments"] if a["kind"] == "test"]


def test_a_party_waits_for_a_clear_test_and_a_current_work_card(api):
    from datetime import date as _d, timedelta as _td
    house = place(api, name="Test House")
    charge(api, house["id"], label="Doctor", cadence="per_week", amount=60, test_type="weekly", weekday=2)   # Wednesdays
    first = _d(2045, 3, 6)                                    # a Monday
    s = stay(api, first.isoformat(), (first + _td(days=9)).isoformat(), house["id"])
    c = ok(api.post("/api/clients", json={"name": "Party guest"}), 201)
    def warn(day):
        r = api.post("/api/appointments", params={"warn": True}, json={"client_id": c["id"], "service_type": "Party",
                     "duration_minutes": 60, "scheduled_date": f"{day}T20:00:00Z"})
        return [w["message"] for w in r.json()["detail"]["warnings"] if w["type"] == "clearance"] if r.status_code == 409 else []
    assert any("No test yet" in m for m in warn("2045-03-07"))                     # Tuesday, before the doctor's day
    assert any("no result yet" in m for m in warn("2045-03-09"))                   # Thursday, result not marked
    test = next(a for a in ok(api.get(f"/api/tours/{s['id']}/summary"))["appointments"] if a["kind"] == "test")
    marked = ok(api.put(f"/api/appointments/{test['id']}/test-result", json={"result": "clear"}))
    assert marked["test_result"] == "clear"
    assert warn("2045-03-09") == []
    # The stay changing makes its tests again: the result stays.
    ok(api.put(f"/api/tours/{s['id']}", json={"kind": "tour", "name": "Spring stint", "start_date": first.isoformat(),
                                              "end_date": (first + _td(days=10)).isoformat(), "starts_at": f"{first.isoformat()}T00:00:00Z",
                                              "ends_at": f"{(first + _td(days=11)).isoformat()}T00:00:00Z", "source_id": house["id"]}))
    assert warn("2045-03-09") == []
    ok(api.post("/api/documents", json={"name": "Work card", "kind": "work_card", "expires_on": "2045-03-08", "source_id": house["id"]}), 201)
    assert any("Work card" in m and "ran out" in m for m in warn("2045-03-09"))
