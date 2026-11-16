"""The inquiry pipeline, and regulars who have gone quiet.
Run with:  docker compose run --rm tests"""
import os
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

PASSWORD = "correct-horse-battery"
YEAR = {"start": "2026-01-01T00:00:00Z", "end": "2027-01-01T00:00:00Z"}


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "pl-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    return new_user(admin)


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def inquiry(api, name, found_via=None, when="2026-03-01T12:00:00Z", **more):
    return ok(api.post("/api/inquiries", json={"name": name, "found_via": found_via, "received_at": when, **more}), 201)


def move(api, e, stage, **more):
    return ok(api.post(f"/api/inquiries/{e['id']}/stage", json={"stage": stage, **more}))


def test_an_inquiry_moves_through_the_stages(api):
    e = inquiry(api, "  @quiet_guy ", " Tryst ", contact="@quiet_guy on X", wanted="2h dinner, Friday")
    assert (e["name"], e["found_via"], e["stage"], e["lost_from"]) == ("@quiet_guy", "Tryst", "new", None)
    assert move(api, e, "replied")["stage"] == "replied"
    assert move(api, e, "screening")["stage"] == "screening"
    lost = move(api, e, "lost", lost_reason="Wouldn't screen")
    assert (lost["stage"], lost["lost_from"], lost["lost_reason"]) == ("lost", "screening", "Wouldn't screen")
    assert move(api, e, "lost", lost_reason="Still no")["lost_from"] == "screening"      # stays where it was lost from
    back = move(api, e, "deposit")
    assert (back["stage"], back["lost_from"], back["lost_reason"]) == ("deposit", None, None)

    person = ok(api.post("/api/clients", json={"name": "Quentin", "found_via": "Tryst"}), 201)
    linked = ok(api.put(f"/api/inquiries/{e['id']}", json={"name": "@quiet_guy", "found_via": "Tryst", "stage": "booked", "client_id": person["id"]}))
    assert linked["client_name"] == "Quentin" and linked["received_at"].startswith("2026-03-01")   # the date is kept
    ok(api.delete(f"/api/clients/{person['id']}"), 204)
    assert ok(api.get("/api/inquiries", params={"show": "booked"}))[0]["client_id"] is None        # the inquiry outlives the contact

    assert api.post("/api/inquiries", json={"name": " "}).status_code == 400
    assert api.post("/api/inquiries", json={"name": "x", "stage": "maybe"}).status_code == 400
    assert api.post("/api/inquiries", json={"name": "x", "client_id": 999999}).status_code == 400
    assert api.post(f"/api/inquiries/{e['id']}/stage", json={"stage": "maybe"}).status_code == 400
    assert api.post("/api/inquiries/999999/stage", json={"stage": "booked"}).status_code == 404
    assert api.get("/api/inquiries", params={"show": "nope"}).status_code == 400


def test_lists_by_where_they_are(api):
    a, b, c = inquiry(api, "A"), inquiry(api, "B", when="2026-03-02T12:00:00Z"), inquiry(api, "C")
    move(api, b, "booked")
    move(api, c, "lost")
    assert [e["name"] for e in ok(api.get("/api/inquiries"))] == ["A"]
    assert [e["name"] for e in ok(api.get("/api/inquiries", params={"show": "booked"}))] == ["B"]
    assert [e["name"] for e in ok(api.get("/api/inquiries", params={"show": "lost"}))] == ["C"]
    assert [e["name"] for e in ok(api.get("/api/inquiries", params={"show": "all"}))][0] == "B"    # newest first
    ok(api.delete(f"/api/inquiries/{a['id']}"), 204)
    assert ok(api.get("/api/inquiries")) == []


def test_the_summary_shows_where_inquiries_drop_out_and_which_sources_book(api):
    for i in range(4):
        e = inquiry(api, f"T{i}", "Tryst")
        if i < 3:
            move(api, e, "replied")
        if i < 2:
            move(api, e, "booked")
        if i == 2:
            move(api, e, "lost", lost_reason="Wouldn't screen")
    x = inquiry(api, "X1", "twitter")
    move(api, x, "lost", lost_reason="Wanted a discount")
    move(api, inquiry(api, "X2", "X"), "lost", lost_reason="Wanted a discount")
    inquiry(api, "Unknown")
    inquiry(api, "Last year", "Tryst", when="2025-06-01T12:00:00Z")

    s = ok(api.get("/api/inquiries/summary", params=YEAR))
    assert (s["total"], s["booked"], s["lost"], s["open"]) == (7, 2, 3, 2)
    assert s["rate"] == round(2 / 7, 4)
    assert {f["stage"]: f["count"] for f in s["funnel"]} == {"new": 7, "replied": 3, "screening": 2, "deposit": 2, "booked": 2}
    assert s["lost_reasons"] == [{"reason": "Wanted a discount", "count": 2}, {"reason": "Wouldn't screen", "count": 1}]
    sources = {r["key"]: r for r in s["sources"]}
    assert (sources["tryst"]["inquiries"], sources["tryst"]["booked"], sources["tryst"]["rate"]) == (4, 2, 0.5)
    assert (sources["x"]["inquiries"], sources["x"]["booked"], sources["x"]["lost"]) == (2, 0, 2)
    assert s["sources"][-1]["label"] == "Not recorded"
    empty = ok(api.get("/api/inquiries/summary", params={"start": "2020-01-01T00:00:00Z", "end": "2020-02-01T00:00:00Z"}))
    assert empty["total"] == 0 and empty["rate"] is None


def test_regulars_who_have_gone_quiet(api):
    now = datetime.now(timezone.utc)
    ago = lambda days: (now - timedelta(days=days)).isoformat()   # noqa: E731

    def seen(client_id, days, paid=300, status="completed"):
        return ok(api.post("/api/appointments", params={"warn": "false"}, json={
            "client_id": client_id, "service_type": "Dinner", "duration_minutes": 60, "scheduled_date": ago(days),
            "rate": paid, "amount_paid": paid, "status": status}), 201)

    def person(name, **more):
        return ok(api.post("/api/clients", json={"name": name, **more}), 201)

    regular, big, recent, once = person("Regular", found_via="Tryst"), person("Big spender"), person("Recent"), person("Once")
    rebooked, blocked, gone = person("Rebooked"), person("Blocked", do_not_see=True), person("Inactive", is_active=False)
    for days in (160, 130, 100):
        seen(regular["id"], days)
    seen(big["id"], 400, paid=2000)
    seen(big["id"], 200, paid=2000)
    seen(recent["id"], 40)
    seen(recent["id"], 10)
    seen(once["id"], 300)
    for c in (rebooked, blocked, gone):
        seen(c["id"], 300)
        seen(c["id"], 200)
    seen(rebooked["id"], -5, paid=0, status="scheduled")          # has something booked ahead

    rows = ok(api.get("/api/marketing/lapsed"))
    assert [r["display_name"] for r in rows] == ["Big spender", "Regular"]      # most paid first
    r = rows[1]
    assert (r["bookings"], r["usual_gap_days"], r["total_paid"], r["per_booking"], r["found_via"]) == (3, 30, 900, 300, "Tryst")
    assert r["days_since"] in (99, 100)
    assert [x["display_name"] for x in ok(api.get("/api/marketing/lapsed", params={"days": 150}))] == ["Big spender"]
    assert api.get("/api/marketing/lapsed", params={"days": 1}).status_code == 422


def test_people_only_see_their_own(api, admin):
    e = inquiry(api, "Mine", "Tryst")
    other = new_user(admin)
    assert ok(other.get("/api/inquiries", params={"show": "all"})) == [] and ok(other.get("/api/marketing/lapsed")) == []
    assert ok(other.get("/api/inquiries/summary", params=YEAR))["total"] == 0
    assert other.put(f"/api/inquiries/{e['id']}", json={"name": "Theirs"}).status_code == 404
    assert other.post(f"/api/inquiries/{e['id']}/stage", json={"stage": "booked"}).status_code == 404
    other.delete(f"/api/inquiries/{e['id']}")
    assert ok(api.get("/api/inquiries"))[0]["stage"] == "new"
    for path in ("/api/inquiries", "/api/marketing/lapsed"):
        assert TestClient(main.app).get(path).status_code == 401
