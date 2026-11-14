"""Tests for the year-end tax summary.
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
    name = "t-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)


def test_the_year_adds_up_by_kind_of_income_and_main_category(api):
    house = ok(api.post("/api/income-sources", json={"name": "The House", "kind": "brothel", "gift_share_percent": 50}), 201)
    ok(api.post("/api/income", json={"source_id": house["id"], "kind": "shift", "date": "2044-03-01T20:00:00Z", "gross": 1000, "fees": 500}), 201)
    ok(api.post("/api/income", json={"source_id": house["id"], "kind": "gift", "date": "2044-04-01T20:00:00Z", "gross": 2000, "fees": 1000}), 201)
    ok(api.post("/api/income", json={"kind": "tips", "date": "2044-05-01T20:00:00Z", "gross": 100, "status": "pending"}), 201)
    ok(api.post("/api/income", json={"kind": "tips", "date": "2045-01-01T20:00:00Z", "gross": 999}), 201)   # next year
    sam = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    ok(api.post("/api/appointments", json={"client_id": sam["id"], "service_type": "Dinner", "duration_minutes": 60,
                                           "scheduled_date": "2044-06-01T20:00:00Z", "status": "completed", "rate": 400, "amount_paid": 400}), 201)
    for cat, amount in (("room_rent", 300), ("workspace", 50), ("marketing", 120)):
        ok(api.post("/api/expenses", json={"description": "x", "amount": amount, "category": cat, "date": "2044-02-01T12:00:00Z"}), 201)

    t = ok(api.get("/api/tax-summary", params={"year": 2044, "set_aside_percent": 25}))
    by_kind = {i["key"]: i for i in t["income"]}
    assert (by_kind["gift"]["gross"], by_kind["gift"]["fees"]) == (2000, 1000)
    assert by_kind["calendar"]["gross"] == 400 and "tips" not in by_kind   # pending isn't income yet
    assert (t["gross_income"], t["fees"], t["total_expenses"]) == (3400, 1500, 470)
    assert t["profit"] == 3400 - 1500 - 470 and t["pending"] == 100
    work = next(g for g in t["expenses"] if g["key"] == "workspace")
    assert work["total"] == 350 and {l["label"] for l in work["lines"]} == {"Room & board", "General"}
    assert t["set_aside"] == {"percent": 25, "amount": round((3400 - 1500 - 470) * 0.25, 2)}


def test_the_year_follows_your_time_zone(api):
    # 1 Jan 2045 at 03:00 UTC is still New Year's Eve 2044 in Los Angeles (UTC-8, getTimezoneOffset 480).
    ok(api.post("/api/income", json={"kind": "tips", "date": "2045-01-01T03:00:00Z", "gross": 50}), 201)
    assert ok(api.get("/api/tax-summary", params={"year": 2044, "tz_offset": 480}))["gross_income"] == 50
    assert ok(api.get("/api/tax-summary", params={"year": 2044}))["gross_income"] == 0


def test_partners_shares_are_left_out(api, admin):
    pal = ok(api.post("/api/clients", json={"name": "Pal", "role": "partner"}), 201)
    inc = ok(api.post("/api/income", json={"kind": "sale", "date": "2044-03-01T20:00:00Z", "gross": 1000}), 201)
    ok(api.put(f"/api/splits/income/{inc['id']}", json={"parties": [{"partner_id": pal["id"], "share_type": "percent", "share_value": 40}]}))
    assert ok(api.get("/api/tax-summary", params={"year": 2044}))["gross_income"] == 600
    assert ok(admin.get("/api/tax-summary", params={"year": 2044}))["gross_income"] == 0


# ---------- US quarterly estimated tax ----------

def test_due_dates_follow_the_irs_periods_and_skip_weekends():
    import taxes
    from datetime import date as d
    assert [taxes.due_date(2026, q) for q in (1, 2, 3, 4)] == [d(2026, 4, 15), d(2026, 6, 15), d(2026, 9, 15), d(2027, 1, 15)]
    assert taxes.due_date(2028, 3) == d(2028, 9, 15)      # a Friday
    assert taxes.due_date(2029, 4) == d(2030, 1, 15)
    assert taxes.due_date(2023, 1) == d(2023, 4, 17)      # 15 April 2023 was a Saturday


def test_each_period_shows_profit_set_aside_and_payments(api):
    # Q2 is April and May only: income on 31 May is Q2, on 1 June is Q3.
    ok(api.post("/api/income", json={"kind": "tips", "date": "2044-05-31T12:00:00Z", "gross": 1000}), 201)
    ok(api.post("/api/income", json={"kind": "tips", "date": "2044-06-01T12:00:00Z", "gross": 400}), 201)
    ok(api.post("/api/expenses", json={"description": "x", "amount": 200, "category": "marketing", "date": "2044-04-10T12:00:00Z"}), 201)
    ok(api.post("/api/tax-summary/payments", json={"year": 2044, "quarter": 2, "amount": 150, "paid_on": "2044-06-14"}), 201)
    ok(api.post("/api/tax-summary/payments", json={"year": 2044, "quarter": 2, "authority": "state", "amount": 40, "paid_on": "2044-06-14"}), 201)
    q = {x["quarter"]: x for x in ok(api.get("/api/tax-summary/quarters", params={"year": 2044, "set_aside_percent": 25}))["quarters"]}
    assert (q[2]["profit"], q[2]["set_aside"], q[2]["paid_federal"], q[2]["paid_state"]) == (800, 200, 150, 40)
    assert (q[3]["profit"], q[3]["set_aside"]) == (400, 100)
    assert q[1]["profit"] == 0 and q[2]["due"] == "2044-06-15"
    # Payments aren't expenses, but the year's summary lists them.
    year = ok(api.get("/api/tax-summary", params={"year": 2044}))
    assert year["total_expenses"] == 200
    assert year["estimated_payments"] == [{"authority": "federal", "total": 150, "payments": 1},
                                          {"authority": "state", "total": 40, "payments": 1}]
    assert api.post("/api/tax-summary/payments", json={"year": 2044, "quarter": 5, "amount": 1, "paid_on": "2044-06-14"}).status_code == 400


def test_payments_are_private_and_can_be_deleted(api, admin):
    p = ok(api.post("/api/tax-summary/payments", json={"year": 2044, "quarter": 1, "amount": 99, "paid_on": "2044-04-14"}), 201)
    admin.delete(f"/api/tax-summary/payments/{p['id']}")
    assert ok(api.get("/api/tax-summary/quarters", params={"year": 2044}))["total_paid"] == 99
    assert api.delete(f"/api/tax-summary/payments/{p['id']}").status_code == 204
    assert ok(api.get("/api/tax-summary/quarters", params={"year": 2044}))["total_paid"] == 0


def test_reminders_a_week_before_each_due_date(api):
    r = ok(api.put("/api/tax-summary/reminders", json={"enabled": True}))
    assert r["tasks"] == 4
    titles = [t["title"] for t in ok(api.get("/api/tasks")) if t["title"].startswith("Estimated tax payment due")]
    assert len(titles) == 4 and ok(api.get("/api/tax-summary/reminders"))["enabled"]
    ok(api.put("/api/tax-summary/reminders", json={"enabled": False}))
    assert not [t for t in ok(api.get("/api/tasks")) if t["title"].startswith("Estimated tax payment due")]
