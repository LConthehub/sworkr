"""Custom content orders: request, quote, payment (logged as income), delivery, and the menu of prices.
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
YEAR = {"start": "2026-01-01T00:00:00Z", "end": "2027-01-01T00:00:00Z"}


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "cu-" + uuid.uuid4().hex[:8]
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


def order(api, buyer="@fan", title="5 minute video", **more):
    return ok(api.post("/api/customs", json={"buyer": buyer, "title": title, **more}), 201)


def test_an_order_from_request_to_delivery(api):
    place = ok(api.post("/api/income-sources", json={"name": "OnlyFans", "kind": "platform", "fee_percent": 20}), 201)
    o = order(api, " @fan ", " Name video ", details="Say 'Alex', red dress", price=150, due_date=day(5), source_id=place["id"],
              requested_at="2026-03-01T12:00:00Z")
    assert (o["buyer"], o["title"], o["status"], o["payment"], o["owed"], o["days_left"], o["late"]) == \
        ("@fan", "Name video", "requested", "unpaid", 150, 5, False)
    assert o["source_name"] == "OnlyFans"
    assert ok(api.post(f"/api/customs/{o['id']}/status", json={"status": "quoted"}))["status"] == "quoted"

    part = ok(api.post(f"/api/customs/{o['id']}/payment", json={"amount": 50, "paid_on": "2026-03-02T12:00:00Z"}))
    assert (part["status"], part["amount_paid"], part["payment"], part["owed"]) == ("to_make", 50, "part", 100)   # a deposit accepts it
    paid = ok(api.post(f"/api/customs/{o['id']}/payment", json={"amount": 100, "fees": 0}))
    assert (paid["payment"], paid["owed"]) == ("paid", 0)
    income = sorted(ok(api.get("/api/income")), key=lambda i: i["gross"])
    assert [(i["gross"], i["fees"], i["kind"], i["source_name"]) for i in income] == [(50, 10, "sale", "OnlyFans"), (100, 0, "sale", "OnlyFans")]
    assert income[0]["description"] == "Custom: Name video (@fan)" and income[0]["date"].startswith("2026-03-02")

    done = ok(api.post(f"/api/customs/{o['id']}/delivered", json={"delivered_at": "2026-03-05T12:00:00Z", "delivery_note": "Sent in DMs"}))
    assert (done["status"], done["delivery_note"], done["late"]) == ("delivered", "Sent in DMs", False)
    assert done["delivered_at"].startswith("2026-03-05") and done["requested_at"].startswith("2026-03-01")
    assert ok(api.post(f"/api/customs/{o['id']}/status", json={"status": "to_make"}))["delivered_at"] is None       # reopened

    assert api.post(f"/api/customs/{o['id']}/payment", json={"amount": 0}).status_code == 400
    assert api.post(f"/api/customs/{o['id']}/status", json={"status": "maybe"}).status_code == 400
    assert api.post("/api/customs/999999/payment", json={"amount": 5}).status_code == 404
    assert api.post("/api/customs", json={"buyer": " ", "title": "x"}).status_code == 400
    assert api.post("/api/customs", json={"buyer": "x", "title": "y", "price": -1}).status_code == 400
    assert api.post("/api/customs", json={"buyer": "x", "title": "y", "source_id": 999999}).status_code == 400
    assert api.post("/api/customs", json={"buyer": "x", "title": "y", "client_id": 999999}).status_code == 400
    assert api.post("/api/customs", json={"buyer": "x", "title": "y", "set_path": "../etc"}).status_code == 400

    ok(api.delete(f"/api/customs/{o['id']}"), 204)
    assert len(ok(api.get("/api/income"))) == 2                    # the money that came in stays in income


def test_the_list_counts_what_needs_attention(api):
    order(api, title="Just asked")
    late = order(api, title="Late and paid", price=100, due_date=day(-2))
    ok(api.post(f"/api/customs/{late['id']}/payment", json={"amount": 100, "log_income": False}))
    unpaid = order(api, title="Started unpaid", price=80, due_date=day(3), status="to_make")
    sent = order(api, title="Sent", price=60, status="delivered")
    order(api, title="No thanks", status="declined")

    data = ok(api.get("/api/customs"))
    assert [o["title"] for o in data["orders"]] == ["Late and paid", "Started unpaid", "Just asked"]     # soonest due first
    assert data["attention"] == {"to_make": 2, "late": 1, "not_paid": 1, "paid_waiting": 100, "to_answer": 1}
    assert data["orders"][0]["late"] is True and ok(api.get("/api/income")) == []
    assert [o["title"] for o in ok(api.get("/api/customs", params={"show": "delivered"}))["orders"]] == ["Sent"]
    assert [o["title"] for o in ok(api.get("/api/customs", params={"show": "declined"}))["orders"]] == ["No thanks"]
    everything = ok(api.get("/api/customs", params={"show": "all"}))
    assert len(everything["orders"]) == 5 and everything["attention"]["to_make"] == 2
    assert api.get("/api/customs", params={"show": "nope"}).status_code == 400

    edited = ok(api.put(f"/api/customs/{unpaid['id']}", json={"buyer": "@fan", "title": "Started unpaid", "price": 80, "status": "to_make",
                                                              "can_resell": True, "set_path": "Customs/2026-03 fan"}))
    assert edited["can_resell"] is True and edited["set_path"] == "Customs/2026-03 fan" and edited["due_date"] is None
    assert sent["delivered_at"] is not None


def test_the_summary(api):
    place = ok(api.post("/api/income-sources", json={"name": "Fansly", "kind": "platform"}), 201)
    a = order(api, title="A", price=100, source_id=place["id"], requested_at="2026-02-01T12:00:00Z", can_resell=True)
    ok(api.post(f"/api/customs/{a['id']}/payment", json={"amount": 100}))
    ok(api.post(f"/api/customs/{a['id']}/delivered", json={"delivered_at": "2026-02-05T12:00:00Z"}))
    b = order(api, title="B", price=200, requested_at="2026-02-10T12:00:00Z")
    ok(api.post(f"/api/customs/{b['id']}/payment", json={"amount": 50}))
    order(api, title="C", price=999, status="declined", requested_at="2026-02-11T12:00:00Z")
    order(api, title="Last year", price=500, requested_at="2025-02-11T12:00:00Z")

    s = ok(api.get("/api/customs/summary", params=YEAR))
    assert (s["orders"], s["delivered"], s["declined"], s["open"]) == (3, 1, 1, 1)
    assert (s["paid"], s["owed"], s["average_price"], s["average_days"], s["can_resell"]) == (150, 150, 150, 4.0, 1)
    assert s["places"] == [{"source_id": place["id"], "label": "Fansly", "orders": 1, "paid": 100},
                           {"source_id": None, "label": "No place set", "orders": 2, "paid": 50}]


def test_the_menu(api):
    a = ok(api.post("/api/customs/menu", json={"label": " 5 minute video ", "price": 100}), 201)
    ok(api.post("/api/customs/menu", json={"label": "Say my name", "price": 20, "notes": "Add-on"}), 201)
    assert [(m["label"], m["price"]) for m in ok(api.get("/api/customs/menu"))] == [("5 minute video", 100), ("Say my name", 20)]
    assert ok(api.put(f"/api/customs/menu/{a['id']}", json={"label": "5 minute video", "price": 120}))["price"] == 120
    assert api.post("/api/customs/menu", json={"label": " "}).status_code == 400
    assert api.post("/api/customs/menu", json={"label": "x", "price": -5}).status_code == 400
    assert api.put("/api/customs/menu/999999", json={"label": "x"}).status_code == 404
    ok(api.delete(f"/api/customs/menu/{a['id']}"), 204)
    assert len(ok(api.get("/api/customs/menu"))) == 1


def test_people_only_see_their_own(api, admin):
    o = order(api, price=50)
    item = ok(api.post("/api/customs/menu", json={"label": "Mine", "price": 1}), 201)
    other = new_user(admin)
    assert ok(other.get("/api/customs", params={"show": "all"}))["orders"] == [] and ok(other.get("/api/customs/menu")) == []
    assert ok(other.get("/api/customs/summary", params={"start": "2020-01-01T00:00:00Z", "end": "2030-01-01T00:00:00Z"}))["orders"] == 0
    assert other.put(f"/api/customs/{o['id']}", json={"buyer": "x", "title": "y"}).status_code == 404
    assert other.post(f"/api/customs/{o['id']}/payment", json={"amount": 5}).status_code == 404
    assert other.post(f"/api/customs/{o['id']}/delivered", json={}).status_code == 404
    assert other.put(f"/api/customs/menu/{item['id']}", json={"label": "x"}).status_code == 404
    other.delete(f"/api/customs/{o['id']}")
    other.delete(f"/api/customs/menu/{item['id']}")
    assert len(ok(api.get("/api/customs"))["orders"]) == 1 and len(ok(api.get("/api/customs/menu"))) == 1
    for path in ("/api/customs", "/api/customs/menu"):
        assert TestClient(main.app).get(path).status_code == 401
