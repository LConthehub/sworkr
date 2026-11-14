"""Tests for contacts (names, social media handles, industry) and tasks. Run with:  docker compose run --rm tests"""
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

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    name = "ct-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


# ---------- contacts ----------

def test_a_handle_can_be_all_that_is_known(api):
    c = ok(api.post("/api/clients", json={"handles": [{"platform": "Instagram", "handle": "sunny.days"}]}), 201)
    assert c["name"] is None and c["display_name"] == "@sunny.days (Instagram)"
    assert c["handles"] == [{"platform": "Instagram", "handle": "sunny.days"}]
    assert api.post("/api/clients", json={"name": " ", "handles": [{"handle": "  "}]}).status_code == 400


def test_shown_by_name_or_by_a_chosen_handle(api):
    body = {"name": "Jordan Avery", "industry": "Finance",
            "handles": [{"platform": "X (Twitter)", "handle": "@javery"}, {"platform": "Telegram", "handle": "jordan_a"}]}
    c = ok(api.post("/api/clients", json=body), 201)
    assert c["display_name"] == "Jordan Avery" and c["industry"] == "Finance"
    c = ok(api.put(f"/api/clients/{c['id']}", json={**body, "display_handle": 1}))
    assert c["display_name"] == "@jordan_a (Telegram)" and c["name"] == "Jordan Avery"
    c = ok(api.put(f"/api/clients/{c['id']}", json={**body, "display_handle": 9}))   # no such handle: back to the name
    assert c["display_name"] == "Jordan Avery" and c["display_handle"] is None

    # What they're shown as is what bookings and search use.
    appt = ok(api.post("/api/appointments", json={"client_id": c["id"], "service_type": "S", "duration_minutes": 60,
                                                   "scheduled_date": "2045-01-01T20:00:00Z"}), 201)
    ok(api.put(f"/api/clients/{c['id']}", json={**body, "display_handle": 0}))
    assert ok(api.get(f"/api/appointments/{appt['id']}"))["client_name"] == "@javery (X (Twitter))"
    for term in ("javery", "jordan_a", "finance", "Avery"):
        assert [x["id"] for x in ok(api.get("/api/clients", params={"search": term}))] == [c["id"]], term
        assert ok(api.get("/api/search", params={"q": term, "entity_type": "clients"}))["count"] == 1, term


def test_links_and_phone_numbers_are_shown_as_typed(api):
    c = ok(api.post("/api/clients", json={"handles": [{"platform": "Signal", "handle": "+1 555 0100"}]}), 201)
    assert c["display_name"] == "+1 555 0100 (Signal)"
    assert api.post("/api/clients", json={"name": "x", "handles": [{"handle": "h"}] * 13}).status_code == 400


def test_contacts_csv_round_trip_with_handles(api):
    ok(api.post("/api/clients", json={"name": "Has Handles", "industry": "Tech",
                                      "handles": [{"platform": "Instagram", "handle": "@hh"}]}), 201)
    text = api.get("/api/csv/clients").text
    assert "Instagram: @hh" in text and "Tech" in text
    r = api.post("/api/csv/clients", content="name,handles,industry\n,Reddit: u/quiet_one; @plain,Law\n")
    assert r.status_code == 200, r.text
    c = next(x for x in ok(api.get("/api/clients", params={"limit": 200})) if x["industry"] == "Law")
    assert c["display_name"] == "u/quiet_one (Reddit)"
    assert c["handles"] == [{"platform": "Reddit", "handle": "u/quiet_one"}, {"platform": None, "handle": "@plain"}]


# ---------- tasks ----------

def test_tasks_can_be_added_ticked_off_and_filtered(api):
    client = ok(api.post("/api/clients", json={"name": "Task Contact"}), 201)
    tour = ok(api.post("/api/tours", json={"name": "Berlin", "start_date": "2045-03-01", "end_date": "2045-03-03",
                                           "starts_at": "2045-03-01T00:00:00Z", "ends_at": "2045-03-04T00:00:00Z"}), 201)
    a = ok(api.post("/api/tasks", json={"title": "Book hotel", "due_date": "2045-02-20", "tour_id": tour["id"]}), 201)
    b = ok(api.post("/api/tasks", json={"title": "Send thank-you", "due_date": "2045-02-10",
                                        "due_at": "2045-02-10T18:00:00Z", "client_id": client["id"], "notes": "Text"}), 201)
    c = ok(api.post("/api/tasks", json={"title": "Update ad photos"}), 201)
    assert (a["tour_name"], b["client_name"], c["due_date"], a["done"]) == ("Berlin", "Task Contact", None, False)
    assert [t["id"] for t in ok(api.get("/api/tasks"))] == [b["id"], a["id"], c["id"]]   # soonest first, undated last

    done = ok(api.post(f"/api/tasks/{b['id']}/done", json={"done": True}))
    assert done["done"] and done["done_at"]
    assert [t["id"] for t in ok(api.get("/api/tasks"))] == [a["id"], c["id"]]
    assert [t["id"] for t in ok(api.get("/api/tasks", params={"status": "done"}))] == [b["id"]]
    assert [t["id"] for t in ok(api.get("/api/tasks", params={"status": "all", "start": "2045-02-15",
                                                              "end": "2045-03-01"}))] == [a["id"]]
    undone = ok(api.post(f"/api/tasks/{b['id']}/done", json={"done": False}))
    assert not undone["done"] and undone["done_at"] is None

    edited = ok(api.put(f"/api/tasks/{c['id']}", json={"title": "Update ad photos", "due_date": "2045-04-01", "done": True}))
    assert edited["due_date"] == "2045-04-01" and edited["done"]
    assert api.delete(f"/api/tasks/{c['id']}").status_code == 204
    assert c["id"] not in [t["id"] for t in ok(api.get("/api/tasks", params={"status": "all"}))]


def test_task_rules(api):
    for body in ({"title": " "}, {"title": "x" * 301}, {"title": "x", "due_at": "2045-01-01T10:00:00Z"},
                 {"title": "x", "client_id": 999999}, {"title": "x", "tour_id": 999999}):
        assert api.post("/api/tasks", json=body).status_code == 400, body
    assert api.get("/api/tasks", params={"status": "maybe"}).status_code == 400


def test_tasks_are_private(api, admin):
    t = ok(api.post("/api/tasks", json={"title": "Mine"}), 201)
    assert t["id"] not in [x["id"] for x in ok(admin.get("/api/tasks", params={"status": "all"}))]
    assert admin.put(f"/api/tasks/{t['id']}", json={"title": "Taken"}).status_code == 404
    assert admin.post(f"/api/tasks/{t['id']}/done", json={"done": True}).status_code == 404
    admin.delete(f"/api/tasks/{t['id']}")
    assert ok(api.get("/api/tasks"))[0]["title"] == "Mine"
    theirs = ok(admin.post("/api/clients", json={"name": "Not yours"}), 201)
    assert api.post("/api/tasks", json={"title": "x", "client_id": theirs["id"]}).status_code == 400


def test_deleting_a_contact_keeps_their_tasks(api):
    client = ok(api.post("/api/clients", json={"name": "Leaving"}), 201)
    t = ok(api.post("/api/tasks", json={"title": "Follow up", "client_id": client["id"]}), 201)
    api.delete(f"/api/clients/{client['id']}")
    left = next(x for x in ok(api.get("/api/tasks")) if x["id"] == t["id"])
    assert left["client_id"] is None and left["client_name"] is None


# ---------- couples ----------

def test_couples_are_two_linked_contacts_and_can_book_together(api):
    maria = ok(api.post("/api/clients", json={"name": "Maria"}), 201)
    sam = ok(api.post("/api/clients", json={"name": "Sam", "couple_with": maria["id"]}), 201)
    assert sam["couple_with"] == maria["id"] and sam["couple_name"] == "Maria"
    assert ok(api.get(f"/api/clients/{maria['id']}"))["couple_name"] == "Sam"          # linked both ways
    assert api.post("/api/clients", json={"name": "Self", "couple_with": 999999}).status_code == 400

    appt = ok(api.post("/api/appointments", json={"client_id": maria["id"], "second_client_id": sam["id"], "service_type": "Couple",
                                                  "duration_minutes": 120, "scheduled_date": "2049-05-01T20:00:00Z"}), 201)
    assert appt["client_name"] == "Maria & Sam" and appt["second_client_id"] == sam["id"]
    for person in (maria, sam):                                   # it shows on both people's history
        history = ok(api.get(f"/api/clients/{person['id']}/summary"))["appointments"]
        assert [a["id"] for a in history] == [appt["id"]]
    assert api.post("/api/appointments", json={"client_id": maria["id"], "second_client_id": maria["id"], "service_type": "x",
                                               "duration_minutes": 60, "scheduled_date": "2049-05-02T20:00:00Z"}).status_code == 400

    # Linking Maria to someone else unlinks Sam; unlinking clears both sides.
    alex = ok(api.post("/api/clients", json={"name": "Alex"}), 201)
    ok(api.put(f"/api/clients/{maria['id']}", json={"name": "Maria", "couple_with": alex["id"]}))
    assert ok(api.get(f"/api/clients/{sam['id']}"))["couple_with"] is None
    assert ok(api.get(f"/api/clients/{alex['id']}"))["couple_with"] == maria["id"]
    ok(api.put(f"/api/clients/{alex['id']}", json={"name": "Alex"}))
    assert ok(api.get(f"/api/clients/{maria['id']}"))["couple_with"] is None


def test_a_do_not_see_half_of_a_couple_is_warned_about(api):
    ok_one = ok(api.post("/api/clients", json={"name": "Fine"}), 201)
    flagged = ok(api.post("/api/clients", json={"name": "Flagged", "do_not_see": True, "do_not_see_reason": "No-show"}), 201)
    r = api.post("/api/appointments", params={"warn": True}, json={
        "client_id": ok_one["id"], "second_client_id": flagged["id"], "service_type": "Couple", "duration_minutes": 60,
        "scheduled_date": "2049-06-01T20:00:00Z"})
    assert r.status_code == 409 and "Flagged" in r.json()["detail"]["warnings"][0]["message"]
