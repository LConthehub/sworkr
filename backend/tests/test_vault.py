"""Tests for sealing saved passwords with a key kept outside the database.
Run with:  docker compose run --rm tests"""
import os
import sqlite3
import sys
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import backup  # noqa: E402
import calendar_sync  # noqa: E402
import mail  # noqa: E402
import main  # noqa: E402
import signin  # noqa: E402
import vault  # noqa: E402


def _db():
    main.init_db()
    db = sqlite3.connect(main.DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def _user(db, name):
    db.execute("INSERT OR IGNORE INTO users (username, password_hash, is_admin, created_at) VALUES (?, 'x', 0, '2026-01-01')", (name,))
    return db.execute("SELECT id FROM users WHERE username = ?", (name,)).fetchone()[0]


def _stored(db, user_id, key):
    return db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()[0]


def test_a_secret_is_sealed_and_opens_again():
    sealed = vault.seal("cal_password", "app-pass-1234")
    assert sealed.startswith(vault.PREFIX) and "app-pass-1234" not in sealed
    assert vault.unseal("cal_password", sealed) == "app-pass-1234"
    assert vault.seal("cal_password", "app-pass-1234") != sealed   # a fresh nonce every time
    assert vault.seal("cal_password", sealed) == sealed            # never sealed twice


def test_ordinary_settings_and_empty_values_are_left_alone():
    assert vault.seal("cal_url", "https://cloud.example.com") == "https://cloud.example.com"
    assert vault.seal("cal_password", None) is None and vault.seal("cal_password", "") == ""
    assert vault.unseal("cal_password", None) is None
    assert vault.unseal("cal_password", "saved-before-sealing") == "saved-before-sealing"


def test_a_sealed_value_only_opens_under_its_own_setting():
    sealed = vault.seal("cal_password", "app-pass-1234")
    assert vault.unseal("mail_password", sealed) is None


def test_the_key_is_a_file_outside_the_database():
    vault.seal("cal_password", "x")
    path = os.path.join(vault.key_dir(), vault.KEY_FILE)
    assert os.path.getsize(path) == 32
    assert os.path.abspath(path) != os.path.abspath(main.DB_PATH)
    with open(main.DB_PATH, "rb") as db_file, open(path, "rb") as key_file:
        assert key_file.read() not in db_file.read()


def test_with_another_key_the_value_counts_as_not_saved(monkeypatch, tmp_path):
    sealed = vault.seal("backup_passphrase", "a long backup passphrase")
    monkeypatch.setenv("KEY_DIR", str(tmp_path))   # as if the database were opened on another computer
    assert vault.unseal("backup_passphrase", sealed) is None
    assert vault.unseal("backup_passphrase", vault.PREFIX + "not-base64!") is None
    monkeypatch.delenv("KEY_DIR")
    assert vault.unseal("backup_passphrase", sealed) == "a long backup passphrase"


def test_every_place_that_saves_a_password_seals_it():
    db = _db()
    uid = _user(db, "vault-user")
    calendar_sync.set_setting(db, uid, "cal_password", "calendar-pw")
    mail._set(db, uid, "mail_password", "mail-pw")
    main.content._set(db, uid, "content_password", "content-pw")
    signin._set(db, uid, "totp_secret", "JBSWY3DPEHPK3PXP")
    calendar_sync.set_setting(db, uid, "cal_username", "lc")
    backup._set(db, "backup_passphrase", "a long backup passphrase")
    db.commit()

    for key, plain in (("cal_password", "calendar-pw"), ("mail_password", "mail-pw"),
                       ("content_password", "content-pw"), ("totp_secret", "JBSWY3DPEHPK3PXP")):
        assert _stored(db, uid, key).startswith(vault.PREFIX) and plain not in _stored(db, uid, key)
    assert _stored(db, uid, "cal_username") == "lc"
    raw = db.execute("SELECT value FROM settings WHERE key = 'backup_passphrase'").fetchone()[0]
    assert raw.startswith(vault.PREFIX)

    assert calendar_sync.get_setting(db, uid, "cal_password") == "calendar-pw"
    assert mail.load_settings(db, uid)["password"] == "mail-pw"
    assert main.content._get(db, uid, "content_password") == "content-pw"
    assert main.content._get(db, uid, "cal_password") == "calendar-pw"   # the library can borrow the calendar login
    assert signin._setting(db, uid, "totp_secret") == "JBSWY3DPEHPK3PXP"
    assert backup._setting(db, "backup_passphrase") == "a long backup passphrase"
    backup._set(db, "backup_passphrase", None)
    db.commit()
    db.close()


def test_passwords_saved_by_an_older_version_are_sealed_at_startup():
    db = _db()
    uid = _user(db, "vault-old")
    db.execute("INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, 'mail_password', 'old-plain-pw')", (uid,))
    db.execute("INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, 'mail_username', 'me@example.com')", (uid,))
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('backup_passphrase', 'old plain passphrase')")
    db.commit()
    db.close()

    db = _db()   # init_db runs the sealing pass
    assert _stored(db, uid, "mail_password").startswith(vault.PREFIX)
    assert _stored(db, uid, "mail_username") == "me@example.com"
    assert mail._get(db, uid, "mail_password") == "old-plain-pw"
    assert backup._setting(db, "backup_passphrase") == "old plain passphrase"
    assert vault.seal_existing(db) == 0   # nothing left to do the second time
    backup._set(db, "backup_passphrase", None)
    db.commit()
    db.close()
