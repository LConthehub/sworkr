"""Database upgrade tests. Run with:  docker compose run --rm tests"""
import os
import dbfile as sqlite3  # noqa: E402  (the encrypted engine, like the app)
import subprocess
import sys
import tempfile

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import migrations  # noqa: E402
import vault  # noqa: E402

OLD_SCHEMA = """
    CREATE TABLE clients (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, contact_phone TEXT,
        email TEXT UNIQUE, bio TEXT, is_active INTEGER DEFAULT 1 CHECK(is_active IN (0, 1)),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE client_tags (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, tag_name TEXT NOT NULL,
        FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE);
    CREATE TABLE appointments (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, service_type TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0), scheduled_date TEXT NOT NULL,
        status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled', 'completed', 'cancelled')), notes TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE);
    CREATE TABLE expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, description TEXT NOT NULL,
        amount REAL NOT NULL CHECK(amount >= 0), category TEXT NOT NULL DEFAULT 'other', date TEXT NOT NULL,
        notes TEXT, created_at TEXT NOT NULL,
        FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL);
    CREATE INDEX idx_clients_active ON clients(is_active);
    CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
    CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL, FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE);
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
"""
T = "2026-11-12T18:00:00+00:00"


def old_database(with_user=True):
    """A database as the previous version of sworkr left it, with some data in it."""
    folder = tempfile.mkdtemp(prefix="sworkr-migrate-")
    path = os.path.join(folder, "sworkr.db")
    db = sqlite3.connect(path)
    db.executescript(OLD_SCHEMA)
    if with_user:
        db.execute("INSERT INTO users (username, password_hash, is_admin, created_at) VALUES ('lc', 'x', 1, ?)", (T,))
    db.execute("INSERT INTO clients VALUES (1, 'Maria', '+1-555-0101', 'maria@example.com', 'Regular', 1, ?, ?)", (T, T))
    db.execute("INSERT INTO clients VALUES (2, 'Real Person', NULL, NULL, NULL, 0, ?, ?)", (T, T))
    db.execute("INSERT INTO client_tags (client_id, tag_name) VALUES (1, 'regular'), (1, 'verified'), (99, 'orphan')")
    db.execute("INSERT INTO appointments VALUES (1, 1, 'Session', 60, '2026-11-20T20:00:00', 'scheduled', 'n', ?, ?)", (T, T))
    db.execute("INSERT INTO appointments VALUES (2, 2, 'Dinner', 120, '2026-11-21T03:00:00+00:00', 'completed', NULL, ?, ?)", (T, T))
    db.execute("INSERT INTO expenses VALUES (1, 1, 'Taxi', 20.5, 'travel', ?, NULL, ?)", (T, T))
    db.execute("INSERT INTO settings VALUES ('cal_enabled', '0')")
    db.commit()
    db.close()
    return path


def rows(path, sql, *params):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(sql, params)]
    finally:
        db.close()


def test_new_database_ends_at_latest_version_without_a_copy():
    path = os.path.join(tempfile.mkdtemp(prefix="sworkr-migrate-"), "sworkr.db")
    assert migrations.run(path) == migrations.LATEST
    assert not [n for n in os.listdir(os.path.dirname(path)) if "before" in n]
    columns = {r["name"] for r in rows(path, "PRAGMA table_info(appointments)")}
    assert {"owner_id", "rate", "amount_paid", "location", "safety_checkin", "series_id"} <= columns


def test_upgrade_keeps_every_record_and_gives_it_to_the_admin():
    path = old_database()
    assert migrations.run(path) == migrations.LATEST

    clients = rows(path, "SELECT * FROM clients ORDER BY id")
    assert [(c["id"], c["name"], c["email"], c["is_active"], c["owner_id"]) for c in clients] == [
        (1, "Maria", "maria@example.com", 1, 1), (2, "Real Person", None, 0, 1)]
    assert clients[0]["screening_status"] == "unscreened" and clients[0]["do_not_see"] == 0
    assert sorted(t["tag_name"] for t in rows(path, "SELECT tag_name FROM client_tags")) == ["regular", "verified"]

    appts = rows(path, "SELECT * FROM appointments ORDER BY id")
    assert [(a["client_id"], a["service_type"], a["status"], a["owner_id"], a["amount_paid"]) for a in appts] == [
        (1, "Session", "scheduled", 1, 0), (2, "Dinner", "completed", 1, 0)]
    assert appts[0]["scheduled_date"] == "2026-11-20T20:00:00+00:00"       # old time without a zone marked as UTC
    assert rows(path, "SELECT amount, owner_id FROM expenses") == [{"amount": 20.5, "owner_id": 1}]
    assert rows(path, "SELECT value FROM settings WHERE key LIKE 'cal%'") == []   # moved to the person (v5)
    assert rows(path, "SELECT value FROM settings WHERE key = 'seeded'") == [{"value": "1"}]
    assert rows(path, "PRAGMA foreign_key_check") == []


def test_upgrade_saves_a_copy_of_the_old_database_first():
    path = old_database()
    migrations.run(path)
    copy = os.path.join(os.path.dirname(path), f"sworkr.before-v{migrations.LATEST}.db")
    assert os.path.exists(copy)
    assert "owner_id" not in {r["name"] for r in rows(copy, "PRAGMA table_info(clients)")}
    assert len(rows(copy, "SELECT * FROM clients")) == 2


def test_running_again_changes_nothing():
    path = old_database()
    migrations.run(path)
    before = rows(path, "SELECT * FROM clients") + rows(path, "SELECT * FROM appointments")
    assert migrations.run(path) == migrations.LATEST
    assert rows(path, "SELECT * FROM clients") + rows(path, "SELECT * FROM appointments") == before


def test_new_ids_continue_after_the_old_ones():
    path = old_database()
    migrations.run(path)
    db = sqlite3.connect(path)
    cur = db.execute("INSERT INTO clients (name, display_name, owner_id, created_at, updated_at) VALUES ('New', 'New', 1, ?, ?)", (T, T))
    assert cur.lastrowid == 3
    db.close()


def test_same_email_is_allowed_for_different_owners_but_not_twice_for_one():
    path = old_database()
    migrations.run(path)
    db = sqlite3.connect(path)
    db.execute("INSERT INTO users (username, password_hash, created_at) VALUES ('second', 'x', ?)", (T,))
    db.execute("INSERT INTO clients (name, display_name, email, owner_id, created_at, updated_at) VALUES ('M2', 'M2', 'maria@example.com', 2, ?, ?)", (T, T))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO clients (name, display_name, email, owner_id, created_at, updated_at) VALUES ('M3', 'M3', 'maria@example.com', 1, ?, ?)", (T, T))
    db.close()


def test_a_failed_migration_leaves_the_database_untouched(monkeypatch):
    path = old_database()

    def broken(conn):
        conn.execute("ALTER TABLE expenses ADD COLUMN half_done TEXT")
        raise RuntimeError("boom")

    monkeypatch.setattr(migrations, "MIGRATIONS", [migrations.MIGRATIONS[0], (2, "broken", broken, True)])
    with pytest.raises(RuntimeError):
        migrations.run(path)
    assert rows(path, "PRAGMA user_version") == [{"user_version": 1}]
    assert "half_done" not in {r["name"] for r in rows(path, "PRAGMA table_info(expenses)")}
    assert len(rows(path, "SELECT * FROM clients")) == 2


def test_a_database_from_a_newer_sworkr_is_refused():
    path = old_database()
    migrations.run(path)
    db = sqlite3.connect(path)
    db.execute(f"PRAGMA user_version = {migrations.LATEST + 1}")
    db.close()
    with pytest.raises(RuntimeError, match="only knows up to"):
        migrations.run(path)


def run_app(path, script):
    """Start the real app on a database, in its own process, and run a few lines against it."""
    env = {**os.environ, "DATA_DIR": os.path.dirname(path), "KEY_DIR": vault.key_dir(), "SEED_DB": "1", "BACKGROUND_JOBS": "0", "CALENDAR_SYNC": "0"}
    code = ("from fastapi.testclient import TestClient\nimport main\napi = TestClient(main.app)\n" + script)
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout


def test_old_data_without_an_account_goes_to_the_first_account_created():
    path = old_database(with_user=False)
    out = run_app(path, """
r = api.post('/api/auth/setup', json={'username': 'lc', 'password': 'correct-horse-battery'})
assert r.status_code == 201, r.text
print(sorted(c['name'] for c in api.get('/api/clients').json()))
print(len(api.get('/api/appointments').json()), len(api.get('/api/expenses').json()))
""")
    assert out.splitlines() == ["['Maria', 'Real Person']", "2 1"]   # and no sample data was added on top


def test_sample_data_appears_once_on_a_new_database_and_never_again():
    path = os.path.join(tempfile.mkdtemp(prefix="sworkr-migrate-"), "sworkr.db")
    first = run_app(path, """
api.post('/api/auth/setup', json={'username': 'lc', 'password': 'correct-horse-battery'})
print(len(api.get('/api/clients').json()), api.get('/api/sample-data').json()['present'])
print(api.delete('/api/sample-data').json())
print(len(api.get('/api/clients').json()), len(api.get('/api/appointments').json()), len(api.get('/api/expenses').json()))
""")
    assert first.splitlines() == ["5 True", "{'clients': 5, 'appointments': 5, 'expenses': 5}", "0 0 0"]
    again = run_app(path, """
api.post('/api/auth/login', json={'username': 'lc', 'password': 'correct-horse-battery'})
print(len(api.get('/api/clients').json()), api.get('/api/sample-data').json()['present'])
""")
    assert again.splitlines() == ["0 False"]   # restarting with no clients does not bring the samples back


def test_upgrade_adds_tours_tests_and_new_expense_categories():
    path = old_database()
    migrations.run(path)
    assert rows(path, "SELECT id, description, amount, category, owner_id, tour_id, source FROM expenses") == [
        {"id": 1, "description": "Taxi", "amount": 20.5, "category": "travel", "owner_id": 1, "tour_id": None, "source": None}]
    assert {"kind", "test_type", "cost"} <= {r["name"] for r in rows(path, "PRAGMA table_info(appointments)")}
    assert {"birthday", "drink_preferences", "food_preferences"} <= {r["name"] for r in rows(path, "PRAGMA table_info(clients)")}
    assert rows(path, "SELECT DISTINCT kind FROM appointments") == [{"kind": "client"}]
    db = sqlite3.connect(path)
    try:
        for category in ("medical", "room_rent"):
            db.execute("INSERT INTO expenses (description, amount, category, date, created_at) VALUES ('x', 1, ?, ?, ?)",
                       (category, T, T))
        # Since v4 each user has their own categories, checked by the app rather than a fixed list in the table.
        db.execute("INSERT INTO expenses (description, amount, category, date, created_at) VALUES ('x', 1, 'c1a2b3c4', ?, ?)",
                   (T, T))
    finally:
        db.close()


def test_upgrade_to_v4_adds_income_goals_and_own_categories():
    path = old_database()
    migrations.run(path)
    tables = {r["name"] for r in rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"income", "income_sources", "goals", "goal_entries", "expense_categories"} <= tables
    assert rows(path, "SELECT category, currency FROM expenses") == [{"category": "travel", "currency": "USD"}]
    assert {r["currency"] for r in rows(path, "SELECT currency FROM appointments")} == {"USD"}
    assert rows(path, "PRAGMA foreign_key_check") == []


def test_upgrade_to_v5_contacts_tasks_and_personal_sync():
    path = old_database()
    db = sqlite3.connect(path)
    db.execute("UPDATE settings SET value = '1' WHERE key = 'cal_enabled'")
    db.executemany("INSERT INTO settings (key, value) VALUES (?, ?)",
                   [("cal_url", "https://cloud.example.com"), ("cal_username", "lc"), ("cal_password", "app-pw")])
    db.commit()
    db.close()
    migrations.run(path)
    clients = rows(path, "SELECT id, name, display_name, handles, industry FROM clients ORDER BY id")
    assert clients[0] == {"id": 1, "name": "Maria", "display_name": "Maria", "handles": None, "industry": None}
    assert "tasks" in {r["name"] for r in rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    moved = {r["key"]: r["value"] for r in rows(path, "SELECT key, value FROM user_settings WHERE user_id = 1")}
    assert moved["cal_url"] == "https://cloud.example.com" and moved["cal_password"] == "app-pw" and moved["cal_enabled"] == "1"
    assert rows(path, "SELECT * FROM settings WHERE key LIKE 'cal%'") == []
    assert rows(path, "PRAGMA foreign_key_check") == []


def test_upgrade_to_v6_fills_in_kinds_of_work_for_starter_places(monkeypatch):
    path = old_database()
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:5])   # stop at v5 first
    monkeypatch.setattr(migrations, "LATEST", 5)
    migrations.run(path)
    monkeypatch.undo()
    db = sqlite3.connect(path)
    db.executemany("INSERT INTO income_sources (owner_id, name, created_at, updated_at) VALUES (1, ?, ?, ?)",
                   [("OF", T, T), ("my club", T, T), ("Something else", T, T)])
    db.commit()
    db.close()
    migrations.run(path)
    assert {r["name"]: r["work_type"] for r in rows(path, "SELECT name, work_type FROM income_sources")} == {
        "OF": "content", "my club": "dancer", "Something else": None}


def test_upgrade_to_v7_partners_room_and_board_and_license_fees(monkeypatch):
    path = old_database()
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:6])
    monkeypatch.setattr(migrations, "LATEST", 6)
    migrations.run(path)
    monkeypatch.undo()
    db = sqlite3.connect(path)
    db.executemany("INSERT INTO expense_categories (owner_id, key, label, created_at) VALUES (1, ?, ?, ?)",
                   [("room_rent", "Room rent", T), ("travel", "Getting around", T)])
    db.execute("INSERT INTO expenses (description, amount, category, date, created_at, owner_id, source) "
               "VALUES ('Room rent – Chicago', 150, 'room_rent', ?, ?, 1, 'tour_room')", (T, T))
    db.execute("""INSERT INTO user_settings (user_id, key, value) VALUES (1, 'work_types', '["brothel", "cam"]')""")
    db.commit()
    db.close()
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:7])   # v7 itself (v11 renames these)
    monkeypatch.setattr(migrations, "LATEST", 7)
    migrations.run(path)
    labels = {r["key"]: r["label"] for r in rows(path, "SELECT key, label FROM expense_categories WHERE owner_id = 1")}
    assert labels["room_rent"] == "Room & board" and labels["travel"] == "Getting around"   # own names are kept
    assert "License & permit fees" in labels.values()
    assert rows(path, "SELECT description FROM expenses WHERE source = 'tour_room'") == [{"description": "Room & board – Chicago"}]
    assert rows(path, "SELECT DISTINCT role FROM clients") == [{"role": "client"}]
    tables = {r["name"] for r in rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"split_agreements", "agreement_parties", "split_records", "splits", "settlements"} <= tables


def test_upgrade_to_v11_puts_categories_in_two_levels_and_merges_duplicates(monkeypatch):
    path = old_database()
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:10])
    monkeypatch.setattr(migrations, "LATEST", 10)
    migrations.run(path)
    monkeypatch.undo()
    db = sqlite3.connect(path)
    db.executemany("INSERT INTO expense_categories (owner_id, key, label, sort_order, created_at) VALUES (1, ?, ?, ?, ?)", [
        ("marketing", "Marketing & ads", 1, T), ("travel", "Getting around", 2, T), ("medical", "Medical & tests", 3, T),
        ("equipment", "Equipment", 4, T), ("other", "Other", 5, T),
        ("c1", "Agency & booking fees", 6, T), ("c2", "Agent & booking fees", 7, T),      # the same thing twice
        ("c3", "Photo & video gear", 8, T), ("c4", "Cam gear & lighting", 9, T),
        ("c5", "Fitness & classes", 10, T), ("c6", "Shoot travel", 11, T), ("c7", "My own thing", 12, T),
        ("c8", "costumes & heels", 13, T)])
    for i, cat in enumerate(["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "marketing"]):
        db.execute("INSERT INTO expenses (description, amount, category, date, created_at, owner_id) VALUES (?, 1, ?, ?, ?, 1)",
                   (f"e{i}", cat, T, T))
    db.commit()
    db.close()
    migrations.run(path)

    cats = {r["key"]: r for r in rows(path, "SELECT key, label, parent_key, color FROM expense_categories WHERE owner_id = 1")}
    by_label = {r["label"]: r for r in cats.values()}
    # Main categories are there; old default names updated, names people chose kept.
    assert {"workspace", "fees", "health", "wardrobe", "gear", "fitness", "room_rent"} <= set(cats)
    assert cats["marketing"]["label"] == "Marketing" and cats["travel"]["label"] == "Getting around"
    assert (cats["medical"]["label"], cats["medical"]["parent_key"]) == ("Tests & doctor", "health")
    assert (cats["equipment"]["label"], cats["equipment"]["parent_key"]) == ("Equipment & toys", "gear")
    assert cats["room_rent"]["parent_key"] == "workspace"
    assert cats["equipment"]["color"] is None and cats["c7"]["color"] is None   # subcategories use their main one's
    # Duplicates merged into one subcategory, with all their expenses.
    assert by_label["Agency & booking fees"]["parent_key"] == "fees" and "c2" not in cats
    assert by_label["Camera & lighting"]["parent_key"] == "gear" and "c4" not in cats
    assert by_label["Costumes & props"]["parent_key"] == "wardrobe"
    assert "c5" not in cats and "c6" not in cats      # merged into main categories
    assert cats["c7"]["parent_key"] == "other"         # their own: kept, under Other
    spent = {r["description"]: r["category"] for r in rows(path, "SELECT description, category FROM expenses")}
    assert spent["e1"] == "c1" and spent["e3"] == "c3" and spent["e4"] == "fitness" and spent["e5"] == "travel"
    assert spent["e8"] == "marketing" and spent["e6"] == "c7"
    assert all(r["parent_key"] is None or r["parent_key"] in cats for r in cats.values())


def test_upgrade_to_v12_gives_venues_a_precise_kind(monkeypatch):
    path = old_database()
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:11])
    monkeypatch.setattr(migrations, "LATEST", 11)
    migrations.run(path)
    monkeypatch.undo()
    db = sqlite3.connect(path)
    db.executemany("INSERT INTO income_sources (owner_id, name, kind, work_type, created_at, updated_at) VALUES (1, ?, ?, ?, ?, ?)", [
        ("House", "venue", "brothel", T, T), ("Club", "venue", "dancer", T, T), ("Dungeon", "venue", "fetish", T, T),
        ("Con", "venue", "cosplay", T, T), ("Somewhere", "venue", None, T, T), ("My brothel or agency", "agency", "brothel", T, T),
        ("Real agency", "agency", "brothel", T, T), ("OF", "platform", "content", T, T)])
    db.execute("INSERT INTO income (owner_id, source_id, date, gross, created_at, updated_at) VALUES (1, 2, ?, 100, ?, ?)", (T, T, T))
    db.commit()
    db.close()
    migrations.run(path)
    kinds = {r["name"]: r["kind"] for r in rows(path, "SELECT name, kind FROM income_sources")}
    assert kinds == {"House": "brothel", "Club": "club", "Dungeon": "studio", "Con": "event", "Somewhere": "club",
                     "My brothel or agency": "brothel", "Real agency": "agency", "OF": "platform"}
    assert rows(path, "SELECT source_id FROM income") == [{"source_id": 2}]
    assert rows(path, "SELECT COUNT(*) AS n FROM place_charges") == [{"n": 0}]


def test_upgrade_to_v16_gives_brothels_a_half_share_of_gifts(monkeypatch):
    path = old_database()
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:15])
    monkeypatch.setattr(migrations, "LATEST", 15)
    migrations.run(path)
    monkeypatch.undo()
    db = sqlite3.connect(path)
    db.executemany("INSERT INTO income_sources (owner_id, name, kind, created_at, updated_at) VALUES (1, ?, ?, ?, ?)",
                   [("House", "brothel", T, T), ("Club", "club", T, T)])
    db.commit()
    db.close()
    migrations.run(path)
    assert {r["name"]: r["gift_share_percent"] for r in rows(path, "SELECT name, gift_share_percent FROM income_sources")} == {
        "House": 50, "Club": None}


def test_upgrade_to_v18_keeps_charges_and_allows_quarterly_ones(monkeypatch):
    path = old_database()
    monkeypatch.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:17])
    monkeypatch.setattr(migrations, "LATEST", 17)
    migrations.run(path)
    monkeypatch.undo()
    db = sqlite3.connect(path)
    db.execute("INSERT INTO income_sources (id, owner_id, name, kind, created_at, updated_at) VALUES (7, 1, 'House', 'brothel', ?, ?)", (T, T))
    db.execute("INSERT INTO place_charges (owner_id, source_id, label, amount, cadence, created_at, updated_at) "
               "VALUES (1, 7, 'License', 275, 'per_year', ?, ?)", (T, T))
    db.commit()
    db.close()
    migrations.run(path)
    assert rows(path, "SELECT label, cadence FROM place_charges") == [{"label": "License", "cadence": "per_year"}]
    db = sqlite3.connect(path)
    db.execute("INSERT INTO place_charges (owner_id, source_id, label, cadence, created_at, updated_at) "
               "VALUES (1, 7, 'Quarterly', 'per_quarter', ?, ?)", (T, T))
    db.commit()
    db.close()


def test_upgrade_to_v22_adds_arrangements_and_mileage():
    path = old_database()
    migrations.run(path)
    tables = {r["name"] for r in rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"arrangements", "mileage", "tax_payments", "passkeys", "auth_challenges"} <= tables
