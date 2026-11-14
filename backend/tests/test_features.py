"""Tests for income, screening, booking warnings, client history, accounts and data separation.
Run with:  docker compose run --rm tests"""
import os
import sqlite3
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


def login(username="owner", password=PASSWORD):
    c = TestClient(main.app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture(scope="module")
def api():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture(scope="module")
def other(api):
    """A second, non-admin user with their own login."""
    name = "second-" + uuid.uuid4().hex[:6]
    r = api.post("/api/users", json={"username": name, "password": PASSWORD})
    assert r.status_code == 201, r.text
    c = login(name)
    c.user_id, c.username = r.json()["id"], name
    return c


_next_day = iter(range(1, 100000))


def slot(hour=10):
    """A start time on a day no other test uses, so tests don't trip each other's overlap checks."""
    day = datetime(2040, 1, 1, hour, tzinfo=timezone.utc) + timedelta(days=next(_next_day))
    return day.isoformat().replace("+00:00", "Z")


def make_client(api, name=None, **fields):
    r = api.post("/api/clients", json={"name": name or "C " + uuid.uuid4().hex[:6], **fields})
    assert r.status_code == 201, r.text
    return r.json()


def book(api, client, when=None, expect=201, params=None, **fields):
    body = {"client_id": client["id"], "service_type": "Session", "duration_minutes": 60,
            "scheduled_date": when or slot(), **fields}
    r = api.post("/api/appointments", json=body, params=params or {})
    assert r.status_code == expect, r.text
    return r.json()


def db_exec(sql, *params):
    db = sqlite3.connect(main.DB_PATH)
    try:
        db.execute(sql, params)
        db.commit()
    finally:
        db.close()


# ---------- screening ----------

def test_screening_fields_are_saved_and_default_to_unscreened(api):
    c = make_client(api)
    assert (c["screening_status"], c["do_not_see"], c["references"]) == ("unscreened", False, None)

    r = api.put(f"/api/clients/{c['id']}", json={
        "name": c["name"], "screening_status": "verified", "screening_notes": "ID checked",
        "references": "Provider A, Provider B", "do_not_see": True, "do_not_see_reason": "No-show twice"})
    assert r.status_code == 200, r.text
    saved = api.get(f"/api/clients/{c['id']}").json()
    assert (saved["screening_status"], saved["screening_notes"], saved["references"]) == (
        "verified", "ID checked", "Provider A, Provider B")
    assert (saved["do_not_see"], saved["do_not_see_reason"]) == (True, "No-show twice")
    assert api.put(f"/api/clients/{c['id']}", json={"name": "x", "screening_status": "maybe"}).status_code == 422


def test_client_list_filters_by_screening_and_do_not_see_and_finds_phone_numbers(api):
    tag = uuid.uuid4().hex[:6]
    flagged = make_client(api, f"Flag {tag}", do_not_see=True, contact_phone="+1 555 7788")
    pending = make_client(api, f"Pend {tag}", screening_status="pending")

    def names(**params):
        return {c["name"] for c in api.get("/api/clients", params={"limit": 200, "search": tag, **params}).json()}

    assert names() == {flagged["name"], pending["name"]}
    assert names(do_not_see=1) == {flagged["name"]}
    assert names(screening="pending") == {pending["name"]}
    found = api.get("/api/clients", params={"search": "555 7788"}).json()
    assert flagged["id"] in [c["id"] for c in found]


# ---------- income ----------

def test_rate_and_payments(api):
    c = make_client(api)
    a = book(api, c)
    assert (a["rate"], a["amount_paid"], a["payment_status"]) == (None, 0, "none")

    a = book(api, c, rate=300, amount_paid=100, payment_method="cash")
    assert (a["rate"], a["amount_paid"], a["payment_status"], a["payment_method"]) == (300, 100, "partial", "cash")
    assert book(api, c, rate=300)["payment_status"] == "unpaid"

    paid = api.post(f"/api/appointments/{a['id']}/mark-paid").json()
    assert (paid["amount_paid"], paid["payment_status"]) == (300, "paid")

    no_rate = book(api, c)
    assert api.post(f"/api/appointments/{no_rate['id']}/mark-paid").status_code == 400
    assert api.post("/api/appointments/999999/mark-paid").status_code == 404


def test_money_validation(api):
    c = make_client(api)
    book(api, c, rate=-1, expect=400)
    book(api, c, amount_paid=-5, expect=400)
    book(api, c, rate="lots", expect=422)


# ---------- booking warnings ----------

def test_overlap_warns_only_when_asked_and_never_saves_then(api):
    c, d = make_client(api, "First Booked"), make_client(api)
    when = slot(10)
    first = book(api, c, when, duration_minutes=120)

    half_past = when.replace("T10:00", "T11:30")
    r = api.post("/api/appointments", params={"warn": "true"}, json={
        "client_id": d["id"], "service_type": "Session", "duration_minutes": 60, "scheduled_date": half_past})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "needs_confirmation"
    assert [(w["type"], w["appointment_id"], w["client_name"]) for w in detail["warnings"]] == [
        ("overlap", first["id"], "First Booked")]
    assert api.get("/api/appointments", params={"client_id": d["id"]}).json() == []      # nothing was saved

    book(api, d, half_past)                                                              # confirmed: saves
    assert len(api.get("/api/appointments", params={"client_id": d["id"]}).json()) == 1


def test_back_to_back_and_cancelled_bookings_do_not_warn(api):
    c = make_client(api)
    when = slot(10)
    book(api, c, when, duration_minutes=60)
    book(api, c, when.replace("T10:00", "T11:00"), params={"warn": "true"})              # starts as the other ends
    book(api, c, when.replace("T10:00", "T09:00"), params={"warn": "true"})              # ends as the other starts

    cancelled_day = slot(10)
    book(api, c, cancelled_day, status="cancelled")
    book(api, c, cancelled_day, params={"warn": "true"})                                  # cancelled ones don't count


def test_long_bookings_that_started_earlier_are_found(api):
    c = make_client(api)
    when = slot(20)                                                                       # overnight, 12 hours
    book(api, c, when, duration_minutes=720)
    next_morning = (datetime.fromisoformat(when.replace("Z", "+00:00")) + timedelta(hours=10)).isoformat()
    book(api, c, next_morning, params={"warn": "true"}, expect=409)


def test_do_not_see_client_warns(api):
    c = make_client(api, "Trouble", do_not_see=True, do_not_see_reason="Aggressive")
    r = api.post("/api/appointments", params={"warn": "true"}, json={
        "client_id": c["id"], "service_type": "Session", "duration_minutes": 60, "scheduled_date": slot()})
    assert r.status_code == 409
    warning = r.json()["detail"]["warnings"][0]
    assert warning["type"] == "do_not_see" and "Aggressive" in warning["message"]
    assert book(api, c)["client_do_not_see"] is True                                      # still possible on purpose


def test_editing_warns_only_when_the_time_or_client_changes(api):
    c = make_client(api)
    when = slot(10)
    a = book(api, c, when)
    b = book(api, c, when)                                                                # already overlapping

    def save(**changes):
        body = {"client_id": c["id"], "service_type": "Session", "duration_minutes": 60, "scheduled_date": when, **changes}
        return api.put(f"/api/appointments/{b['id']}", params={"warn": "true"}, json=body).status_code

    assert save(notes="just a note") == 200                                               # nothing that matters changed
    assert save(duration_minutes=90) == 409                                               # now it's a new overlap question
    assert save(scheduled_date=slot()) == 200                                             # moved to a free day
    assert a["id"] != b["id"]


# ---------- repeating appointments ----------

def test_repeating_appointment_creates_a_series(api):
    c = make_client(api)
    first = slot(19)
    start = datetime.fromisoformat(first.replace("Z", "+00:00"))
    repeats = [(start + timedelta(days=7 * i)).isoformat() for i in (1, 2, 3)]
    a = book(api, c, first, rate=200, amount_paid=50, repeat_dates=repeats)

    series = api.get("/api/appointments", params={"client_id": c["id"]}).json()
    assert len(series) == 4
    assert {s["series_id"] for s in series} == {a["series_id"]} and a["series_id"]
    assert [s["rate"] for s in series] == [200] * 4
    assert [s["amount_paid"] for s in series] == [50, 0, 0, 0]                            # the deposit is not copied

    # delete the third and everything after it
    assert api.delete(f"/api/appointments/{series[2]['id']}", params={"scope": "following"}).status_code == 204
    assert [s["id"] for s in api.get("/api/appointments", params={"client_id": c["id"]}).json()] == [
        series[0]["id"], series[1]["id"]]
    assert api.delete(f"/api/appointments/{series[0]['id']}").status_code == 204          # just one
    assert len(api.get("/api/appointments", params={"client_id": c["id"]}).json()) == 1


def test_too_many_repeats_is_refused(api):
    c = make_client(api)
    start = datetime(2060, 1, 1, tzinfo=timezone.utc)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(1, 54)]
    book(api, c, start.isoformat(), repeat_dates=dates, expect=400)


# ---------- location + check-in ----------

def test_location_is_saved(api):
    c = make_client(api)
    a = book(api, c, location_type="outcall", location="Hotel Example, room 412")
    assert (a["location_type"], a["location"]) == ("outcall", "Hotel Example, room 412")
    book(api, c, location_type="moon", expect=422)


def test_check_in_and_completing_both_count_as_checked_in(api):
    c = make_client(api)
    a = book(api, c, safety_checkin=True)
    assert a["safety_checkin"] is True and a["checked_in_at"] is None
    assert api.post(f"/api/appointments/{a['id']}/check-in").json()["checked_in_at"]

    b = book(api, c, safety_checkin=True)
    done = api.put(f"/api/appointments/{b['id']}/status", params={"status": "completed"}).json()
    assert done["checked_in_at"]
    assert api.post("/api/appointments/999999/check-in").status_code == 404


# ---------- client history ----------

def test_client_summary_adds_up_history_and_money(api):
    c = make_client(api, "History Person")
    past = "2020-03-01T20:00:00Z"
    a1 = book(api, c, past, rate=300, amount_paid=300)
    api.put(f"/api/appointments/{a1['id']}/status", params={"status": "completed"})
    a2 = book(api, c, "2020-04-01T20:00:00Z", rate=300, amount_paid=100)
    api.put(f"/api/appointments/{a2['id']}/status", params={"status": "completed"})
    book(api, c, "2020-05-01T20:00:00Z", status="cancelled", amount_paid=50)            # kept deposit
    upcoming = book(api, c, rate=400)

    s = api.get(f"/api/clients/{c['id']}/summary").json()
    assert s["client"]["name"] == "History Person"
    assert s["stats"]["appointments"] == 4
    assert (s["stats"]["completed"], s["stats"]["cancelled"], s["stats"]["upcoming"]) == (2, 1, 1)
    assert (s["stats"]["total_paid"], s["stats"]["outstanding"]) == (450, 200)
    assert s["stats"]["first_seen"].startswith("2020-03-01") and s["stats"]["last_seen"].startswith("2020-04-01")
    assert s["stats"]["next_appointment"] == upcoming["scheduled_date"].replace("Z", "+00:00")
    assert [a["id"] for a in s["appointments"]][0] == upcoming["id"]                      # newest first
    assert api.get("/api/clients/999999/summary").status_code == 404


def test_client_notes(api):
    c = make_client(api)
    assert api.post(f"/api/clients/{c['id']}/notes", json={"body": "  "}).status_code == 400
    n1 = api.post(f"/api/clients/{c['id']}/notes", json={"body": "Prefers afternoons"}).json()
    n2 = api.post(f"/api/clients/{c['id']}/notes", json={"body": "Allergic to perfume"}).json()
    notes = api.get(f"/api/clients/{c['id']}/summary").json()["notes"]
    assert {n["body"] for n in notes} == {"Prefers afternoons", "Allergic to perfume"}
    assert api.delete(f"/api/clients/{c['id']}/notes/{n1['id']}").status_code == 204
    assert [n["id"] for n in api.get(f"/api/clients/{c['id']}/summary").json()["notes"]] == [n2["id"]]
    assert api.post("/api/clients/999999/notes", json={"body": "x"}).status_code == 404
    api.delete(f"/api/clients/{c['id']}")
    assert api.get(f"/api/clients/{c['id']}/summary").status_code == 404


# ---------- expenses ----------

def test_expenses_can_be_listed_by_date_range(api):
    tag = uuid.uuid4().hex[:6]
    for day in ("2019-01-15", "2019-02-15", "2019-03-15"):
        r = api.post("/api/expenses", json={"description": f"R {tag}", "amount": 1, "date": f"{day}T12:00:00Z"})
        assert r.status_code == 201
    got = api.get("/api/expenses", params={"start": "2019-02-01T00:00:00Z", "end": "2019-03-01T00:00:00Z"}).json()
    assert [e["date"][:10] for e in got if e["description"] == f"R {tag}"] == ["2019-02-15"]


# ---------- sample data ----------

def test_sample_data_can_be_removed_without_touching_real_records(api):
    real = make_client(api, "Real Client", email=f"{uuid.uuid4().hex[:6]}@real.test")
    sample = make_client(api, "Maria Johnson", email="maria@example.com")
    book(api, sample)
    api.post("/api/expenses", json={"description": "Massage table", "amount": 350, "category": "equipment"})
    kept = api.post("/api/expenses", json={"description": "Massage table", "amount": 351, "category": "equipment"}).json()

    assert api.get("/api/sample-data").json() == {"present": True, "clients": 1, "expenses": 1}
    assert api.delete("/api/sample-data").json() == {"clients": 1, "appointments": 1, "expenses": 1}
    assert api.get("/api/sample-data").json()["present"] is False
    assert api.get(f"/api/clients/{sample['id']}").status_code == 404
    assert api.get(f"/api/clients/{real['id']}").status_code == 200
    assert kept["id"] in [e["id"] for e in api.get("/api/expenses", params={"limit": 500}).json()]


# ---------- automatic log-out ----------

def test_auto_logout_setting(api):
    s = api.get("/api/account/settings").json()
    assert s["idle_minutes"] == 120 and 0 in s["idle_choices"]
    assert api.put("/api/account/settings", json={"idle_minutes": 7}).status_code == 400
    assert api.put("/api/account/settings", json={"idle_minutes": 30}).json()["idle_minutes"] == 30
    assert api.put("/api/account/settings", json={"idle_minutes": 120}).status_code == 200


def test_an_unused_session_is_logged_out(api, other):
    device = login(other.username)
    assert device.get("/api/clients").status_code == 200

    def last_used(minutes_ago):
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
        db_exec("UPDATE sessions SET last_seen_at = ? WHERE user_id = ? AND token_hash != ''", stamp, other.user_id)

    last_used(100)
    assert device.get("/api/clients").status_code == 200           # under the 2 hour default, and counts as use
    last_used(130)
    assert device.get("/api/clients").status_code == 401           # over it: logged out
    assert device.get("/api/clients").status_code == 401           # and stays logged out
    other.post("/api/auth/login", json={"username": other.username, "password": PASSWORD})


def test_background_requests_do_not_keep_a_session_alive(other):
    device = login(other.username)
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=100)).isoformat(timespec="seconds")
    db_exec("UPDATE sessions SET last_seen_at = ? WHERE user_id = ?", stamp, other.user_id)
    assert device.get("/api/safety/watch", headers={"X-Background": "1"}).status_code == 200
    db = sqlite3.connect(main.DB_PATH)
    seen = {r[0] for r in db.execute("SELECT last_seen_at FROM sessions WHERE user_id = ?", (other.user_id,))}
    db.close()
    assert seen == {stamp}                                         # polling did not count as activity
    other.post("/api/auth/login", json={"username": other.username, "password": PASSWORD})


def test_never_log_out_setting(other):
    assert other.put("/api/account/settings", json={"idle_minutes": 0}).status_code == 200
    device = login(other.username)
    stamp = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
    db_exec("UPDATE sessions SET last_seen_at = ? WHERE user_id = ?", stamp, other.user_id)
    assert device.get("/api/clients").status_code == 200
    other.post("/api/auth/login", json={"username": other.username, "password": PASSWORD})
    assert other.put("/api/account/settings", json={"idle_minutes": 120}).status_code == 200


# ---------- users and data separation ----------

def test_only_admins_manage_users(api, other):
    assert other.get("/api/users").status_code == 403
    assert other.post("/api/users", json={"username": "sneaky", "password": PASSWORD}).status_code == 403
    assert other.delete(f"/api/users/{other.user_id}").status_code == 403
    assert other.get("/api/backup").status_code == 403
    assert other.post("/api/backup/download", json={"passphrase": "long-enough-passphrase"}).status_code == 403

    listed = api.get("/api/users").json()
    assert {"owner", other.username} <= {u["username"] for u in listed}
    assert api.post("/api/users", json={"username": other.username, "password": PASSWORD}).status_code == 409
    assert api.post("/api/users", json={"username": "x", "password": PASSWORD}).status_code == 400
    assert api.post("/api/users", json={"username": "shorty", "password": "short"}).status_code == 400
    me = [u for u in listed if u["username"] == "owner"][0]
    assert api.delete(f"/api/users/{me['id']}").status_code == 400     # can't delete yourself


def test_users_cannot_see_or_change_each_others_records(api, other):
    tag = uuid.uuid4().hex[:6]
    mine = make_client(api, f"Private {tag}", email=f"{tag}@private.test", tags=[f"t{tag}"])
    appt = book(api, mine, rate=500, notes=f"secret {tag}")
    exp = api.post("/api/expenses", json={"description": f"Hidden {tag}", "amount": 9, "client_id": mine["id"]}).json()
    note = api.post(f"/api/clients/{mine['id']}/notes", json={"body": "private note"}).json()

    # reading
    assert other.get(f"/api/clients/{mine['id']}").status_code == 404
    assert other.get(f"/api/clients/{mine['id']}/summary").status_code == 404
    assert other.get(f"/api/appointments/{appt['id']}").status_code == 404
    assert mine["id"] not in [c["id"] for c in other.get("/api/clients", params={"limit": 200}).json()]
    assert other.get("/api/appointments", params={"limit": 1000}).json() == []
    assert other.get("/api/expenses", params={"limit": 500}).json() == []
    assert other.get("/api/expenses/summary").json()["expense_count"] == 0
    assert other.get("/api/search", params={"q": tag}).json()["count"] == 0
    assert other.get("/api/appointments/service-types").json() == []
    assert tag not in other.get("/api/csv/clients").text
    assert tag not in other.get("/api/csv/expenses").text

    # changing
    assert other.put(f"/api/clients/{mine['id']}", json={"name": "Hacked"}).status_code == 404
    assert other.delete(f"/api/clients/{mine['id']}").status_code == 204
    assert other.post(f"/api/clients/{mine['id']}/notes", json={"body": "x"}).status_code == 404
    assert other.delete(f"/api/clients/{mine['id']}/notes/{note['id']}").status_code == 204
    body = {"client_id": mine["id"], "service_type": "S", "duration_minutes": 60, "scheduled_date": slot()}
    assert other.post("/api/appointments", json=body).status_code == 400            # not their client
    assert other.put(f"/api/appointments/{appt['id']}", json=body).status_code == 404
    assert other.put(f"/api/appointments/{appt['id']}/status", params={"status": "cancelled"}).status_code == 404
    assert other.post(f"/api/appointments/{appt['id']}/mark-paid").status_code == 404
    assert other.post(f"/api/appointments/{appt['id']}/check-in").status_code == 404
    assert other.delete(f"/api/appointments/{appt['id']}").status_code == 204
    assert other.put(f"/api/expenses/{exp['id']}", json={"description": "Hacked", "amount": 1}).status_code == 404
    assert other.delete(f"/api/expenses/{exp['id']}").status_code == 204
    assert other.post("/api/expenses", json={"description": "x", "amount": 1, "client_id": mine["id"]}).status_code == 400

    # nothing of mine changed
    assert api.get(f"/api/clients/{mine['id']}").json()["name"] == f"Private {tag}"
    assert api.get(f"/api/appointments/{appt['id']}").json()["status"] == "scheduled"
    assert api.get(f"/api/clients/{mine['id']}/summary").json()["notes"][0]["body"] == "private note"
    assert exp["id"] in [e["id"] for e in api.get("/api/expenses", params={"limit": 500}).json()]


def test_two_users_can_each_have_a_client_with_the_same_email(api, other):
    email = f"{uuid.uuid4().hex[:6]}@shared.test"
    make_client(api, "Mine", email=email)
    theirs = make_client(other, "Theirs", email=email)
    assert other.post("/api/clients", json={"name": "Again", "email": email}).status_code == 409
    assert [c["name"] for c in other.get("/api/clients", params={"search": email}).json()] == ["Theirs"]
    other.delete(f"/api/clients/{theirs['id']}")


def test_overlap_warnings_ignore_other_users_bookings(api, other):
    when = slot(10)
    book(api, make_client(api), when)
    book(other, make_client(other), when, params={"warn": "true"})


def test_csv_import_only_matches_the_importers_own_clients(api, other):
    email = f"{uuid.uuid4().hex[:6]}@csv.test"
    mine = make_client(api, "Owner Version", email=email)
    r = other.post("/api/csv/clients", content=f"name,email\nTheir Version,{email}\n".encode(),
                   headers={"Content-Type": "text/csv"})
    assert r.json() == {"created": 1, "updated": 0, "skipped": 0}
    assert api.get(f"/api/clients/{mine['id']}").json()["name"] == "Owner Version"
    assert [c["name"] for c in other.get("/api/clients", params={"search": email}).json()] == ["Their Version"]


def test_csv_round_trips_the_screening_columns(api):
    tag = uuid.uuid4().hex[:6]
    make_client(api, f"Csv {tag}", screening_status="verified", do_not_see=True, do_not_see_reason="=risky",
                references="Ref One")
    text = api.get("/api/csv/clients").content.decode("utf-8-sig")
    line = [row for row in text.splitlines() if f"Csv {tag}" in row][0]
    assert "verified" in line and ",yes," in line and "'=risky" in line and "Ref One" in line

    r = api.post("/api/csv/clients", headers={"Content-Type": "text/csv"}, content=(
        f"name,screening,do_not_see\nNew {tag},pending,yes\nBad {tag},sometimes,perhaps\n").encode())
    assert r.status_code == 400
    assert len(r.json()["detail"]["errors"]) == 2
    r = api.post("/api/csv/clients", headers={"Content-Type": "text/csv"},
                 content=f"name,screening,do_not_see\nNew {tag},pending,yes\n".encode())
    assert r.json()["created"] == 1
    new = [c for c in api.get("/api/clients", params={"search": f"New {tag}"}).json()][0]
    assert (new["screening_status"], new["do_not_see"]) == ("pending", True)


def test_admin_can_reset_a_users_password_and_delete_them_with_their_data(api):
    name = "temp-" + uuid.uuid4().hex[:6]
    user_id = api.post("/api/users", json={"username": name, "password": PASSWORD}).json()["id"]
    temp = login(name)
    c = make_client(temp, "Temp's client")
    book(temp, c)
    temp.post("/api/expenses", json={"description": "Temp's expense", "amount": 3})

    assert api.post(f"/api/users/{user_id}/password", json={"password": "short"}).status_code == 400
    assert api.post(f"/api/users/{user_id}/password", json={"password": PASSWORD + "-new"}).status_code == 204
    assert temp.get("/api/clients").status_code == 401                         # their devices are logged out
    assert login(name, PASSWORD + "-new").get("/api/clients").status_code == 200

    assert api.delete(f"/api/users/{user_id}").status_code == 204
    db = sqlite3.connect(main.DB_PATH)
    left = [db.execute(f"SELECT COUNT(*) FROM {t} WHERE owner_id = ?", (user_id,)).fetchone()[0]
            for t in ("clients", "appointments", "expenses")]
    db.close()
    assert left == [0, 0, 0]
    assert TestClient(main.app).post("/api/auth/login", json={"username": name, "password": PASSWORD + "-new"}).status_code == 401
    assert api.delete(f"/api/users/{user_id}").status_code == 404
