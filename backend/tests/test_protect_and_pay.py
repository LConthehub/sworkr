"""Tests for shoot paperwork, stolen-content takedowns, the decoy password, platform tax forms, the payout
calendar and orders that go in the post.
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
import payouts  # noqa: E402

PASSWORD = "correct-horse-battery"
DECOY = "nothing-to-see-here"


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "pp-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return name, c


@pytest.fixture
def api(admin):
    return new_user(admin)[1]


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


# ---------- shoot paperwork ----------

def test_paperwork_lists_who_is_missing_what(api):
    shoot = ok(api.post("/api/shoots", json={"title": "Beach set", "status": "released"}), 201)
    shoot = ok(api.post(f"/api/shoots/{shoot['id']}/people", json={"name": "Jade", "role": "co-star"}), 201)
    shoot = ok(api.post(f"/api/shoots/{shoot['id']}/people", json={"name": "Sam", "role": "photographer"}), 201)
    shoot = ok(api.post(f"/api/shoots/{shoot['id']}/people", json={"name": "Mo", "role": "makeup"}), 201)
    jade, sam = shoot["people"][0], shoot["people"][1]

    p = ok(api.get("/api/paperwork"))
    assert [x["name"] for x in p["people"]] == ["Jade", "Sam"]          # makeup needs none
    assert p["people"][0]["missing"] == ["ID check", "release"] and p["people"][1]["missing"] == ["release"]
    assert p["incomplete"] == 2 and p["released_incomplete"] == 2 and "MODEL RELEASE" in p["release_text"]

    today = date.today().isoformat()
    shoot = ok(api.put(f"/api/shoots/people/{jade['id']}/paperwork", json={"id_checked_on": today, "release_signed_on": today}))
    j = shoot["people"][0]
    assert j["id_checked"] and j["release_signed"] and j["id_checked_on"] == today
    assert {x["name"]: x["missing"] for x in ok(api.get("/api/paperwork"))["people"]}["Jade"] == ["where the copies are"]
    ok(api.put(f"/api/shoots/people/{jade['id']}/paperwork",
               json={"id_checked_on": today, "release_signed_on": today, "records_kept": "Locked folder on the NAS"}))
    p = ok(api.get("/api/paperwork"))
    assert p["incomplete"] == 1 and p["people"][0]["name"] == "Sam" and p["people"][1]["missing"] == []

    # Unticking the box in the ordinary form takes the date with it.
    shoot = ok(api.put(f"/api/shoots/people/{jade['id']}", json={"name": "Jade", "role": "co-star", "id_checked": False, "release_signed": True}))
    assert shoot["people"][0]["id_checked_on"] is None and shoot["people"][0]["release_signed_on"] == today
    assert api.put(f"/api/shoots/people/{sam['id'] + 9999}/paperwork", json={}).status_code == 404


# ---------- stolen content ----------

def test_leak_goes_from_found_to_removed_with_a_notice(api):
    long_ago = (date.today() - timedelta(days=12)).isoformat()
    leak = ok(api.post("/api/leaks", json={"found_on": long_ago, "site": "leaksite.example", "url": "https://leaksite.example/x",
                                           "what": "Red lace set", "original_url": "https://fans.example/me"}), 201)
    assert leak["status"] == "found" and not leak["chase"]
    n = ok(api.get(f"/api/leaks/{leak['id']}/notice"))
    assert "https://leaksite.example/x" in n["body"] and "Red lace set" in n["body"] and "penalty of perjury" in n["body"]
    assert n["missing"] == ["the name to sign with", "a contact address"]
    ok(api.put("/api/leaks/settings", json={"sign_as": "R. Agent", "contact": "takedown@example.com"}))
    n = ok(api.get(f"/api/leaks/{leak['id']}/notice"))
    assert "Signed: R. Agent" in n["body"] and n["missing"] == []

    sent = ok(api.post(f"/api/leaks/{leak['id']}/status", json={"status": "sent", "on": long_ago, "sent_to": "abuse@leaksite.example"}))
    assert sent["days_waiting"] == 12 and sent["chase"] and sent["sent_to"] == "abuse@leaksite.example"
    listing = ok(api.get("/api/leaks"))
    assert listing["to_chase"] == 1 and listing["counts"]["sent"] == 1 and listing["settings"]["sign_as"] == "R. Agent"
    gone = ok(api.post(f"/api/leaks/{leak['id']}/status", json={"status": "removed"}))
    assert gone["removed_on"] == date.today().isoformat() and not gone["chase"]
    back = ok(api.post(f"/api/leaks/{leak['id']}/status", json={"status": "found"}))       # it came back
    assert back["sent_on"] is None and back["removed_on"] is None
    assert api.post(f"/api/leaks/{leak['id']}/status", json={"status": "burned"}).status_code == 400
    assert api.post("/api/leaks", json={"found_on": long_ago, "site": "  "}).status_code == 400
    assert api.delete(f"/api/leaks/{leak['id']}").status_code == 204
    assert ok(api.get("/api/leaks"))["leaks"] == []


def test_leaks_are_private_to_their_owner(admin, api):
    leak = ok(api.post("/api/leaks", json={"found_on": date.today().isoformat(), "site": "x.example"}), 201)
    other = new_user(admin)[1]
    assert other.get(f"/api/leaks/{leak['id']}/notice").status_code == 404
    assert ok(other.get("/api/leaks"))["leaks"] == []


# ---------- decoy password ----------

def test_decoy_password_opens_a_separate_empty_account(admin):
    name, real = new_user(admin)
    ok(real.post("/api/clients", json={"name": "A real client"}), 201)
    assert ok(real.get("/api/account/decoy")) == {"enabled": False}
    assert real.put("/api/account/decoy", json={"current_password": "wrong-password-here", "decoy_password": DECOY}).status_code == 400
    assert real.put("/api/account/decoy", json={"current_password": PASSWORD, "decoy_password": PASSWORD}).status_code == 400
    assert real.put("/api/account/decoy", json={"current_password": PASSWORD, "decoy_password": "short"}).status_code == 400
    assert ok(real.put("/api/account/decoy", json={"current_password": PASSWORD, "decoy_password": DECOY})) == {"enabled": True}

    decoy = TestClient(main.app)
    me = ok(decoy.post("/api/auth/login", json={"username": name, "password": DECOY}))
    assert me["username"] == name and me["is_admin"] is False
    assert ok(decoy.get("/api/clients")) == []                                   # none of the real records
    assert ok(decoy.get("/api/auth/status"))["user"]["username"] == name
    ok(decoy.post("/api/clients", json={"name": "Aunt May"}), 201)
    assert ok(decoy.get("/api/account/decoy")) == {"enabled": False}             # looks like any account without one

    # The real password still opens the real account, which has a note that the decoy was used.
    again = TestClient(main.app)
    ok(again.post("/api/auth/login", json={"username": name, "password": PASSWORD}))
    assert [c["name"] for c in ok(again.get("/api/clients"))] == ["A real client"]
    assert "decoy" in [e["outcome"] for e in ok(again.get("/api/account/sign-ins"))]

    # Hidden: not in the list of users, and its internal name can't be signed in to.
    users = ok(admin.get("/api/users"))
    assert all(not u["username"].startswith("~") for u in users) and sum(u["username"] == name for u in users) == 1
    db = main.get_db()
    internal = db.execute("SELECT u.username FROM decoys d JOIN users u ON u.id = d.decoy_user_id "
                          "JOIN users r ON r.id = d.user_id WHERE r.username = ?", (name,)).fetchone()[0]
    db.close()
    assert TestClient(main.app).post("/api/auth/login", json={"username": internal, "password": DECOY}).status_code == 401

    # From inside the decoy, the real password is not "the current password".
    assert decoy.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "another-long-password"}).status_code == 400

    # Changing the decoy password keeps what's in it and logs the decoy out everywhere.
    ok(again.put("/api/account/decoy", json={"current_password": PASSWORD, "decoy_password": DECOY + "-2"}))
    assert decoy.get("/api/clients").status_code == 401
    assert TestClient(main.app).post("/api/auth/login", json={"username": name, "password": DECOY}).status_code == 401
    decoy2 = TestClient(main.app)
    ok(decoy2.post("/api/auth/login", json={"username": name, "password": DECOY + "-2"}))
    assert [c["name"] for c in ok(decoy2.get("/api/clients"))] == ["Aunt May"]

    # Removing it takes the decoy account and its records away.
    assert again.post("/api/account/decoy/remove", json={"current_password": "wrong-password-here"}).status_code == 400
    assert ok(again.post("/api/account/decoy/remove", json={"current_password": PASSWORD})) == {"enabled": False}
    assert TestClient(main.app).post("/api/auth/login", json={"username": name, "password": DECOY + "-2"}).status_code == 401
    assert decoy2.get("/api/clients").status_code == 401
    db = main.get_db()
    assert db.execute("SELECT COUNT(*) FROM users WHERE username = ?", (internal,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM clients WHERE name = 'Aunt May'").fetchone()[0] == 0
    db.close()
    assert [c["name"] for c in ok(again.get("/api/clients"))] == ["A real client"]


def test_deleting_a_login_takes_its_decoy_too(admin):
    name, real = new_user(admin)
    ok(real.put("/api/account/decoy", json={"current_password": PASSWORD, "decoy_password": DECOY}))
    user_id = next(u["id"] for u in ok(admin.get("/api/users")) if u["username"] == name)
    db = main.get_db()
    decoy_id = db.execute("SELECT decoy_user_id FROM decoys WHERE user_id = ?", (user_id,)).fetchone()[0]
    db.close()
    assert admin.delete(f"/api/users/{user_id}").status_code == 204
    db = main.get_db()
    assert db.execute("SELECT COUNT(*) FROM users WHERE id IN (?, ?)", (user_id, decoy_id)).fetchone()[0] == 0
    db.close()


# ---------- platform tax forms ----------

def test_tax_forms_are_checked_against_what_was_recorded(api):
    year = date.today().year
    fans = ok(api.post("/api/income-sources", json={"name": "FanSite", "kind": "platform", "fee_percent": 20}), 201)
    clips = ok(api.post("/api/income-sources", json={"name": "ClipShop", "kind": "platform"}), 201)
    quiet = ok(api.post("/api/income-sources", json={"name": "Quiet one", "kind": "platform"}), 201)
    for source, gross, fees in ((fans, 1000, 200), (fans, 500, 100), (clips, 300, 0), (quiet, 50, 0)):
        ok(api.post("/api/income", json={"source_id": source["id"], "date": f"{year}-03-10T12:00:00Z", "kind": "payout",
                                         "gross": gross, "fees": fees}), 201)
    ok(api.post("/api/tax-summary/forms", json={"year": year, "source_id": fans["id"], "amount": 1200}), 201)     # reports what was paid out
    ok(api.post("/api/tax-summary/forms", json={"year": year, "source_id": clips["id"], "amount": 450}), 201)     # more than recorded
    ok(api.post("/api/tax-summary/forms", json={"year": year, "label": "Old agency", "amount": 80}), 201)
    out = ok(api.get("/api/tax-summary/forms", params={"year": year}))
    by = {f["source_name"] or f["label"]: f for f in out["forms"]}
    assert by["FanSite"]["verdict"] == "match" and by["FanSite"]["matches"] == "after fees" and by["FanSite"]["recorded_gross"] == 1500
    assert by["ClipShop"]["verdict"] == "form_higher" and by["ClipShop"]["gap"] == 150
    assert by["Old agency"]["verdict"] == "no_place"
    assert out["without_form"] == [{"source_id": quiet["id"], "name": "Quiet one", "recorded_gross": 50}]
    assert api.post("/api/tax-summary/forms", json={"year": year, "amount": 10}).status_code == 400
    assert api.post("/api/tax-summary/forms", json={"year": year, "source_id": 999999, "amount": 10}).status_code == 400
    assert api.delete(f"/api/tax-summary/forms/{by['ClipShop']['id']}").status_code == 204
    assert len(ok(api.get("/api/tax-summary/forms", params={"year": year}))["forms"]) == 2


# ---------- payout calendar ----------

def test_payout_days_follow_each_rule():
    wed = date(2026, 11, 18)                                          # a Wednesday
    assert payouts.lands_on(wed, "weekly", 4) == date(2026, 11, 20)   # the Friday after
    assert payouts.lands_on(wed, "weekly", 2) == date(2026, 11, 25)   # earned on payday: next week's
    assert payouts.lands_on(wed, "twice_monthly", 0) == date(2026, 12, 1)
    assert payouts.lands_on(date(2026, 11, 3), "twice_monthly", 0) == date(2026, 11, 15)
    assert payouts.lands_on(wed, "monthly", 7) == date(2026, 12, 7)
    assert payouts.lands_on(date(2026, 12, 20), "monthly", 7) == date(2027, 1, 7)
    assert payouts.lands_on(wed, "days_after", 21) == date(2026, 12, 9)
    assert payouts.describe("weekly", 4) == "Every Friday" and payouts.describe("days_after", 1) == "1 day after it's earned"


def test_payout_calendar_places_pending_money(api):
    today = date(2026, 11, 19)
    fans = ok(api.post("/api/income-sources", json={"name": "FanSite", "kind": "platform"}), 201)
    cams = ok(api.post("/api/income-sources", json={"name": "CamSite", "kind": "platform"}), 201)
    bare = ok(api.post("/api/income-sources", json={"name": "No rule", "kind": "platform"}), 201)
    rule = ok(api.put(f"/api/payouts/rules/{fans['id']}", json={"every": "weekly", "day": 4}))
    assert rule["rule"] == "Every Friday"
    ok(api.put(f"/api/payouts/rules/{cams['id']}", json={"every": "days_after", "day": 3}))
    assert api.put(f"/api/payouts/rules/{fans['id']}", json={"every": "monthly", "day": 31}).status_code == 400
    assert api.put("/api/payouts/rules/999999", json={"every": "weekly", "day": 1}).status_code == 404

    def pending(source, day, gross, fees=0, **extra):
        return ok(api.post("/api/income", json={"source_id": source["id"], "date": f"{day}T12:00:00Z", "kind": "payout",
                                                "gross": gross, "fees": fees, "status": "pending", **extra}), 201)
    pending(fans, "2026-11-17", 500, 100)                 # Friday the 20th
    pending(fans, "2026-11-18", 200, 40)                  # the same Friday
    pending(cams, "2026-11-10", 90)                       # the 13th: late
    pending(bare, "2026-11-15", 60)                       # no rule, no date
    pending(bare, "2026-11-15", 70, payout_date="2026-11-30")
    ok(api.post("/api/income", json={"source_id": fans["id"], "date": "2026-11-18T12:00:00Z", "kind": "payout", "gross": 999}), 201)  # arrived

    cal = ok(api.get("/api/payouts", params={"today": today.isoformat()}))
    assert [(d["date"], d["total"], d["late"]) for d in cal["days"]] == [
        ("2026-11-13", 90, True), ("2026-11-20", 560, False), ("2026-11-30", 70, False)]
    assert cal["days"][1]["days_away"] == 1 and all(i["guessed"] for i in cal["days"][1]["items"])
    assert cal["days"][2]["items"][0]["guessed"] is False
    assert cal["expected"] == 720 and cal["late"] == 90 and cal["undated_total"] == 60 and len(cal["undated"]) == 1
    assert {p["name"]: p["rule"] for p in cal["places"]}["CamSite"] == "3 days after it's earned"
    assert api.delete(f"/api/payouts/rules/{cams['id']}").status_code == 204
    assert ok(api.get("/api/payouts", params={"today": today.isoformat()}))["undated_total"] == 150


# ---------- orders that go in the post ----------

def test_an_item_order_is_packed_posted_and_delivered(api):
    order = ok(api.post("/api/customs", json={"buyer": "sockfan", "title": "Worn socks", "price": 40, "status": "to_make"}), 201)
    assert order["is_item"] is False and order["to_post"] is False
    order = ok(api.put(f"/api/customs/{order['id']}/shipping", json={"is_item": True}))
    assert order["is_item"] and order["to_post"] is False                       # not paid yet
    ok(api.post(f"/api/customs/{order['id']}/payment", json={"amount": 40, "log_income": False}))
    assert ok(api.get("/api/customs"))["attention"]["to_post"] == 1
    today = date.today().isoformat()
    order = ok(api.put(f"/api/customs/{order['id']}/shipping", json={"is_item": True, "packed_on": today}))
    assert order["packed_on"] == today and order["status"] == "to_make" and order["to_post"]
    order = ok(api.put(f"/api/customs/{order['id']}/shipping",
                       json={"is_item": True, "packed_on": today, "posted_on": today, "carrier": "USPS", "tracking": "9400 1"}))
    assert order["status"] == "delivered" and order["delivery_note"] == "Posted with USPS (9400 1)" and not order["to_post"]
    assert ok(api.get("/api/customs"))["attention"]["to_post"] == 0
    assert api.put("/api/customs/999999/shipping", json={"is_item": True}).status_code == 404
