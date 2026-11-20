"""The busy link: times only, off until made, and gone when replaced or turned off.
Run with:  docker compose -f docker-compose.dev.yml run --rm tests"""
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


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    name = "busy-" + uuid.uuid4().hex[:8]
    r = admin.post("/api/users", json={"username": name, "password": PASSWORD})
    assert r.status_code == 201, r.text
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def soon(days: int, hour: int = 15) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


def book(api, when: datetime, **fields):
    client = api.post("/api/clients", json={"name": "Secret Person"}).json()
    r = api.post("/api/appointments", json={"client_id": client["id"], "service_type": "Secret Service", "duration_minutes": 90,
                                            "scheduled_date": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "notes": "private note",
                                            "location": "Hotel Secret", **fields})
    assert r.status_code == 201, r.text
    return r.json()


def test_off_until_made_and_only_times_are_in_it(api):
    assert api.get("/api/busy-link").json() == {"on": False, "path": None, "read_at": None, "days_back": 31, "days_ahead": 365}
    when = soon(3)
    book(api, when)
    book(api, soon(4), status="cancelled")
    book(api, soon(500))    # further off than the link reaches
    day = soon(10).date()
    tour = api.post("/api/tours", json={"name": "Secret City", "location": "Secret Street", "notes": "private note",
                                        "start_date": day.isoformat(), "end_date": (day + timedelta(days=2)).isoformat(),
                                        "starts_at": f"{day.isoformat()}T00:00:00Z",
                                        "ends_at": f"{(day + timedelta(days=3)).isoformat()}T00:00:00Z"})
    assert tour.status_code == 201, tour.text

    made = api.put("/api/busy-link").json()
    assert made["on"] and made["path"].startswith("/busy/") and made["path"].endswith(".ics")
    assert api.put("/api/busy-link").json()["path"] == made["path"]    # asking again keeps the same link

    # A calendar app has no session: the address alone is the key.
    reader = TestClient(main.app)
    answer = reader.get(made["path"])
    assert answer.status_code == 200 and answer.headers["content-type"].startswith("text/calendar")
    assert answer.headers["cache-control"] == "private, no-store"
    text = answer.text
    assert text.count("BEGIN:VEVENT") == 2
    assert f"DTSTART:{when.strftime('%Y%m%dT%H%M%SZ')}" in text
    assert f"DTEND:{(when + timedelta(minutes=90)).strftime('%Y%m%dT%H%M%SZ')}" in text and "SUMMARY:Busy" in text
    assert f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}" in text and "SUMMARY:Away" in text
    assert f"DTEND;VALUE=DATE:{(day + timedelta(days=3)).strftime('%Y%m%d')}" in text
    # Nothing about who, what, where or why.
    for word in ("Secret", "private", "Hotel", "Session", "DESCRIPTION", "LOCATION"):
        assert word not in text
    assert api.get("/api/busy-link").json()["read_at"]


def test_time_off_is_off_and_someone_else_sees_only_their_own(api, admin):
    day = soon(5).date().isoformat()
    r = api.post("/api/tours", json={"kind": "time_off", "time_off_type": "vacation", "name": "Secret Beach", "start_date": day,
                                     "end_date": day, "starts_at": f"{day}T00:00:00Z", "ends_at": f"{day}T23:59:00Z"})
    assert r.status_code == 201, r.text
    mine = api.put("/api/busy-link").json()["path"]
    text = TestClient(main.app).get(mine).text
    assert "SUMMARY:Off" in text and "Secret" not in text and "Vacation" not in text

    theirs = admin.put("/api/busy-link").json()["path"]
    assert theirs != mine and "SUMMARY:Off" not in TestClient(main.app).get(theirs).text
    admin.delete("/api/busy-link")


def test_a_new_link_stops_the_old_one_and_off_forgets_it(api):
    reader = TestClient(main.app)
    assert api.post("/api/busy-link/renew").status_code == 404
    first = api.put("/api/busy-link").json()["path"]
    second = api.post("/api/busy-link/renew").json()["path"]
    assert second != first
    assert [reader.get(first).status_code, reader.get(second).status_code] == [404, 200]
    # A guess at someone's link, a link with the right person and the wrong key, and nonsense: all simply not there.
    person = second.split("/")[2].split("-")[0]
    for wrong in (f"/busy/{person}-{'0' * 64}.ics", f"/busy/999999-{second.split('-')[1]}", "/busy/hello.ics"):
        assert reader.get(wrong).status_code == 404
    assert api.delete("/api/busy-link").json() == {"on": False, "path": None, "read_at": None, "days_back": 31, "days_ahead": 365}
    assert reader.get(second).status_code == 404
    assert TestClient(main.app).get("/api/busy-link").status_code == 401
