"""Tests for tour planning: pack lists and budgets.
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
    name = "tp-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)


def tour(api, first="2044-06-01", last="2044-06-05", name="Chicago"):
    end = date.fromisoformat(last) + timedelta(days=1)
    return ok(api.post("/api/tours", json={"kind": "tour", "name": name, "start_date": first, "end_date": last,
                                           "starts_at": f"{first}T00:00:00Z", "ends_at": f"{end.isoformat()}T00:00:00Z"}), 201)


def test_a_starter_template_is_offered_until_you_save_one(api):
    offered = ok(api.get("/api/pack-templates"))
    assert offered[0]["starter"] and "ID" in offered[0]["items"] and offered[0]["id"] is None
    t = ok(api.post("/api/pack-templates", json={"name": "Outcall bag", "items": ["Condoms", "condoms ", "Wipes", ""]}), 201)
    assert t["items"] == ["Condoms", "Wipes"]               # blanks and repeats dropped
    assert [x["name"] for x in ok(api.get("/api/pack-templates"))] == ["Outcall bag"]


def test_a_tours_pack_list_from_templates_and_one_offs(api):
    t = tour(api)
    bag = ok(api.post("/api/pack-templates", json={"name": "Bag", "items": ["Heels", "Wipes"]}), 201)
    ok(api.post(f"/api/tours/{t['id']}/pack", json={"label": "wipes"}), 201)
    items = ok(api.post(f"/api/tours/{t['id']}/pack", json={"template_id": bag["id"]}), 201)
    assert [i["label"] for i in items] == ["wipes", "Heels"]   # Wipes already there: not added twice
    items = ok(api.put(f"/api/tour-pack/{items[1]['id']}", json={"packed": True}))
    assert [i["packed"] for i in items] == [False, True]
    assert api.delete(f"/api/tour-pack/{items[0]['id']}").status_code == 204
    assert [i["label"] for i in ok(api.get(f"/api/tours/{t['id']}/pack"))] == ["Heels"]
    ok(api.post(f"/api/tours/{t['id']}/pack", json={"items": ["ID", "Phone + charger"]}), 201)
    assert len(ok(api.get(f"/api/tours/{t['id']}/pack"))) == 3


def test_budget_planned_against_actual_by_main_category(api):
    t = tour(api)
    ok(api.post("/api/expenses", json={"description": "Flight", "amount": 300, "category": "travel",
                                       "date": "2044-06-01T12:00:00Z", "tour_id": t["id"]}), 201)
    ok(api.post("/api/expenses", json={"description": "Room", "amount": 120, "category": "room_rent",   # a subcategory
                                       "date": "2044-06-02T12:00:00Z"}), 201)                          # dated during the tour
    ok(api.post("/api/expenses", json={"description": "Before", "amount": 999, "category": "travel",
                                       "date": "2044-05-01T12:00:00Z"}), 201)
    b = ok(api.put(f"/api/tours/{t['id']}/budget", json={"lines": [{"category": "travel", "planned": 250},
                                                                   {"category": "workspace", "planned": 500}]}))
    by = {l["category"]: l for l in b["lines"]}
    assert (by["travel"]["planned"], by["travel"]["actual"]) == (250, 300)
    assert (by["workspace"]["planned"], by["workspace"]["actual"]) == (500, 120)    # room & board counts as Workspace
    assert (b["planned"], b["actual"], b["left"]) == (750, 420, 330)
    assert api.put(f"/api/tours/{t['id']}/budget", json={"lines": [{"category": "room_rent", "planned": 1}]}).status_code == 400


def test_tour_plans_are_private(api, admin):
    t = tour(api)
    assert admin.get(f"/api/tours/{t['id']}/pack").status_code == 404
    assert admin.get(f"/api/tours/{t['id']}/budget").status_code == 404
    items = ok(api.post(f"/api/tours/{t['id']}/pack", json={"label": "Heels"}), 201)
    assert admin.put(f"/api/tour-pack/{items[0]['id']}", json={"packed": True}).status_code == 404


def test_meals_feed_the_pack_list_and_the_food_budget(api):
    ok(api.get("/api/expense-categories"))          # (everyone has Food & drink)
    t = tour(api)
    ok(api.post(f"/api/tours/{t['id']}/meals", json={"day": "2044-06-01", "meal": "dinner", "what": "Pasta night",
                                                     "groceries": "Pasta, sauce, parmesan", "cost": 18}), 201)
    meals = ok(api.post(f"/api/tours/{t['id']}/meals", json={"meal": "snack", "what": "Road snacks",
                                                             "groceries": "Almonds, Pasta, sparkling water", "cost": 12}), 201)
    assert [m["what"] for m in meals] == ["Pasta night", "Road snacks"]
    ok(api.post(f"/api/tours/{t['id']}/pack", json={"label": "parmesan"}), 201)
    r = ok(api.post(f"/api/tours/{t['id']}/meals/to-pack"))
    labels = [i["label"] for i in r["pack"]]
    assert r["added"] == 4 and sorted(l.lower() for l in labels) == ["almonds", "parmesan", "pasta", "sauce", "sparkling water"]
    b = ok(api.get(f"/api/tours/{t['id']}/budget"))
    food = next(l for l in b["lines"] if l["category"] == "food")
    assert (food["planned"], food["from_meals"]) == (30, True)
    # A food amount set by hand wins over the meals' total.
    b = ok(api.put(f"/api/tours/{t['id']}/budget", json={"lines": [{"category": "food", "planned": 50}]}))
    assert next(l for l in b["lines"] if l["category"] == "food")["planned"] == 50
    assert api.post(f"/api/tours/{t['id']}/meals", json={"meal": "brunch", "what": "x"}).status_code == 400
    assert api.delete(f"/api/tour-meals/{meals[0]['id']}").status_code == 204
    assert len(ok(api.get(f"/api/tours/{t['id']}/meals"))) == 1


def test_a_convention_has_a_booth_list_whose_buys_land_on_the_trip(api):
    t = ok(api.post("/api/tours", json={"kind": "tour", "name": "AVN week", "purpose": "convention", "start_date": "2045-01-20",
                                        "end_date": "2045-01-23", "starts_at": "2045-01-20T00:00:00Z", "ends_at": "2045-01-24T00:00:00Z"}), 201)
    assert t["purpose"] == "convention"
    c = ok(api.get(f"/api/tours/{t['id']}/convention"))
    assert c["items"] == [] and any(s["kind"] == "booth" for s in c["starter"])
    c = ok(api.post(f"/api/tours/{t['id']}/convention", json={"kind": "promo", "label": "Prints to sign", "qty": 50, "unit_cost": 2}), 201)
    item = c["items"][0]
    assert (item["total"], c["planned"], c["bought"]) == (100, 100, 0)
    c = ok(api.post(f"/api/convention-items/{item['id']}/bought"))
    assert c["bought"] == 100 and c["items"][0]["bought"]
    assert api.post(f"/api/convention-items/{item['id']}/bought").status_code == 400          # once
    e = next(x for x in ok(api.get("/api/expenses")) if x["description"].startswith("Prints to sign"))
    assert e["tour_id"] == t["id"] and e["amount"] == 100
    work = tour(api)
    assert api.get(f"/api/tours/{work['id']}/convention").status_code == 400                   # a work tour has no booth list
