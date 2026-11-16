"""Tests for downloading everything and erasing everything.
Run with:  docker compose run --rm tests"""
import io
import json
import os
import sys
import tempfile
import uuid
import zipfile

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import calendar_sync  # noqa: E402
import main  # noqa: E402
import privacy  # noqa: E402
import signin  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_account(admin):
    name = "p-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return name, c


def fill(c, tag):
    client = c.post("/api/clients", json={"name": f"Contact {tag}", "tags": ["regular"]})
    assert client.status_code == 201
    assert c.post("/api/expenses", json={"description": f"Taxi {tag}", "amount": 20, "client_id": client.json()["id"]}).status_code == 201
    return client.json()


def user_id(name):
    db = main.get_db()
    try:
        return db.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]
    finally:
        db.close()


def test_every_table_with_an_owner_is_covered():
    db = main.get_db()
    try:
        tables = privacy.owned_tables(db)
    finally:
        db.close()
    for expected in ("clients", "appointments", "expenses", "income", "tasks", "documents", "blocklist", "med_schedules"):
        assert expected in tables
    assert "users" not in tables and "sessions" not in tables


def test_the_download_holds_my_records_and_nobody_elses(admin):
    name, c = new_account(admin)
    _, other = new_account(admin)
    fill(c, "mine")
    fill(other, "theirs")

    summary = c.get("/api/account/data").json()
    assert summary["by_kind"]["clients"] == 1 and summary["by_kind"]["expenses"] == 1

    r = c.get("/api/account/data/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert name in z.read("README.txt").decode()
    clients = json.loads(z.read("clients.json"))
    assert [x["name"] for x in clients] == ["Contact mine"]
    assert [x["description"] for x in json.loads(z.read("expenses.json"))] == ["Taxi mine"]
    assert len(json.loads(z.read("client_tags.json"))) == 1
    assert "theirs" not in "".join(z.read(n).decode() for n in z.namelist())


def test_the_download_leaves_out_saved_passwords_and_sign_in_secrets(admin):
    name, c = new_account(admin)
    uid = user_id(name)
    db = main.get_db()
    try:
        calendar_sync.set_setting(db, uid, "cal_password", "calendar-app-pw")
        calendar_sync.set_setting(db, uid, "cal_username", "me")
        signin._set(db, uid, "totp_secret", "JBSWY3DPEHPK3PXP")
        db.commit()
    finally:
        db.close()
    z = zipfile.ZipFile(io.BytesIO(c.get("/api/account/data/export").content))
    everything = "".join(z.read(n).decode() for n in z.namelist())
    assert "calendar-app-pw" not in everything and "JBSWY3DPEHPK3PXP" not in everything and "sealed:" not in everything
    keys = [s["key"] for s in json.loads(z.read("settings.json"))]
    assert "cal_username" in keys and "cal_password" not in keys and "totp_secret" not in keys
    assert not any(n.startswith(("sessions", "passkeys", "recovery_codes", "users")) for n in z.namelist())


def test_erasing_needs_the_password_and_the_word(admin):
    _, c = new_account(admin)
    fill(c, "keep")
    before = c.get("/api/account/data").json()["records"]
    assert c.post("/api/account/data/erase", json={"password": PASSWORD, "confirm": "yes"}).status_code == 400
    assert c.post("/api/account/data/erase", json={"password": "not-the-password", "confirm": "ERASE"}).status_code == 403
    assert c.get("/api/account/data").json()["records"] == before >= 2


def test_erasing_removes_everything_of_mine_and_only_mine(admin):
    name, c = new_account(admin)
    _, other = new_account(admin)
    fill(c, "wipe-me-7731")
    fill(other, "theirs")
    theirs_before = other.get("/api/account/data").json()["records"]
    uid = user_id(name)
    db = main.get_db()
    try:
        calendar_sync.set_setting(db, uid, "cal_password", "calendar-app-pw")
        signin._set(db, uid, "two_step", "1")
        signin._set(db, uid, "two_step_method", "app")
        signin._set(db, uid, "totp_secret", "JBSWY3DPEHPK3PXP")
        db.commit()
    finally:
        db.close()
    second_device = TestClient(main.app)
    db = main.get_db()
    try:   # a second signed-in device, without going through the two-step prompt
        import auth
        token = auth.create_session(db, uid)
    finally:
        db.close()
    second_device.cookies.set(auth.SESSION_COOKIE, token)
    assert second_device.get("/api/account/data").status_code == 200

    r = c.post("/api/account/data/erase", json={"password": PASSWORD, "confirm": "ERASE"})
    assert r.status_code == 200 and r.json()["erased"] >= 3

    assert c.get("/api/account/data").json() == {"records": 0, "by_kind": {}, "erase_word": "ERASE"}
    assert c.get("/api/clients").json() == []
    assert other.get("/api/account/data").json()["records"] == theirs_before
    assert [x["name"] for x in other.get("/api/clients").json()] == ["Contact theirs"]
    assert second_device.get("/api/account/data").status_code == 401   # other devices are signed out

    db = main.get_db()
    try:
        left = {r["key"] for r in db.execute("SELECT key FROM user_settings WHERE user_id = ?", (uid,))}
        assert left == {"two_step", "two_step_method", "totp_secret"}   # the login stays as protected as it was
        assert db.execute("SELECT COUNT(*) FROM client_tags WHERE client_id NOT IN (SELECT id FROM clients)").fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        db.close()
    with open(main.DB_PATH, "rb") as f:
        assert b"wipe-me-7731" not in f.read()   # overwritten in the file, not just unlinked


def test_erasing_is_off_in_the_demo(admin, monkeypatch):
    import demo
    _, c = new_account(admin)
    monkeypatch.setattr(demo, "ENABLED", True)
    assert c.post("/api/account/data/erase", json={"password": PASSWORD, "confirm": "ERASE"}).status_code == 403
