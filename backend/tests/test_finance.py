"""Tests for places you earn, income, savings goals, own expense categories and the "how I work" setups.
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
    name = "f-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def add_income(api, when="2044-03-10T20:00:00Z", **fields):
    return ok(api.post("/api/income", json={"date": when, "gross": 100, **fields}), 201)


# ---------- expense categories ----------

def test_everyone_starts_with_the_built_in_categories(api):
    cats = ok(api.get("/api/expense-categories"))
    assert [(c["key"], c["parent_key"]) for c in cats] == [
        ("workspace", None), ("room_rent", "workspace"), ("cleaning", "workspace"), ("fees", None),
        ("health", None), ("medical", "health"), ("wardrobe", None), ("gear", None), ("equipment", "gear"),
        ("marketing", None), ("travel", None), ("fitness", None), ("other", None)]
    assert all(c["builtin"] and not c["hidden"] and c["color"] for c in cats)
    # A subcategory shows its main category's colour.
    colors = {c["key"]: c["color"] for c in cats}
    assert colors["room_rent"] == colors["workspace"]


def test_subcategories_can_be_added_moved_and_promoted(api):
    shoes = ok(api.post("/api/expense-categories", json={"label": "Shoes", "parent_key": "wardrobe"}), 201)
    assert shoes["parent_key"] == "wardrobe" and shoes["color"] == next(
        c["color"] for c in ok(api.get("/api/expense-categories")) if c["key"] == "wardrobe")
    # Only one level: not under a subcategory, not under something missing.
    assert api.post("/api/expense-categories", json={"label": "Heels", "parent_key": shoes["key"]}).status_code == 400
    assert api.post("/api/expense-categories", json={"label": "Heels", "parent_key": "nope"}).status_code == 400

    # Moving it; leaving parent_key out of an update keeps it where it is.
    ok(api.put(f"/api/expense-categories/{shoes['key']}", json={"label": "Shoes", "parent_key": "other"}))
    other_color = next(c["color"] for c in ok(api.get("/api/expense-categories")) if c["key"] == "other")
    renamed = ok(api.put(f"/api/expense-categories/{shoes['key']}", json={"label": "Shoes & heels", "color": other_color}))
    assert renamed["parent_key"] == "other"
    # Saving the colour it was shown in (its main category's) doesn't pin it.
    ok(api.put("/api/expense-categories/other", json={"label": "Other", "color": "#111111"}))
    assert next(c["color"] for c in ok(api.get("/api/expense-categories")) if c["key"] == shoes["key"]) == "#111111"

    # Built-in main categories can be renamed (but stay main categories); own ones can become main ones.
    ok(api.put("/api/expense-categories/wardrobe", json={"label": "Glam"}))
    assert api.put("/api/expense-categories/wardrobe", json={"label": "Glam", "parent_key": "other"}).status_code == 400
    top = ok(api.put(f"/api/expense-categories/{shoes['key']}", json={"label": "Shoes & heels", "parent_key": None}))
    assert top["parent_key"] is None and top["color"]

    # A main category with subcategories can't go under another; deleting it moves them to Other.
    boots = ok(api.post("/api/expense-categories", json={"label": "Boots", "parent_key": top["key"]}), 201)
    assert api.put(f"/api/expense-categories/{top['key']}", json={"label": "x", "parent_key": "gear"}).status_code == 400
    ok(api.post("/api/expenses", json={"description": "Thigh-highs", "amount": 80, "category": boots["key"]}), 201)
    assert api.delete(f"/api/expense-categories/{top['key']}").status_code == 204
    cats = {c["key"]: c for c in ok(api.get("/api/expense-categories"))}
    assert cats[boots["key"]]["parent_key"] == "other" and cats[boots["key"]]["used"] == 1
    assert cats["wardrobe"]["label"] == "Glam"


def test_own_categories_can_be_added_renamed_hidden_and_deleted(api):
    heels = ok(api.post("/api/expense-categories", json={"label": "Costumes & heels"}), 201)
    assert heels["parent_key"] is None
    assert heels["key"].startswith("c") and heels["color"].startswith("#") and not heels["builtin"]
    assert api.post("/api/expense-categories", json={"label": "costumes & HEELS"}).status_code == 409

    exp = ok(api.post("/api/expenses", json={"description": "Pleasers", "amount": 90, "category": heels["key"]}), 201)
    assert exp["category"] == heels["key"]
    assert api.post("/api/expenses", json={"description": "x", "amount": 1, "category": "yachts"}).status_code == 422

    renamed = ok(api.put(f"/api/expense-categories/{heels['key']}", json={"label": "Heels", "color": "#123456"}))
    assert (renamed["label"], renamed["color"], renamed["used"]) == ("Heels", "#123456", 1)
    ok(api.put("/api/expense-categories/travel", json={"label": "Travel", "hidden": True}))
    assert api.put("/api/expense-categories/other", json={"label": "Other", "hidden": True}).status_code == 400
    assert api.put("/api/expense-categories/travel", json={"label": "x", "color": "red"}).status_code == 400
    assert api.delete("/api/expense-categories/travel").status_code == 400   # built-in: hide instead

    assert api.delete(f"/api/expense-categories/{heels['key']}").status_code == 204
    assert ok(api.get("/api/expenses"))[0]["category"] == "other"


def test_categories_are_private(api, admin):
    mine = ok(api.post("/api/expense-categories", json={"label": "Secret thing"}), 201)
    assert mine["key"] not in [c["key"] for c in ok(admin.get("/api/expense-categories"))]
    assert admin.post("/api/expenses", json={"description": "x", "amount": 1, "category": mine["key"]}).status_code == 422
    assert admin.put(f"/api/expense-categories/{mine['key']}", json={"label": "Mine now"}).status_code == 404


def test_csv_import_matches_categories_by_name(api):
    heels = ok(api.post("/api/expense-categories", json={"label": "Heels"}), 201)
    r = api.post("/api/csv/expenses", content="date,description,amount,category\n2044-01-02,Boots,50,heels\n2044-01-03,Taxi,9,Travel\n")
    assert r.status_code == 200, r.text
    got = {e["description"]: e["category"] for e in ok(api.get("/api/expenses"))}
    assert got == {"Boots": heels["key"], "Taxi": "travel"}
    # "Main > sub" works too.
    r = api.post("/api/csv/expenses", content="date,description,amount,category\n2044-01-05,Rent,500,Workspace > Room & board\n")
    assert r.status_code == 200, r.text
    assert {e["description"]: e["category"] for e in ok(api.get("/api/expenses"))}["Rent"] == "room_rent"
    assert "Heels" in api.get("/api/csv/expenses").text
    r = api.post("/api/csv/expenses", content="date,description,amount,category\n2044-01-02,X,5,Spaceships\n")
    assert r.status_code == 400 and "Spaceships" in r.text


# ---------- places you earn and income ----------

def test_places_you_earn(api, admin):
    club = ok(api.post("/api/income-sources", json={"name": "Club Velvet", "kind": "club", "fee_per_shift": 60}), 201)
    of = ok(api.post("/api/income-sources", json={"name": "OF", "kind": "platform", "fee_percent": 20}), 201)
    assert api.post("/api/income-sources", json={"name": "Bad", "fee_percent": 120}).status_code == 400
    assert api.post("/api/income-sources", json={"name": " "}).status_code == 400
    assert api.post("/api/income-sources", json={"name": "Euro site", "currency": "EUR"}).status_code == 400
    assert api.post("/api/income-sources", json={"name": "Site", "kind": "castle"}).status_code == 422
    ok(api.put(f"/api/income-sources/{club['id']}", json={"name": "Club Velvet", "kind": "club", "fee_per_shift": 80, "archived": True}))
    assert [s["name"] for s in ok(api.get("/api/income-sources"))] == ["OF", "Club Velvet"]   # archived last
    assert ok(admin.get("/api/income-sources")) == [] or of["id"] not in [s["id"] for s in ok(admin.get("/api/income-sources"))]
    assert admin.put(f"/api/income-sources/{of['id']}", json={"name": "Taken"}).status_code == 404


def test_income_records_fees_and_pending_payouts(api, admin):
    of = ok(api.post("/api/income-sources", json={"name": "OF", "kind": "platform", "fee_percent": 20}), 201)
    paid = add_income(api, source_id=of["id"], kind="subscription", gross=500, fees=100)
    assert (paid["net"], paid["source_name"], paid["status"], paid["currency"]) == (400, "OF", "received", "USD")
    pending = add_income(api, when="2044-03-12T20:00:00Z", kind="tips", gross=80, fees=16, status="pending")
    shift = add_income(api, when="2044-03-13T04:00:00Z", kind="shift", gross=40, fees=60, description="Slow Tuesday")
    assert shift["net"] == -20                                  # a house fee can cost more than the night made
    assert api.post("/api/income", json={"date": "2044-03-10T20:00:00Z", "gross": -5}).status_code == 400
    assert api.post("/api/income", json={"date": "2044-03-10T20:00:00Z", "gross": 5, "currency": "GBP"}).status_code == 400
    assert api.post("/api/income", json={"date": "2044-03-10T20:00:00Z", "gross": 5, "kind": "lottery"}).status_code == 422

    assert [i["id"] for i in ok(api.get("/api/income", params={"status": "pending"}))] == [pending["id"]]
    got = ok(api.post(f"/api/income/{pending['id']}/received"))
    assert got["status"] == "received" and got["payout_date"]
    assert len(ok(api.get("/api/income", params={"start": "2044-03-11T00:00:00Z", "end": "2044-03-14T00:00:00Z"}))) == 2

    # Private to its owner.
    assert ok(admin.get("/api/income", params={"start": "2044-03-01T00:00:00Z", "end": "2044-04-01T00:00:00Z"})) == []
    assert admin.put(f"/api/income/{paid['id']}", json={"date": "2044-03-10T20:00:00Z", "gross": 1}).status_code == 404
    assert admin.post("/api/income", json={"date": "2044-03-10T20:00:00Z", "gross": 1, "source_id": of["id"]}).status_code == 400
    admin.delete(f"/api/income/{paid['id']}")
    assert len(ok(api.get("/api/income"))) == 3

    # Deleting a place keeps its income, unlinked.
    assert api.delete(f"/api/income-sources/{of['id']}").status_code == 204
    assert ok(api.get(f"/api/income", params={"status": "received"}))[-1]["source_id"] is None


def test_income_counts_toward_tours_and_the_earnings_comparison(api):
    tour = ok(api.post("/api/tours", json={"name": "Vegas", "start_date": "2044-05-01", "end_date": "2044-05-03",
                                          "starts_at": "2044-05-01T00:00:00Z", "ends_at": "2044-05-04T00:00:00Z"}), 201)
    add_income(api, when="2044-05-02T03:00:00Z", kind="tips", gross=300, fees=0)
    add_income(api, when="2044-05-02T04:00:00Z", kind="sale", gross=200, fees=40, status="pending")   # not paid out yet
    add_income(api, when="2044-05-09T03:00:00Z", gross=999)                                           # after the tour
    f = ok(api.get(f"/api/tours/{tour['id']}/summary"))
    assert (f["figures"]["income"], f["figures"]["other_income"], f["figures"]["booking_income"]) == (300, 300, 0)
    assert len(f["income"]) == 2   # the pending sale is listed, but not counted as income yet

    rows = ok(api.get("/api/earnings/compare", params={"by": "month", "start": "2044-05-01T00:00:00Z",
                                                        "end": "2044-06-01T00:00:00Z"}))["rows"]
    assert rows[0]["figures"]["income"] == 1299


# ---------- savings goals ----------

def test_a_goal_with_a_target_and_money_in_and_out(api, admin):
    soon = (date.today() + timedelta(days=70)).isoformat()
    g = ok(api.post("/api/goals", json={"name": "Emergency fund", "target_amount": 1000, "target_date": soon}), 201)
    assert (g["balance"], g["progress"], g["remaining"], g["reached"]) == (0, 0, 1000, False)
    assert g["per_week_needed"] == 100

    g = ok(api.post(f"/api/goals/{g['id']}/entries", json={"amount": 300, "note": "First week"}), 201)
    g = ok(api.post(f"/api/goals/{g['id']}/entries", json={"amount": -50}), 201)
    assert (g["balance"], g["progress"], g["remaining"]) == (250, 0.25, 750)
    assert api.post(f"/api/goals/{g['id']}/entries", json={"amount": -500}).status_code == 400   # more than is in it
    assert api.post(f"/api/goals/{g['id']}/entries", json={"amount": 0}).status_code == 400
    g = ok(api.post(f"/api/goals/{g['id']}/entries", json={"amount": 750}), 201)
    assert g["reached"] and g["progress"] == 1

    # Private.
    assert ok(admin.get("/api/goals")) == [] or g["id"] not in [x["id"] for x in ok(admin.get("/api/goals"))]
    assert admin.post(f"/api/goals/{g['id']}/entries", json={"amount": 5}).status_code == 404
    admin.delete(f"/api/goals/{g['id']}")
    assert len(ok(api.get("/api/goals"))) == 1

    dated = ok(api.post(f"/api/goals/{g['id']}/entries", json={"amount": 5, "date": "2044-01-31"}), 201)
    assert dated["entries"][0]["date"] == "2044-01-31"
    api.delete(f"/api/goals/{g['id']}/entries/{dated['entries'][0]['id']}")
    entry = next(e for e in ok(api.get("/api/goals"))[0]["entries"] if e["amount"] == 750)
    assert api.delete(f"/api/goals/{g['id']}/entries/{entry['id']}").status_code == 204
    assert ok(api.get("/api/goals"))[0]["balance"] == 250


def test_a_tax_goal_suggests_a_share_of_what_comes_in(api):
    start = date.today() - timedelta(days=3)
    g = ok(api.post("/api/goals", json={"name": "Taxes", "kind": "tax", "rule_type": "percent", "rule_amount": 25,
                                        "starts_on": start.isoformat()}), 201)
    assert (g["rule_expected"], g["suggested"]) == (0, 0)
    client = ok(api.post("/api/clients", json={"name": "Payer"}), 201)
    ok(api.post("/api/appointments", json={"client_id": client["id"], "service_type": "S", "duration_minutes": 60,
                                           "scheduled_date": f"{(start + timedelta(days=1)).isoformat()}T20:00:00Z",
                                           "rate": 400, "amount_paid": 400, "status": "completed"}), 201)
    add_income(api, when=f"{start.isoformat()}T12:00:00Z", gross=250, fees=50)
    add_income(api, when=f"{(start - timedelta(days=5)).isoformat()}T12:00:00Z", gross=1000)   # before the goal began
    add_income(api, when=f"{start.isoformat()}T13:00:00Z", gross=1000, status="pending")       # not received yet
    g = ok(api.get("/api/goals"))[0]
    assert (g["rule_basis"], g["rule_expected"], g["suggested"]) == (600, 150, 150)
    g = ok(api.post(f"/api/goals/{g['id']}/entries", json={"amount": 100}), 201)
    assert g["suggested"] == 50
    g = ok(api.post(f"/api/goals/{g['id']}/entries", json={"amount": -100, "note": "Paid estimated tax"}), 201)
    assert g["suggested"] == 50 and g["balance"] == 0          # paying the tax doesn't make it ask again


def test_weekly_and_per_booking_rules(api):
    start = date.today() - timedelta(days=15)                  # third week running
    weekly = ok(api.post("/api/goals", json={"name": "Move", "rule_type": "weekly", "rule_amount": 50,
                                             "starts_on": start.isoformat()}), 201)
    assert weekly["suggested"] == 150
    per = ok(api.post("/api/goals", json={"name": "Camera", "rule_type": "per_booking", "rule_amount": 20,
                                          "starts_on": start.isoformat()}), 201)
    client = ok(api.post("/api/clients", json={"name": "C"}), 201)
    for days, status in ((1, "completed"), (2, "completed"), (3, "cancelled")):
        ok(api.post("/api/appointments", json={"client_id": client["id"], "service_type": "S", "duration_minutes": 60,
                                               "scheduled_date": f"{(start + timedelta(days=days)).isoformat()}T20:00:00Z",
                                               "status": status}), 201)
    per = next(g for g in ok(api.get("/api/goals")) if g["id"] == per["id"])
    assert (per["rule_basis"], per["suggested"]) == (2, 40)


def test_goal_rules_are_checked(api):
    for body in ({"name": ""}, {"name": "x", "target_amount": 0}, {"name": "x", "rule_type": "percent"},
                 {"name": "x", "rule_type": "percent", "rule_amount": 150}, {"name": "x", "currency": "JPY"},
                 {"name": "x", "color": "pink"}):
        assert api.post("/api/goals", json=body).status_code == 400, body
    g = ok(api.post("/api/goals", json={"name": "x", "rule_type": "none", "rule_amount": 99}), 201)
    assert g["rule_amount"] is None and g["suggested"] is None


# ---------- how I work ----------

def test_work_profile_adds_starter_categories_and_places_once(api):
    profile = ok(api.get("/api/work-profile"))
    assert profile["work_types"] is None
    assert {o["key"] for o in profile["options"]} >= {"brothel", "independent", "dancer", "cam", "phone", "content"}

    r = ok(api.put("/api/work-profile", json={"work_types": ["dancer", "content"]}))
    assert "Shoes & heels" in r["added"]["categories"] and "OF" in r["added"]["sources"]
    all_cats = ok(api.get("/api/expense-categories"))
    cats = {c["label"]: c for c in all_cats}
    assert cats["Shoes & heels"]["parent_key"] == "wardrobe" and cats["Camera & lighting"]["parent_key"] == "gear"
    assert cats["House fees & tip-outs"]["parent_key"] == "fees"
    # Kinds of work share subcategories instead of each bringing its own copy.
    assert [c["label"] for c in all_cats].count("Costumes & props") == 1
    sources = {s["name"]: s for s in ok(api.get("/api/income-sources"))}
    assert sources["OF"]["fee_percent"] == 20 and "My club" in sources

    # Again, plus one more kind: nothing is doubled, and only the new kind's things are added.
    r = ok(api.put("/api/work-profile", json={"work_types": ["dancer", "content", "cam"]}))
    assert "OF" not in r["added"]["sources"] and "My cam site" in r["added"]["sources"]
    assert "Makeup & beauty" not in r["added"]["categories"]      # dancer already added it
    assert len(ok(api.get("/api/income-sources"))) == 4
    assert ok(api.get("/api/work-profile"))["work_types"] == ["dancer", "content", "cam"]
    assert api.put("/api/work-profile", json={"work_types": ["astronaut"]}).status_code == 400
    ok(api.put("/api/work-profile", json={"work_types": []}))      # "skip" is remembered as an empty list
    assert ok(api.get("/api/work-profile"))["work_types"] == []


# ---------- comparing kinds of work ----------

def test_income_compared_by_kind_of_work_and_by_place(api):
    ok(api.put("/api/work-profile", json={"work_types": ["dancer", "content"]}))
    sources = {s["name"]: s for s in ok(api.get("/api/income-sources"))}
    assert sources["OF"]["work_type"] == "content" and sources["My club"]["work_type"] == "dancer"
    side = ok(api.post("/api/income-sources", json={"name": "Side gig"}), 201)
    assert side["work_type"] is None
    assert api.post("/api/income-sources", json={"name": "x", "work_type": "astronaut"}).status_code == 400

    when = "2047-02-10T20:00:00Z"
    add_income(api, when=when, source_id=sources["OF"]["id"], gross=500, fees=100)
    add_income(api, when=when, source_id=sources["OF"]["id"], gross=50, fees=10, status="pending")
    add_income(api, when=when, source_id=sources["My club"]["id"], kind="shift", gross=300, fees=60)
    add_income(api, when=when, source_id=side["id"], gross=100)
    add_income(api, when="2047-04-01T20:00:00Z", source_id=sources["My club"]["id"], gross=999)   # outside the range
    client = ok(api.post("/api/clients", json={"name": "Booker"}), 201)
    ok(api.post("/api/appointments", json={"client_id": client["id"], "service_type": "S", "duration_minutes": 60,
                                           "scheduled_date": "2047-02-11T20:00:00Z", "rate": 600, "amount_paid": 600}), 201)

    range_ = {"start": "2047-02-01T00:00:00Z", "end": "2047-03-01T00:00:00Z"}
    r = ok(api.get("/api/earnings/by-source", params={**range_, "group": "work_type"}))
    rows = {x["key"]: x for x in r["rows"]}
    assert [x["key"] for x in r["rows"]] == ["bookings", "content", "dancer", "other"]   # biggest first
    assert (rows["content"]["gross"], rows["content"]["fees"], rows["content"]["net"], rows["content"]["pending"]) == (500, 100, 400, 40)
    assert rows["dancer"]["net"] == 240 and rows["dancer"]["label"] == "Dancer"
    assert rows["bookings"]["net"] == 600 and rows["other"]["net"] == 100
    assert r["total"] == 1340 and rows["bookings"]["share"] == round(600 / 1340, 4)

    by_place = ok(api.get("/api/earnings/by-source", params={**range_, "group": "source"}))
    labels = {x["label"]: x["net"] for x in by_place["rows"]}
    assert labels == {"In-person bookings": 600, "OF": 400, "My club": 240, "Side gig": 100}
    assert api.get("/api/earnings/by-source", params={**range_, "group": "moon"}).status_code == 400


def test_choosing_a_kind_of_work_again_doesnt_add_a_renamed_place_twice(api):
    r = api.put("/api/work-profile", json={"work_types": ["brothel"]})
    assert r.status_code == 200, r.text
    mine = [s for s in api.get("/api/income-sources").json() if s["kind"] == "brothel"]
    assert len(mine) == 1
    body = {k: mine[0][k] for k in ("kind", "fee_percent", "fee_per_shift", "token_value", "payout_note", "notes", "archived", "work_type")}
    assert api.put(f"/api/income-sources/{mine[0]['id']}", json={**body, "name": "Cheryl's Ranch"}).status_code == 200
    assert api.put("/api/work-profile", json={"work_types": ["brothel", "dancer"]}).status_code == 200
    names = [s["name"] for s in api.get("/api/income-sources").json() if s["kind"] == "brothel"]
    assert names == ["Cheryl's Ranch"]
