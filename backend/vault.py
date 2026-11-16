"""
Saved passwords, sealed.

sworkr has to keep a few secrets it must be able to read back: the app passwords for the calendar,
the mailbox and the content library, the passphrase for automatic backups, and the authenticator-app
secret. They are stored in the settings tables encrypted (AES-256-GCM) with a key that lives in its
own file, outside the database. So a copy of the database alone (a stolen .db file, the copy saved
before an upgrade, a backup file opened somewhere else) does not give those passwords away.

What this does not do: protect against someone who has the whole computer, key file included.
That is what disk encryption and locked mode are for.

If the key file is lost, or a backup is restored on another computer, the sealed values can't be
read. They then count as "not saved": the person types the password in again and it is sealed with
the new key. Nothing else in the database depends on this key.
"""

import base64
import logging
import os
import secrets
import threading
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("sworkr.vault")

# Settings whose value is a secret. Everything else in the settings tables is stored as it is.
SECRET_KEYS = frozenset({"cal_password", "content_password", "mail_password", "backup_passphrase", "totp_secret",
                         "offsite_password", "mail2_password", "mail3_password", "mail4_password", "mail5_password"})

PREFIX = "sealed:v1:"
KEY_FILE = "settings.key"

_lock = threading.Lock()


def key_dir() -> str:
    """Where the key file lives. In Docker this is its own volume, apart from the database's."""
    explicit = os.environ.get("KEY_DIR")
    if explicit:
        return explicit
    data = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    return os.path.join(data, "keys")


def _keyring_secret(name: str) -> bytes:
    """A 32-byte secret kept in the computer's own keychain (Windows Credential Manager, the macOS Keychain, the
    Secret Service on Linux), made the first time. Used by the desktop app, so the keys aren't files at all."""
    import keyring
    stored = keyring.get_password("sworkr", name)
    if stored:
        key = base64.b64decode(stored)
        if len(key) == 32:
            return key
        raise ValueError(f"The keychain entry sworkr/{name} isn't a sworkr key")
    key = secrets.token_bytes(32)
    keyring.set_password("sworkr", name, base64.b64encode(key).decode())
    return key


_secrets: dict = {}


def secret(name: str) -> bytes:
    """A 32-byte secret by name (settings.key seals saved passwords; database.key encrypts the database).
    Kept in the system keychain when SWORKR_KEY_STORE=keychain, otherwise as a file in key_dir()."""
    store = os.environ.get("SWORKR_KEY_STORE", "file")
    cache_key = (store, key_dir(), name)
    with _lock:
        if cache_key not in _secrets:
            _secrets[cache_key] = _keyring_secret(name) if store == "keychain" else _file_secret(os.path.join(key_dir(), name))
        return _secrets[cache_key]


def _key() -> bytes:
    return secret(KEY_FILE)


def _file_secret(path: str) -> bytes:
    """A 32-byte secret kept in a file, made the first time."""
    try:
        with open(path, "rb") as f:
            key = f.read()
        if len(key) != 32:
            raise ValueError(f"{path} is not a sworkr key file")
        return key
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = secrets.token_bytes(32)
    # "x": never write over a key that appeared in the meantime; that would orphan what it sealed.
    try:
        with open(path, "xb") as f:
            f.write(key)
    except FileExistsError:
        with open(path, "rb") as f:
            key = f.read()
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def is_sealed(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(PREFIX)


def seal(name: str, value: Optional[str]) -> Optional[str]:
    """What to store for setting `name`. Only secrets are changed; an empty value stays empty."""
    if name not in SECRET_KEYS or not value or is_sealed(value):
        return value
    nonce = secrets.token_bytes(12)
    # The setting's name is bound in, so a sealed value can't be moved to another setting and still open.
    sealed = AESGCM(_key()).encrypt(nonce, value.encode(), name.encode())
    return PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode()


def unseal(name: str, stored: Optional[str]) -> Optional[str]:
    """The readable value of setting `name`. None when it was sealed with a key this computer doesn't have."""
    if name not in SECRET_KEYS or not is_sealed(stored):
        return stored   # not a secret, or saved before sealing existed (seal_existing catches those at startup)
    try:
        raw = base64.urlsafe_b64decode(stored[len(PREFIX):])
        return AESGCM(_key()).decrypt(raw[:12], raw[12:], name.encode()).decode()
    except (InvalidTag, ValueError):
        log.warning("The saved %s can't be read with this computer's key; it needs entering again", name)
        return None


def seal_existing(db) -> int:
    """Seal any secret still stored readable (saved by an older version). Returns how many were sealed."""
    done = 0
    marks = ",".join("?" * len(SECRET_KEYS))
    names = tuple(sorted(SECRET_KEYS))
    for r in db.execute(f"SELECT user_id, key, value FROM user_settings WHERE key IN ({marks})", names).fetchall():
        if r[2] and not is_sealed(r[2]):
            db.execute("UPDATE user_settings SET value = ? WHERE user_id = ? AND key = ?", (seal(r[1], r[2]), r[0], r[1]))
            done += 1
    for r in db.execute(f"SELECT key, value FROM settings WHERE key IN ({marks})", names).fetchall():
        if r[1] and not is_sealed(r[1]):
            db.execute("UPDATE settings SET value = ? WHERE key = ?", (seal(r[0], r[1]), r[0]))
            done += 1
    return done
