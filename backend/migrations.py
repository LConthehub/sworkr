"""
Database migrations.

The database remembers which version it is at (SQLite's `user_version`). At startup every
migration with a higher number runs, in order, each in its own transaction: a migration either
applies completely or not at all. Before upgrading a database that already has data, a copy is
saved next to it as `sworkr.before-v<N>.db`, so an upgrade can always be undone by hand.

To change the schema: add a function and append it to MIGRATIONS. Never edit a migration that
has already shipped; add a new one instead.
"""

import logging
import os
import dbfile as sqlite3

log = logging.getLogger("sworkr.migrations")


# ==================== MIGRATIONS ====================

def _m1_baseline(conn):
    """The original tables. Every statement is 'IF NOT EXISTS', so this is safe on any old database."""
    for statement in """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            contact_phone TEXT,
            email TEXT UNIQUE,
            bio TEXT,
            is_active INTEGER DEFAULT 1 CHECK(is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS client_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            tag_name TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            service_type TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
            scheduled_date TEXT NOT NULL,
            status TEXT DEFAULT 'scheduled' CHECK(status IN ('scheduled', 'completed', 'cancelled')),
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            description TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount >= 0),
            category TEXT NOT NULL DEFAULT 'other' CHECK(category IN ('equipment', 'marketing', 'travel', 'cleaning', 'other')),
            date TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_clients_active ON clients(is_active);
        CREATE INDEX IF NOT EXISTS idx_appointments_client ON appointments(client_id);
        CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(scheduled_date);
        CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category);
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)
    """.split(";"):
        conn.execute(statement)

    # Very old versions stored UTC times without a timezone. Mark them as UTC explicitly.
    for table, cols in {"clients": ["created_at", "updated_at"],
                        "appointments": ["scheduled_date", "created_at", "updated_at"],
                        "expenses": ["date", "created_at"]}.items():
        for col in cols:
            conn.execute(f"""
                UPDATE {table} SET {col} = {col} || '+00:00'
                WHERE {col} IS NOT NULL AND {col} NOT LIKE '%+%' AND {col} NOT LIKE '%Z'
                  AND substr({col}, 11, 1) = 'T' AND length({col}) >= 19
            """)


def _m2_owners_money_screening_safety(conn):
    """
    - Every client, appointment and expense belongs to a user (owner_id).
    - Clients: screening status, references, and a "do not see" flag. The same email may now be used
      by different users' clients (it used to be unique across the whole database).
    - Appointments: rate and amount paid, location, safety check-in, and a series id for repeats.
    - Dated notes per client, and per-user settings.
    - Sessions remember when they were last used, for automatic log-out.
    """
    # SQLite can't drop the old UNIQUE(email), so the clients table is rebuilt.
    conn.execute("""
        CREATE TABLE clients_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER REFERENCES users(id),
            name TEXT NOT NULL,
            contact_phone TEXT,
            email TEXT,
            bio TEXT,
            is_active INTEGER DEFAULT 1 CHECK(is_active IN (0, 1)),
            screening_status TEXT NOT NULL DEFAULT 'unscreened'
                CHECK(screening_status IN ('unscreened', 'pending', 'verified', 'declined')),
            screening_notes TEXT,
            references_text TEXT,
            do_not_see INTEGER NOT NULL DEFAULT 0 CHECK(do_not_see IN (0, 1)),
            do_not_see_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO clients_new (id, name, contact_phone, email, bio, is_active, created_at, updated_at)
        SELECT id, name, contact_phone, email, bio, is_active, created_at, updated_at FROM clients
    """)
    conn.execute("DROP TABLE clients")
    conn.execute("ALTER TABLE clients_new RENAME TO clients")
    conn.execute("CREATE INDEX idx_clients_active ON clients(is_active)")
    conn.execute("CREATE INDEX idx_clients_owner ON clients(owner_id)")
    conn.execute("""
        CREATE UNIQUE INDEX idx_clients_owner_email ON clients(COALESCE(owner_id, 0), email)
        WHERE email IS NOT NULL
    """)

    for column in (
        "owner_id INTEGER REFERENCES users(id)",
        "rate REAL",
        "amount_paid REAL NOT NULL DEFAULT 0",
        "payment_method TEXT",
        "location_type TEXT",
        "location TEXT",
        "safety_checkin INTEGER NOT NULL DEFAULT 0",
        "checked_in_at TEXT",
        "alert_sent_at TEXT",
        "alert_error TEXT",
        "series_id TEXT",
    ):
        conn.execute(f"ALTER TABLE appointments ADD COLUMN {column}")
    conn.execute("CREATE INDEX idx_appointments_owner ON appointments(owner_id, scheduled_date)")

    conn.execute("ALTER TABLE expenses ADD COLUMN owner_id INTEGER REFERENCES users(id)")
    conn.execute("CREATE INDEX idx_expenses_owner ON expenses(owner_id, date)")

    conn.execute("""
        CREATE TABLE client_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            owner_id INTEGER REFERENCES users(id),
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_client_notes_client ON client_notes(client_id, created_at)")

    conn.execute("""
        CREATE TABLE user_settings (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (user_id, key)
        )
    """)

    conn.execute("ALTER TABLE sessions ADD COLUMN last_seen_at TEXT")

    # Tidy up links to clients that no longer exist, so the rebuilt table has no dangling references.
    conn.execute("DELETE FROM client_tags WHERE client_id NOT IN (SELECT id FROM clients)")
    conn.execute("UPDATE appointments SET client_id = NULL "
                 "WHERE client_id IS NOT NULL AND client_id NOT IN (SELECT id FROM clients)")
    conn.execute("UPDATE expenses SET client_id = NULL "
                 "WHERE client_id IS NOT NULL AND client_id NOT IN (SELECT id FROM clients)")
    conn.execute("DELETE FROM sessions WHERE user_id NOT IN (SELECT id FROM users)")

    # Everything that already exists belongs to the first admin (there has only ever been one account).
    # If no account exists yet, the rows stay unowned and are handed to the first account at setup.
    owner = conn.execute("SELECT id FROM users ORDER BY is_admin DESC, id LIMIT 1").fetchone()
    if owner:
        for table in ("clients", "appointments", "expenses"):
            conn.execute(f"UPDATE {table} SET owner_id = ? WHERE owner_id IS NULL", (owner[0],))

    # Sample data is only ever added to a brand-new database. One that already has data is past that.
    if conn.execute("SELECT 1 FROM clients LIMIT 1").fetchone() or owner:
        conn.execute("INSERT INTO settings (key, value) VALUES ('seeded', '1') "
                     "ON CONFLICT(key) DO UPDATE SET value = '1'")


def _m3_tours_tests_preferences(conn):
    """
    - Tours and time off (days off, vacations): periods on the calendar.
    - Expenses: new categories 'medical' and 'room_rent', and links to a tour, to the health test that
      created them, and whether sworkr generated them (room rent per tour day).
    - Appointments: a kind ('client' or 'test' for a health test), the test type and its cost.
    - Clients: birthday, drink and food preferences.
    """
    conn.execute("""
        CREATE TABLE tours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER REFERENCES users(id),
            kind TEXT NOT NULL DEFAULT 'tour' CHECK(kind IN ('tour', 'time_off')),
            time_off_type TEXT CHECK(time_off_type IS NULL OR time_off_type IN ('day_off', 'vacation')),
            name TEXT,
            location TEXT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            room_rent_per_day REAL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_tours_owner ON tours(owner_id, starts_at)")

    for column in ("kind TEXT NOT NULL DEFAULT 'client'", "test_type TEXT", "cost REAL"):
        conn.execute(f"ALTER TABLE appointments ADD COLUMN {column}")

    for column in ("birthday TEXT", "drink_preferences TEXT", "food_preferences TEXT"):
        conn.execute(f"ALTER TABLE clients ADD COLUMN {column}")

    # SQLite can't change a CHECK constraint, so the expenses table is rebuilt with the new categories.
    conn.execute("""
        CREATE TABLE expenses_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount >= 0),
            category TEXT NOT NULL DEFAULT 'other' CHECK(category IN
                ('equipment', 'marketing', 'travel', 'cleaning', 'medical', 'room_rent', 'other')),
            date TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            tour_id INTEGER REFERENCES tours(id) ON DELETE SET NULL,
            appointment_id INTEGER REFERENCES appointments(id) ON DELETE CASCADE,
            source TEXT
        )
    """)
    conn.execute("""
        INSERT INTO expenses_new (id, client_id, description, amount, category, date, notes, created_at, owner_id)
        SELECT id, client_id, description, amount, category, date, notes, created_at, owner_id FROM expenses
    """)
    conn.execute("DROP TABLE expenses")
    conn.execute("ALTER TABLE expenses_new RENAME TO expenses")
    conn.execute("CREATE INDEX idx_expenses_category ON expenses(category)")
    conn.execute("CREATE INDEX idx_expenses_owner ON expenses(owner_id, date)")
    conn.execute("CREATE INDEX idx_expenses_tour ON expenses(tour_id)")
    conn.execute("CREATE INDEX idx_expenses_appointment ON expenses(appointment_id)")


def _m4_income_goals_categories(conn):
    """
    - Places you earn (venues, platforms, agencies) with their fee rules.
    - Income that isn't a booking: payouts, tips, sales, shifts. Gross, fees, and whether it's been paid out.
    - Savings goals and the money put into (or taken out of) them.
    - Each user's own expense categories. The fixed list is gone from the expenses table (so it's rebuilt),
      and categories are checked against the user's own list instead.
    - Every amount gets a currency. Only USD is used for now; the column makes adding others easier later.
    """
    conn.execute("""
        CREATE TABLE expense_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            label TEXT NOT NULL,
            color TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0, 1)),
            created_at TEXT NOT NULL,
            UNIQUE (owner_id, key)
        )
    """)
    conn.execute("""
        CREATE TABLE income_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'other' CHECK(kind IN ('venue', 'platform', 'agency', 'phone', 'other')),
            fee_percent REAL CHECK(fee_percent IS NULL OR (fee_percent >= 0 AND fee_percent <= 100)),
            fee_per_shift REAL CHECK(fee_per_shift IS NULL OR fee_per_shift >= 0),
            token_value REAL CHECK(token_value IS NULL OR token_value >= 0),
            payout_note TEXT,
            notes TEXT,
            currency TEXT NOT NULL DEFAULT 'USD',
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_income_sources_owner ON income_sources(owner_id)")
    conn.execute("""
        CREATE TABLE income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source_id INTEGER REFERENCES income_sources(id) ON DELETE SET NULL,
            date TEXT NOT NULL,
            description TEXT,
            kind TEXT NOT NULL DEFAULT 'other',
            tokens REAL CHECK(tokens IS NULL OR tokens >= 0),
            gross REAL NOT NULL CHECK(gross >= 0),
            fees REAL NOT NULL DEFAULT 0 CHECK(fees >= 0),
            status TEXT NOT NULL DEFAULT 'received' CHECK(status IN ('received', 'pending')),
            payout_date TEXT,
            notes TEXT,
            currency TEXT NOT NULL DEFAULT 'USD',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_income_owner ON income(owner_id, date)")
    conn.execute("""
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'savings' CHECK(kind IN ('savings', 'tax')),
            target_amount REAL CHECK(target_amount IS NULL OR target_amount > 0),
            target_date TEXT,
            rule_type TEXT NOT NULL DEFAULT 'none' CHECK(rule_type IN ('none', 'percent', 'weekly', 'per_booking')),
            rule_amount REAL CHECK(rule_amount IS NULL OR rule_amount >= 0),
            starts_on TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            color TEXT,
            notes TEXT,
            currency TEXT NOT NULL DEFAULT 'USD',
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_goals_owner ON goals(owner_id)")
    conn.execute("""
        CREATE TABLE goal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_goal_entries_goal ON goal_entries(goal_id, date)")

    conn.execute("ALTER TABLE appointments ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")

    # The expenses table without the fixed category list, and with a currency.
    conn.execute("""
        CREATE TABLE expenses_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount >= 0),
            category TEXT NOT NULL DEFAULT 'other',
            date TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            owner_id INTEGER REFERENCES users(id),
            tour_id INTEGER REFERENCES tours(id) ON DELETE SET NULL,
            appointment_id INTEGER REFERENCES appointments(id) ON DELETE CASCADE,
            source TEXT,
            currency TEXT NOT NULL DEFAULT 'USD'
        )
    """)
    conn.execute("""
        INSERT INTO expenses_new (id, client_id, description, amount, category, date, notes, created_at, owner_id,
                                  tour_id, appointment_id, source)
        SELECT id, client_id, description, amount, category, date, notes, created_at, owner_id,
               tour_id, appointment_id, source FROM expenses
    """)
    conn.execute("DROP TABLE expenses")
    conn.execute("ALTER TABLE expenses_new RENAME TO expenses")
    conn.execute("CREATE INDEX idx_expenses_category ON expenses(category)")
    conn.execute("CREATE INDEX idx_expenses_owner ON expenses(owner_id, date)")
    conn.execute("CREATE INDEX idx_expenses_tour ON expenses(tour_id)")
    conn.execute("CREATE INDEX idx_expenses_appointment ON expenses(appointment_id)")


def _m5_contacts_tasks_personal_sync(conn):
    """
    - Clients become contacts: the name is optional, they can have social media handles, they can be shown
      by one of those handles, and they have an industry. `display_name` is what they're shown as everywhere.
      SQLite can't drop NOT NULL from `name`, so the table is rebuilt.
    - Tasks: a simple to-do list.
    - Calendar sync is per person now: the shared settings move to the account that set them up.
    """
    conn.execute("""
        CREATE TABLE clients_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER REFERENCES users(id),
            name TEXT,
            display_name TEXT NOT NULL,
            handles TEXT,
            display_handle INTEGER,
            industry TEXT,
            contact_phone TEXT,
            email TEXT,
            bio TEXT,
            is_active INTEGER DEFAULT 1 CHECK(is_active IN (0, 1)),
            screening_status TEXT NOT NULL DEFAULT 'unscreened'
                CHECK(screening_status IN ('unscreened', 'pending', 'verified', 'declined')),
            screening_notes TEXT,
            references_text TEXT,
            do_not_see INTEGER NOT NULL DEFAULT 0 CHECK(do_not_see IN (0, 1)),
            do_not_see_reason TEXT,
            birthday TEXT,
            drink_preferences TEXT,
            food_preferences TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        INSERT INTO clients_new (id, owner_id, name, display_name, contact_phone, email, bio, is_active, screening_status,
                                 screening_notes, references_text, do_not_see, do_not_see_reason, birthday,
                                 drink_preferences, food_preferences, created_at, updated_at)
        SELECT id, owner_id, name, name, contact_phone, email, bio, is_active, screening_status,
               screening_notes, references_text, do_not_see, do_not_see_reason, birthday,
               drink_preferences, food_preferences, created_at, updated_at FROM clients
    """)
    conn.execute("DROP TABLE clients")
    conn.execute("ALTER TABLE clients_new RENAME TO clients")
    conn.execute("CREATE INDEX idx_clients_active ON clients(is_active)")
    conn.execute("CREATE INDEX idx_clients_owner ON clients(owner_id)")
    conn.execute("""
        CREATE UNIQUE INDEX idx_clients_owner_email ON clients(COALESCE(owner_id, 0), email)
        WHERE email IS NOT NULL
    """)

    conn.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            notes TEXT,
            due_date TEXT,
            due_at TEXT,
            done_at TEXT,
            client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            tour_id INTEGER REFERENCES tours(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_tasks_owner ON tasks(owner_id, done_at, due_date)")

    # Calendar sync settings: from one shared set to the person who set it up.
    shared = {k: v for k, v in conn.execute("SELECT key, value FROM settings WHERE key LIKE 'cal\\_%' ESCAPE '\\'")}
    owner = shared.get("cal_owner_id")
    if not (owner and owner.isdigit()):
        row = conn.execute("SELECT id FROM users ORDER BY is_admin DESC, id LIMIT 1").fetchone()
        owner = str(row[0]) if row else None
    if owner and shared.get("cal_url"):
        for key in ("cal_enabled", "cal_url", "cal_username", "cal_password", "cal_discreet", "cal_last_sync_at"):
            if shared.get(key) is not None:
                conn.execute("INSERT OR REPLACE INTO user_settings (user_id, key, value) VALUES (?, ?, ?)",
                             (int(owner), key, shared[key]))
    conn.execute("DELETE FROM settings WHERE key LIKE 'cal\\_%' ESCAPE '\\'")


def _m6_source_work_types(conn):
    """Each place you earn can say which kind of work it's for (dancer, cam, content…), so income can be
    compared between kinds of work. Places added from a starter setup get theirs filled in."""
    import json
    conn.execute("ALTER TABLE income_sources ADD COLUMN work_type TEXT")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json")
    try:
        with open(path, encoding="utf-8") as f:
            presets = json.load(f)["work_types"]
    except (OSError, ValueError, KeyError):
        return
    for key, preset in presets.items():
        for source in preset.get("sources", []):
            conn.execute("UPDATE income_sources SET work_type = ? WHERE work_type IS NULL AND LOWER(name) = LOWER(?)",
                         (key, source["name"]))


def _m7_partners_splits_room_board(conn):
    """
    - Contacts get a role: client, partner (another worker), crew (photographer, driver…) or other.
    - Splitting money with partners, kept privately: which partners share a booking, income or cost and how
      much each gets, who collected or paid the money, reusable split agreements, and settle-up payments.
    - "Room rent" is now "Room & board" (renamed only where nobody has renamed it themselves).
    - Brothel and agency workers get a "License & permit fees" expense category.
    """
    conn.execute("ALTER TABLE clients ADD COLUMN role TEXT NOT NULL DEFAULT 'client'")
    conn.execute("""
        CREATE TABLE split_agreements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            notes TEXT,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE agreement_parties (
            agreement_id INTEGER NOT NULL REFERENCES split_agreements(id) ON DELETE CASCADE,
            partner_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            booking_pct REAL NOT NULL DEFAULT 0 CHECK(booking_pct >= 0 AND booking_pct <= 100),
            content_pct REAL NOT NULL DEFAULT 0 CHECK(content_pct >= 0 AND content_pct <= 100),
            costs_pct REAL NOT NULL DEFAULT 0 CHECK(costs_pct >= 0 AND costs_pct <= 100),
            PRIMARY KEY (agreement_id, partner_id)
        )
    """)
    # One row per booking, income or expense that's shared: who handled the money (NULL = you).
    conn.execute("""
        CREATE TABLE split_records (
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            record_type TEXT NOT NULL CHECK(record_type IN ('appointment', 'income', 'expense')),
            record_id INTEGER NOT NULL,
            handled_by INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            agreement_id INTEGER REFERENCES split_agreements(id) ON DELETE SET NULL,
            PRIMARY KEY (record_type, record_id)
        )
    """)
    conn.execute("""
        CREATE TABLE splits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            record_type TEXT NOT NULL CHECK(record_type IN ('appointment', 'income', 'expense')),
            record_id INTEGER NOT NULL,
            partner_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            share_type TEXT NOT NULL CHECK(share_type IN ('percent', 'amount')),
            share_value REAL NOT NULL CHECK(share_value >= 0)
        )
    """)
    conn.execute("CREATE INDEX idx_splits_record ON splits(record_type, record_id)")
    conn.execute("CREATE INDEX idx_splits_partner ON splits(partner_id)")
    conn.execute("""
        CREATE TABLE settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            partner_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            direction TEXT NOT NULL CHECK(direction IN ('paid_them', 'they_paid')),
            note TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_settlements_partner ON settlements(partner_id, date)")

    conn.execute("UPDATE expense_categories SET label = 'Room & board' WHERE key = 'room_rent' AND label = 'Room rent'")
    conn.execute("UPDATE expenses SET description = 'Room & board' || substr(description, 10) "
                 "WHERE source = 'tour_room' AND description LIKE 'Room rent%'")
    for (user_id, value) in conn.execute("SELECT user_id, value FROM user_settings WHERE key = 'work_types'").fetchall():
        if value and '"brothel"' in value and not conn.execute(
                "SELECT 1 FROM expense_categories WHERE owner_id = ? AND LOWER(label) = 'license & permit fees'", (user_id,)).fetchone():
            count = conn.execute("SELECT COUNT(*) FROM expense_categories WHERE owner_id = ?", (user_id,)).fetchone()[0]
            conn.execute("INSERT INTO expense_categories (owner_id, key, label, color, sort_order, created_at) "
                         "VALUES (?, ?, 'License & permit fees', '#b45309', ?, datetime('now'))",
                         (user_id, "c" + os.urandom(4).hex(), count))


def _m8_posts(conn):
    """Planned and posted social media and fan site posts, pointing at files in the person's content library
    (their Nextcloud, Synology, WebDAV or mounted folder; the files themselves are never stored in sworkr)."""
    conn.execute("""
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform TEXT NOT NULL,
            account TEXT,
            scheduled_at TEXT,
            status TEXT NOT NULL DEFAULT 'idea' CHECK(status IN ('idea', 'ready', 'scheduled', 'posted', 'skipped')),
            caption TEXT,
            price REAL CHECK(price IS NULL OR price >= 0),
            set_path TEXT,
            file_paths TEXT,
            posted_at TEXT,
            post_url TEXT,
            notes TEXT,
            series_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_posts_owner ON posts(owner_id, scheduled_at)")


def _m9_couples(conn):
    """Couples: two client contacts can be linked, and a booking can include both people."""
    conn.execute("ALTER TABLE clients ADD COLUMN couple_with INTEGER REFERENCES clients(id) ON DELETE SET NULL")
    conn.execute("ALTER TABLE appointments ADD COLUMN second_client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL")


def _m10_cycle(conn):
    """Cycle tracking (opt-in, private): logged periods. Predictions are worked out from these, not stored."""
    conn.execute("""
        CREATE TABLE cycle_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            start_date TEXT NOT NULL,
            end_date TEXT,
            flow TEXT CHECK(flow IS NULL OR flow IN ('light', 'medium', 'heavy')),
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_cycle_owner ON cycle_entries(owner_id, start_date)")


# The two-level expense categories as v11 left them. (finance.py has the live copy; this one must never change.)
_V11_TOPS = [
    ("workspace", "Workspace", "#c2410c"), ("fees", "Fees & licenses", "#b45309"),
    ("health", "Health & safety", "#0f9488"), ("wardrobe", "Look & wardrobe", "#fc4c9c"),
    ("gear", "Gear & tech", "#7c3aed"), ("marketing", "Marketing", "#e67eb6"), ("travel", "Travel", "#a73178"),
    ("fitness", "Fitness & training", "#65a30d"), ("other", "Other", "#4b86a6"),
]
_V11_SUBS = [("room_rent", "Room & board", "workspace"), ("cleaning", "Cleaning & laundry", "workspace"),
             ("medical", "Tests & doctor", "health"), ("equipment", "Equipment & toys", "gear")]
_V11_OLD_LABELS = {"marketing": "Marketing & ads", "medical": "Medical & tests", "equipment": "Equipment"}
# What each old starter category becomes: a built-in key to merge into, or (parent, new label).
_V11_RENAMES = {
    "license & permit fees": ("fees", "Licenses & permits"),
    "agency & booking fees": ("fees", "Agency & booking fees"),
    "agent & booking fees": ("fees", "Agency & booking fees"),
    "lingerie & outfits": ("wardrobe", "Lingerie & outfits"),
    "makeup & beauty": ("wardrobe", "Makeup & beauty"),
    "wardrobe & grooming": ("wardrobe", "Makeup & beauty"),
    "costumes & heels": ("wardrobe", "Costumes & props"),
    "costumes & toys": ("wardrobe", "Costumes & props"),
    "costumes & props": ("wardrobe", "Costumes & props"),
    "props & outfits": ("wardrobe", "Costumes & props"),
    "wigs & makeup": ("wardrobe", "Wigs & hair"),
    "latex & leather": ("wardrobe", "Latex & leather"),
    "ads & verification": ("marketing", "Ads & verification"),
    "photographers & shoots": ("marketing", "Photographers & shoots"),
    "promotion": ("marketing", "Promotion"),
    "prints & merch": ("marketing", "Prints & merch"),
    "incall rent": ("workspace", "Incall rent"),
    "dungeon rental": ("workspace", "Dungeon & studio hire"),
    "screening & safety": ("health", "Screening & safety"),
    "cam gear & lighting": ("gear", "Camera & lighting"),
    "photo & video gear": ("gear", "Camera & lighting"),
    "internet & tech": ("gear", "Phone & internet"),
    "phone & internet": ("gear", "Phone & internet"),
    "editing apps": ("gear", "Apps & software"),
    "convention fees": ("travel", "Conventions & events"),
    "fitness & classes": "fitness",
    "shoot travel": "travel",
    "equipment & gear": "equipment",
}


def _m11_category_groups(conn):
    """Expense categories get two levels: a few main ones everyone has (Workspace, Fees & licenses, …) with
    subcategories under them. The old starter categories, which overlapped a lot, are renamed into
    subcategories and duplicates are merged (their expenses move with them). Anything else someone made
    becomes a subcategory of Other. Names people chose themselves are kept."""
    conn.execute("ALTER TABLE expense_categories ADD COLUMN parent_key TEXT")
    owners = [r[0] for r in conn.execute("SELECT DISTINCT owner_id FROM expense_categories").fetchall()]
    builtin = {k for k, _, _ in _V11_TOPS} | {k for k, _, _ in _V11_SUBS}

    for owner in owners:
        def key_for_label(label, but=None):
            r = conn.execute("SELECT key FROM expense_categories WHERE owner_id = ? AND LOWER(label) = LOWER(?) AND key IS NOT ?",
                             (owner, label, but)).fetchone()
            return r[0] if r else None

        def merge(from_key, into_key):
            conn.execute("UPDATE expenses SET category = ? WHERE owner_id = ? AND category = ?", (into_key, owner, from_key))
            conn.execute("UPDATE expense_categories SET parent_key = ? WHERE owner_id = ? AND parent_key = ?", (into_key, owner, from_key))
            conn.execute("DELETE FROM expense_categories WHERE owner_id = ? AND key = ?", (owner, from_key))

        def put(key, label, color, parent):
            if conn.execute("SELECT 1 FROM expense_categories WHERE owner_id = ? AND key = ?", (owner, key)).fetchone():
                conn.execute("UPDATE expense_categories SET parent_key = ? WHERE owner_id = ? AND key = ?", (parent, owner, key))
                if parent:   # subcategories show their main category's colour
                    conn.execute("UPDATE expense_categories SET color = NULL WHERE owner_id = ? AND key = ?", (owner, key))
                if key in _V11_OLD_LABELS:   # only the old default name; a name someone chose stays
                    conn.execute("UPDATE expense_categories SET label = ? WHERE owner_id = ? AND key = ? AND label = ?",
                                 (label, owner, key, _V11_OLD_LABELS[key]))
            else:
                # Someone may already have made a category with this name: it becomes this one.
                clash = key_for_label(label)
                conn.execute("INSERT INTO expense_categories (owner_id, key, label, color, parent_key, created_at) "
                             "VALUES (?, ?, ?, ?, ?, datetime('now'))", (owner, key, f"{label} ({key})", color, parent))
                if clash and clash not in builtin:
                    merge(clash, key)
                elif clash:   # a built-in already uses the name (renamed by hand): keep both, this one marked
                    return
                conn.execute("UPDATE expense_categories SET label = ? WHERE owner_id = ? AND key = ?", (label, owner, key))

        for key, label, color in _V11_TOPS:
            put(key, label, color, None)
        for key, label, parent in _V11_SUBS:
            put(key, label, None, parent)

        for key, label in conn.execute("SELECT key, label FROM expense_categories WHERE owner_id = ? ORDER BY sort_order, id",
                                       (owner,)).fetchall():
            if key in builtin:
                continue
            target = _V11_RENAMES.get(label.strip().lower())
            if isinstance(target, str):
                merge(key, target)
            elif target:
                parent, new_label = target
                existing = key_for_label(new_label, but=key)
                if existing:
                    merge(key, existing)
                else:
                    conn.execute("UPDATE expense_categories SET label = ?, parent_key = ?, color = NULL WHERE owner_id = ? AND key = ?",
                                 (new_label, parent, owner, key))
            else:
                conn.execute("UPDATE expense_categories SET parent_key = 'other', color = NULL WHERE owner_id = ? AND key = ?",
                             (owner, key))

        # Main categories in the fixed order, then each one's subcategories in the order they had.
        for order, (key, _, _) in enumerate(_V11_TOPS):
            conn.execute("UPDATE expense_categories SET sort_order = ? WHERE owner_id = ? AND key = ?", (order, owner, key))
        subs = conn.execute("SELECT key FROM expense_categories WHERE owner_id = ? AND parent_key IS NOT NULL ORDER BY sort_order, id",
                            (owner,)).fetchall()
        for order, (key,) in enumerate(subs):
            conn.execute("UPDATE expense_categories SET sort_order = ? WHERE owner_id = ? AND key = ?", (100 + order, owner, key))


def _m12_place_kinds_and_charges(conn):
    """Places get more precise kinds (brothel, club, studio, event instead of one 'venue'), and each place can
    have charges you pay it: room & board, a doctor, a license, room hire. Charges are logged as expenses (a
    doctor's visit as a health test), and a license with a renewal date gets a reminder task."""
    old_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'income_sources'").fetchone()[0]
    old_check = "CHECK(kind IN ('venue', 'platform', 'agency', 'phone', 'other'))"
    assert old_check in old_sql
    new_sql = old_sql.replace(old_check, "CHECK(kind IN ('brothel', 'club', 'agency', 'platform', 'phone', 'studio', 'event', 'other'))")
    conn.execute(new_sql.replace("CREATE TABLE income_sources", "CREATE TABLE income_sources_new", 1))
    columns = ", ".join(r[1] for r in conn.execute("PRAGMA table_info(income_sources)"))
    conn.execute(f"""
        INSERT INTO income_sources_new ({columns})
        SELECT {columns.replace("kind", "CASE WHEN kind = 'venue' THEN CASE work_type WHEN 'brothel' THEN 'brothel' "
                                "WHEN 'fetish' THEN 'studio' WHEN 'cosplay' THEN 'event' ELSE 'club' END "
                                "WHEN kind = 'agency' AND work_type = 'brothel' AND name = 'My brothel or agency' THEN 'brothel' "
                                "ELSE kind END", 1)}
        FROM income_sources
    """)
    conn.execute("DROP TABLE income_sources")
    conn.execute("ALTER TABLE income_sources_new RENAME TO income_sources")
    conn.execute("CREATE INDEX idx_income_sources_owner ON income_sources(owner_id)")

    conn.execute("""
        CREATE TABLE place_charges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES income_sources(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            amount REAL CHECK(amount IS NULL OR amount >= 0),
            cadence TEXT NOT NULL CHECK(cadence IN ('per_booking', 'per_shift', 'per_day', 'per_week', 'per_month',
                                                    'per_year', 'per_stay', 'once')),
            category TEXT NOT NULL DEFAULT 'other',
            test_type TEXT CHECK(test_type IS NULL OR test_type IN ('weekly', 'monthly', 'yearly')),
            renews_on TEXT,
            task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_place_charges_source ON place_charges(source_id)")


def _m13_stays(conn):
    """A tour can be a stay at one of your places (a brothel, a club, a convention): the place's daily,
    weekly, monthly and per-stay charges are then logged for it. Health tests made that way remember their stay."""
    conn.execute("ALTER TABLE tours ADD COLUMN source_id INTEGER REFERENCES income_sources(id) ON DELETE SET NULL")
    conn.execute("ALTER TABLE appointments ADD COLUMN from_tour_id INTEGER REFERENCES tours(id) ON DELETE CASCADE")


def _m14_personas(conn):
    """Personas: the names someone works under. Contacts, places you earn and posts can each name one."""
    conn.execute("""
        CREATE TABLE personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            color TEXT,
            notes TEXT,
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_personas_owner ON personas(owner_id)")
    for table in ("clients", "income_sources", "posts"):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN persona_id INTEGER REFERENCES personas(id) ON DELETE SET NULL")


def _m15_blocklist(conn):
    """A bad-date list: people to warn about or refuse, matched by phone, email or handle."""
    conn.execute("""
        CREATE TABLE blocklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            phone TEXT,
            phone_key TEXT,
            email TEXT,
            handle TEXT,
            name TEXT,
            description TEXT,
            area TEXT,
            reported_on TEXT,
            severity TEXT NOT NULL DEFAULT 'warn' CHECK(severity IN ('warn', 'block')),
            list_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    for column in ("phone_key", "email", "handle", "list_name"):
        conn.execute(f"CREATE INDEX idx_blocklist_{column} ON blocklist(owner_id, {column})")


def _m16_gifts_and_allowances(conn):
    """Gifts and allowances: income can name the contact it came from, and a place can take a share of gifts
    (a brothel usually charges half a gift's value). Brothels start at 50%."""
    conn.execute("ALTER TABLE income ADD COLUMN client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL")
    conn.execute("ALTER TABLE income_sources ADD COLUMN gift_share_percent REAL "
                 "CHECK(gift_share_percent IS NULL OR (gift_share_percent >= 0 AND gift_share_percent <= 100))")
    conn.execute("UPDATE income_sources SET gift_share_percent = 50 WHERE kind = 'brothel'")


def _m17_meds(conn):
    """Birth control and regular meds (opt-in, private): what you take and on what rhythm, and a short log."""
    conn.execute("""
        CREATE TABLE med_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            method TEXT NOT NULL,
            started_on TEXT,
            replace_by TEXT,
            refill_every_days INTEGER,
            cost REAL CHECK(cost IS NULL OR cost >= 0),
            discreet INTEGER NOT NULL DEFAULT 1 CHECK(discreet IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
            notes TEXT,
            task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE med_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            med_id INTEGER NOT NULL REFERENCES med_schedules(id) ON DELETE CASCADE,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('taken', 'missed', 'changed', 'refilled')),
            note TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_med_logs ON med_logs(med_id, date)")


def _m18_quarterly_charges(conn):
    """Charges can come every quarter (some places license workers quarterly, not yearly)."""
    old_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'place_charges'").fetchone()[0]
    old = "'per_month',\n                                                    'per_year'"
    assert old in old_sql, "place_charges is not as v12 made it"
    new_sql = old_sql.replace(old, "'per_month',\n                                                    'per_quarter', 'per_year'")
    conn.execute(new_sql.replace("CREATE TABLE place_charges", "CREATE TABLE place_charges_new", 1))
    columns = ", ".join(r[1] for r in conn.execute("PRAGMA table_info(place_charges)"))
    conn.execute(f"INSERT INTO place_charges_new ({columns}) SELECT {columns} FROM place_charges")
    conn.execute("DROP TABLE place_charges")
    conn.execute("ALTER TABLE place_charges_new RENAME TO place_charges")
    conn.execute("CREATE INDEX idx_place_charges_source ON place_charges(source_id)")


def _m19_documents(conn):
    """Documents that expire (licenses, work cards, ID, platform verification), with a reminder before."""
    conn.execute("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'other',
            issued_on TEXT,
            expires_on TEXT,
            remind_days_before INTEGER NOT NULL DEFAULT 30,
            source_id INTEGER REFERENCES income_sources(id) ON DELETE SET NULL,
            persona_id INTEGER REFERENCES personas(id) ON DELETE SET NULL,
            notes TEXT,
            task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_documents_owner ON documents(owner_id, expires_on)")


def _m20_cancellations(conn):
    """A cancelled booking says who cancelled it (client in time, late, a no-show, or you) and any fee owed."""
    conn.execute("ALTER TABLE appointments ADD COLUMN cancel_reason TEXT "
                 "CHECK(cancel_reason IS NULL OR cancel_reason IN ('client', 'late', 'no_show', 'me'))")
    conn.execute("ALTER TABLE appointments ADD COLUMN cancellation_fee REAL CHECK(cancellation_fee IS NULL OR cancellation_fee >= 0)")


def _m21_tax_payments_passkeys_two_step(conn):
    """Estimated tax payments (US quarterly), passkeys, and two-step sign-in with an emailed code."""
    conn.execute("""
        CREATE TABLE tax_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            year INTEGER NOT NULL,
            quarter INTEGER NOT NULL CHECK(quarter BETWEEN 1 AND 4),
            authority TEXT NOT NULL DEFAULT 'federal' CHECK(authority IN ('federal', 'state')),
            amount REAL NOT NULL CHECK(amount >= 0),
            paid_on TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_tax_payments_owner ON tax_payments(owner_id, year)")
    conn.execute("""
        CREATE TABLE passkeys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            credential_id TEXT NOT NULL UNIQUE,
            public_key TEXT NOT NULL,
            sign_count INTEGER NOT NULL DEFAULT 0,
            transports TEXT,
            rp_id TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT
        )
    """)
    # Short-lived: a sign-in code waiting to be typed, or a passkey challenge waiting for the browser.
    conn.execute("""
        CREATE TABLE auth_challenges (
            token_hash TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            secret TEXT NOT NULL,
            data TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT NOT NULL
        )
    """)


def _m22_arrangements_mileage(conn):
    """Arrangements (a client's regular allowance, with a reminder when it's due) and a mileage log."""
    conn.execute("""
        CREATE TABLE arrangements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_id INTEGER NOT NULL UNIQUE REFERENCES clients(id) ON DELETE CASCADE,
            amount REAL CHECK(amount IS NULL OR amount >= 0),
            cadence TEXT NOT NULL CHECK(cadence IN ('per_meet', 'weekly', 'biweekly', 'monthly')),
            next_due TEXT,
            notes TEXT,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
            task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE mileage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            miles REAL NOT NULL CHECK(miles > 0),
            purpose TEXT,
            tour_id INTEGER REFERENCES tours(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_mileage_owner ON mileage(owner_id, date)")


def _m23_sign_in_hardening(conn):
    """Where each session was opened, a sign-in history, sign-in throttling that survives a restart, and
    recovery codes for two-step sign-in."""
    for column in ("ip", "user_agent", "method", "device_hash"):
        conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} TEXT")
    conn.execute("""
        CREATE TABLE signin_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            outcome TEXT NOT NULL,
            method TEXT,
            ip TEXT,
            user_agent TEXT,
            device_hash TEXT,
            at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_signin_events_user ON signin_events(user_id, at)")
    conn.execute("""
        CREATE TABLE login_throttle (
            key TEXT PRIMARY KEY,
            failures INTEGER NOT NULL,
            locked_until REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE recovery_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            used_at TEXT
        )
    """)


def _m24_found_via(conn):
    """How each client found you (an ad site, a social account, a referral), so income can be compared by where
    clients come from."""
    conn.execute("ALTER TABLE clients ADD COLUMN found_via TEXT")


def _m25_campaigns_places_snippets(conn):
    """Promo posts, organized: campaigns (a push with a goal and dates), the places you post in (a subreddit, a
    channel) with their rules, and saved bits of text. A post can belong to a campaign, name its place, and
    record how many inquiries it brought."""
    conn.execute("""
        CREATE TABLE campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            goal TEXT,
            start_date TEXT,
            end_date TEXT,
            tour_id INTEGER REFERENCES tours(id) ON DELETE SET NULL,
            set_path TEXT,
            notes TEXT,
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_campaigns_owner ON campaigns(owner_id)")
    conn.execute("""
        CREATE TABLE post_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            platform TEXT NOT NULL,
            name TEXT NOT NULL,
            rules TEXT,
            wait_days INTEGER CHECK(wait_days IS NULL OR wait_days >= 0),
            link TEXT,
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_post_places_owner ON post_places(owner_id)")
    conn.execute("""
        CREATE TABLE snippets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_snippets_owner ON snippets(owner_id)")
    conn.execute("ALTER TABLE posts ADD COLUMN campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL")
    conn.execute("ALTER TABLE posts ADD COLUMN place TEXT")
    conn.execute("ALTER TABLE posts ADD COLUMN inquiries INTEGER CHECK(inquiries IS NULL OR inquiries >= 0)")
    conn.execute("CREATE INDEX idx_posts_campaign ON posts(campaign_id)")


def _m26_inquiries(conn):
    """Inquiries: who got in touch, where they came from, and how far each one got towards a booking."""
    conn.execute("""
        CREATE TABLE inquiries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            contact TEXT,
            found_via TEXT,
            received_at TEXT NOT NULL,
            wanted TEXT,
            wanted_date TEXT,
            stage TEXT NOT NULL DEFAULT 'new' CHECK(stage IN ('new', 'replied', 'screening', 'deposit', 'booked', 'lost')),
            lost_from TEXT,
            lost_reason TEXT,
            client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_inquiries_owner ON inquiries(owner_id, received_at)")


def _m27_listings(conn):
    """Ad listings: an ad on a site that runs for a while, costs money and gets renewed. A renewal's cost is an
    expense that remembers which ad it paid for."""
    conn.execute("""
        CREATE TABLE listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            site TEXT NOT NULL,
            title TEXT,
            city TEXT,
            start_date TEXT,
            end_date TEXT,
            cost REAL CHECK(cost IS NULL OR cost >= 0),
            renew_days INTEGER CHECK(renew_days IS NULL OR renew_days > 0),
            ad_text TEXT,
            link TEXT,
            paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0, 1)),
            notes TEXT,
            tour_id INTEGER REFERENCES tours(id) ON DELETE SET NULL,
            persona_id INTEGER REFERENCES personas(id) ON DELETE SET NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_listings_owner ON listings(owner_id, end_date)")
    conn.execute("ALTER TABLE expenses ADD COLUMN listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL")


def _m28_custom_content(conn):
    """Custom content: made-to-order photos and videos (who, what, price, paid, due, delivered), a menu of usual
    prices, and income that remembers which order it was a payment for."""
    conn.execute("""
        CREATE TABLE custom_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            buyer TEXT NOT NULL,
            title TEXT NOT NULL,
            details TEXT,
            client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            source_id INTEGER REFERENCES income_sources(id) ON DELETE SET NULL,
            persona_id INTEGER REFERENCES personas(id) ON DELETE SET NULL,
            requested_at TEXT NOT NULL,
            price REAL CHECK(price IS NULL OR price >= 0),
            amount_paid REAL NOT NULL DEFAULT 0 CHECK(amount_paid >= 0),
            status TEXT NOT NULL DEFAULT 'requested' CHECK(status IN ('requested', 'quoted', 'to_make', 'delivered', 'declined')),
            due_date TEXT,
            delivered_at TEXT,
            delivery_note TEXT,
            set_path TEXT,
            can_resell INTEGER NOT NULL DEFAULT 0 CHECK(can_resell IN (0, 1)),
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_custom_orders_owner ON custom_orders(owner_id, status, due_date)")
    conn.execute("""
        CREATE TABLE custom_menu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            price REAL CHECK(price IS NULL OR price >= 0),
            notes TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_custom_menu_owner ON custom_menu(owner_id)")
    conn.execute("ALTER TABLE income ADD COLUMN custom_order_id INTEGER REFERENCES custom_orders(id) ON DELETE SET NULL")


def _m29_test_kinds(conn):
    """Health tests on each person's own schedule: kinds of test with a name, how many days apart they're due and
    a usual cost, instead of a fixed weekly, monthly and yearly. A place's doctor charge can be any of them."""
    import re
    conn.execute("""
        CREATE TABLE test_kinds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            label TEXT NOT NULL,
            every_days INTEGER CHECK(every_days IS NULL OR every_days > 0),
            cost REAL CHECK(cost IS NULL OR cost >= 0),
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (owner_id, key)
        )
    """)
    # place_charges only allowed the three fixed kinds: rebuild it without that rule.
    old_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'place_charges'").fetchone()[0]
    rule = "test_type TEXT CHECK(test_type IS NULL OR test_type IN ('weekly', 'monthly', 'yearly')),"
    assert rule in old_sql, "place_charges is not as v12 made it"
    new_sql = re.sub(r'CREATE TABLE "?place_charges"?', "CREATE TABLE place_charges_new", old_sql.replace(rule, "test_type TEXT,"), count=1)
    conn.execute(new_sql)
    columns = ", ".join(r[1] for r in conn.execute("PRAGMA table_info(place_charges)"))
    conn.execute(f"INSERT INTO place_charges_new ({columns}) SELECT {columns} FROM place_charges")
    conn.execute("DROP TABLE place_charges")
    conn.execute("ALTER TABLE place_charges_new RENAME TO place_charges")
    conn.execute("CREATE INDEX idx_place_charges_source ON place_charges(source_id)")


def _m30_shoots(conn):
    """Planning a content shoot: the shoot (date, place, concept), the people on it, and its lists (goals, shots,
    wardrobe, prep, budget, marketing). An expense can remember which shoot it was for."""
    conn.execute("""
        CREATE TABLE shoots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planning'
                CHECK(status IN ('idea', 'planning', 'booked', 'shot', 'editing', 'released', 'cancelled')),
            shoot_date TEXT,
            start_time TEXT,
            hours REAL,
            concept TEXT,
            location_name TEXT,
            location_address TEXT,
            location_notes TEXT,
            set_path TEXT,
            campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
            tour_id INTEGER REFERENCES tours(id) ON DELETE SET NULL,
            persona_id INTEGER REFERENCES personas(id) ON DELETE SET NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_shoots_owner ON shoots(owner_id, shoot_date)")
    conn.execute("""
        CREATE TABLE shoot_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            shoot_id INTEGER NOT NULL REFERENCES shoots(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('goal', 'shot', 'wardrobe', 'prep', 'budget', 'marketing')),
            label TEXT NOT NULL,
            notes TEXT,
            done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0, 1)),
            amount REAL CHECK(amount IS NULL OR amount >= 0),
            actual REAL CHECK(actual IS NULL OR actual >= 0),
            due_date TEXT,
            expense_id INTEGER REFERENCES expenses(id) ON DELETE SET NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_shoot_items_shoot ON shoot_items(shoot_id)")
    conn.execute("""
        CREATE TABLE shoot_people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            shoot_id INTEGER NOT NULL REFERENCES shoots(id) ON DELETE CASCADE,
            name TEXT,
            contact_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            role TEXT NOT NULL DEFAULT 'other',
            fee REAL CHECK(fee IS NULL OR fee >= 0),
            agreement TEXT,
            id_checked INTEGER NOT NULL DEFAULT 0 CHECK(id_checked IN (0, 1)),
            release_signed INTEGER NOT NULL DEFAULT 0 CHECK(release_signed IN (0, 1)),
            confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1)),
            notes TEXT,
            expense_id INTEGER REFERENCES expenses(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_shoot_people_shoot ON shoot_people(shoot_id)")
    conn.execute("ALTER TABLE expenses ADD COLUMN shoot_id INTEGER REFERENCES shoots(id) ON DELETE SET NULL")


def _m31_rates(conn):
    """The rate card: what each service costs, how long it is, and which persona it's under."""
    conn.execute("""
        CREATE TABLE rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            minutes INTEGER CHECK(minutes IS NULL OR minutes > 0),
            price REAL NOT NULL CHECK(price >= 0),
            notes TEXT,
            persona_id INTEGER REFERENCES personas(id) ON DELETE SET NULL,
            archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_rates_owner ON rates(owner_id)")


def _m32_collaborators(conn):
    """Co-workers and crew are one group now: collaborators. Crew keep a note of what they were."""
    conn.execute("UPDATE clients SET industry = COALESCE(NULLIF(TRIM(industry), ''), 'Crew'), role = 'partner' WHERE role = 'crew'")


def _m33_tips(conn):
    """Tips: a workplace can keep a share of them, and a tip can belong to a booking."""
    conn.execute("ALTER TABLE income_sources ADD COLUMN tip_share_percent REAL "
                 "CHECK(tip_share_percent IS NULL OR (tip_share_percent >= 0 AND tip_share_percent <= 100))")
    conn.execute("ALTER TABLE income ADD COLUMN appointment_id INTEGER REFERENCES appointments(id) ON DELETE SET NULL")
    conn.execute("CREATE INDEX idx_income_appointment ON income(appointment_id)")


def _m34_paid_how_and_kelly_cut(conn):
    """Income says how it was paid (cash, bank transfer…). A workplace can take a Kelly cut: a share off the top
    when a driver brought the client, before the house's own share. Income remembers how much that was."""
    conn.execute("ALTER TABLE income ADD COLUMN payment_method TEXT")
    conn.execute("ALTER TABLE income ADD COLUMN transport_cut REAL CHECK(transport_cut IS NULL OR transport_cut >= 0)")
    conn.execute("ALTER TABLE income_sources ADD COLUMN transport_cut_percent REAL "
                 "CHECK(transport_cut_percent IS NULL OR (transport_cut_percent >= 0 AND transport_cut_percent <= 100))")


def _m35_house_rules(conn):
    """A workplace's own rules. Cuts: any number of named deductions (a Kelly cut for a cab, another for a limo, a
    runner's fee, a card fee), each a percentage or an amount, taken off the top or from your share. And cash the
    office holds until payout, with how much you may keep on you. Income remembers which cuts were taken."""
    conn.execute("""
        CREATE TABLE source_cuts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES income_sources(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'percent' CHECK(kind IN ('percent', 'amount')),
            value REAL NOT NULL CHECK(value >= 0),
            basis TEXT NOT NULL DEFAULT 'top' CHECK(basis IN ('top', 'mine')),
            auto INTEGER NOT NULL DEFAULT 0 CHECK(auto IN (0, 1)),
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_source_cuts_source ON source_cuts(source_id)")
    conn.execute("""
        INSERT INTO source_cuts (owner_id, source_id, label, kind, value, basis, auto, sort_order, created_at)
        SELECT owner_id, id, 'Kelly cut', 'percent', transport_cut_percent, 'top', 0, 0, updated_at
        FROM income_sources WHERE transport_cut_percent > 0
    """)
    conn.execute("ALTER TABLE income_sources ADD COLUMN holds_cash INTEGER NOT NULL DEFAULT 0 CHECK(holds_cash IN (0, 1))")
    conn.execute("ALTER TABLE income_sources ADD COLUMN cash_limit REAL CHECK(cash_limit IS NULL OR cash_limit >= 0)")
    conn.execute("ALTER TABLE income ADD COLUMN cuts TEXT")


def _m36_tag_pricing(conn):
    """A contact tag can change the price: a percentage off, an amount off, or a locked-in rate (they keep paying
    what they last paid for a service, whatever the rate card says now)."""
    conn.execute("""
        CREATE TABLE tag_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tag TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('percent', 'amount', 'locked')),
            value REAL CHECK(value IS NULL OR value >= 0),
            created_at TEXT NOT NULL,
            UNIQUE (owner_id, tag)
        )
    """)


def _m37_preset_names(conn):
    """A workplace remembers which starter place it began as, so renaming it doesn't bring the starter back."""
    import json as _json
    conn.execute("ALTER TABLE income_sources ADD COLUMN preset_name TEXT")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json")
    with open(path, encoding="utf-8") as f:
        names = {s["name"].lower() for key, p in _json.load(f).items() if not key.startswith("_") for s in p.get("sources", [])}
    for row in conn.execute("SELECT id, name FROM income_sources").fetchall():
        if (row[1] or "").lower() in names:
            conn.execute("UPDATE income_sources SET preset_name = name WHERE id = ?", (row[0],))


def _m38_ntfy(conn):
    """Push notifications (ntfy): what has already been sent, so a restart doesn't send it again."""
    conn.execute("""
        CREATE TABLE ntfy_sent (
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            PRIMARY KEY (owner_id, key)
        )
    """)


def _m39_club_pay(conn):
    """How a club pays: contractor or employee, house fees by arrival time, dances, VIP, tip-outs (JSON)."""
    conn.execute("ALTER TABLE income_sources ADD COLUMN club_pay TEXT")


def _m40_injections(conn):
    """Injections on a schedule (GLP-1, hormones): how often, the sites to rotate through and the dose steps
    (JSON), and which site and dose each logged injection was."""
    conn.execute("ALTER TABLE med_schedules ADD COLUMN every_days INTEGER")
    conn.execute("ALTER TABLE med_schedules ADD COLUMN sites TEXT")
    conn.execute("ALTER TABLE med_schedules ADD COLUMN doses TEXT")
    conn.execute("ALTER TABLE med_logs ADD COLUMN site TEXT")
    conn.execute("ALTER TABLE med_logs ADD COLUMN dose TEXT")


def _m41_tour_planning(conn):
    """Planning a tour: pack list templates, each tour's checklist, and a budget per main expense category."""
    conn.execute("""
        CREATE TABLE pack_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            items TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE tour_pack (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tour_id INTEGER NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            packed INTEGER NOT NULL DEFAULT 0 CHECK(packed IN (0, 1)),
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX idx_tour_pack ON tour_pack(tour_id, sort_order)")
    conn.execute("""
        CREATE TABLE tour_budget (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tour_id INTEGER NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
            category TEXT NOT NULL,
            planned REAL NOT NULL CHECK(planned >= 0),
            UNIQUE (tour_id, category)
        )
    """)


def _m42_tour_meals(conn):
    """Meals and snacks planned for a tour, with their groceries and a rough cost."""
    conn.execute("""
        CREATE TABLE tour_meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tour_id INTEGER NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
            day TEXT,
            meal TEXT NOT NULL DEFAULT 'snack',
            what TEXT NOT NULL,
            groceries TEXT,
            cost REAL CHECK(cost IS NULL OR cost >= 0)
        )
    """)
    conn.execute("CREATE INDEX idx_tour_meals ON tour_meals(tour_id, day)")


def _m43_social(conn):
    """Social accounts the person connected (credentials sealed), auto-posting, and each post's numbers."""
    conn.execute("""
        CREATE TABLE social_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            network TEXT NOT NULL CHECK(network IN ('bluesky', 'mastodon', 'reddit')),
            server TEXT NOT NULL,
            handle TEXT,
            display TEXT,
            client_id TEXT,
            secret TEXT,
            label TEXT NOT NULL DEFAULT 'none' CHECK(label IN ('none', 'suggestive', 'nudity', 'porn')),
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_social_accounts_owner ON social_accounts(owner_id)")
    conn.execute("ALTER TABLE posts ADD COLUMN social_account_id INTEGER REFERENCES social_accounts(id) ON DELETE SET NULL")
    conn.execute("ALTER TABLE posts ADD COLUMN remote_id TEXT")
    conn.execute("ALTER TABLE posts ADD COLUMN auto_post INTEGER NOT NULL DEFAULT 0 CHECK(auto_post IN (0, 1))")
    conn.execute("ALTER TABLE posts ADD COLUMN post_error TEXT")
    conn.execute("CREATE INDEX idx_posts_auto ON posts(auto_post, scheduled_at)")
    conn.execute("""
        CREATE TABLE post_stats (
            post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
            likes INTEGER,
            reposts INTEGER,
            replies INTEGER,
            views INTEGER,
            source TEXT,
            fetched_at TEXT NOT NULL
        )
    """)


def _m44_receipts(conn):
    """Receipts as issued: number, wording and amount kept, so a reprint looks the same."""
    conn.execute("""
        CREATE TABLE receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            appointment_id INTEGER REFERENCES appointments(id) ON DELETE SET NULL,
            year INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            number TEXT NOT NULL,
            issued_on TEXT NOT NULL,
            billed_to TEXT,
            description TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            currency TEXT NOT NULL DEFAULT 'USD',
            method TEXT,
            note TEXT,
            business TEXT,
            contact TEXT,
            footer TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(owner_id, year, seq)
        )
    """)
    conn.execute("CREATE INDEX idx_receipts_appt ON receipts(appointment_id)")


def _m45_post_alt_text(conn):
    """A description of each picture in a post (alt text), as JSON: {"path": "what it shows"}."""
    conn.execute("ALTER TABLE posts ADD COLUMN alt_text TEXT")


def _m46_doctor_day(conn):
    """The weekday a workplace's doctor comes (0 Monday .. 6 Sunday), so tests on a tour land on that day."""
    conn.execute("ALTER TABLE place_charges ADD COLUMN weekday INTEGER CHECK(weekday IS NULL OR weekday BETWEEN 0 AND 6)")


def _m47_envelopes(conn):
    """Goals can be envelopes (money in, money out, no target), and an envelope can fill itself from what a
    workplace is holding for you (its income not paid out yet)."""
    conn.execute("ALTER TABLE goals ADD COLUMN envelope INTEGER NOT NULL DEFAULT 0 CHECK(envelope IN (0, 1))")
    conn.execute("ALTER TABLE goals ADD COLUMN source_id INTEGER REFERENCES income_sources(id) ON DELETE SET NULL")


def _m48_client_profiles(conn):
    """Getting to know a client: languages, translator, culture, topics to talk about and avoid, deceased."""
    conn.execute("""
        CREATE TABLE client_profiles (
            client_id INTEGER PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            languages TEXT,
            translator INTEGER NOT NULL DEFAULT 0 CHECK(translator IN (0, 1)),
            culture TEXT,
            talk_about TEXT,
            avoid TEXT,
            deceased INTEGER NOT NULL DEFAULT 0 CHECK(deceased IN (0, 1)),
            deceased_on TEXT,
            updated_at TEXT NOT NULL
        )
    """)


def _m49_routines(conn):
    """Routines: named checklists (morning, night, before and after a booking), ticked off day by day."""
    conn.execute("""
        CREATE TABLE routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            when_for TEXT NOT NULL DEFAULT 'any',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE routine_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE routine_checks (
            step_id INTEGER NOT NULL REFERENCES routine_steps(id) ON DELETE CASCADE,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            day TEXT NOT NULL,
            PRIMARY KEY (step_id, day)
        )
    """)


def _m50_booking_reviews(conn):
    """After a booking: a few quick answers about how it went, kept with the client."""
    conn.execute("""
        CREATE TABLE booking_reviews (
            appointment_id INTEGER PRIMARY KEY REFERENCES appointments(id) ON DELETE CASCADE,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
            rating TEXT CHECK(rating IS NULL OR rating IN ('great', 'fine', 'bad')),
            again TEXT CHECK(again IS NULL OR again IN ('yes', 'maybe', 'no')),
            talked_about TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_booking_reviews_client ON booking_reviews(client_id)")


def _m51_wallet_dashboard(conn):
    """Each goal or envelope can be shown on the dashboard's Wallet card, or not."""
    conn.execute("ALTER TABLE goals ADD COLUMN on_dashboard INTEGER NOT NULL DEFAULT 1 CHECK(on_dashboard IN (0, 1))")


MIGRATIONS = [
    (1, "baseline tables", _m1_baseline, False),
    (2, "owners, income, screening, safety check-in, client notes", _m2_owners_money_screening_safety, True),
    (3, "tours and time off, health tests, room rent, client preferences", _m3_tours_tests_preferences, True),
    (4, "income, places you earn, savings goals, own expense categories, currencies", _m4_income_goals_categories, True),
    (5, "contacts with handles and industry, tasks, calendar sync per person", _m5_contacts_tasks_personal_sync, True),
    (6, "kind of work for each place you earn", _m6_source_work_types, False),
    (7, "partners and splits, room & board, license fees", _m7_partners_splits_room_board, False),
    (8, "post planner", _m8_posts, False),
    (9, "couples", _m9_couples, False),
    (10, "cycle tracking", _m10_cycle, False),
    (11, "expense categories in two levels", _m11_category_groups, False),
    (12, "kinds of place, and charges each place makes", _m12_place_kinds_and_charges, True),
    (13, "stays: tours at one of your places", _m13_stays, False),
    (14, "personas", _m14_personas, False),
    (15, "bad-date list", _m15_blocklist, False),
    (16, "gifts, allowances and the house's share of gifts", _m16_gifts_and_allowances, False),
    (17, "birth control and regular meds", _m17_meds, False),
    (18, "quarterly charges", _m18_quarterly_charges, True),
    (19, "documents that expire", _m19_documents, False),
    (20, "cancellations, no-shows and their fees", _m20_cancellations, False),
    (21, "estimated tax payments, passkeys, two-step sign-in", _m21_tax_payments_passkeys_two_step, False),
    (22, "arrangements and mileage", _m22_arrangements_mileage, False),
    (23, "session details, sign-in history, lasting throttle, recovery codes", _m23_sign_in_hardening, False),
    (24, "how each client found you", _m24_found_via, False),
    (25, "campaigns, places you post in, saved text", _m25_campaigns_places_snippets, False),
    (26, "inquiries", _m26_inquiries, False),
    (27, "ad listings", _m27_listings, False),
    (28, "custom content orders and menu", _m28_custom_content, False),
    (29, "health tests on your own schedule", _m29_test_kinds, True),
    (30, "content shoot planning", _m30_shoots, False),
    (31, "rate card", _m31_rates, False),
    (32, "co-workers and crew become collaborators", _m32_collaborators, False),
    (33, "tips and the house's share of them", _m33_tips, False),
    (34, "how income was paid, and the Kelly cut", _m34_paid_how_and_kelly_cut, False),
    (35, "house rules: cuts, and cash the office holds", _m35_house_rules, False),
    (36, "prices by contact tag", _m36_tag_pricing, False),
    (37, "workplaces remember their starter place", _m37_preset_names, False),
    (38, "push notifications", _m38_ntfy, False),
    (39, "club pay", _m39_club_pay, False),
    (40, "injections: site rotation and dose steps", _m40_injections, False),
    (41, "tour planning: pack lists and budgets", _m41_tour_planning, False),
    (42, "tour meals and snacks", _m42_tour_meals, False),
    (43, "social accounts, auto-posting and post numbers", _m43_social, False),
    (44, "discreet receipts", _m44_receipts, False),
    (45, "alt text for post pictures", _m45_post_alt_text, False),
    (46, "doctor day for workplace health tests", _m46_doctor_day, False),
    (47, "envelopes", _m47_envelopes, False),
    (48, "client profiles", _m48_client_profiles, False),
    (49, "routines", _m49_routines, False),
    (50, "after-booking questions", _m50_booking_reviews, False),
    (51, "wallet: choose what the dashboard shows", _m51_wallet_dashboard, False),
]
LATEST = MIGRATIONS[-1][0]


# ==================== RUNNER ====================

def current_version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _has_data(conn) -> bool:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return any(t in tables and conn.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone()
               for t in ("clients", "appointments", "expenses", "users"))


def _save_copy(conn, db_path: str, target: int) -> str:
    copy_path = os.path.join(os.path.dirname(db_path), f"sworkr.before-v{target}.db")
    if os.path.exists(copy_path):
        os.replace(copy_path, copy_path + ".old")
    dest = sqlite3.connect(copy_path)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return copy_path


def run(db_path: str) -> int:
    """Bring the database at db_path up to date. Returns the version it ends at."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    # A database (and upgrade copies) saved before encryption: encrypted first, once, and checked.
    sqlite3.encrypt_folder(os.path.dirname(db_path))
    # isolation_level=None: we say BEGIN/COMMIT ourselves, so table changes are part of the transaction too.
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        version = current_version(conn)
        if version > LATEST:
            raise RuntimeError(
                f"This database is version {version}, but this copy of sworkr only knows up to {LATEST}. "
                "Update sworkr, or restore the database copy made before the upgrade.")
        pending = [m for m in MIGRATIONS if m[0] > version]
        if not pending:
            return version
        if _has_data(conn):
            copy_path = _save_copy(conn, db_path, LATEST)
            log.warning("Upgrading the database from v%s to v%s. A copy was saved at %s", version, LATEST, copy_path)
        for number, name, migrate, rebuilds_tables in pending:
            # Foreign keys must be off while a table is rebuilt, and can only be switched outside a transaction.
            conn.execute(f"PRAGMA foreign_keys = {'OFF' if rebuilds_tables else 'ON'}")
            conn.execute("BEGIN IMMEDIATE")
            try:
                if current_version(conn) >= number:   # another process got here first
                    conn.execute("ROLLBACK")
                    continue
                migrate(conn)
                if rebuilds_tables:
                    broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                    if broken:
                        raise RuntimeError(f"Migration {number} would leave {len(broken)} broken links between tables")
                conn.execute(f"PRAGMA user_version = {number}")
                conn.execute("COMMIT")
                log.info("Database migration %s applied: %s", number, name)
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return current_version(conn)
    finally:
        conn.close()
