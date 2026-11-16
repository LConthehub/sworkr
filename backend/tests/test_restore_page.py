"""Tests for restoring a backup from the Account page.
Run with:  docker compose run --rm tests"""
import base64
import glob
import os
import sqlite3
import sys
import tempfile
import uuid

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

PASSWORD = "correct-horse-battery"
PASSPHRASE = "a long backup passphrase"


def signed_in(name="owner"):
    c = TestClient(main.app)
    if name == "owner" and c.post("/api/auth/setup", json={"username": name, "password": PASSWORD}).status_code == 201:
        return c
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def names(c):
    return {x["name"] for x in c.get("/api/clients").json()}


def test_restoring_from_the_page_brings_the_backup_back_and_keeps_a_copy():
    api = signed_in()
    before, after = "Before " + uuid.uuid4().hex[:6], "After " + uuid.uuid4().hex[:6]
    assert api.post("/api/clients", json={"name": before}).status_code == 201
    blob = api.post("/api/backup/download", json={"passphrase": PASSPHRASE}).content
    assert api.post("/api/clients", json={"name": after}).status_code == 201
    body = {"file": base64.b64encode(blob).decode(), "passphrase": PASSPHRASE, "password": PASSWORD, "confirm": "RESTORE"}

    # Every way of getting it wrong leaves things exactly as they are.
    assert api.post("/api/backup/restore", json={**body, "confirm": "yes"}).status_code == 400
    assert api.post("/api/backup/restore", json={**body, "password": "not-my-password"}).status_code == 403
    r = api.post("/api/backup/restore", json={**body, "passphrase": "not the passphrase"})
    assert r.status_code == 400 and "Wrong passphrase" in r.json()["detail"]
    assert api.post("/api/backup/restore", json={**body, "file": "not base64 at all!"}).status_code == 400
    damaged = base64.b64encode(blob[:-20]).decode()
    assert api.post("/api/backup/restore", json={**body, "file": damaged}).status_code == 400
    assert {before, after} <= names(api)
    assert glob.glob(os.path.join(main.DATA_DIR, "sworkr.before-restore-*.db")) == []

    r = api.post("/api/backup/restore", json=body)
    assert r.status_code == 200 and r.json()["restored"] is True
    assert api.get("/api/clients").status_code == 401            # everyone is signed out, this browser included

    api = signed_in()
    found = names(api)
    assert before in found and after not in found

    kept = glob.glob(os.path.join(main.DATA_DIR, "sworkr.before-restore-*.db"))
    assert len(kept) == 1 and os.path.basename(kept[0]) == r.json()["kept_as"]
    copy = sqlite3.connect(kept[0])
    try:
        assert copy.execute("SELECT COUNT(*) FROM clients WHERE name = ?", (after,)).fetchone()[0] == 1   # the way back
    finally:
        copy.close()
    os.remove(kept[0])


def test_only_an_admin_can_restore_and_never_in_the_demo(monkeypatch):
    import demo
    api = signed_in()
    assert api.post("/api/users", json={"username": "restore-helper", "password": PASSWORD}).status_code in (201, 409)
    blob = api.post("/api/backup/download", json={"passphrase": PASSPHRASE}).content
    body = {"file": base64.b64encode(blob).decode(), "passphrase": PASSPHRASE, "password": PASSWORD, "confirm": "RESTORE"}
    assert signed_in("restore-helper").post("/api/backup/restore", json=body).status_code == 403
    monkeypatch.setattr(demo, "ENABLED", True)
    assert api.post("/api/backup/restore", json=body).status_code == 403
