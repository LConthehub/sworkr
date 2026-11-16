"""Push notifications with ntfy: settings that protect privacy, what gets sent and when, and nothing sent twice.
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
import ntfy  # noqa: E402

PASSWORD = "correct-horse-battery"
TOPIC = "k3j4h5g6f7d8s9a0q1w2"           # long and random, as the public server needs
GOOD = {"enabled": True, "server": "https://ntfy.sh", "topic": TOPIC, "lead_minutes": 60, "digest_hour": 9, "details": False, "timezone": "UTC"}


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "nt-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    return new_user(admin)


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(ntfy, "publish", lambda s, title, message, priority=3, tags=None: out.append((title, message, s["topic"], s.get("token"))))
    return out


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json() if r.content else None


def save(api, **more):
    return ok(api.put("/api/ntfy/settings", json={**GOOD, **more}))


def pass_at(api, when):
    """One pass for this person only (the other tests' people share the database)."""
    return ntfy.run_once(main.get_db, when, only=api.get("/api/auth/status").json()["user"]["id"])


NOW = datetime(2030, 6, 10, 15, 0, tzinfo=timezone.utc)      # a Monday, 3 pm UTC


def book(api, name, minutes_from_now, service="One hour", kind="client", **more):
    c = ok(api.post("/api/clients", json={"name": name}), 201) if kind == "client" else None
    body = {"service_type": service, "duration_minutes": 60, "scheduled_date": (NOW + timedelta(minutes=minutes_from_now)).isoformat(), **more}
    if kind == "test":
        body.update({"kind": "test", "test_type": "weekly", "cost": 0})
    else:
        body["client_id"] = c["id"]
    return ok(api.post("/api/appointments", params={"warn": "false"}, json=body), 201)


def test_settings_protect_privacy(api):
    s = save(api, token="  tk_secret_token  ")
    assert (s["enabled"], s["topic"], s["has_token"], s["public_server"], s["lead_minutes"], s["digest_hour"]) == (True, TOPIC, True, True, 60, 9)
    assert "tk_secret_token" not in str(s) and "token" not in s
    db = main.get_db()
    try:
        stored = db.execute("SELECT value FROM user_settings WHERE key = 'ntfy_token'").fetchall()
    finally:
        db.close()
    assert stored and all(r["value"].startswith("sealed:") for r in stored)               # sealed in the database
    assert save(api)["has_token"] is True                                                  # blank keeps it
    assert save(api, clear_token=True)["has_token"] is False

    # a short topic on the public server is a topic anyone could guess
    assert api.put("/api/ntfy/settings", json={**GOOD, "topic": "mybookings"}).status_code == 400
    assert api.put("/api/ntfy/settings", json={**GOOD, "topic": "has spaces and a lot of other bad characters"}).status_code == 400
    assert api.put("/api/ntfy/settings", json={**GOOD, "topic": ""}).status_code == 400
    # your own server can have a short one
    own = save(api, server="https://ntfy.example.org/", topic="me")
    assert (own["server"], own["public_server"]) == ("https://ntfy.example.org", False)
    # https for anything on the internet; plain http only on this computer or a home network
    assert api.put("/api/ntfy/settings", json={**GOOD, "server": "http://ntfy.example.org"}).status_code == 400
    for fine in ("http://localhost:8081", "http://192.168.1.20", "http://nas.local", "http://ntfy"):
        assert save(api, server=fine, topic="me")["server"] == fine
    for bad in ("ftp://ntfy.sh", "https://user:pw@ntfy.sh", "https://ntfy.sh?x=1", "javascript:alert(1)"):
        assert api.put("/api/ntfy/settings", json={**GOOD, "server": bad}).status_code == 400, bad
    assert api.put("/api/ntfy/settings", json={**GOOD, "lead_minutes": 7}).status_code == 400
    assert api.put("/api/ntfy/settings", json={**GOOD, "digest_hour": 24}).status_code == 400
    assert save(api, digest_hour=None)["digest_hour"] is None and save(api, timezone="Not/AZone")["timezone"] == "UTC"


def test_a_saved_token_is_never_sent_to_a_different_server(api, sent):
    save(api, server="https://ntfy.example.org", topic="me", token="tk_for_my_server")
    r = api.put("/api/ntfy/settings", json={**GOOD, "server": "https://evil.example.net", "topic": "me"})
    assert r.status_code == 400 and "enter the access token again" in r.text
    assert save(api, server="https://evil.example.net", topic="me", token="a new one typed in")["has_token"] is True
    assert save(api, server="https://ntfy.example.org", topic="me", clear_token=True)["has_token"] is False


def test_a_test_notification_and_its_failures(api, monkeypatch):
    assert api.post("/api/ntfy/test").status_code == 400                                   # nothing saved yet
    save(api)
    calls = []
    monkeypatch.setattr(ntfy, "publish", lambda s, title, message, priority=3, tags=None: calls.append(s["topic"]))
    assert ok(api.post("/api/ntfy/test")) == {"ok": True} and calls == [TOPIC]

    def refuse(*a, **k):
        raise ntfy.NtfyError("The server turned it down")
    monkeypatch.setattr(ntfy, "publish", refuse)
    r = api.post("/api/ntfy/test")
    assert r.status_code == 502 and "turned it down" in r.text
    assert TestClient(main.app).post("/api/ntfy/test").status_code == 401


def test_publish_speaks_ntfys_json_and_maps_errors(monkeypatch):
    seen = {}

    class Reply:
        def __init__(self, code):
            self.status_code = code

    def fake_post(url, content=None, headers=None, timeout=None, follow_redirects=None):
        seen.update(url=url, body=__import__("json").loads(content), headers=headers, redirects=follow_redirects)
        return Reply(seen.get("code", 200))
    monkeypatch.setattr(ntfy.httpx, "post", fake_post)
    ntfy.publish({"server": "https://ntfy.example.org", "topic": "t", "token": "tk_x"}, "Hello", "World é ✓", tags=["calendar"])
    assert seen["url"] == "https://ntfy.example.org" and seen["body"] == {"topic": "t", "title": "Hello", "message": "World é ✓", "priority": 3, "tags": ["calendar"]}
    assert seen["headers"]["Authorization"] == "Bearer tk_x" and seen["redirects"] is False      # a redirect could carry the token elsewhere
    for code, words in ((401, "access token"), (429, "too many"), (500, "500")):
        seen["code"] = code
        with pytest.raises(ntfy.NtfyError, match=words):
            ntfy.publish({"server": "https://ntfy.example.org", "topic": "t", "token": None}, "a", "b")

    def down(*a, **k):
        raise ntfy.httpx.ConnectError("no route")
    monkeypatch.setattr(ntfy.httpx, "post", down)
    with pytest.raises(ntfy.NtfyError, match="Couldn't reach ntfy.example.org"):
        ntfy.publish({"server": "https://ntfy.example.org", "topic": "t"}, "a", "b")


def test_a_heads_up_before_a_booking_is_sent_once_and_names_no_one(api, sent):
    save(api, digest_hour=None)
    soon = book(api, "Jordan Avery", 45)
    book(api, "Later", 200)                                          # outside the hour
    book(api, "Done already", 30, status="completed")
    book(api, "Past", -20)
    assert pass_at(api, NOW) == 1
    assert sent == [("Coming up", "A booking starts at 3:45 PM", TOPIC, None)]
    assert "Jordan" not in str(sent)
    assert pass_at(api, NOW + timedelta(minutes=1)) == 0                  # not again
    assert pass_at(api, NOW + timedelta(minutes=150)) == 1                                  # the later one, when its hour comes
    # moved to another time: it's news again
    ok(api.put(f"/api/appointments/{soon['id']}", params={"warn": "false"}, json={
        "client_id": soon["client_id"], "service_type": "One hour", "duration_minutes": 60, "scheduled_date": (NOW + timedelta(minutes=150)).isoformat()}))
    assert pass_at(api, NOW + timedelta(minutes=125)) == 1


def test_names_only_when_asked_and_health_tests_say_so(api, sent):
    save(api, digest_hour=None, details=True)
    book(api, "Jordan Avery", 20, service="Dinner date")
    book(api, None, 40, kind="test")
    assert pass_at(api, NOW) == 2
    assert sorted(m for _, m, _, _ in sent) == ["A health test at 3:40 PM", "Jordan Avery at 3:20 PM, Dinner date"]


def test_the_daily_summary_once_a_day_only_when_there_is_something_to_say(api, sent):
    save(api, lead_minutes=0, digest_hour=9)
    morning = datetime(2030, 6, 10, 8, 0, tzinfo=timezone.utc)
    assert pass_at(api, morning) == 0                                    # too early
    assert pass_at(api, morning + timedelta(hours=1)) == 0 and sent == []   # 9 am, nothing planned: nothing to say
    ok(api.post("/api/tasks", json={"title": "Send the release", "due_date": "2030-06-10"}), 201)
    assert pass_at(api, morning + timedelta(hours=2)) == 0               # today's summary was already settled at 9
    next_day = datetime(2030, 6, 11, 9, 30, tzinfo=timezone.utc)
    ok(api.post("/api/tasks", json={"title": "Another", "due_date": "2030-06-11"}), 201)
    book(api, "Avery", 24 * 60 + 5 * 60)                            # tomorrow 8 pm
    ok(api.post("/api/inquiries", json={"name": "Someone new"}), 201)
    assert pass_at(api, next_day) == 1
    title, message, topic, token = sent[0]
    assert (title, topic) == ("Today", TOPIC)
    assert message.splitlines() == ["1 booking today", "2 tasks due", "1 inquiry to answer"]
    assert "Avery" not in message
    assert pass_at(api, next_day + timedelta(hours=3)) == 0              # once a day


def test_the_summary_covers_what_each_part_of_sworkr_knows(api, sent):
    save(api, lead_minutes=0, digest_hour=0, timezone="America/New_York")
    ok(api.put("/api/booking-policy", json={"deposit_percent": 25, "late_cancel_hours": 24, "late_cancel_fee_percent": 50, "no_show_fee_percent": 100}))
    book(api, "Needs a deposit", 60 * 30, rate=800, amount_paid=0)
    ok(api.post("/api/inquiries", json={"name": "A"}), 201)
    ok(api.post("/api/inquiries", json={"name": "B"}), 201)
    ok(api.post("/api/customs", json={"buyer": "x", "title": "y", "due_date": "2030-06-01"}), 201)
    ok(api.post("/api/shoots", json={"title": "Soon", "shoot_date": "2030-06-12"}), 201)
    ok(api.post("/api/posts", json={"platform": "X", "status": "scheduled", "scheduled_at": "2030-06-10T12:00:00Z"}), 201)
    ok(api.post("/api/listings", json={"site": "Tryst", "end_date": "2030-06-11"}), 201)
    ok(api.post("/api/documents", json={"name": "Card", "expires_on": "2030-06-20"}), 201)
    assert pass_at(api, NOW) == 1
    # (a document also makes its own reminder task, which is already due)
    assert set(sent[0][1].splitlines()) == {"1 task due", "1 post to put up", "1 deposit to collect", "2 inquiries to answer", "1 custom late",
                                            "1 shoot in the next 3 days", "1 ad running out", "1 document running out soon"}


def test_the_hour_is_in_the_persons_own_time_zone(api, sent):
    save(api, lead_minutes=0, digest_hour=9, timezone="Asia/Tokyo")
    ok(api.post("/api/tasks", json={"title": "Task", "due_date": "2030-06-10"}), 201)
    # 9 am in Tokyo on the 10th is 00:00 UTC; 8:59 there is still the morning before
    assert pass_at(api, datetime(2030, 6, 9, 23, 59, tzinfo=timezone.utc)) == 0 and sent == []
    assert pass_at(api, datetime(2030, 6, 10, 0, 1, tzinfo=timezone.utc)) == 1


def test_a_down_server_is_retried_and_nothing_is_marked_sent(api, monkeypatch):
    save(api, digest_hour=None)
    book(api, "Avery", 30)
    attempts = []

    def flaky(s, title, message, priority=3, tags=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise ntfy.NtfyError("down")
    monkeypatch.setattr(ntfy, "publish", flaky)
    assert pass_at(api, NOW) == 0
    assert pass_at(api, NOW + timedelta(minutes=1)) == 1 and len(attempts) == 2


def test_people_only_notify_themselves_and_the_demo_never_sends(api, admin, sent, monkeypatch):
    save(api, digest_hour=None)
    book(api, "Mine", 30)
    other = new_user(admin)
    assert ok(other.get("/api/ntfy/settings"))["enabled"] is False and ok(other.get("/api/ntfy/settings"))["topic"] == ""
    assert pass_at(api, NOW) == 1 and [t for _, _, t, _ in sent] == [TOPIC]
    import demo
    monkeypatch.setattr(demo, "ENABLED", True)
    assert api.put("/api/ntfy/settings", json=GOOD).status_code == 403 and api.post("/api/ntfy/test").status_code == 403
    assert ok(api.get("/api/ntfy/settings"))["demo"] is True
    assert TestClient(main.app).get("/api/ntfy/settings").status_code == 401
