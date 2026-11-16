"""
The database file, encrypted.

Everything sworkr keeps is in one SQLite file. That file is encrypted with SQLCipher (AES-256), page by page,
with a random 256-bit key that is kept apart from it: in its own Docker volume, or in the computer's own
keychain in the desktop app (see vault.secret). A copy of the database file on its own, such as a copied data
folder, an old upgrade copy, or the file pulled off a disk, can't be read without that key.

What it doesn't do: protect against someone who can use the computer while sworkr's key is there. Disk
encryption and a locked computer account still matter.

If the key is lost, the database can't be opened. Encrypted backups are the way back: they are made with your
backup passphrase, not with this key, so they restore on any computer.

Every connection to a database file goes through `connect`. The rest of sworkr imports this module in place of
`sqlite3` (`import dbfile as sqlite3`), so Row, IntegrityError and the rest come from the same engine.
"""

import logging
import os
from typing import Optional

from sqlcipher3 import dbapi2 as _engine
from sqlcipher3.dbapi2 import *  # noqa: F401,F403  (Row, Connection, the error classes, …)

import vault

log = logging.getLogger("sworkr.dbfile")

KEY_NAME = "database.key"
PLAIN_HEADER = b"SQLite format 3\x00"


def _key_pragma() -> str:
    return "PRAGMA key = \"x'" + vault.secret(KEY_NAME).hex() + "'\""


def connect(path: str, *args, plain: bool = False, **kwargs):
    """A connection to the database at `path`, unlocked with this computer's key (or unencrypted with plain=True,
    only for the inside of a backup file, which has its own encryption)."""
    conn = _engine.connect(path, *args, **kwargs)
    if not plain:
        conn.execute(_key_pragma())
    return conn


def is_plain(path: str) -> bool:
    """Whether a database file is stored unencrypted (made before encryption, or a plain copy)."""
    try:
        with open(path, "rb") as f:
            return f.read(16) == PLAIN_HEADER
    except OSError:
        return False


def _copy_into(source, schema: str, target: str, key: Optional[str]) -> None:
    """Copy every table, index and row of `source` into a new file at `target`, encrypted with `key` (None: plain)."""
    version = source.execute("PRAGMA user_version").fetchone()[0]
    key_sql = "''" if key is None else f"\"x'{key}'\""
    source.execute(f"ATTACH DATABASE ? AS {schema} KEY {key_sql}", (target,))
    try:
        source.execute(f"SELECT sqlcipher_export('{schema}')")
        source.execute(f"PRAGMA {schema}.user_version = {int(version)}")
    finally:
        source.execute(f"DETACH DATABASE {schema}")


def export_plain(conn, target: str) -> None:
    """Write an unencrypted copy of an open (keyed) database to `target`: the inside of a backup file."""
    _copy_into(conn, "plaincopy", target, None)


def import_plain(source_path: str, target: str) -> None:
    """Write an encrypted copy of an unencrypted database file to `target` (a new file)."""
    source = connect(source_path, plain=True)
    try:
        _copy_into(source, "keyed", target, vault.secret(KEY_NAME).hex())
    finally:
        source.close()


def _tables_and_rows(conn) -> dict:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def encrypt_in_place(path: str) -> bool:
    """Encrypt an unencrypted database file. The encrypted copy is checked (same tables, same row counts, same
    version, intact) before it replaces the original. Returns whether anything was done."""
    if not is_plain(path):
        return False
    tmp = path + ".encrypting"
    for leftover in (tmp, tmp + "-journal"):
        if os.path.exists(leftover):
            os.remove(leftover)
    import_plain(path, tmp)
    before = connect(path, plain=True)
    after = connect(tmp)
    try:
        same = (_tables_and_rows(before) == _tables_and_rows(after)
                and before.execute("PRAGMA user_version").fetchone()[0] == after.execute("PRAGMA user_version").fetchone()[0]
                and after.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
    finally:
        before.close()
        after.close()
    if not same:
        os.remove(tmp)
        raise RuntimeError(f"Encrypting {path} didn't give an identical copy; it was left as it was")
    for side in (path + "-wal", path + "-shm", path + "-journal"):
        if os.path.exists(side):
            os.remove(side)
    os.replace(tmp, path)
    log.warning("Encrypted %s", os.path.basename(path))
    return True


def encrypt_folder(folder: str) -> int:
    """Encrypt every unencrypted database in sworkr's data folder: the database and the copies saved before
    upgrades and restores. Returns how many were encrypted."""
    if not os.path.isdir(folder):
        return 0
    done = 0
    for name in sorted(os.listdir(folder)):
        if name.endswith((".db", ".db.old")) and is_plain(os.path.join(folder, name)):
            done += encrypt_in_place(os.path.join(folder, name))
    return done
