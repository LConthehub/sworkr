"""Tests for personas: the names someone works under.
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
    name = "n-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)

def test_personas_can_be_added_renamed_and_deleted(api):
    lux = ok(api.post("/api/personas", json={"name": "Lux"}), 201)
    assert lux["color"].startswith("#") and not lux["archived"]
    assert api.post("/api/personas", json={"name": "lux"}).status_code == 409
    assert api.post("/api/personas", json={"name": " "}).status_code == 400
    ok(api.put(f"/api/personas/{lux['id']}", json={"name": "Lux Noir", "archived": True}))
    assert [p["name"] for p in ok(api.get("/api/personas"))] == ["Lux Noir"]
    assert api.delete(f"/api/personas/{lux['id']}").status_code == 204
    assert ok(api.get("/api/personas")) == []


def test_contacts_places_and_posts_name_a_persona(api):
    lux = ok(api.post("/api/personas", json={"name": "Lux"}), 201)
    client = ok(api.post("/api/clients", json={"name": "Sam", "persona_id": lux["id"]}), 201)
    assert client["persona_id"] == lux["id"]
    # Saving without persona_id (an older app, an import) leaves it alone; null clears it.
    assert ok(api.put(f"/api/clients/{client['id']}", json={"name": "Sam R"}))["persona_id"] == lux["id"]
    assert ok(api.put(f"/api/clients/{client['id']}", json={"name": "Sam R", "persona_id": None}))["persona_id"] is None
    place = ok(api.post("/api/income-sources", json={"name": "OF", "kind": "platform", "persona_id": lux["id"]}), 201)
    assert place["persona_id"] == lux["id"]
    post = ok(api.post("/api/posts", json={"platform": "OF", "persona_id": lux["id"]}), 201)
    assert post["persona_id"] == lux["id"]
    assert ok(api.get("/api/personas"))[0]["places"] == 1

    # Deleting the persona keeps everything, without it.
    assert api.delete(f"/api/personas/{lux['id']}").status_code == 204
    assert ok(api.get(f"/api/clients/{client['id']}"))["persona_id"] is None
    assert next(s for s in ok(api.get("/api/income-sources")) if s["id"] == place["id"])["persona_id"] is None


def test_personas_are_private(api, admin):
    lux = ok(api.post("/api/personas", json={"name": "Lux"}), 201)
    assert admin.post("/api/clients", json={"name": "x", "persona_id": lux["id"]}).status_code == 400
    assert admin.put(f"/api/personas/{lux['id']}", json={"name": "Mine"}).status_code == 404
    assert lux["id"] not in [p["id"] for p in ok(admin.get("/api/personas"))]


def test_earnings_compared_by_persona(api):
    lux = ok(api.post("/api/personas", json={"name": "Lux"}), 201)
    kit = ok(api.post("/api/personas", json={"name": "Kit"}), 201)
    of = ok(api.post("/api/income-sources", json={"name": "OF", "kind": "platform", "persona_id": kit["id"]}), 201)
    ok(api.post("/api/income", json={"source_id": of["id"], "date": "2044-03-10T20:00:00Z", "gross": 100, "fees": 20}), 201)
    ok(api.post("/api/income", json={"date": "2044-03-11T20:00:00Z", "gross": 50}), 201)
    sam = ok(api.post("/api/clients", json={"name": "Sam", "persona_id": lux["id"]}), 201)
    ok(api.post("/api/appointments", json={"client_id": sam["id"], "service_type": "Dinner", "duration_minutes": 60,
                                           "scheduled_date": "2044-03-12T20:00:00Z", "status": "completed",
                                           "rate": 400, "amount_paid": 400}), 201)
    r = ok(api.get("/api/earnings/by-source", params={"start": "2044-03-01T00:00:00Z", "end": "2044-04-01T00:00:00Z",
                                                      "group": "persona"}))
    assert {row["label"]: row["net"] for row in r["rows"]} == {"Lux": 400, "Kit": 80, "No persona": 50}


def test_contacts_can_be_listed_by_persona(api):
    lux = ok(api.post("/api/personas", json={"name": "Lux"}), 201)
    ok(api.post("/api/clients", json={"name": "Sam", "persona_id": lux["id"]}), 201)
    ok(api.post("/api/clients", json={"name": "Ana"}), 201)
    assert [c["name"] for c in ok(api.get("/api/clients", params={"persona_id": lux["id"]}))] == ["Sam"]
    assert [c["name"] for c in ok(api.get("/api/clients", params={"persona_id": 0}))] == ["Ana"]
