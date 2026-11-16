"""Planning a content shoot: place, people, lists, budget and what's still to do.
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
TODAY = datetime.now(timezone.utc).date()
day = lambda n: (TODAY + timedelta(days=n)).isoformat()   # noqa: E731


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "sh-" + uuid.uuid4().hex[:8]
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


def shoot(api, title="Red lace", **more):
    return ok(api.post("/api/shoots", json={"title": title, **more}), 201)


def item(api, s, kind, label, **more):
    return ok(api.post(f"/api/shoots/{s['id']}/items", json={"kind": kind, "label": label, **more}), 201)


def person(api, s, **more):
    return ok(api.post(f"/api/shoots/{s['id']}/people", json=more), 201)


def test_a_shoot_with_its_place_and_lists(api):
    s = shoot(api, " Red lace ", shoot_date=day(20), start_time="14:30", hours=3, concept="Boudoir, warm light",
              location_name="Studio 5", location_address="12 Mill St", location_notes="Ring the bell. No shoes on the backdrop.")
    assert (s["title"], s["status"], s["summary"]["days_left"], s["items"], s["people"]) == ("Red lace", "planning", 20, [], [])
    item(api, s, "goal", "3 pay-per-view sets")
    item(api, s, "shot", "On the bed, 20 photos")
    item(api, s, "wardrobe", "Red lace set", notes="Needs steaming")
    item(api, s, "prep", "Book the studio", due_date=day(5))
    full = item(api, s, "marketing", "Teaser on X the day before", due_date=day(19))
    assert sorted(i["kind"] for i in full["items"]) == ["goal", "marketing", "prep", "shot", "wardrobe"]
    wardrobe = next(i for i in full["items"] if i["kind"] == "wardrobe")
    done = ok(api.put(f"/api/shoots/items/{wardrobe['id']}", json={"kind": "wardrobe", "label": "Red lace set", "done": True}))
    assert done["summary"]["counts"]["wardrobe"] == {"total": 1, "done": 1} and done["summary"]["counts"]["prep"] == {"total": 1, "done": 0}
    gone = ok(api.delete(f"/api/shoots/items/{wardrobe['id']}"))
    assert gone["summary"]["counts"]["wardrobe"]["total"] == 0

    changed = ok(api.put(f"/api/shoots/{s['id']}", json={"title": "Red lace", "status": "shot", "shoot_date": day(20)}))
    assert changed["status"] == "shot" and changed["location_name"] is None
    assert [x["title"] for x in ok(api.get("/api/shoots", params={"show": "done"}))] == ["Red lace"]
    assert ok(api.get("/api/shoots")) == [] and "items" not in ok(api.get("/api/shoots", params={"show": "all"}))[0]

    assert api.post("/api/shoots", json={"title": " "}).status_code == 400
    assert api.post("/api/shoots", json={"title": "x", "status": "maybe"}).status_code == 400
    assert api.post("/api/shoots", json={"title": "x", "start_time": "2pm"}).status_code == 400
    assert api.post("/api/shoots", json={"title": "x", "campaign_id": 999999}).status_code == 400
    assert api.post("/api/shoots", json={"title": "x", "set_path": "../x"}).status_code == 400
    assert api.post(f"/api/shoots/{s['id']}/items", json={"kind": "nope", "label": "x"}).status_code == 400
    assert api.post(f"/api/shoots/{s['id']}/items", json={"kind": "prep", "label": " "}).status_code == 400
    assert api.get("/api/shoots/999999").status_code == 404 and api.get("/api/shoots", params={"show": "x"}).status_code == 400


def test_people_fees_and_the_budget(api):
    s = shoot(api, shoot_date=day(30))
    jade = ok(api.post("/api/clients", json={"name": "Jade", "role": "partner"}), 201)
    person(api, s, name="Mika", role="photographer", fee=300, confirmed=True)
    full = person(api, s, contact_id=jade["id"], role="co-star", agreement="Both can post. Sales 60/40 to whoever sells.")
    mika, co = full["people"]
    assert (mika["display_name"], co["display_name"], co["contact_name"]) == ("Mika", "Jade", "Jade")
    item(api, s, "budget", "Studio hire", amount=150)
    full = item(api, s, "budget", "Lingerie", amount=80)
    assert (full["summary"]["planned"], full["summary"]["spent"], full["summary"]["left_to_spend"]) == (530, 0, 530)
    studio = next(i for i in full["items"] if i["label"] == "Studio hire")

    paid = ok(api.post(f"/api/shoots/items/{studio['id']}/pay", json={"amount": 170, "paid_on": "2026-03-01"}))
    line = next(i for i in paid["items"] if i["label"] == "Studio hire")
    assert (line["actual"], line["done"], paid["summary"]["spent"], paid["summary"]["left_to_spend"]) == (170, True, 170, 360)
    paid = ok(api.post(f"/api/shoots/people/{mika['id']}/pay", json={}))
    assert paid["summary"]["spent"] == 470
    expenses = sorted(ok(api.get("/api/expenses")), key=lambda e: e["amount"])
    assert [(e["description"], e["amount"], e["category"]) for e in expenses] == [
        ("Red lace: Studio hire", 170, "marketing"), ("Red lace: Mika (photographer)", 300, "marketing")]
    assert expenses[0]["date"].startswith("2026-03-01")
    assert api.post(f"/api/shoots/items/{studio['id']}/pay", json={}).status_code == 409           # not twice
    assert api.post(f"/api/shoots/people/{mika['id']}/pay", json={}).status_code == 409
    assert api.post(f"/api/shoots/people/{co['id']}/pay", json={}).status_code == 400              # no fee to pay
    goal = next(i for i in item(api, s, "goal", "A trailer")["items"] if i["kind"] == "goal")
    assert api.post(f"/api/shoots/items/{goal['id']}/pay", json={"amount": 5}).status_code == 400  # only budget lines

    # a paid co-star's fee is logged against them
    ok(api.put(f"/api/shoots/people/{co['id']}", json={"contact_id": jade["id"], "role": "co-star", "fee": 100}))
    ok(api.post(f"/api/shoots/people/{co['id']}/pay", json={}))
    assert [e["client_id"] for e in ok(api.get("/api/expenses")) if e["amount"] == 100] == [jade["id"]]

    assert api.post(f"/api/shoots/{s['id']}/people", json={"role": "photographer"}).status_code == 400      # who?
    assert api.post(f"/api/shoots/{s['id']}/people", json={"name": "x", "role": "boss"}).status_code == 400
    assert api.post(f"/api/shoots/{s['id']}/people", json={"contact_id": 999999}).status_code == 400
    after = ok(api.delete(f"/api/shoots/people/{mika['id']}"))
    assert len(after["people"]) == 1 and after["summary"]["spent"] == 570                           # what was paid stays in expenses
    ok(api.delete(f"/api/shoots/{s['id']}"), 204)
    assert len(ok(api.get("/api/expenses"))) == 3 and api.get(f"/api/shoots/{s['id']}").status_code == 404


def test_what_still_needs_doing(api):
    undated = shoot(api, "Some day")
    assert undated["summary"]["warnings"] == ["No date yet"]
    s = shoot(api, "This week", shoot_date=day(1))
    person(api, s, name="Mika", role="photographer")
    person(api, s, name="Jade", role="co-star", confirmed=True, id_checked=True)
    item(api, s, "prep", "Charge the lights")
    full = item(api, s, "wardrobe", "Boots")
    assert full["summary"]["warnings"] == ["No location yet", "Not confirmed: Mika", "1 thing still to prepare",
                                           "1 wardrobe item not packed", "ID or release still needed: Jade"]
    far = shoot(api, "Next month", shoot_date=day(40))
    item(api, far, "prep", "Book flights")
    assert ok(api.get(f"/api/shoots/{far['id']}"))["summary"]["warnings"] == []                    # too far off to nag
    late = shoot(api, "Slipped", shoot_date=day(-3))
    assert late["summary"]["warnings"] == ["The date has passed: mark it as shot, or move it"]
    shot = ok(api.put(f"/api/shoots/{s['id']}", json={"title": "This week", "status": "shot", "shoot_date": day(1)}))
    assert shot["summary"]["warnings"] == ["ID or release still needed: Jade"]                     # still matters after the day
    assert [x["title"] for x in ok(api.get("/api/shoots"))] == ["Slipped", "Next month", "Some day"]   # soonest first, undated last


def test_copying_a_shoot_and_starting_its_campaign(api):
    s = shoot(api, "Beach day", shoot_date=day(10), location_name="North beach", set_path="2026-12 Beach")
    person(api, s, name="Mika", role="photographer", fee=250, confirmed=True, release_signed=True, id_checked=True)
    item(api, s, "wardrobe", "White bikini", done=True)
    item(api, s, "goal", "2 sets")
    item(api, s, "budget", "Parking", amount=20, actual=20)
    copy = ok(api.post(f"/api/shoots/{s['id']}/copy"), 201)
    assert (copy["title"], copy["shoot_date"], copy["location_name"], copy["status"]) == ("Beach day (copy)", None, "North beach", "planning")
    assert [(i["kind"], i["label"], i["done"], i["actual"]) for i in copy["items"]] == [
        ("budget", "Parking", False, None), ("goal", "2 sets", False, None), ("wardrobe", "White bikini", False, None)]
    [mika] = copy["people"]
    assert (mika["fee"], mika["confirmed"], mika["release_signed"], mika["id_checked"]) == (250, False, False, True)   # a new release each time

    linked = ok(api.post(f"/api/shoots/{s['id']}/campaign"), 201)
    [campaign] = ok(api.get("/api/campaigns"))
    assert linked["campaign_id"] == campaign["id"] and linked["campaign_name"] == "Beach day"
    assert (campaign["goal"], campaign["set_path"], campaign["start_date"]) == ("2 sets", "2026-12 Beach", day(10))
    assert api.post(f"/api/shoots/{s['id']}/campaign").status_code == 409
    ok(api.delete(f"/api/campaigns/{campaign['id']}"), 204)
    assert ok(api.get(f"/api/shoots/{s['id']}"))["campaign_id"] is None


def test_people_only_see_their_own(api, admin):
    s = shoot(api)
    full = person(api, item(api, s, "budget", "Studio", amount=10), name="Mika", role="photographer", fee=5)
    line, mika = full["items"][0], full["people"][0]
    other = new_user(admin)
    assert ok(other.get("/api/shoots", params={"show": "all"})) == [] and other.get(f"/api/shoots/{s['id']}").status_code == 404
    assert other.put(f"/api/shoots/{s['id']}", json={"title": "Theirs"}).status_code == 404
    assert other.post(f"/api/shoots/{s['id']}/items", json={"kind": "prep", "label": "x"}).status_code == 404
    assert other.post(f"/api/shoots/{s['id']}/copy").status_code == 404
    assert other.put(f"/api/shoots/items/{line['id']}", json={"kind": "budget", "label": "x"}).status_code == 404
    assert other.post(f"/api/shoots/items/{line['id']}/pay", json={}).status_code == 404
    assert other.post(f"/api/shoots/people/{mika['id']}/pay", json={}).status_code == 404
    assert other.delete(f"/api/shoots/people/{mika['id']}").status_code == 404
    other.delete(f"/api/shoots/{s['id']}")
    assert len(ok(api.get(f"/api/shoots/{s['id']}"))["people"]) == 1
    assert TestClient(main.app).get("/api/shoots").status_code == 401
