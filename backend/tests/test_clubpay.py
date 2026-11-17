"""Tests for club pay: contractor or employee, house fees by arrival, dances, VIP, tip-outs.
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
    name = "cp-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)


CONTRACTOR = {
    "status": "contractor",
    "house_fees": [{"until": None, "fee": 80}, {"until": "21:00", "fee": 40}],   # out of order on purpose
    "dance_price": 20, "dance_house": 5, "dance_house_kind": "amount",
    "vip_house_percent": 50,
    "tip_outs": [{"label": "DJ", "kind": "amount", "value": 20}, {"label": "House mom", "kind": "percent", "value": 10}],
}


def club(api, pay):
    return ok(api.post("/api/income-sources", json={"name": "Club", "kind": "club", "club_pay": pay}), 201)


def shift(api, c, **fields):
    return ok(api.post(f"/api/income-sources/{c['id']}/club-shift", json=fields))


def test_a_contractor_shift_statement(api):
    c = club(api, CONTRACTOR)
    assert [r["until"] for r in c["club_pay"]["house_fees"]] == ["21:00", None]   # kept in time order
    s = shift(api, c, arrived="20:30", hours=6, dances=10, vip=300, tips=50, fines=10)
    # made: 10 dances x $20 + $300 VIP + $50 tips = $550
    # taken: house fee $40 (before 9), dances 10 x $5, half the VIP $150, DJ $20,
    #        house mom 10% of what's left before tip-outs (550 - 40 - 50 - 150 = 310 -> $31), fines $10
    assert s["gross"] == 550
    assert {t["label"]: t["amount"] for t in s["taken"]} == {
        "House fee": 40, "House's cut of dances": 50, "House's VIP share": 150,
        "Tip-out: DJ": 20, "Tip-out: House mom": 31, "Fines": 10}
    assert s["take_home"] == 550 - (40 + 50 + 150 + 20 + 31 + 10)


def test_arriving_later_costs_more(api):
    c = club(api, CONTRACTOR)
    early = shift(api, c, arrived="20:59")
    late = shift(api, c, arrived="21:00")
    assert next(t["amount"] for t in early["taken"] if t["label"] == "House fee") == 40
    assert next(t["amount"] for t in late["taken"] if t["label"] == "House fee") == 80


def test_an_employee_gets_a_wage_and_pays_no_house_fee(api):
    c = club(api, {"status": "employee", "hourly_wage": 15, "house_fees": [{"until": None, "fee": 80}],
                   "dance_price": 30, "dance_house": 50, "dance_house_kind": "percent"})
    s = shift(api, c, hours=8, dances=4, tips=40)
    assert (s["wage"], s["gross"]) == (120, 120 + 120 + 40)
    assert {t["label"]: t["amount"] for t in s["taken"]} == {"House's cut of dances": 60}
    assert s["take_home"] == 280 - 60


def test_club_pay_is_checked_kept_and_private(api, admin):
    assert api.post("/api/income-sources", json={"name": "x", "kind": "club",
                                                 "club_pay": {"status": "intern"}}).status_code == 400
    assert api.post("/api/income-sources", json={"name": "x", "kind": "club",
                                                 "club_pay": {"house_fees": [{"until": "9pm", "fee": 1}]}}).status_code == 400
    c = club(api, CONTRACTOR)
    # Saving the workplace without club_pay leaves it alone.
    same = ok(api.put(f"/api/income-sources/{c['id']}", json={"name": "Club Velvet", "kind": "club"}))
    assert same["club_pay"]["dance_price"] == 20
    assert admin.post(f"/api/income-sources/{c['id']}/club-shift", json={}).status_code == 404
    assert api.post(f"/api/income-sources/{c['id']}/club-shift", json={"arrived": "late"}).status_code == 400
