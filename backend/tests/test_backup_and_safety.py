"""Tests for encrypted backups, the maintenance commands and safety check-in alerts.
Run with:  docker compose run --rm tests"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import backup  # noqa: E402
import main  # noqa: E402
import migrations  # noqa: E402
import safety  # noqa: E402

PASSWORD = "correct-horse-battery"
PASSPHRASE = "a long backup passphrase"


@pytest.fixture(scope="module")
def api():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def make_client(api, name=None, **fields):
    r = api.post("/api/clients", json={"name": name or "C " + uuid.uuid4().hex[:6], **fields})
    assert r.status_code == 201, r.text
    return r.json()


def open_backup(blob, passphrase=PASSPHRASE):
    """Decrypt a backup and open the database inside it."""
    path = os.path.join(tempfile.mkdtemp(prefix="sworkr-restore-"), "sworkr.db")
    backup.restore_into(path, blob, passphrase)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db, path


# ==================== BACKUPS ====================

def test_encryption_round_trip_and_wrong_passphrase():
    blob = backup.encrypt(b"hello" * 1000, PASSPHRASE)
    assert blob.startswith(backup.MAGIC) and b"hello" not in blob
    assert backup.decrypt(blob, PASSPHRASE) == b"hello" * 1000
    assert backup.encrypt(b"hello", PASSPHRASE) != backup.encrypt(b"hello", PASSPHRASE)   # fresh salt every time
    with pytest.raises(backup.BackupError, match="Wrong passphrase"):
        backup.decrypt(blob, "not the passphrase")
    with pytest.raises(backup.BackupError, match="Wrong passphrase"):
        backup.decrypt(blob[:-1] + bytes([blob[-1] ^ 1]), PASSPHRASE)                     # tampered with
    with pytest.raises(backup.BackupError, match="isn't a sworkr backup"):
        backup.decrypt(b"just some file", PASSPHRASE)


def test_downloaded_backup_contains_the_data_and_nothing_readable(api):
    name = "Backup Marker " + uuid.uuid4().hex
    make_client(api, name, email=f"{uuid.uuid4().hex[:6]}@backup.test")

    assert api.post("/api/backup/download", json={"passphrase": "short"}).status_code == 400
    r = api.post("/api/backup/download", json={"passphrase": PASSPHRASE})
    assert r.status_code == 200
    assert r.headers["content-disposition"].endswith('.swbak"')
    assert name.encode() not in r.content and b"SQLite format" not in r.content

    db, _ = open_backup(r.content)
    assert db.execute("SELECT COUNT(*) FROM clients WHERE name = ?", (name,)).fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
    db.close()
    with pytest.raises(backup.BackupError):
        open_backup(r.content, "wrong passphrase here")


def test_restore_replaces_the_database_even_while_it_is_open(api):
    blob = api.post("/api/backup/download", json={"passphrase": PASSPHRASE}).content
    target = os.path.join(tempfile.mkdtemp(prefix="sworkr-restore-"), "sworkr.db")
    migrations.run(target)
    holder = sqlite3.connect(target)                         # like the running app holding it open
    holder.execute("INSERT INTO users (username, password_hash, created_at) VALUES ('stale', 'x', 'now')")
    holder.commit()
    backup.restore_into(target, blob, PASSPHRASE)
    names = {r[0] for r in holder.execute("SELECT username FROM users")}
    holder.close()
    assert "owner" in names and "stale" not in names


def test_automatic_backups_are_written_and_old_ones_removed(api, monkeypatch):
    folder = tempfile.mkdtemp(prefix="sworkr-backups-")
    monkeypatch.setattr(backup, "BACKUP_DIR", folder)
    monkeypatch.setattr(backup, "BACKUP_KEEP", 3)

    assert api.get("/api/backup").json()["auto_enabled"] is False
    assert backup.run_auto_backup() is None                                     # off: nothing happens
    assert api.put("/api/backup/auto", json={"enabled": True}).status_code == 400
    assert api.put("/api/backup/auto", json={"enabled": True, "passphrase": "short"}).status_code == 400

    status = api.put("/api/backup/auto", json={"enabled": True, "passphrase": PASSPHRASE}).json()
    assert status["auto_enabled"] and status["files"] == 1 and status["last_backup_at"] and not status["last_error"]
    assert "passphrase" not in str(status).lower().replace("auto_enabled", "")  # never sent back
    assert backup.run_auto_backup() is None                                     # not due again yet

    for i in range(5):                                                          # five more days go by
        open(os.path.join(folder, f"sworkr-2020-01-0{i + 1}-000000.swbak"), "wb").write(b"old")
    name = backup.run_auto_backup(force=True)
    kept = sorted(os.listdir(folder))
    assert len(kept) == 3 and name in kept and "sworkr-2020-01-01-000000.swbak" not in kept
    db, _ = open_backup(open(os.path.join(folder, name), "rb").read())
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
    db.close()

    assert api.put("/api/backup/auto", json={"enabled": False}).json()["auto_enabled"] is False
    assert backup.run_auto_backup(force=True) is None


def test_automatic_backup_failure_is_reported(api, monkeypatch):
    blocker = os.path.join(tempfile.mkdtemp(prefix="sworkr-backups-"), "a-file")
    open(blocker, "w").close()
    monkeypatch.setattr(backup, "BACKUP_DIR", os.path.join(blocker, "cannot-exist"))
    status = api.put("/api/backup/auto", json={"enabled": True, "passphrase": PASSPHRASE}).json()
    assert status["last_error"] and status["files"] == 0
    api.put("/api/backup/auto", json={"enabled": False})


# ==================== MAINTENANCE COMMANDS ====================

def manage(data_dir, *args, stdin=""):
    env = {**os.environ, "DATA_DIR": data_dir}
    return subprocess.run([sys.executable, "manage.py", *args], cwd=BACKEND, env=env, input=stdin,
                          capture_output=True, text=True)


@pytest.fixture
def separate_db():
    """A small database of its own, so these commands don't disturb the other tests."""
    folder = tempfile.mkdtemp(prefix="sworkr-manage-")
    path = os.path.join(folder, "sworkr.db")
    migrations.run(path)
    db = sqlite3.connect(path)
    db.execute("INSERT INTO users (username, password_hash, is_admin, created_at) VALUES ('lc', ?, 1, 'now')",
               (auth.hash_password("the-old-password"),))
    db.execute("INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES ('t', 1, 'now', 'later')")
    db.execute("INSERT INTO clients (name, display_name, owner_id, created_at, updated_at) VALUES ('Before', 'Before', 1, 'now', 'now')")
    db.commit()
    db.close()
    return folder, path


def test_reset_password_command(separate_db):
    folder, path = separate_db
    out = manage(folder, "reset-password", "--password", "a-brand-new-password")
    assert out.returncode == 0 and "Password changed for lc" in out.stdout, out.stderr

    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    assert auth.check_login(db, "lc", "a-brand-new-password")
    assert not auth.check_login(db, "lc", "the-old-password")
    assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0       # every device logged out
    db.close()

    assert manage(folder, "reset-password", "nobody", "--password", "a-brand-new-password").returncode != 0
    assert manage(folder, "reset-password", "--password", "short").returncode != 0
    assert "lc" in manage(folder, "list-users").stdout


def test_backup_and_restore_commands(separate_db):
    folder, path = separate_db
    out_dir = tempfile.mkdtemp(prefix="sworkr-backups-")
    out = manage(folder, "backup", out_dir, "--passphrase", PASSPHRASE)
    assert out.returncode == 0, out.stderr
    backup_file = os.path.join(out_dir, os.listdir(out_dir)[0])

    db = sqlite3.connect(path)
    db.execute("UPDATE clients SET name = 'After'")
    db.commit()
    db.close()

    wrong = manage(folder, "restore-backup", backup_file, "--passphrase", "not the passphrase", "--yes")
    assert wrong.returncode != 0 and "Wrong passphrase" in wrong.stderr
    declined = manage(folder, "restore-backup", backup_file, "--passphrase", PASSPHRASE, stdin="no\n")
    assert declined.returncode != 0 and "Nothing was changed" in declined.stderr

    done = manage(folder, "restore-backup", backup_file, "--passphrase", PASSPHRASE, stdin="RESTORE\n")
    assert done.returncode == 0, done.stderr
    db = sqlite3.connect(path)
    assert db.execute("SELECT name FROM clients").fetchone()[0] == "Before"
    db.close()
    kept = [n for n in os.listdir(folder) if n.startswith("sworkr.before-restore-")]
    assert len(kept) == 1                                                       # what was there is kept, just in case
    old = sqlite3.connect(os.path.join(folder, kept[0]))
    assert old.execute("SELECT name FROM clients").fetchone()[0] == "After"
    old.close()


# ==================== SAFETY CHECK-IN ====================

class Outbox:
    def __init__(self):
        self.sent, self.fail = [], None

    def send(self, to, subject, body):
        if self.fail:
            raise RuntimeError(self.fail)
        self.sent.append({"to": to, "subject": subject, "body": body})


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr(safety, "send_email", box.send)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "sworkr@example.test")
    return box


@pytest.fixture
def armed(api, outbox):
    r = api.put("/api/safety", json={"contact_name": "Sam", "contact_email": "sam@example.test", "grace_minutes": 30,
                                     "include_details": True, "instructions": "Call me, then call 555-0100",
                                     "timezone": "America/Los_Angeles"})
    assert r.status_code == 200 and r.json()["armed"] is True
    yield api
    # leave nothing waiting for a check-in behind
    db = sqlite3.connect(main.DB_PATH)
    db.execute("UPDATE appointments SET checked_in_at = ? WHERE safety_checkin = 1 AND checked_in_at IS NULL",
               (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
    db.commit()
    db.close()


def started_ago(api, minutes_ago, duration=60, **fields):
    """An appointment with check-in on that started this many minutes ago."""
    client = make_client(api, "Safety Client", contact_phone="+1 555 0199")
    start = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    r = api.post("/api/appointments", json={
        "client_id": client["id"], "service_type": "Outcall", "duration_minutes": duration, "scheduled_date": start,
        "safety_checkin": True, "location_type": "outcall", "location": "Hotel Example 412", **fields})
    assert r.status_code == 201, r.text
    return r.json()


def test_safety_settings(api, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    assert api.put("/api/safety", json={"contact_email": "not an email"}).status_code == 400
    assert api.put("/api/safety", json={"contact_email": "sam@example.test", "grace_minutes": 7}).status_code == 400
    s = api.put("/api/safety", json={"contact_name": " Sam ", "contact_email": "sam@example.test", "grace_minutes": 45}).json()
    assert (s["contact_name"], s["grace_minutes"]) == ("Sam", 45)
    assert s["email_configured"] is False and s["armed"] is False     # no email account set up: says so plainly
    assert api.post("/api/safety/test").status_code == 400


def test_test_message_goes_to_the_contact(armed, outbox):
    assert armed.post("/api/safety/test").json() == {"sent_to": "sam@example.test"}
    assert outbox.sent[0]["to"] == "sam@example.test" and "test" in outbox.sent[0]["subject"].lower()
    assert armed.post("/api/safety/test").status_code == 429     # one test a minute, so the contact isn't spammed
    assert len(outbox.sent) == 1
    safety._last_test_sent.clear()
    outbox.fail = "connection refused"
    assert armed.post("/api/safety/test").status_code == 502
    assert armed.post("/api/safety/test").status_code == 502     # a failed send can be retried at once


def test_no_alert_before_the_end_plus_grace(armed, outbox):
    started_ago(armed, 30)            # still in progress
    started_ago(armed, 80)            # ended 20 minutes ago, grace is 30
    assert safety.run_alerts() == 0 and outbox.sent == []
    assert len(armed.get("/api/safety/watch").json()) == 2          # but the app shows both as waiting


def test_alert_is_sent_once_with_the_details(armed, outbox):
    appt = started_ago(armed, 100)    # ended 40 minutes ago
    assert safety.run_alerts() == 1
    mail = outbox.sent[0]
    assert mail["to"] == "sam@example.test" and "has not checked in" in mail["subject"]
    for expected in ("owner", "Safety Client", "+1 555 0199", "Hotel Example 412", "outcall",
                     "Call me, then call 555-0100", "America/Los_Angeles"):
        assert expected in mail["body"], expected
    assert safety.run_alerts() == 0 and len(outbox.sent) == 1        # not again
    assert armed.get(f"/api/appointments/{appt['id']}").json()["alert_sent_at"]


def test_details_can_be_left_out(armed, outbox):
    armed.put("/api/safety", json={"contact_email": "sam@example.test", "grace_minutes": 30, "include_details": False})
    started_ago(armed, 100)
    assert safety.run_alerts() == 1
    body = outbox.sent[0]["body"]
    assert "Safety Client" not in body and "Hotel Example" not in body and "have not checked in" in body


def test_checking_in_completing_or_cancelling_stops_the_alert(armed, outbox):
    a, b, c = started_ago(armed, 100), started_ago(armed, 100), started_ago(armed, 100)
    armed.post(f"/api/appointments/{a['id']}/check-in")
    armed.put(f"/api/appointments/{b['id']}/status", params={"status": "completed"})
    armed.put(f"/api/appointments/{c['id']}/status", params={"status": "cancelled"})
    assert safety.run_alerts() == 0 and outbox.sent == []
    assert armed.get("/api/safety/watch").json() == []


def test_appointments_without_check_in_never_alert(armed, outbox):
    client = make_client(armed)
    start = (datetime.now(timezone.utc) - timedelta(minutes=200)).isoformat()
    armed.post("/api/appointments", json={"client_id": client["id"], "service_type": "S", "duration_minutes": 60,
                                          "scheduled_date": start})
    assert safety.run_alerts() == 0 and outbox.sent == []


def test_failed_alert_is_recorded_and_retried(armed, outbox):
    appt = started_ago(armed, 100)
    outbox.fail = "mail server down"
    assert safety.run_alerts() == 0
    assert "mail server down" in armed.get("/api/safety").json()["last_error"]
    assert "mail server down" in armed.get("/api/safety/watch").json()[0]["alert_error"]
    outbox.fail = None
    assert safety.run_alerts() == 1                                   # goes out on the next round
    assert armed.get("/api/safety").json()["last_error"] is None
    assert armed.get(f"/api/appointments/{appt['id']}").json()["alert_sent_at"]


def test_alert_missed_while_the_computer_was_off_goes_out_late_but_not_a_day_later(armed, outbox):
    started_ago(armed, 60 * 10)       # ended 9 hours ago: still sent
    started_ago(armed, 60 * 30)       # ended over a day ago: too late to be useful
    assert safety.run_alerts() == 1


def test_moving_an_alerted_appointment_arms_it_again(armed, outbox):
    appt = started_ago(armed, 100)
    assert safety.run_alerts() == 1
    later = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    moved = armed.put(f"/api/appointments/{appt['id']}", json={
        "client_id": appt["client_id"], "service_type": "Outcall", "duration_minutes": 60, "scheduled_date": later,
        "safety_checkin": True}).json()
    assert moved["alert_sent_at"] is None and moved["checked_in_at"] is None


def test_each_users_alert_goes_to_their_own_contact(armed, outbox):
    name = "safety-" + uuid.uuid4().hex[:6]
    armed.post("/api/users", json={"username": name, "password": PASSWORD})
    second = TestClient(main.app)
    second.post("/api/auth/login", json={"username": name, "password": PASSWORD})
    second.put("/api/safety", json={"contact_email": "their-friend@example.test", "grace_minutes": 15})
    started_ago(second, 100)
    started_ago(armed, 100)
    assert safety.run_alerts() == 2
    assert {(m["to"], name in m["subject"]) for m in outbox.sent} == {
        ("their-friend@example.test", True), ("sam@example.test", False)}
    assert len(second.get("/api/safety/watch").json()) == 1          # each sees only their own


def test_real_email_is_built_and_sent_through_smtp(monkeypatch):
    """send_email itself, against a stand-in for the mail server."""
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, context=None):
            calls.append(("connect", host, port))

        def starttls(self, context=None):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, msg):
            calls.append(("send", msg["From"], msg["To"], msg["Subject"], msg.get_content().strip()))

        def quit(self):
            calls.append(("quit",))

    monkeypatch.setattr(safety.smtplib, "SMTP", FakeSMTP)
    for key, value in {"SMTP_HOST": "smtp.example.test", "SMTP_PORT": "2525", "SMTP_USER": "me@example.test",
                       "SMTP_PASSWORD": "pw", "SMTP_FROM": "", "SMTP_SECURITY": "starttls"}.items():
        monkeypatch.setenv(key, value)
    safety.send_email("sam@example.test", "Subject line", "Body text")
    assert calls == [("connect", "smtp.example.test", 2525), ("starttls",), ("login", "me@example.test", "pw"),
                     ("send", "me@example.test", "sam@example.test", "Subject line", "Body text"), ("quit",)]

    monkeypatch.setenv("SMTP_HOST", "")
    with pytest.raises(RuntimeError, match="isn't set up"):
        safety.send_email("sam@example.test", "s", "b")
