"""How clients found you, and what each way of being found brings in.
Run with:  docker compose run --rm tests"""
import os
import sys
import tempfile
import uuid

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import marketing  # noqa: E402

PASSWORD = "correct-horse-battery"
YEAR = {"start": "2026-01-01T00:00:00Z", "end": "2027-01-01T00:00:00Z"}


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    name = "mk-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def client(api, name, found_via=None, **more):
    return ok(api.post("/api/clients", json={"name": name, "found_via": found_via, **more}), 201)


def booking(api, client_id, paid, when="2026-03-10T19:00:00Z"):
    return ok(api.post("/api/appointments", json={"client_id": client_id, "service_type": "Dinner", "duration_minutes": 60,
                                                  "scheduled_date": when, "rate": paid, "amount_paid": paid}), 201)


def report(api, **params):
    data = ok(api.get("/api/marketing/found-via", params={**YEAR, **params}))
    return data, {r["key"]: r for r in data["rows"]}


def test_found_via_is_saved_tidied_and_can_be_cleared(api):
    c = client(api, "Avery", "  Tryst   ads ")
    assert c["found_via"] == "Tryst ads"
    assert ok(api.get(f"/api/clients/{c['id']}"))["found_via"] == "Tryst ads"
    changed = ok(api.put(f"/api/clients/{c['id']}", json={"name": "Avery", "found_via": "Eros"}))
    assert changed["found_via"] == "Eros"
    assert ok(api.put(f"/api/clients/{c['id']}", json={"name": "Avery", "found_via": " "}))["found_via"] is None
    assert len(client(api, "Long", "x" * 300)["found_via"]) == marketing.MAX_LENGTH


def test_spellings_of_the_same_place_are_one_group():
    assert marketing.source_key(" TRYST ") == marketing.source_key("tryst") == "tryst"
    assert marketing.source_key("Twitter") == marketing.source_key("X (Twitter)") == marketing.source_key("x") == "x"
    assert marketing.source_key(None) == marketing.source_key("  ") == marketing.NOT_RECORDED


def test_income_is_counted_for_the_way_each_client_found_you(api):
    a, b = client(api, "Avery", "Tryst"), client(api, "Blake", "tryst")
    c, d = client(api, "Casey", "Twitter"), client(api, "Drew")
    client(api, "Jade", "Tryst", role="partner")           # a co-worker isn't a client who found you
    booking(api, a["id"], 400)
    booking(api, a["id"], 300)
    booking(api, b["id"], 200)
    booking(api, c["id"], 500)
    booking(api, d["id"], 100)
    booking(api, a["id"], 999, when="2025-06-01T19:00:00Z")   # another year: not counted
    booking(api, b["id"], 0)                                   # nothing paid yet: not counted

    data, rows = report(api)
    assert rows["tryst"]["label"] == "Tryst"                  # the spelling used most (a tie: the capitalised one)
    assert (rows["tryst"]["clients"], rows["tryst"]["bookings"], rows["tryst"]["income"]) == (2, 3, 900)
    assert rows["tryst"]["per_client"] == 450
    assert (rows["x"]["clients"], rows["x"]["income"]) == (1, 500)
    assert rows[marketing.NOT_RECORDED]["label"] == "Not recorded" and rows[marketing.NOT_RECORDED]["income"] == 100
    assert data["total"] == 1500 and rows["tryst"]["share"] == 0.6
    assert [r["key"] for r in data["rows"]] == ["tryst", "x", marketing.NOT_RECORDED]   # unknown always last
    assert rows["tryst"]["new_clients"] == 2                  # added this year

    assert ok(api.get("/api/marketing/found-via/options")) == ["Tryst", "Twitter"]
    assert api.get("/api/marketing/found-via", params={"start": YEAR["end"], "end": YEAR["start"]}).status_code == 400


def test_a_co_workers_share_and_client_gifts(api):
    a = client(api, "Avery", "Eros")
    jade = client(api, "Jade", role="partner")
    duo = booking(api, a["id"], 1000)
    ok(api.put(f"/api/splits/appointment/{duo['id']}", json={"parties": [{"partner_id": jade["id"], "share_type": "percent", "share_value": 40}]}))
    ok(api.post("/api/income", json={"date": "2026-04-01T12:00:00Z", "gross": 250, "kind": "gift", "client_id": a["id"]}), 201)
    ok(api.post("/api/income", json={"date": "2026-04-02T12:00:00Z", "gross": 70, "kind": "gift", "client_id": a["id"], "status": "pending"}), 201)
    _, rows = report(api)
    assert rows["eros"]["income"] == 850                      # 600 of the duo + the gift; the pending one isn't in yet


def test_people_only_see_their_own(api, admin):
    client(api, "Avery", "Tryst")
    name = "mk-" + uuid.uuid4().hex[:8]
    ok(admin.post("/api/users", json={"username": name, "password": PASSWORD}), 201)
    other = TestClient(main.app)
    ok(other.post("/api/auth/login", json={"username": name, "password": PASSWORD}))
    assert report(other)[0]["rows"] == [] and ok(other.get("/api/marketing/found-via/options")) == []
    assert TestClient(main.app).get("/api/marketing/found-via", params=YEAR).status_code == 401


def test_marketing_spend_is_matched_by_whole_words(api):
    a, b = client(api, "Avery", "Tryst"), client(api, "Blake", "X")
    booking(api, a["id"], 500)
    booking(api, b["id"], 100)
    for description, amount, notes in (("Tryst renewal", 120, None), ("Taxi to the shoot", 40, None),
                                       ("Promoted post", 60, "on Twitter"), ("Banner: tryst and x", 50, None)):
        ok(api.post("/api/expenses", json={"description": description, "amount": amount, "category": "marketing",
                                           "notes": notes, "date": "2026-02-01T12:00:00Z"}), 201)
    ok(api.post("/api/expenses", json={"description": "Tryst hotel", "amount": 300, "category": "travel", "date": "2026-02-01T12:00:00Z"}), 201)
    data, rows = report(api)
    assert rows["tryst"]["spend"] == 145 and rows["tryst"]["profit"] == 355     # 120 + half the banner
    assert rows["x"]["spend"] == 85 and rows["x"]["profit"] == 15               # the Twitter post + half the banner; not the taxi
    assert data["spent"] == 270 and data["unmatched_spend"] == 40               # travel isn't marketing


def test_found_via_goes_out_and_comes_back_in_the_contacts_csv(api):
    import csv
    import io
    client(api, "Avery", "Tryst")
    exported = api.get("/api/csv/clients")
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert rows[0]["found_via"] == "Tryst"
    upload = api.post("/api/csv/clients", content=f"id,name,found via\n{rows[0]['id']},Avery,  Eros \n,Blake,X\n".encode(),
                      headers={"Content-Type": "text/csv"})
    assert upload.status_code == 200, upload.text
    _, by = report(api)
    assert set(by) == {"eros", "x"}
