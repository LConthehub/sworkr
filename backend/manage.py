"""
Command-line tools for looking after sworkr. Run them inside the api container:

    docker compose exec sworkr python manage.py list-users
    docker compose exec sworkr python manage.py reset-password [username]
    docker compose exec sworkr python manage.py backup /backups
    docker compose exec sworkr python manage.py restore-backup /backups/sworkr-2026-01-31-120000.swbak

These need access to the computer sworkr runs on, which is the point: someone who can't log in
to that computer can't reset a password.
"""

import argparse
import getpass
import os
import dbfile as sqlite3
import sys
from datetime import datetime

import auth
import backup
import migrations

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "sworkr.db")


def connect():
    if not os.path.exists(DB_PATH):
        sys.exit(f"No database found at {DB_PATH}")
    migrations.run(DB_PATH)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def ask_new_secret(what: str, minimum: int) -> str:
    while True:
        first = getpass.getpass(f"New {what} (at least {minimum} characters): ")
        if len(first) < minimum:
            print(f"Too short: {len(first)} characters.")
            continue
        if getpass.getpass(f"Type the {what} again: ") != first:
            print("They don't match. Try again.")
            continue
        return first


def list_users(args):
    db = connect()
    rows = db.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()
    if not rows:
        print("No accounts yet. Open sworkr in the browser to create the first one.")
    for r in rows:
        print(f"{r['id']:>3}  {r['username']:<20} {'admin' if r['is_admin'] else 'user ':<6} created {r['created_at'][:10]}")


def reset_password(args):
    db = connect()
    users = db.execute("SELECT id, username FROM users ORDER BY id").fetchall()
    if not users:
        sys.exit("No accounts yet. Open sworkr in the browser to create the first one.")
    username = (args.username or "").strip().lower()
    if not username:
        if len(users) == 1:
            username = users[0]["username"]
        else:
            sys.exit("Which account? Usernames: " + ", ".join(u["username"] for u in users))
    user = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        sys.exit(f"No account called '{username}'. Usernames: " + ", ".join(u["username"] for u in users))
    password = args.password or ask_new_secret(f"password for {username}", auth.MIN_PASSWORD_LENGTH)
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        sys.exit(f"The password must be at least {auth.MIN_PASSWORD_LENGTH} characters")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(password), user["id"]))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    db.commit()
    print(f"Password changed for {username}. Every device has been logged out.")


def turn_off_two_step(args):
    """For someone whose sign-in codes can't reach them (their email broke): password alone works again."""
    db = connect()
    username = (args.username or "").strip().lower()
    user = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        names = [r["username"] for r in db.execute("SELECT username FROM users ORDER BY id")]
        sys.exit(f"No account called '{username}'. Usernames: " + ", ".join(names))
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, 'two_step', '0') "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = '0'", (user["id"],))
    db.commit()
    print(f"Two-step sign-in is off for {username}: their password alone signs them in again. "
          "They can turn it back on in their settings.")


def make_backup(args):
    db = connect()
    passphrase = args.passphrase or ask_new_secret("backup passphrase", backup.MIN_PASSPHRASE_LENGTH)
    if len(passphrase) < backup.MIN_PASSPHRASE_LENGTH:
        sys.exit(f"The passphrase must be at least {backup.MIN_PASSPHRASE_LENGTH} characters")
    os.makedirs(args.folder, exist_ok=True)
    path = os.path.join(args.folder, backup.backup_filename())
    with open(path, "wb") as f:
        f.write(backup.make_backup(db, passphrase))
    print(f"Backup written to {path}")


def restore_backup(args):
    if not os.path.exists(args.file):
        sys.exit(f"No such file: {args.file}")
    with open(args.file, "rb") as f:
        blob = f.read()
    passphrase = args.passphrase or getpass.getpass("Backup passphrase: ")
    try:
        backup.decrypt(blob, passphrase)   # check the passphrase before touching anything
    except backup.BackupError as e:
        sys.exit(str(e))
    if os.path.exists(DB_PATH) and not args.yes:
        print(f"This replaces everything currently in sworkr with the contents of {os.path.basename(args.file)}.")
        if input("Type RESTORE to continue: ").strip() != "RESTORE":
            sys.exit("Nothing was changed.")
    if os.path.exists(DB_PATH):
        keep = os.path.join(DATA_DIR, f"sworkr.before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db")
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(keep)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
        print(f"The current database was kept as {keep}")
    try:
        backup.restore_into(DB_PATH, blob, passphrase)
    except backup.BackupError as e:
        sys.exit(str(e))
    version = migrations.run(DB_PATH)   # an older backup is upgraded to the current layout
    print(f"Restored (database version {version}). Restart sworkr now:  docker compose restart api")


def main():
    parser = argparse.ArgumentParser(description="sworkr maintenance tools")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-users", help="show the accounts").set_defaults(run=list_users)

    p = sub.add_parser("reset-password", help="set a new password for an account")
    p.add_argument("username", nargs="?")
    p.add_argument("--password", help=argparse.SUPPRESS)
    p.set_defaults(run=reset_password)

    p = sub.add_parser("turn-off-two-step", help="let an account sign in with just its password again")
    p.add_argument("username")
    p.set_defaults(run=turn_off_two_step)

    p = sub.add_parser("backup", help="write an encrypted backup into a folder")
    p.add_argument("folder", nargs="?", default=backup.BACKUP_DIR)
    p.add_argument("--passphrase", help=argparse.SUPPRESS)
    p.set_defaults(run=make_backup)

    p = sub.add_parser("restore-backup", help="replace the database with a backup file")
    p.add_argument("file")
    p.add_argument("--passphrase", help=argparse.SUPPRESS)
    p.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    p.set_defaults(run=restore_backup)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
