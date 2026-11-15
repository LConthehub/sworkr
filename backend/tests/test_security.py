"""Security tests: cross-site requests, headers, API docs, login throttling, cookies, and that one user can
never read or change another user's records. Run with:  docker compose run --rm tests"""
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

import auth  # noqa: E402
import main  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin, is_admin=False):
    name = "s-" + uuid.uuid4().hex[:8]
    r = admin.post("/api/users", json={"username": name, "password": PASSWORD, "is_admin": is_admin})
    assert r.status_code == 201, r.text
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


# ---------- requests started by other websites ----------

@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_changes_started_by_another_website_are_refused(admin, site):
    user = new_user(admin)
    r = user.post("/api/clients", json={"name": "Planted"}, headers={"Sec-Fetch-Site": site})
    assert r.status_code == 403
    r = user.post("/api/csv/clients", content=b"name\nPlanted\n", headers={"Sec-Fetch-Site": site})
    assert r.status_code == 403
    assert user.delete("/api/clients/1", headers={"Sec-Fetch-Site": site}).status_code == 403
    assert user.get("/api/clients").json() == []


def test_sworkrs_own_pages_can_still_make_changes(admin):
    user = new_user(admin)
    for site in ("same-origin", "none", None):
        headers = {"Sec-Fetch-Site": site} if site else {}
        assert user.post("/api/clients", json={"name": f"From {site}"}, headers=headers).status_code == 201
    # Reading is allowed from anywhere (the browser itself stops other sites reading the answer).
    assert user.get("/api/clients", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_login_from_another_website_is_refused(admin):
    c = TestClient(main.app)
    r = c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and auth.SESSION_COOKIE not in r.cookies


# ---------- headers, docs, cookies ----------

def test_api_answers_carry_security_headers(admin):
    for r in (admin.get("/api/clients"), admin.get("/api/health"), TestClient(main.app).get("/api/clients")):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["cache-control"] == "no-store"


def test_api_docs_are_off():
    c = TestClient(main.app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404


def test_session_cookie_is_secure_behind_https(admin):
    name = "c-" + uuid.uuid4().hex[:8]
    admin.post("/api/users", json={"username": name, "password": PASSWORD})
    c = TestClient(main.app)
    r = c.post("/api/auth/login", json={"username": name, "password": PASSWORD}, headers={"X-Forwarded-Proto": "https"})
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    r = c.post("/api/auth/login", json={"username": name, "password": PASSWORD})
    assert "secure" not in r.headers["set-cookie"].lower()   # plain http on this computer still works


# ---------- password guessing ----------

def test_guessing_many_usernames_from_one_address_is_slowed_down():
    c = TestClient(main.app)
    visitor = {"X-Forwarded-For": f"203.0.113.{uuid.uuid4().int % 250}"}
    for i in range(auth.ip_throttle.FREE_ATTEMPTS):
        r = c.post("/api/auth/login", json={"username": f"nobody{i}-{uuid.uuid4().hex[:4]}", "password": "x" * 8}, headers=visitor)
        assert r.status_code == 401
    r = c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}, headers=visitor)
    assert r.status_code == 429      # even the right password waits once this address is locked
    other = {"X-Forwarded-For": "198.51.100.7"}
    assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}, headers=other).status_code == 200


def test_unknown_usernames_and_wrong_passwords_look_the_same(admin):
    c = TestClient(main.app)
    a = c.post("/api/auth/login", json={"username": "owner", "password": "wrong-password"}, headers={"X-Forwarded-For": "192.0.2.1"})
    b = c.post("/api/auth/login", json={"username": "no-such-user", "password": "wrong-password"}, headers={"X-Forwarded-For": "192.0.2.1"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


# ---------- admin-only things ----------

def test_only_an_admin_sees_backups_and_users(admin):
    user = new_user(admin)
    # Calendar sync is per person: each sees only their own settings.
    assert user.get("/api/calendar-sync").json()["url"] == ""
    assert user.get("/api/backup").status_code == 403
    assert user.get("/api/users").status_code == 403
    assert admin.get("/api/calendar-sync").status_code == 200


def test_setup_cannot_be_run_again(admin):
    r = TestClient(main.app).post("/api/auth/setup", json={"username": "intruder", "password": PASSWORD})
    assert r.status_code == 403


def test_nothing_works_without_logging_in():
    c = TestClient(main.app)
    for method, path in [("get", "/api/clients"), ("get", "/api/tours"), ("get", "/api/tours/summary"),
                         ("get", "/api/expenses"), ("get", "/api/earnings/compare?start=2026-01-01T00:00:00Z&end=2026-02-01T00:00:00Z"),
                         ("get", "/api/csv/clients"), ("get", "/api/search?q=a"), ("post", "/api/tours"),
                         ("get", "/api/appointments/test-costs"), ("get", "/api/safety")]:
        assert getattr(c, method)(path).status_code == 401, path


# ---------- one user's records are invisible to another ----------

def test_another_user_cannot_reach_any_of_my_records(admin):
    me, them = new_user(admin), new_user(admin)
    client = me.post("/api/clients", json={"name": "Private Person", "birthday": "1990-01-02"}).json()
    note = me.post(f"/api/clients/{client['id']}/notes", json={"body": "secret"}).json()
    appt = me.post("/api/appointments", json={"client_id": client["id"], "service_type": "S", "duration_minutes": 60,
                                              "scheduled_date": "2043-01-05T20:00:00Z", "rate": 100}).json()
    tour = me.post("/api/tours", json={"name": "Mine", "start_date": "2043-01-04", "end_date": "2043-01-06",
                                       "starts_at": "2043-01-04T00:00:00Z", "ends_at": "2043-01-07T00:00:00Z",
                                       "room_rent_per_day": 50}).json()
    test = me.post("/api/appointments", json={"kind": "test", "test_type": "weekly", "cost": 60, "duration_minutes": 30,
                                              "scheduled_date": "2043-01-05T10:00:00Z", "tour_id": tour["id"]}).json()
    expense = me.post("/api/expenses", json={"description": "Mine", "amount": 10}).json()

    reads = [f"/api/clients/{client['id']}", f"/api/clients/{client['id']}/summary", f"/api/appointments/{appt['id']}",
             f"/api/appointments/{test['id']}", f"/api/tours/{tour['id']}", f"/api/tours/{tour['id']}/summary"]
    for path in reads:
        assert them.get(path).status_code == 404, path
    for path in ("/api/clients", "/api/appointments", "/api/expenses", "/api/tours", "/api/tours/summary"):
        assert them.get(path).json() == [], path
    assert them.get("/api/search", params={"q": "Private"}).json()["count"] == 0
    assert "Private" not in them.get("/api/csv/clients").text

    # Changing or deleting my things, or pointing their own records at them, gets nowhere.
    assert them.put(f"/api/clients/{client['id']}", json={"name": "Hacked"}).status_code == 404
    assert them.put(f"/api/tours/{tour['id']}", json={"name": "Hacked", "start_date": "2043-01-04", "end_date": "2043-01-06",
                                                       "starts_at": "2043-01-04T00:00:00Z", "ends_at": "2043-01-07T00:00:00Z"}).status_code == 404
    assert them.put(f"/api/appointments/{appt['id']}/status", params={"status": "cancelled"}).status_code == 404
    assert them.post(f"/api/appointments/{appt['id']}/mark-paid").status_code == 404
    assert them.put(f"/api/expenses/{expense['id']}", json={"description": "x", "amount": 1}).status_code == 404
    assert them.post(f"/api/clients/{client['id']}/notes", json={"body": "x"}).status_code == 404
    assert them.post("/api/appointments", json={"client_id": client["id"], "service_type": "S", "duration_minutes": 60,
                                                "scheduled_date": "2043-02-01T20:00:00Z"}).status_code == 400
    assert them.post("/api/expenses", json={"description": "x", "amount": 1, "tour_id": tour["id"]}).status_code == 400
    assert them.post("/api/expenses", json={"description": "x", "amount": 1, "client_id": client["id"]}).status_code == 400
    assert them.post("/api/appointments", json={"kind": "test", "test_type": "weekly", "duration_minutes": 30,
                                                "scheduled_date": "2043-02-01T10:00:00Z", "tour_id": tour["id"]}).status_code == 400
    for path in (f"/api/clients/{client['id']}/notes/{note['id']}", f"/api/appointments/{appt['id']}",
                 f"/api/tours/{tour['id']}", f"/api/expenses/{expense['id']}", f"/api/clients/{client['id']}"):
        them.delete(path)

    # Everything of mine is still there, unchanged.
    summary = me.get(f"/api/clients/{client['id']}/summary").json()
    assert summary["client"]["name"] == "Private Person" and [n["body"] for n in summary["notes"]] == ["secret"]
    assert me.get(f"/api/appointments/{appt['id']}").json()["status"] == "scheduled"
    assert me.get(f"/api/appointments/{appt['id']}").json()["amount_paid"] == 0
    assert me.get(f"/api/tours/{tour['id']}").json()["name"] == "Mine"
    assert len([e for e in me.get("/api/expenses").json() if e["category"] == "room_rent"]) == 3
    assert any(e["id"] == expense["id"] and e["description"] == "Mine" for e in me.get("/api/expenses").json())


def test_text_that_looks_like_code_is_stored_as_plain_text(admin):
    """SQL or HTML typed into a field is saved and returned exactly as typed, never run."""
    user = new_user(admin)
    tricky = "Robert'); DROP TABLE clients;-- <script>alert(1)</script> %_\\"
    c = user.post("/api/clients", json={"name": tricky, "food_preferences": tricky}).json()
    assert c["name"] == tricky and c["food_preferences"] == tricky
    assert user.get("/api/search", params={"q": "%"}).json()["count"] == 1        # % is matched literally
    assert user.get("/api/clients", params={"search": "_"}).json()[0]["name"] == tricky
    assert len(user.get("/api/clients").json()) == 1
