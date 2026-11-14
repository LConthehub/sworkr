"""API tests. Run them inside Docker with:  docker compose run --rm tests"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

# Use a throwaway database so tests never touch real data. Must be set before importing main.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="sworkr-test-")
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"  # no background thread talking to Nextcloud
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

PASSWORD = "correct-horse-battery"
APPOINTMENT = {"service_type": "Session", "duration_minutes": 60, "scheduled_date": "2030-01-01T10:00:00Z"}


@pytest.fixture(scope="module")
def api():
    """A logged-in API client: creates the first (admin) account."""
    c = TestClient(main.app)
    r = c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD})
    assert r.status_code == 201
    return c


def anonymous():
    return TestClient(main.app)


def make_client(api, name, **fields):
    r = api.post("/api/clients", json={"name": name, **fields})
    assert r.status_code == 201, r.text
    return r.json()


def as_utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def is_closed(conn):
    try:
        conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


# ---------- auth ----------

def test_health_is_public():
    assert anonymous().get("/api/health").json() == {"status": "ok"}


def test_api_requires_login(api):
    anon = anonymous()
    for path in ("/api/clients", "/api/appointments", "/api/expenses", "/api/expenses/summary", "/api/search?q=a"):
        assert anon.get(path).status_code == 401, path


def test_setup_only_works_once(api):
    r = anonymous().post("/api/auth/setup", json={"username": "intruder", "password": PASSWORD})
    assert r.status_code == 403


def test_auth_status(api):
    assert api.get("/api/auth/status").json() == {
        "setup_required": False, "user": {"id": 1, "username": "owner", "is_admin": True}, "demo": False}
    assert anonymous().get("/api/auth/status").json() == {"setup_required": False, "user": None, "demo": False}


def test_login_and_logout(api):
    other = anonymous()
    assert other.post("/api/auth/login", json={"username": "owner", "password": "wrong-password"}).status_code == 401
    assert other.post("/api/auth/login", json={"username": " Owner ", "password": PASSWORD}).status_code == 200
    assert other.get("/api/clients").status_code == 200
    assert other.post("/api/auth/logout").status_code == 204
    assert other.get("/api/clients").status_code == 401


def test_change_password(api):
    other = anonymous()
    assert other.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    new = PASSWORD + "-2"

    def change(current, to):
        return api.post("/api/auth/change-password", json={"current_password": current, "new_password": to}).status_code

    assert change("not-the-password", new) == 400
    assert change(PASSWORD, "short") == 400
    assert change(PASSWORD, new) == 204
    assert api.get("/api/clients").status_code == 200       # this device stays logged in
    assert other.get("/api/clients").status_code == 401     # other devices are logged out
    assert other.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 401
    assert change(new, PASSWORD) == 204                     # put it back for the other tests


# ---------- clients ----------

def test_client_crud(api):
    r = api.post("/api/clients", json={"name": "Ada Lovelace", "email": "Ada@Example.com", "tags": ["VIP", "vip ", ""]})
    assert r.status_code == 201
    ada = r.json()
    assert (ada["email"], ada["tags"], ada["is_active"]) == ("ada@example.com", ["vip"], True)
    assert api.get(f"/api/clients/{ada['id']}").json()["name"] == "Ada Lovelace"

    r = api.put(f"/api/clients/{ada['id']}", json={"name": "Ada King", "tags": ["math"], "is_active": False})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["email"], r.json()["tags"], r.json()["is_active"]) == ("Ada King", None, ["math"], False)

    assert api.delete(f"/api/clients/{ada['id']}").status_code == 204
    assert api.get(f"/api/clients/{ada['id']}").status_code == 404
    assert api.put(f"/api/clients/{ada['id']}", json={"name": "Gone"}).status_code == 404


def test_client_validation(api):
    first = make_client(api, "Dup One", email="dup@example.com")
    assert api.post("/api/clients", json={"name": "Dup Two", "email": "DUP@example.com"}).status_code == 409
    second = make_client(api, "Dup Two")
    assert api.put(f"/api/clients/{second['id']}", json={"name": "Dup Two", "email": "dup@example.com"}).status_code == 409
    assert api.post("/api/clients", json={"name": "   "}).status_code == 400
    assert api.put(f"/api/clients/{first['id']}", json={"name": ""}).status_code == 400


def test_client_list_filters(api):
    make_client(api, "Filter Alpha", tags=["gold"])
    make_client(api, "Filter Beta", is_active=False)

    def names(**params):
        return [c["name"] for c in api.get("/api/clients", params={"limit": 200, **params}).json()]

    assert names(search="filter") == ["Filter Beta", "Filter Alpha"]      # newest first
    assert names(search="  FILTER ") == ["Filter Beta", "Filter Alpha"]
    assert names(search="filter", is_active=1) == ["Filter Alpha"]
    assert names(search="filter", is_active=0) == ["Filter Beta"]
    assert names(tag_filter="GOLD") == ["Filter Alpha"]
    assert names(search="filter", limit=1, page=2) == ["Filter Alpha"]
    assert names(search="%") == []                                        # % and _ are not wildcards
    assert names(search="_") == []
    assert len(names(search="   ")) >= 2                                  # a blank filter means no filter


# ---------- appointments ----------

def test_appointment_crud(api):
    c = make_client(api, "Appt Client")
    body = {"client_id": c["id"], "service_type": " Consultation ", "duration_minutes": 45,
            "scheduled_date": "2030-03-10T15:00:00+02:00", "notes": "bring forms"}
    r = api.post("/api/appointments", json=body)
    assert r.status_code == 201
    appt = r.json()
    assert (appt["service_type"], appt["client_name"], appt["status"]) == ("Consultation", "Appt Client", "scheduled")
    assert as_utc(appt["scheduled_date"]) == datetime(2030, 3, 10, 13, tzinfo=timezone.utc)   # stored as UTC

    assert api.get(f"/api/appointments/{appt['id']}").json()["notes"] == "bring forms"
    assert "Consultation" in api.get("/api/appointments/service-types").json()

    def listed(**params):
        return [a["id"] for a in api.get("/api/appointments", params={"client_id": c["id"], **params}).json()]

    assert listed() == [appt["id"]]
    assert listed(start="2030-03-10T13:00:00Z", end="2030-03-10T13:00:01Z") == [appt["id"]]
    assert listed(start="2030-03-10T13:00:01Z") == []
    assert listed(end="2030-03-10T13:00:00Z") == []
    assert listed(status="completed") == []

    r = api.put(f"/api/appointments/{appt['id']}", json={**body, "duration_minutes": 90, "status": "completed"})
    assert (r.status_code, r.json()["duration_minutes"], r.json()["status"]) == (200, 90, "completed")
    r = api.put(f"/api/appointments/{appt['id']}/status", params={"status": "cancelled"})
    assert (r.status_code, r.json()["status"]) == (200, "cancelled")

    assert api.delete(f"/api/appointments/{appt['id']}").status_code == 204
    assert api.get(f"/api/appointments/{appt['id']}").status_code == 404


def test_appointment_validation(api):
    c = make_client(api, "Appt Rules")
    ok = {"client_id": c["id"], **APPOINTMENT}
    assert api.post("/api/appointments", json={**ok, "client_id": 999999}).status_code == 400
    assert api.post("/api/appointments", json={**ok, "duration_minutes": 0}).status_code == 400
    assert api.post("/api/appointments", json={**ok, "service_type": "  "}).status_code == 400
    assert api.post("/api/appointments", json={**ok, "status": "maybe"}).status_code == 422
    assert api.put("/api/appointments/999999", json=ok).status_code == 404
    assert api.put("/api/appointments/999999/status", params={"status": "completed"}).status_code == 404


def test_deleting_a_client_removes_their_appointments_but_keeps_their_expenses(api):
    c = make_client(api, "Leaving Client")
    appt = api.post("/api/appointments", json={"client_id": c["id"], **APPOINTMENT}).json()
    exp = api.post("/api/expenses", json={"description": "Taxi", "amount": 20, "client_id": c["id"]}).json()
    assert exp["client_name"] == "Leaving Client"

    assert api.delete(f"/api/clients/{c['id']}").status_code == 204
    assert api.get(f"/api/appointments/{appt['id']}").status_code == 404
    kept = [e for e in api.get("/api/expenses").json() if e["id"] == exp["id"]]
    assert kept and kept[0]["client_id"] is None
    api.delete(f"/api/expenses/{exp['id']}")


# ---------- expenses ----------

def test_expense_crud_and_summary(api):
    c = make_client(api, "Expense Client")
    before = api.get("/api/expenses/summary").json()

    r = api.post("/api/expenses", json={"description": "Linen service", "amount": 12.5, "category": "cleaning", "client_id": c["id"]})
    assert r.status_code == 201
    exp = r.json()
    assert (exp["amount"], exp["category"], exp["client_name"]) == (12.5, "cleaning", "Expense Client")

    after = api.get("/api/expenses/summary").json()
    assert after["expense_count"] == before["expense_count"] + 1
    assert after["overall_total"] == round(before["overall_total"] + 12.5, 2)
    assert {"name": "Expense Client", "total_spent": 12.5, "expense_count": 1} in after["top_clients"]

    def ids(**params):
        return [e["id"] for e in api.get("/api/expenses", params=params).json()]

    assert exp["id"] in ids(category="cleaning")
    assert exp["id"] not in ids(category="travel")
    assert ids(client_id=c["id"]) == [exp["id"]]
    assert ids(client_id=c["id"], min_amount=13) == []
    assert ids(client_id=c["id"], max_amount=13) == [exp["id"]]

    r = api.put(f"/api/expenses/{exp['id']}", json={"description": "Linen + towels", "amount": 20, "category": "cleaning"})
    assert r.status_code == 200
    assert (r.json()["description"], r.json()["amount"], r.json()["client_id"]) == ("Linen + towels", 20, None)
    assert r.json()["date"] == exp["date"]                    # the date is kept when it isn't sent

    assert api.delete(f"/api/expenses/{exp['id']}").status_code == 204
    assert api.get("/api/expenses/summary").json()["expense_count"] == before["expense_count"]
    assert api.put(f"/api/expenses/{exp['id']}", json={"description": "Gone", "amount": 1}).status_code == 404


def test_expense_validation(api):
    assert api.post("/api/expenses", json={"description": "Bad", "amount": -5}).status_code == 400
    assert api.post("/api/expenses", json={"description": "Bad", "amount": 5, "client_id": 999999}).status_code == 400
    assert api.post("/api/expenses", json={"description": "  ", "amount": 5}).status_code == 400
    assert api.post("/api/expenses", json={"description": "Bad", "amount": 5, "category": "yachts"}).status_code == 422
    exp = api.post("/api/expenses", json={"description": "Fine", "amount": 5}).json()
    assert api.put(f"/api/expenses/{exp['id']}", json={"description": "Fine", "amount": -1}).status_code == 400
    api.delete(f"/api/expenses/{exp['id']}")


def test_expense_list_limit(api):
    assert api.get("/api/expenses", params={"limit": 500}).status_code == 200    # what the Expenses page asks for
    assert api.get("/api/expenses", params={"limit": 501}).status_code == 422


# ---------- search ----------

def test_search(api):
    c = make_client(api, "Zebedee Quince", email="zq@example.com", tags=["quirky"])
    api.post("/api/appointments", json={"client_id": c["id"], **APPOINTMENT, "service_type": "Zeppelin Tour"})
    api.post("/api/expenses", json={"description": "Zeppelin fuel", "amount": 99})

    def found(q, entity_type="all"):
        r = api.get("/api/search", params={"q": q, "entity_type": entity_type})
        assert r.status_code == 200
        assert r.json()["count"] == len(r.json()["results"])
        return sorted(item["entity_type"] for item in r.json()["results"])

    assert found("zebedee") == ["appointment", "client"]      # the appointment matches on its client's name
    assert found("  ZEBEDEE  ") == ["appointment", "client"]
    assert found("quirky") == ["client"]                      # matched by tag
    assert found("zeppelin") == ["appointment", "expense"]
    assert found("zeppelin", "expenses") == ["expense"]
    assert found("zeppelin", "clients") == []
    assert found("no-such-thing") == []
    assert api.get("/api/search", params={"q": "zeppelin", "entity_type": "bogus"}).status_code == 400


def test_blank_or_wildcard_search_finds_nothing(api):
    make_client(api, "Wildcard Bystander")
    for q in ("", "   ", "%", "_", "%%", "_%"):
        r = api.get("/api/search", params={"q": q})
        assert r.status_code == 200, q
        assert r.json()["count"] == 0, q

    make_client(api, "50% Off Promo")
    r = api.get("/api/search", params={"q": "50%"})
    assert [item["name"] for item in r.json()["results"]] == ["50% Off Promo"]


# ---------- database connections ----------

def test_every_request_closes_its_database_connection(api):
    opened = []
    real_get_db = main.get_db

    def tracking_get_db():
        conn = real_get_db()
        opened.append(conn)
        return conn

    main.get_db = tracking_get_db
    try:
        c = make_client(api, "Connection Check")
        api.get("/api/clients")
        api.get(f"/api/clients/{c['id']}")
        api.get("/api/clients/999999")                                           # 404
        api.post("/api/clients", json={"name": " "})                             # 400
        api.post("/api/expenses", json={"description": "x", "amount": -1})       # 400
        api.post("/api/appointments", json={"client_id": 999999, **APPOINTMENT}) # 400
        api.get("/api/appointments")
        api.get("/api/appointments/service-types")
        api.get("/api/expenses")
        api.get("/api/expenses/summary")
        api.get("/api/search", params={"q": "connection"})
        api.get("/api/auth/status")
        anonymous().get("/api/clients")                                          # 401
        api.delete(f"/api/clients/{c['id']}")
    finally:
        main.get_db = real_get_db

    assert len(opened) > 15
    still_open = sum(not is_closed(conn) for conn in opened)
    assert still_open == 0, f"{still_open} of {len(opened)} connections were left open"
