"""Health tests on each person's own schedule: kinds of test with their own interval and cost.
Run with:  docker compose run --rm tests"""
import os
import dbfile as sqlite3  # noqa: E402  (the encrypted engine, like the app)
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
import migrations  # noqa: E402

PASSWORD = "correct-horse-battery"
NOW = datetime.now(timezone.utc)
at = lambda days: (NOW + timedelta(days=days)).isoformat()   # noqa: E731


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "tk-" + uuid.uuid4().hex[:8]
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


def book_test(api, kind, days, cost=None, status="completed"):
    return ok(api.post("/api/appointments", params={"warn": "false"}, json={
        "kind": "test", "test_type": kind, "duration_minutes": 30, "scheduled_date": at(days), "cost": cost, "status": status}), 201)


def by_key(api):
    return {k["key"]: k for k in ok(api.get("/api/test-kinds"))}


def test_everyone_starts_with_three_and_can_change_them(api):
    kinds = ok(api.get("/api/test-kinds"))
    assert [(k["key"], k["label"], k["every_days"], k["cost"], k["starter"]) for k in kinds] == [
        ("weekly", "Weekly test", 7, None, True), ("monthly", "Monthly test", 30, None, True), ("yearly", "Yearly test", 365, None, True)]
    weekly = kinds[0]
    changed = ok(api.put(f"/api/test-kinds/{weekly['id']}", json={"label": " County  panel ", "every_days": 14, "cost": 85}))
    assert (changed["label"], changed["every_days"], changed["cost"], changed["key"]) == ("County panel", 14, 85, "weekly")
    assert book_test(api, "weekly", -1)["service_type"] == "County panel"          # a new test takes the new name

    own = ok(api.post("/api/test-kinds", json={"label": "Quarterly bloodwork", "every_days": 90, "cost": 210}), 201)
    assert own["key"] not in ("weekly", "monthly", "yearly") and own["starter"] is False
    booked = book_test(api, own["key"], -2, cost=199)
    assert booked["service_type"] == "Quarterly bloodwork" and booked["test_type"] == own["key"]
    assert ok(api.get("/api/appointments/test-costs")) == {"weekly": 85, "monthly": None, "yearly": None, own["key"]: 199}   # last cost is remembered
    [expense] = ok(api.get("/api/expenses"))
    assert (expense["amount"], expense["category"], expense["test_type"]) == (199, "medical", own["key"])

    assert api.post("/api/test-kinds", json={"label": " "}).status_code == 400
    assert api.post("/api/test-kinds", json={"label": "x", "every_days": 0}).status_code == 400
    assert api.post("/api/test-kinds", json={"label": "x", "cost": -1}).status_code == 400
    assert api.put("/api/test-kinds/999999", json={"label": "x"}).status_code == 404
    assert api.post("/api/appointments", json={"kind": "test", "test_type": "made-up", "duration_minutes": 30, "scheduled_date": at(1)}).status_code == 400
    assert api.post("/api/appointments", json={"kind": "test", "duration_minutes": 30, "scheduled_date": at(1)}).status_code == 400


def test_when_the_next_one_is_due(api):
    kinds = by_key(api)
    assert kinds["weekly"]["state"] == "none" and kinds["weekly"]["next_due"] is None       # never done: nothing to count from
    book_test(api, "weekly", -10)
    book_test(api, "monthly", -28)
    book_test(api, "yearly", -100)
    kinds = by_key(api)
    assert (kinds["weekly"]["state"], kinds["weekly"]["due_in_days"]) == ("overdue", -3)
    assert (kinds["monthly"]["state"], kinds["monthly"]["due_in_days"]) == ("soon", 2)
    assert (kinds["yearly"]["state"], kinds["yearly"]["due_in_days"]) == ("ok", 265)

    book_test(api, "weekly", 1, status="scheduled")                 # booked, but after it was due: still overdue
    assert by_key(api)["weekly"]["state"] == "overdue"
    book_test(api, "monthly", 1, status="scheduled")                # booked before it's due
    assert by_key(api)["monthly"]["state"] == "booked"

    # the same history under different local rules
    ok(api.put(f"/api/test-kinds/{kinds['weekly']['id']}", json={"label": "Every 2 weeks", "every_days": 14}))
    assert (by_key(api)["weekly"]["state"], by_key(api)["weekly"]["due_in_days"]) == ("booked", 4)
    ok(api.put(f"/api/test-kinds/{kinds['yearly']['id']}", json={"label": "When I choose", "every_days": None}))
    assert by_key(api)["yearly"]["state"] == "none"


def test_removing_a_kind_keeps_the_history(api):
    unused = ok(api.post("/api/test-kinds", json={"label": "Never used"}), 201)
    used = ok(api.post("/api/test-kinds", json={"label": "Used once", "every_days": 10}), 201)
    book_test(api, used["key"], -1, cost=40)
    kinds = by_key(api)
    for k in (unused, used, kinds["yearly"]):
        ok(api.delete(f"/api/test-kinds/{k['id']}"), 204)
    after = by_key(api)
    assert unused["key"] not in after                                        # never used: gone
    assert after[used["key"]]["archived"] is True and after[used["key"]]["state"] == "none"   # used: hidden, name kept
    assert after["yearly"]["archived"] is True                               # a starter is only ever hidden
    assert ok(api.put(f"/api/test-kinds/{after['yearly']['id']}", json={"label": "Yearly test", "every_days": 365}))["archived"] is False


def test_a_places_doctor_can_be_any_kind(api):
    own = ok(api.post("/api/test-kinds", json={"label": "House doctor, twice a week", "every_days": 4, "cost": 60}), 201)
    place = ok(api.post("/api/income-sources", json={"name": "The Ranch", "kind": "brothel"}), 201)
    charge = ok(api.post(f"/api/income-sources/{place['id']}/charges", json={"label": "Doctor", "amount": 60, "cadence": "per_week", "test_type": own["key"]}), 201)
    assert charge["test_type"] == own["key"] and charge["category"] == "medical"
    assert api.post(f"/api/income-sources/{place['id']}/charges", json={"label": "Doctor", "cadence": "per_week", "test_type": "made-up"}).status_code == 400
    ok(api.delete(f"/api/test-kinds/{own['id']}"), 204)
    assert by_key(api)[own["key"]]["archived"] is True                        # a place still uses it: hidden, not removed


def test_people_only_see_their_own(api, admin):
    own = ok(api.post("/api/test-kinds", json={"label": "Mine"}), 201)
    other = new_user(admin)
    assert own["key"] not in by_key(other) and len(by_key(other)) == 3
    assert other.put(f"/api/test-kinds/{own['id']}", json={"label": "Theirs"}).status_code == 404
    other.delete(f"/api/test-kinds/{own['id']}")
    assert own["key"] in by_key(api)
    assert other.post("/api/appointments", json={"kind": "test", "test_type": own["key"], "duration_minutes": 30, "scheduled_date": at(1)}).status_code == 400
    assert TestClient(main.app).get("/api/test-kinds").status_code == 401


def test_upgrading_keeps_place_charges_and_lets_them_use_any_kind(tmp_path, monkeypatch):
    path = str(tmp_path / "sworkr.db")
    monkeypatch.setattr(migrations, "LATEST", 28)
    monkeypatch.setattr(migrations, "MIGRATIONS", [m for m in migrations.MIGRATIONS if m[0] <= 28])
    assert migrations.run(path) == 28
    db = sqlite3.connect(path)
    db.execute("INSERT INTO users (id, username, password_hash, is_admin, created_at) VALUES (1, 'u', 'x', 1, 'now')")
    db.execute("INSERT INTO income_sources (id, owner_id, name, created_at, updated_at) VALUES (1, 1, 'Ranch', 'now', 'now')")
    db.execute("INSERT INTO place_charges (owner_id, source_id, label, amount, cadence, category, test_type, created_at, updated_at) "
               "VALUES (1, 1, 'Doctor', 60, 'per_week', 'medical', 'weekly', 'now', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO place_charges (owner_id, source_id, label, cadence, test_type, created_at, updated_at) "
                   "VALUES (1, 1, 'Other', 'per_week', 't123', 'now', 'now')")
    db.commit()
    db.close()
    monkeypatch.undo()
    assert migrations.run(path) == migrations.LATEST
    db = sqlite3.connect(path)
    assert db.execute("SELECT label, amount, test_type FROM place_charges").fetchall() == [("Doctor", 60.0, "weekly")]
    db.execute("INSERT INTO place_charges (owner_id, source_id, label, cadence, test_type, created_at, updated_at) "
               "VALUES (1, 1, 'Other', 'per_week', 't123', 'now', 'now')")
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    db.close()
