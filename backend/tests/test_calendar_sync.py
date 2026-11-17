"""Calendar sync tests: against a fake calendar account, and the CalDAV discovery against fake Nextcloud and
iCloud-style servers. Run with:  docker compose run --rm tests"""
import os
import sys
import tempfile
import uuid
import base64

import httpx
import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import calendar_sync  # noqa: E402
import demo  # noqa: E402
import main  # noqa: E402

PASSWORD = "correct-horse-battery"
SETTINGS = {"enabled": True, "url": "https://cloud.example.com/index.php/apps/calendar/",
            "username": "lc", "app_password": "abcde-fghij-klmno-pqrst-uvwxy", "discreet": False}


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    """Every test gets its own person (each person has their own calendar settings)."""
    name = "cal-" + uuid.uuid4().hex[:8]
    r = admin.post("/api/users", json={"username": name, "password": PASSWORD})
    assert r.status_code == 201, r.text
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    c.user_id = r.json()["id"]
    return c


class FakeAccount:
    """Stands in for CalDav: keeps each person's calendar in a dict {(kind, id): ics}."""

    def __init__(self, tasks=True):
        self.items = {}
        self.fail = None
        self.events_url = "https://cal.example/sworkr/"
        self.tasks_url = "https://cal.example/sworkr-tasks/" if tasks else calendar_sync.NO_TASKS

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    @property
    def tasks_supported(self):
        return self.tasks_url != calendar_sync.NO_TASKS

    def prepare(self):
        if self.fail:
            raise calendar_sync.SyncError(self.fail)

    renamed = None

    def rename(self, url, name):
        self.renamed = {**(self.renamed or {}), url: name}
        return True

    events_name, tasks_name = calendar_sync.EVENTS_NAME, calendar_sync.TASKS_NAME

    def list_items(self):
        return set(self.items)

    def put(self, kind, item_id, ics):
        if kind == "task" and not self.tasks_supported:
            return
        self.items[(kind, item_id)] = ics.decode()

    def delete(self, kind, item_id):
        self.items.pop((kind, item_id), None)


@pytest.fixture
def accounts(monkeypatch):
    """One fake account per person."""
    by_user = {}
    def connect(db, owner_id):
        account = by_user.setdefault(owner_id, FakeAccount())
        account.events_name = calendar_sync.get_setting(db, owner_id, "cal_events_name") or calendar_sync.EVENTS_NAME
        account.tasks_name = calendar_sync.get_setting(db, owner_id, "cal_tasks_name") or calendar_sync.TASKS_NAME
        return account
    monkeypatch.setattr(calendar_sync, "_connect", connect)
    return by_user


@pytest.fixture
def api(admin):
    c = new_user(admin)
    assert c.put("/api/calendar-sync", json=SETTINGS).status_code == 200
    return c


def make_appointment(api, client_name="Cal Client", **fields):
    client = api.post("/api/clients", json={"name": client_name}).json()
    body = {"client_id": client["id"], "service_type": "Session", "duration_minutes": 90,
            "scheduled_date": "2030-05-01T15:00:00Z", **fields}
    r = api.post("/api/appointments", json=body)
    assert r.status_code == 201, r.text
    return client, r.json()


def full_sync():
    calendar_sync.run_sync({("all", None, None)})


# ---------- settings ----------

def test_settings_never_send_the_password_back(api):
    status = api.get("/api/calendar-sync").json()
    assert status["enabled"] and status["has_password"] and status["demo"] is False
    assert status["url"] == "https://cloud.example.com"  # pasted calendar page trimmed to the base
    assert "abcde" not in str(status)


def test_blank_password_keeps_the_saved_one(api):
    api.put("/api/calendar-sync", json={**SETTINGS, "app_password": ""})
    db = main.get_db()
    assert calendar_sync.get_setting(db, api.user_id, "cal_password") == SETTINGS["app_password"]
    db.close()


def test_turning_on_needs_all_details(admin):
    c = new_user(admin)
    r = c.put("/api/calendar-sync", json={**SETTINGS, "app_password": None})
    assert r.status_code == 400 and "app password" in r.json()["detail"]


def test_each_person_has_their_own_settings(api, admin):
    other = new_user(admin)
    status = other.get("/api/calendar-sync").json()
    assert status["enabled"] is False and status["url"] == "" and not status["has_password"]


def test_sync_settings_need_login():
    assert TestClient(main.app).get("/api/calendar-sync").status_code == 401


def test_the_demo_refuses_real_accounts(api, monkeypatch):
    monkeypatch.setattr(demo, "ENABLED", True)
    for method, path, body in (("put", "", SETTINGS), ("post", "/test", SETTINGS), ("post", "/sync", None)):
        r = getattr(api, method)(f"/api/calendar-sync{path}", json=body)
        assert r.status_code == 403 and "demo" in r.json()["detail"]
    assert api.get("/api/calendar-sync").json()["demo"] is True


@pytest.mark.parametrize("pasted, expected", [
    ("cloud.example.com", "https://cloud.example.com"),
    ("https://cloud.example.com/", "https://cloud.example.com"),
    ("https://cloud.example.com/index.php/apps/calendar/dayGridMonth/now", "https://cloud.example.com"),
    ("https://example.com/nextcloud/remote.php/dav/", "https://example.com/nextcloud"),
    ("http://192.168.1.5:8080/login", "http://192.168.1.5:8080"),
    ("caldav.icloud.com", "https://caldav.icloud.com"),
])
def test_normalize_url(pasted, expected):
    assert calendar_sync.normalize_url(pasted) == expected


def test_test_connection_reports_the_problem(api, monkeypatch):
    def reject(self):
        raise calendar_sync.SyncError("The calendar server rejected the username or app password")
    monkeypatch.setattr(calendar_sync.CalDav, "discover_home", reject)
    r = api.post("/api/calendar-sync/test", json={"url": "cloud.example.com", "username": "lc"})
    assert r.status_code == 400 and "rejected" in r.json()["detail"]


# ---------- syncing ----------

def test_full_sync_pushes_every_appointment(api, accounts):
    _, appt = make_appointment(api, "Maria Full")
    full_sync()
    event = accounts[api.user_id].items[("appointment", appt["id"])]
    assert "SUMMARY:Session – Maria Full" in event
    assert "DTSTART:20300501T150000Z" in event and "DTEND:20300501T163000Z" in event
    assert api.get("/api/calendar-sync").json()["last_error"] is None


def test_only_your_own_things_go_to_your_calendar(api, admin, accounts):
    other = new_user(admin)
    other.put("/api/calendar-sync", json={**SETTINGS, "username": "someone-else"})
    _, mine = make_appointment(api, "Mine")
    _, theirs = make_appointment(other, "Theirs")
    full_sync()
    assert ("appointment", mine["id"]) in accounts[api.user_id].items
    assert ("appointment", theirs["id"]) not in accounts[api.user_id].items
    assert ("appointment", theirs["id"]) in accounts[other.user_id].items
    assert ("appointment", mine["id"]) not in accounts[other.user_id].items


def test_deleted_appointments_are_removed_even_if_missed(api, accounts):
    _, appt = make_appointment(api, "Gone Soon")
    full_sync()
    accounts[api.user_id].items[("appointment", 987654)] = "deleted while sync was off"
    api.delete(f"/api/appointments/{appt['id']}")
    full_sync()
    assert ("appointment", appt["id"]) not in accounts[api.user_id].items
    assert ("appointment", 987654) not in accounts[api.user_id].items


def test_a_single_deletion_is_removed_at_once(api, accounts):
    _, appt = make_appointment(api, "Quick Delete")
    full_sync()
    api.delete(f"/api/appointments/{appt['id']}")
    calendar_sync.run_sync({("appointment", appt["id"], None)})   # owner unknown once it's gone
    assert ("appointment", appt["id"]) not in accounts[api.user_id].items


def test_single_change_and_contact_rename(api, accounts):
    client, appt = make_appointment(api, "Old Name")
    calendar_sync.run_sync({("appointment", appt["id"], None)})
    assert "Old Name" in accounts[api.user_id].items[("appointment", appt["id"])]
    api.put(f"/api/clients/{client['id']}", json={"name": "New Name"})
    calendar_sync.run_sync({("client", client["id"], None)})
    assert "New Name" in accounts[api.user_id].items[("appointment", appt["id"])]


def test_tours_and_time_off_are_all_day_events(api, accounts):
    tour = api.post("/api/tours", json={"name": "Lisbon", "start_date": "2031-06-01", "end_date": "2031-06-03",
                                        "starts_at": "2031-06-01T00:00:00Z", "ends_at": "2031-06-04T00:00:00Z"}).json()
    off = api.post("/api/tours", json={"kind": "time_off", "time_off_type": "vacation", "start_date": "2031-07-01",
                                       "end_date": "2031-07-01", "starts_at": "2031-07-01T00:00:00Z",
                                       "ends_at": "2031-07-02T00:00:00Z"}).json()
    full_sync()
    event = accounts[api.user_id].items[("period", tour["id"])]
    assert "SUMMARY:Tour: Lisbon" in event
    assert "DTSTART;VALUE=DATE:20310601" in event and "DTEND;VALUE=DATE:20310604" in event
    assert "SUMMARY:Vacation" in accounts[api.user_id].items[("period", off["id"])]
    api.delete(f"/api/tours/{tour['id']}")
    calendar_sync.run_sync({("period", tour["id"], api.user_id)})
    assert ("period", tour["id"]) not in accounts[api.user_id].items


def test_tasks_are_to_dos(api, accounts):
    client = api.post("/api/clients", json={"name": "Task Person"}).json()
    task = api.post("/api/tasks", json={"title": "Buy lingerie", "due_date": "2031-02-03", "client_id": client["id"],
                                        "notes": "Red"}).json()
    full_sync()
    todo = accounts[api.user_id].items[("task", task["id"])]
    assert "BEGIN:VTODO" in todo and "SUMMARY:Buy lingerie" in todo and "DUE;VALUE=DATE:20310203" in todo
    assert "STATUS:NEEDS-ACTION" in todo and "Task Person" in todo
    api.post(f"/api/tasks/{task['id']}/done", json={"done": True})
    calendar_sync.run_sync({("task", task["id"], api.user_id)})
    assert "STATUS:COMPLETED" in accounts[api.user_id].items[("task", task["id"])]


def test_accounts_without_to_dos_still_get_events(api, monkeypatch):
    account = FakeAccount(tasks=False)
    monkeypatch.setattr(calendar_sync, "_connect", lambda db, owner_id: account)
    task = api.post("/api/tasks", json={"title": "Nowhere to go"}).json()
    _, appt = make_appointment(api, "Still Synced")
    full_sync()
    assert ("appointment", appt["id"]) in account.items and ("task", task["id"]) not in account.items
    status = api.get("/api/calendar-sync").json()
    assert status["last_error"] is None and status["tasks_supported"] is False


def test_discreet_hides_names_and_notes(api, accounts):
    api.put("/api/calendar-sync", json={**SETTINGS, "discreet": True})
    _, appt = make_appointment(api, "Secret Person", notes="private note")
    task = api.post("/api/tasks", json={"title": "Call Secret Person"}).json()
    tour = api.post("/api/tours", json={"name": "Secret City", "start_date": "2031-09-01", "end_date": "2031-09-01",
                                        "starts_at": "2031-09-01T00:00:00Z", "ends_at": "2031-09-02T00:00:00Z"}).json()
    full_sync()
    items = accounts[api.user_id].items
    assert "SUMMARY:Appointment" in items[("appointment", appt["id"])]
    assert "SUMMARY:Task" in items[("task", task["id"])] and "SUMMARY:Away" in items[("period", tour["id"])]
    everything = "".join(items.values())
    assert "Secret" not in everything and "private note" not in everything


def test_cancelled_shows_as_cancelled(api, accounts):
    _, appt = make_appointment(api, "Cancel Me", status="cancelled")
    full_sync()
    assert "STATUS:CANCELLED" in accounts[api.user_id].items[("appointment", appt["id"])]


def test_errors_are_recorded_and_cleared(api, accounts):
    accounts.setdefault(api.user_id, FakeAccount()).fail = "Couldn't reach the calendar server: timed out"
    full_sync()
    status = api.get("/api/calendar-sync").json()
    assert "timed out" in status["last_error"] and status["last_error_at"]
    accounts[api.user_id].fail = None
    full_sync()
    assert api.get("/api/calendar-sync").json()["last_error"] is None


def test_nothing_is_pushed_when_off(api, accounts):
    api.put("/api/calendar-sync", json={**SETTINGS, "enabled": False})
    make_appointment(api, "Off Client")
    full_sync()
    assert accounts.get(api.user_id) is None or accounts[api.user_id].items == {}


# ---------- finding the calendar (CalDAV discovery) ----------

def multistatus(*responses):
    body = "".join(f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{props}</d:prop>"
                   "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>" for href, props in responses)
    return httpx.Response(207, content=('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
                                        f'xmlns:c="urn:ietf:params:xml:ns:caldav">{body}</d:multistatus>').encode())


class FakeServer:
    """A tiny CalDAV server. `style` 'nextcloud' or 'icloud' changes where things live and what it allows."""

    def __init__(self, style):
        self.style = style
        self.collections = {}     # path -> component
        self.files = {}
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method, host = request.url.path, request.method, request.url.host
        self.calls.append((method, host, path))
        if request.headers.get("authorization") != "Basic " + base64.b64encode(b"me:secret").decode():
            return httpx.Response(401)
        if self.style == "nextcloud":
            if path == "/.well-known/caldav":
                return httpx.Response(301, headers={"Location": "/remote.php/dav/"})
            if method == "PROPFIND" and path == "/remote.php/dav/":
                return multistatus(("/remote.php/dav/", "<d:current-user-principal><d:href>/remote.php/dav/principals/users/me/</d:href></d:current-user-principal>"))
            if method == "PROPFIND" and path == "/remote.php/dav/principals/users/me/":
                return multistatus((path, "<c:calendar-home-set><d:href>/remote.php/dav/calendars/me/</d:href></c:calendar-home-set>"))
            home = "/remote.php/dav/calendars/me/"
        else:   # iCloud: answers at the root, with the calendars on another host
            if host == "caldav.icloud.example" and method == "PROPFIND" and path in ("/", "/.well-known/caldav"):
                if path == "/.well-known/caldav":
                    return httpx.Response(404)
                return multistatus(("/", "<d:current-user-principal><d:href>/123/principal/</d:href></d:current-user-principal>"))
            if host == "caldav.icloud.example" and path == "/123/principal/":
                return multistatus((path, "<c:calendar-home-set><d:href>https://p01-caldav.icloud.example:443/123/calendars/</d:href></c:calendar-home-set>"))
            home = "/123/calendars/"
        if method == "PROPFIND" and path in self.collections:
            return multistatus((path, "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"),
                               *[(f, "<d:getetag>x</d:getetag>") for f in self.files if f.startswith(path)])
        if method == "PROPFIND" and path == home:
            return multistatus(*[(p, "<d:displayname>made by hand</d:displayname><d:resourcetype><c:calendar/></d:resourcetype>")
                                 for p in self.collections])
        if method == "PROPFIND":
            return httpx.Response(404)
        if method == "MKCALENDAR":
            component = "VTODO" if b"VTODO" in request.content else "VEVENT"
            if self.style == "icloud" and component == "VTODO":
                return httpx.Response(403)     # iCloud doesn't take to-do lists from other apps
            self.collections[path] = component
            self.made = {**getattr(self, "made", {}), path: request.content.decode()}
            return httpx.Response(201)
        if method == "PROPPATCH":
            self.names = {**getattr(self, "names", {}), path: request.content.decode()}
            return httpx.Response(207)
        if method == "PUT":
            self.files[path] = request.content
            return httpx.Response(201)
        if method == "DELETE":
            return httpx.Response(204 if self.files.pop(path, None) else 404)
        return httpx.Response(405)


def test_discovers_and_creates_on_a_nextcloud_style_server():
    server = FakeServer("nextcloud")
    with calendar_sync.CalDav("https://cloud.example.com", "me", "secret", transport=httpx.MockTransport(server)) as dav:
        dav.prepare()
        assert dav.events_url == "https://cloud.example.com/remote.php/dav/calendars/me/sworkr/"
        assert dav.tasks_url == "https://cloud.example.com/remote.php/dav/calendars/me/sworkr-tasks/"
        dav.put("appointment", 7, b"BEGIN:VCALENDAR")
        dav.put("task", 8, b"BEGIN:VCALENDAR")
        assert dav.list_items() == {("appointment", 7), ("task", 8)}
        dav.delete("appointment", 7)
        assert dav.list_items() == {("task", 8)}
    assert server.collections == {"/remote.php/dav/calendars/me/sworkr/": "VEVENT",
                                  "/remote.php/dav/calendars/me/sworkr-tasks/": "VTODO"}


def test_discovers_an_icloud_style_account_on_another_host_without_to_dos():
    server = FakeServer("icloud")
    with calendar_sync.CalDav("https://caldav.icloud.example", "me", "secret", transport=httpx.MockTransport(server)) as dav:
        dav.prepare()
        assert dav.events_url == "https://p01-caldav.icloud.example:443/123/calendars/sworkr/"
        assert not dav.tasks_supported
        dav.put("task", 3, b"BEGIN:VCALENDAR")        # quietly skipped
        dav.put("appointment", 4, b"BEGIN:VCALENDAR")
    assert list(server.files) == ["/123/calendars/sworkr/sworkr-appointment-4.ics"]
    assert all(host != "caldav.icloud.example" for method, host, path in server.calls if method == "PUT")


def test_wrong_password_is_reported_plainly():
    server = FakeServer("nextcloud")
    with calendar_sync.CalDav("https://cloud.example.com", "me", "wrong", transport=httpx.MockTransport(server)) as dav:
        with pytest.raises(calendar_sync.SyncError, match="rejected"):
            dav.prepare()


def test_an_address_with_no_calendar_account():
    transport = httpx.MockTransport(lambda request: httpx.Response(404))
    with calendar_sync.CalDav("https://example.com", "me", "secret", transport=transport) as dav:
        with pytest.raises(calendar_sync.SyncError, match="Couldn't find a calendar account"):
            dav.prepare()


# ---------- event format ----------

def test_long_lines_are_folded_and_text_escaped():
    appt = {"id": 1, "scheduled_date": "2030-01-01T10:00:00+00:00", "duration_minutes": 30,
            "updated_at": "2030-01-01T09:00:00+00:00", "status": "scheduled",
            "service_type": "Long " * 30, "client_name": "A, B; C", "notes": "line1\nline2"}
    ics = calendar_sync.appointment_ics(appt, discreet=False).decode()
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    assert "A\\, B\\; C" in ics.replace("\r\n ", "") and "line1\\nline2" in ics.replace("\r\n ", "")


def test_saved_password_is_never_sent_to_a_different_server(api):
    for change in ({"url": "https://attacker.example"}, {"url": "http://cloud.example.com"}, {"username": "someone-else"}):
        for method, url in (("put", "/api/calendar-sync"), ("post", "/api/calendar-sync/test")):
            r = getattr(api, method)(url, json={**SETTINGS, **change, "app_password": ""})
            assert r.status_code == 400 and "password again" in r.json()["detail"], (change, url)
    db = main.get_db()
    assert calendar_sync.get_setting(db, api.user_id, "cal_url") == "https://cloud.example.com"
    db.close()


# ---------- what the calendar and task list are called ----------

@pytest.mark.parametrize("typed, expected", [
    ("Work", "Work"),
    ("  Work  ", "Work"),
    ("", "sworkr"),
    (None, "sworkr"),
    ("   ", "sworkr"),
])
def test_calendar_names_are_tidied(typed, expected):
    assert calendar_sync.clean_calendar_name(typed, "sworkr") == expected


def test_calendar_names_are_never_too_long():
    assert len(calendar_sync.clean_calendar_name("x" * 500, "sworkr")) <= calendar_sync.NAME_MAX


def test_a_new_calendar_gets_the_chosen_name_safely_escaped():
    server = FakeServer("nextcloud")
    with calendar_sync.CalDav("https://cloud.example.com", "me", "secret", transport=httpx.MockTransport(server),
                              events_name="Work & play", tasks_name="To do") as dav:
        dav.prepare()
        assert dav.events_url.endswith("/sworkr/")       # the address stays the same whatever it's called
        assert dav.rename(dav.events_url, "Work <now>")
    assert "<d:displayname>Work &amp; play</d:displayname>" in server.made["/remote.php/dav/calendars/me/sworkr/"]
    assert "Work &lt;now&gt;" in server.names["/remote.php/dav/calendars/me/sworkr/"]


def test_renaming_happens_at_the_next_sync(api, accounts):
    status = api.put("/api/calendar-sync", json={**SETTINGS, "events_name": "Work", "tasks_name": "To do"}).json()
    assert (status["events_name"], status["tasks_name"]) == ("Work", "To do")
    full_sync()
    me = accounts[api.get("/api/auth/status").json()["user"]["id"]]   # (other people sync too)
    assert set(me.renamed.values()) == {"Work", "To do"}
    me.renamed = None
    full_sync()                                           # done once, not every sync
    assert me.renamed is None
