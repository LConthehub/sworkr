"""Tests for off-site backup copies (WebDAV) and the restore test.
Run with:  docker compose run --rm tests"""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import backup  # noqa: E402
import main  # noqa: E402
import offsite  # noqa: E402
import vault  # noqa: E402

PASSWORD = "correct-horse-battery"
PASSPHRASE = "a long backup passphrase"
FOLDER = "https://cloud.example.com/remote.php/dav/files/me/sworkr-backups"


class Server:
    """A pretend WebDAV folder."""

    def __init__(self):
        self.files, self.exists, self.calls, self.full = {}, False, [], False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.headers.get("authorization") != httpx.BasicAuth("me", "app-pw")._auth_header:
            return httpx.Response(401)
        name = request.url.path.rsplit("/", 1)[-1]
        if request.method == "MKCOL":
            created, self.exists = not self.exists, True
            return httpx.Response(201 if created else 405)
        if request.method == "PUT":
            if self.full:
                return httpx.Response(507)
            self.files[name] = request.content
            return httpx.Response(201)
        if request.method == "DELETE":
            return httpx.Response(204 if self.files.pop(name, None) is not None else 404)
        if request.method == "PROPFIND":
            hrefs = ["/remote.php/dav/files/me/sworkr-backups/"] + [f"/remote.php/dav/files/me/sworkr-backups/{n}" for n in self.files]
            body = "".join(f"<d:response><d:href>{h}</d:href></d:response>" for h in hrefs)
            return httpx.Response(207, content=f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">{body}</d:multistatus>'.encode())
        return httpx.Response(405)


@pytest.fixture(scope="module")
def api():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def server(monkeypatch, tmp_path, api):
    s = Server()
    monkeypatch.setattr(offsite, "_transport", httpx.MockTransport(s))
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path))
    yield s
    api.put("/api/backup/offsite", json={"enabled": False})
    api.put("/api/backup/auto", json={"enabled": False})
    db = main.get_db()
    try:
        for key in ("backup_verified_at", "backup_verified_file", "backup_verify_error", "offsite_last_at", "offsite_last_file"):
            backup._set(db, key, None)
    finally:
        db.close()


def turn_on(api, **over):
    return api.put("/api/backup/offsite", json={"enabled": True, "url": FOLDER, "username": "me", "password": "app-pw", **over})


def test_backup_dates_come_from_the_file_name():
    assert offsite.backup_date("sworkr-2026-11-15-031502.swbak") == date(2026, 11, 15)
    for other in ("notes.txt", "sworkr-2026-13-45-000000.swbak", "sworkr-2026-11-15-031502.swbak.part", "x-sworkr-2026-11-15-031502.swbak"):
        assert offsite.backup_date(other) is None


def test_turning_it_on_tries_the_folder_first(api, server):
    assert turn_on(api, url="cloud.example.com/backups").status_code == 400            # not an address
    assert turn_on(api, password="").status_code == 400                                 # nothing to sign in with
    r = turn_on(api, password="wrong")
    assert r.status_code == 400 and "refused" in r.json()["detail"]
    assert api.get("/api/backup/offsite").json()["enabled"] is False                    # nothing was saved

    status = turn_on(api).json()
    assert status["enabled"] and status["url"] == FOLDER and status["has_password"]
    assert "app-pw" not in str(status)                                                  # never sent back
    assert server.exists
    db = main.get_db()
    try:
        raw = db.execute("SELECT value FROM settings WHERE key = 'offsite_password'").fetchone()[0]
    finally:
        db.close()
    assert raw.startswith(vault.PREFIX)                                                 # sealed in the database


def test_each_automatic_backup_is_copied_off_site_still_encrypted(api, server):
    assert turn_on(api).status_code == 200
    assert api.put("/api/backup/auto", json={"enabled": True, "passphrase": PASSPHRASE}).status_code == 200
    assert len(server.files) == 1
    name, blob = next(iter(server.files.items()))
    assert offsite.backup_date(name) and blob.startswith(backup.MAGIC) and b"SQLite format" not in blob
    assert backup.decrypt(blob, PASSPHRASE).startswith(b"SQLite format 3")
    status = api.get("/api/backup/offsite").json()
    assert status["last_file"] == name and status["last_at"] and not status["last_error"]


def test_turning_it_on_sends_the_backup_that_already_exists(api, server):
    assert api.put("/api/backup/auto", json={"enabled": True, "passphrase": PASSPHRASE}).status_code == 200
    assert server.files == {}
    assert turn_on(api).json()["last_file"] in server.files


def test_a_failed_upload_is_reported_and_the_local_backup_still_happens(api, server):
    assert turn_on(api).status_code == 200
    server.full = True
    status = api.put("/api/backup/auto", json={"enabled": True, "passphrase": PASSPHRASE}).json()
    assert status["files"] == 1 and not status["last_error"]                            # the local one is fine
    assert "out of space" in api.get("/api/backup/offsite").json()["last_error"]
    server.full = False
    assert backup.run_auto_backup(force=True)
    assert api.get("/api/backup/offsite").json()["last_error"] is None


def test_the_newest_copy_is_never_deleted_whatever_the_policy_says(api, server, monkeypatch):
    monkeypatch.setattr(offsite, "which_to_delete", lambda names, today: list(names))   # a policy that wants everything gone
    server.files["sworkr-2020-01-01-000000.swbak"] = b"old"
    server.files["holiday-photos.zip"] = b"not ours"
    assert turn_on(api).status_code == 200
    assert api.put("/api/backup/auto", json={"enabled": True, "passphrase": PASSPHRASE}).status_code == 200
    ours = [n for n in server.files if offsite.backup_date(n)]
    assert len(ours) == 1 and ours[0] != "sworkr-2020-01-01-000000.swbak"
    assert "holiday-photos.zip" in server.files                                         # other people's files are left alone


def test_the_restore_test_opens_the_newest_backup(api, server):
    assert api.post("/api/backup/verify").status_code == 400                            # nothing to test yet
    assert api.put("/api/backup/auto", json={"enabled": True, "passphrase": PASSPHRASE}).status_code == 200
    r = api.post("/api/backup/verify").json()
    assert r["result"]["ok"] and r["result"]["tables"] > 20 and r["verified_at"] and not r["verify_error"]

    newest = os.path.join(backup.BACKUP_DIR, r["result"]["file"])
    with open(newest, "r+b") as f:                                                      # damage the file
        f.seek(100)
        f.write(b"\x00" * 50)
    r = api.post("/api/backup/verify").json()
    assert r["result"]["ok"] is False and r["verify_error"].startswith(r["result"]["file"])


def test_the_restore_test_runs_about_once_a_month(api, server):
    assert api.put("/api/backup/auto", json={"enabled": True, "passphrase": PASSPHRASE}).status_code == 200
    db = main.get_db()
    try:
        assert offsite.verify_if_due(db)["ok"]                                          # never tested: due
        assert offsite.verify_if_due(db) is None                                        # just tested: not due
        long_ago = (datetime.now(timezone.utc) - timedelta(days=offsite.VERIFY_EVERY_DAYS + 1)).isoformat(timespec="seconds")
        backup._set(db, "backup_verified_at", long_ago)
        assert offsite.verify_if_due(db)["ok"]
    finally:
        db.close()


def test_only_an_admin_can_manage_off_site_copies(api):
    assert api.post("/api/users", json={"username": "offsite-helper", "password": PASSWORD}).status_code in (201, 409)
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": "offsite-helper", "password": PASSWORD}).status_code == 200
    assert c.get("/api/backup/offsite").status_code == 403
    assert c.put("/api/backup/offsite", json={"enabled": False}).status_code == 403
    assert c.post("/api/backup/verify").status_code == 403
