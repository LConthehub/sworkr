"""Working with partners: splits on bookings, income and costs, agreements, who owes whom, and that your own
figures count only your share. Run with:  docker compose run --rm tests"""
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
    name = "co-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def partner(api, name="Jade"):
    return ok(api.post("/api/clients", json={"name": name, "role": "partner",
                                             "handles": [{"platform": "Instagram", "handle": name.lower()}]}), 201)


def booking(api, paid=800, when="2048-03-01T20:00:00Z"):
    client = ok(api.post("/api/clients", json={"name": "C " + uuid.uuid4().hex[:4]}), 201)
    return ok(api.post("/api/appointments", json={"client_id": client["id"], "service_type": "Duo", "duration_minutes": 120,
                                                  "scheduled_date": when, "rate": paid, "amount_paid": paid,
                                                  "status": "completed"}), 201)


def balance(api, p):
    return ok(api.get(f"/api/partners/{p['id']}/ledger"))["balance"]


# ---------- partners ----------

def test_partners_are_contacts_with_a_role(api):
    jade = partner(api)
    assert jade["role"] == "partner"
    ok(api.post("/api/clients", json={"name": "A client"}), 201)
    assert [c["display_name"] for c in ok(api.get("/api/clients", params={"role": "partner"}))] == ["Jade"]
    assert api.post("/api/clients", json={"name": "x", "role": "boss"}).status_code == 400
    assert [p["display_name"] for p in ok(api.get("/api/partners"))] == ["Jade"]


# ---------- splits ----------

def test_a_duo_booking_you_were_paid_for(api):
    jade = partner(api)
    b = booking(api, 800)
    split = ok(api.put(f"/api/splits/appointment/{b['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    assert (split["base"], split["mine"], split["parties"][0]["amount"]) == (800, 400, 400)
    assert balance(api, jade) == -400                          # you hold her half: you owe her
    got = ok(api.get(f"/api/appointments/{b['id']}"))
    assert got["my_amount_paid"] == 400 and got["partner_names"] == "Jade"


def test_a_duo_booking_she_was_paid_for(api):
    jade = partner(api)
    b = booking(api, 1000)
    ok(api.put(f"/api/splits/appointment/{b['id']}", json={"handled_by": jade["id"],
                                                           "parties": [{"partner_id": jade["id"], "share_value": 40}]}))
    assert balance(api, jade) == 600                           # she holds your 60%: she owes you


def test_a_party_of_three_with_a_fixed_fee(api):
    jade, ruby = partner(api, "Jade"), partner(api, "Ruby")
    b = booking(api, 1500)
    split = ok(api.put(f"/api/splits/appointment/{b['id']}", json={
        "handled_by": ruby["id"], "parties": [{"partner_id": jade["id"], "share_type": "amount", "share_value": 500},
                                              {"partner_id": ruby["id"], "share_value": 40}]}))
    assert split["mine"] == 400                                # 1500 − 500 − 600
    assert balance(api, ruby) == 400 and balance(api, jade) == 0   # Ruby holds the money and pays both of you


def test_shared_costs(api):
    jade = partner(api)
    mine = ok(api.post("/api/expenses", json={"description": "Hotel suite", "amount": 300, "category": "travel"}), 201)
    hers = ok(api.post("/api/expenses", json={"description": "Photographer", "amount": 200, "category": "other"}), 201)
    ok(api.put(f"/api/splits/expense/{mine['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    ok(api.put(f"/api/splits/expense/{hers['id']}", json={"handled_by": jade["id"], "parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    assert balance(api, jade) == 150 - 100                     # she owes 150 for the hotel, you owe 100 for the photographer
    expenses = {e["description"]: e for e in ok(api.get("/api/expenses"))}
    assert expenses["Hotel suite"]["my_amount"] == 150 and expenses["Photographer"]["my_amount"] == 100


def test_content_income_split_and_pending_payouts(api):
    jade = partner(api)
    sale = ok(api.post("/api/income", json={"date": "2048-04-01T12:00:00Z", "gross": 500, "fees": 100, "kind": "sale"}), 201)
    pending = ok(api.post("/api/income", json={"date": "2048-04-02T12:00:00Z", "gross": 100, "status": "pending"}), 201)
    for r in (sale, pending):
        ok(api.put(f"/api/splits/income/{r['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 40}]}))
    assert balance(api, jade) == -160                          # 40% of the 400 kept; nothing yet for the pending one
    income = {r["id"]: r for r in ok(api.get("/api/income"))}
    assert income[sale["id"]]["my_net"] == 240 and income[pending["id"]]["my_net"] == 100


def test_settling_up(api):
    jade = partner(api)
    b = booking(api, 600)
    ok(api.put(f"/api/splits/appointment/{b['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    book = ok(api.post(f"/api/partners/{jade['id']}/settlements", json={"amount": 300, "direction": "paid_them", "note": "Cash"}), 201)
    assert book["balance"] == 0 and book["entries"][0]["type"] in ("settlement", "appointment")
    settlement = next(e for e in book["entries"] if e["type"] == "settlement")
    api.delete(f"/api/settlements/{settlement['id']}")
    assert balance(api, jade) == -300
    assert api.post(f"/api/partners/{jade['id']}/settlements", json={"amount": 0, "direction": "paid_them"}).status_code == 400
    assert api.post(f"/api/partners/{jade['id']}/settlements", json={"amount": 5, "direction": "sideways"}).status_code == 400


def test_split_rules(api):
    jade, ruby = partner(api, "Jade"), partner(api, "Ruby")
    b = booking(api)
    url = f"/api/splits/appointment/{b['id']}"
    assert api.put(url, json={"parties": [{"partner_id": jade["id"], "share_value": 60}, {"partner_id": ruby["id"], "share_value": 50}]}).status_code == 400
    assert api.put(url, json={"parties": [{"partner_id": jade["id"], "share_value": 10}, {"partner_id": jade["id"], "share_value": 10}]}).status_code == 400
    assert api.put(url, json={"handled_by": ruby["id"], "parties": [{"partner_id": jade["id"], "share_value": 10}]}).status_code == 400
    assert api.put(url, json={"parties": [{"partner_id": jade["id"], "share_type": "half", "share_value": 10}]}).status_code == 400
    assert api.put("/api/splits/tour/1", json={"parties": []}).status_code == 404
    # No parties removes the split.
    ok(api.put(url, json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    assert ok(api.put(url, json={"parties": []}))["parties"] == []
    assert ok(api.get(f"/api/appointments/{b['id']}"))["my_amount_paid"] == 800


def test_splits_are_private(api, admin):
    jade = partner(api)
    b = booking(api)
    ok(api.put(f"/api/splits/appointment/{b['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    assert admin.get(f"/api/splits/appointment/{b['id']}").status_code == 404
    assert admin.put(f"/api/splits/appointment/{b['id']}", json={"parties": []}).status_code == 404
    assert admin.get(f"/api/partners/{jade['id']}/ledger").status_code == 404
    assert admin.post(f"/api/partners/{jade['id']}/settlements", json={"amount": 5, "direction": "paid_them"}).status_code == 404
    mine = booking(admin)
    assert admin.put(f"/api/splits/appointment/{mine['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}).status_code == 400
    assert jade["id"] not in [p["id"] for p in ok(admin.get("/api/partners"))]


def test_deleting_cleans_up(api):
    jade = partner(api)
    b = booking(api)
    ok(api.put(f"/api/splits/appointment/{b['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    api.delete(f"/api/appointments/{b['id']}")
    assert balance(api, jade) == 0
    b2 = booking(api)
    ok(api.put(f"/api/splits/appointment/{b2['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    api.delete(f"/api/clients/{jade['id']}")
    assert ok(api.get(f"/api/appointments/{b2['id']}"))["my_amount_paid"] == 800   # her share went with her


# ---------- agreements ----------

def test_agreements(api):
    jade, ruby = partner(api, "Jade"), partner(api, "Ruby")
    a = ok(api.post("/api/agreements", json={"name": "Jade & me", "parties": [
        {"partner_id": jade["id"], "booking_pct": 50, "content_pct": 40, "costs_pct": 50}]}), 201)
    assert a["mine"] == {"booking": 50, "content": 60, "costs": 50} and a["parties"][0]["partner_name"] == "Jade"
    b = booking(api)
    split = ok(api.put(f"/api/splits/appointment/{b['id']}", json={"agreement_id": a["id"],
                                                                   "parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    assert split["agreement_id"] == a["id"]
    ok(api.put(f"/api/agreements/{a['id']}", json={"name": "Trio", "parties": [
        {"partner_id": jade["id"], "booking_pct": 30}, {"partner_id": ruby["id"], "booking_pct": 30}]}))
    assert ok(api.get("/api/agreements"))[0]["mine"]["booking"] == 40
    for body in ({"name": "", "parties": [{"partner_id": jade["id"]}]}, {"name": "x", "parties": []},
                 {"name": "x", "parties": [{"partner_id": jade["id"], "booking_pct": 70}, {"partner_id": ruby["id"], "booking_pct": 40}]}):
        assert api.post("/api/agreements", json=body).status_code == 400, body
    assert api.delete(f"/api/agreements/{a['id']}").status_code == 204
    assert ok(api.get(f"/api/splits/appointment/{b['id']}"))["agreement_id"] is None   # the split itself stays


# ---------- your figures count only your share ----------

def test_money_figures_tours_comparison_and_goals_use_your_share(api):
    jade = partner(api)
    tour = ok(api.post("/api/tours", json={"name": "Duo tour", "start_date": "2048-06-01", "end_date": "2048-06-02",
                                           "starts_at": "2048-06-01T00:00:00Z", "ends_at": "2048-06-03T00:00:00Z",
                                           "room_rent_per_day": 200}), 201)
    b = booking(api, 1000, when="2048-06-01T20:00:00Z")
    ok(api.put(f"/api/splits/appointment/{b['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    rooms = [e for e in ok(api.get("/api/expenses")) if e["category"] == "room_rent"]
    for e in rooms:
        ok(api.put(f"/api/splits/expense/{e['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    f = ok(api.get(f"/api/tours/{tour['id']}/summary"))["figures"]
    assert (f["income"], f["room_rent"], f["profit"]) == (500, 200, 300)

    # Changing the tour makes its room & board again, keeping the split.
    ok(api.put(f"/api/tours/{tour['id']}", json={"name": "Duo tour", "start_date": "2048-06-01", "end_date": "2048-06-03",
                                                 "starts_at": "2048-06-01T00:00:00Z", "ends_at": "2048-06-04T00:00:00Z",
                                                 "room_rent_per_day": 200}))
    rooms = [e for e in ok(api.get("/api/expenses")) if e["category"] == "room_rent"]
    assert len(rooms) == 3 and all(e["my_amount"] == 100 and e["partner_names"] == "Jade" for e in rooms)
    assert balance(api, jade) == -500 + 300                    # her half of the booking; her half of 3 nights

    work = ok(api.get("/api/earnings/by-source", params={"start": "2048-06-01T00:00:00Z", "end": "2048-07-01T00:00:00Z"}))
    bookings = next(r for r in work["rows"] if r["key"] == "bookings")
    assert (bookings["gross"], bookings["net"], bookings["partners"]) == (1000, 500, 500)

    start = (date.today() - timedelta(days=1)).isoformat()
    b2 = booking(api, 400, when=f"{date.today().isoformat()}T12:00:00Z")
    ok(api.put(f"/api/splits/appointment/{b2['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    goal = ok(api.post("/api/goals", json={"name": "Taxes", "rule_type": "percent", "rule_amount": 25, "starts_on": start}), 201)
    assert goal["rule_basis"] == 500 + 200 and goal["suggested"] == 175   # your halves of both bookings, paid since then


def test_shares_never_add_up_to_more_than_the_money(api):
    """50% plus a fixed $500 of an $800 booking asks for $900: each share is scaled down to fit, never below zero for you."""
    jade, ruby = partner(api, "Jade"), partner(api, "Ruby")
    b = booking(api, 800)
    split = ok(api.put(f"/api/splits/appointment/{b['id']}", json={
        "parties": [{"partner_id": jade["id"], "share_value": 50},
                    {"partner_id": ruby["id"], "share_type": "amount", "share_value": 500}]}))
    amounts = {p["partner_id"]: p["amount"] for p in split["parties"]}
    assert split["mine"] == 0 and split["scaled_down"] is True
    assert amounts == {jade["id"]: round(400 * 800 / 900, 2), ruby["id"]: round(500 * 800 / 900, 2)}
    assert ok(api.get(f"/api/appointments/{b['id']}"))["my_amount_paid"] == 0       # the money figures agree
    assert balance(api, jade) == -round(400 * 800 / 900, 2) and balance(api, ruby) == -round(500 * 800 / 900, 2)
    # A split that fits is left exactly as it was.
    fits = ok(api.put(f"/api/splits/appointment/{b['id']}", json={"parties": [{"partner_id": jade["id"], "share_value": 50}]}))
    assert fits["mine"] == 400 and fits["scaled_down"] is False
