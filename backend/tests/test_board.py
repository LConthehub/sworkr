"""Tests for free room and board: a place's rules (board.py), and how they change a stay's room & board.
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
FEE = 100


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    name = "b-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def house(api, room=FEE, cadence="per_day"):
    h = ok(api.post("/api/income-sources", json={"name": "The House", "kind": "brothel", "fee_percent": 50}), 201)
    ok(api.post(f"/api/income-sources/{h['id']}/charges", json={"label": "Room & board", "cadence": cadence, "amount": room,
                                                                 "category": "room_rent"}), 201)
    return h


def stay(api, h, first="2044-07-01", last="2044-07-10"):
    end = date.fromisoformat(last) + timedelta(days=1)
    return ok(api.post("/api/tours", json={"kind": "tour", "name": "Stint", "start_date": first, "end_date": last,
                                           "starts_at": f"{first}T00:00:00Z", "ends_at": f"{end.isoformat()}T00:00:00Z",
                                           "source_id": h["id"]}), 201)


def earn(api, h, day, gross, kind="shift"):
    return ok(api.post("/api/income", json={"source_id": h["id"], "date": f"{day}T20:00:00Z", "kind": kind,
                                            "gross": gross, "fees": gross / 2}), 201)


def rule(api, h, counts, reaches, frees, **more):
    return ok(api.post(f"/api/income-sources/{h['id']}/board-rules",
                       json={"counts": counts, "reaches": reaches, "frees": frees, **more}), 201)


def room(api, s):
    """The stay's room & board: {day: (amount, why free)}."""
    rows = [e for e in ok(api.get("/api/expenses")) if e.get("tour_id") == s["id"] and e["category"] == "room_rent"]
    return {e["date"][:10]: (e["amount"], e["board_free"]) for e in rows}


def free(api, s):
    return sorted(d for d, (amount, why) in room(api, s).items() if why)


def test_with_no_rules_every_day_is_charged(api):
    h = house(api)
    s = stay(api, h)
    earn(api, h, "2044-07-02", 3000)
    assert free(api, s) == [] and sum(a for a, _ in room(api, s).values()) == 10 * FEE


def test_a_big_party_frees_its_day_and_comes_back_if_it_is_removed(api):
    h = house(api)
    s = stay(api, h)
    rule(api, h, "party", 1000, "day")
    big = earn(api, h, "2044-07-02", 1000)
    earn(api, h, "2044-07-03", 999)
    assert room(api, s)["2044-07-02"] == (0, "A party of $1,000 or more: that day is free")
    assert room(api, s)["2044-07-03"] == (FEE, None)
    st = ok(api.get(f"/api/tours/{s['id']}/summary"))["statement"]
    assert st["charges_total"] == 9 * FEE                                   # the statement agrees
    ok(api.delete(f"/api/income/{big['id']}"), 204)
    assert room(api, s)["2044-07-02"] == (FEE, None)                        # the full amount is back


def test_editing_income_moves_the_free_day(api):
    h = house(api)
    s = stay(api, h)
    rule(api, h, "party", 1000, "day")
    e = earn(api, h, "2044-07-02", 1200)
    ok(api.put(f"/api/income/{e['id']}", json={"source_id": h["id"], "date": "2044-07-05T20:00:00Z", "kind": "shift",
                                               "gross": 1200, "fees": 600}))
    assert free(api, s) == ["2044-07-05"]


def test_a_days_income_adds_up_and_tips_do_not_count(api):
    h = house(api)
    s = stay(api, h)
    rule(api, h, "day", 800, "day")
    earn(api, h, "2044-07-02", 500)
    earn(api, h, "2044-07-02", 300)
    earn(api, h, "2044-07-03", 500)
    earn(api, h, "2044-07-03", 300, kind="tips")
    assert free(api, s) == ["2044-07-02"]


def test_what_you_kept_can_be_what_counts(api):
    h = house(api)
    s = stay(api, h)
    rule(api, h, "party", 500, "day", basis="her_share")
    earn(api, h, "2044-07-02", 800)          # kept 400
    earn(api, h, "2044-07-03", 1000)         # kept 500
    assert free(api, s) == ["2044-07-03"]


def test_a_good_week_frees_the_whole_week(api):
    h = house(api)
    s = stay(api, h)
    rule(api, h, "week", 3000, "week")
    earn(api, h, "2044-07-01", 1000)
    earn(api, h, "2044-07-06", 2000)         # week one of the stay: 1 to 7 July
    earn(api, h, "2044-07-09", 2900)         # week two: short
    assert free(api, s) == [f"2044-07-0{d}" for d in range(1, 8)]


def test_a_weekly_charge_is_free_only_when_its_whole_week_is(api):
    h = house(api, room=500, cadence="per_week")
    s = stay(api, h, last="2044-07-14")
    rule(api, h, "day", 1000, "day")
    earn(api, h, "2044-07-02", 1000)          # one free day doesn't free a week's charge
    assert free(api, s) == []
    rule(api, h, "week", 5000, "week")
    earn(api, h, "2044-07-10", 5000)
    assert room(api, s) == {"2044-07-01": (500, None), "2044-07-08": (0, "$5,000 or more in a week of the stay: that whole week is free")}


def test_a_completed_booking_counts(api):
    h = house(api)
    s = stay(api, h)
    rule(api, h, "party", 1000, "day")
    client = ok(api.post("/api/clients", json={"name": "Sam"}), 201)
    b = ok(api.post("/api/appointments", json={"client_id": client["id"], "duration_minutes": 60, "service_type": "Party",
                                               "scheduled_date": "2044-07-04T21:00:00Z", "rate": 1200}), 201)
    assert free(api, s) == []                                               # not done yet
    ok(api.put(f"/api/appointments/{b['id']}/status", params={"status": "completed"}))
    assert free(api, s) == ["2044-07-04"]
    ok(api.delete(f"/api/appointments/{b['id']}"), 204)
    assert free(api, s) == []


def test_a_rule_only_counts_while_the_house_had_it(api):
    h = house(api)
    s = stay(api, h)
    r = rule(api, h, "party", 1000, "day", starts_on="2044-07-04", ends_on="2044-07-06")
    for d in ("2044-07-03", "2044-07-05", "2044-07-07"):
        earn(api, h, d, 1500)
    assert free(api, s) == ["2044-07-05"]
    ok(api.put(f"/api/board-rules/{r['id']}", json={"counts": "party", "reaches": 1000, "frees": "day"}))   # always
    assert free(api, s) == ["2044-07-03", "2044-07-05", "2044-07-07"]
    ok(api.delete(f"/api/board-rules/{r['id']}"), 204)
    assert free(api, s) == []


def test_changing_the_stay_keeps_its_free_days(api):
    h = house(api)
    s = stay(api, h)
    rule(api, h, "party", 1000, "day")
    earn(api, h, "2044-07-02", 1000)
    ok(api.put(f"/api/tours/{s['id']}", json={"kind": "tour", "name": "Longer stint", "start_date": "2044-07-01",
                                              "end_date": "2044-07-12", "starts_at": "2044-07-01T00:00:00Z",
                                              "ends_at": "2044-07-13T00:00:00Z", "source_id": h["id"]}))
    assert free(api, s) == ["2044-07-02"] and len(room(api, s)) == 12


def test_rules_are_yours_and_checked(api, admin):
    h = house(api)
    body = {"counts": "party", "reaches": 1000, "frees": "day"}
    r = rule(api, h, "party", 1000, "day")
    assert [x["words"] for x in ok(api.get(f"/api/income-sources/{h['id']}/board-rules"))] == ["A party of $1,000 or more: that day is free"]
    assert admin.post(f"/api/income-sources/{h['id']}/board-rules", json=body).status_code == 404
    assert admin.delete(f"/api/board-rules/{r['id']}").status_code == 404
    assert api.post(f"/api/income-sources/{h['id']}/board-rules", json={**body, "reaches": 0}).status_code == 422
    assert api.post(f"/api/income-sources/{h['id']}/board-rules", json={**body, "frees": "month"}).status_code == 422
    assert api.post(f"/api/income-sources/{h['id']}/board-rules",
                    json={**body, "starts_on": "2044-07-05", "ends_on": "2044-07-01"}).status_code == 400
