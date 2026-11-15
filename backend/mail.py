"""
Email, per person: read unread and important messages over IMAP, and reply over SMTP, with the person's own
email account. Each person connects their account on their settings page.

- Nothing from the mailbox is stored in sworkr's database. Messages are fetched when asked for (and kept in
  memory for a minute, so the dashboard doesn't hammer the mail server).
- Emails are only ever shown as plain text: HTML is turned into text here, so nothing in an email can run in
  the browser or load tracking images.
- Opening a message doesn't mark it as read; there's a button for that.
- "Important" means flagged (starred), plus Gmail's own Important label on Gmail.
- In the demo, a made-up inbox is shown instead and nothing is ever sent.
"""

import email
import vault
import email.errors
import email.header
import email.policy
import email.utils
import html
import imaplib
import re
import smtplib
import socket
import ssl
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import getaddresses, make_msgid, parseaddr, parsedate_to_datetime
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/mail")
_get_db: Optional[Callable] = None

TIMEOUT = 20            # seconds for any connection to the mail server
CACHE_SECONDS = 60
MAX_LIST = 50
MAX_BODY_CHARS = 100_000


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


class MailError(Exception):
    pass


# ==================== SETTINGS (per person) ====================

KEYS = ("mail_enabled", "mail_imap_host", "mail_imap_port", "mail_imap_security", "mail_smtp_host", "mail_smtp_port",
        "mail_smtp_security", "mail_username", "mail_password", "mail_from_name", "mail_from_address", "mail_folder")

# Common providers, to fill the form in. Every one of them needs an app password, not the account password.
PROVIDERS = {
    "gmail": {"label": "Gmail", "imap_host": "imap.gmail.com", "imap_port": 993, "imap_security": "ssl",
              "smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_security": "starttls"},
    "icloud": {"label": "iCloud Mail", "imap_host": "imap.mail.me.com", "imap_port": 993, "imap_security": "ssl",
               "smtp_host": "smtp.mail.me.com", "smtp_port": 587, "smtp_security": "starttls"},
    "fastmail": {"label": "Fastmail", "imap_host": "imap.fastmail.com", "imap_port": 993, "imap_security": "ssl",
                 "smtp_host": "smtp.fastmail.com", "smtp_port": 465, "smtp_security": "ssl"},
    "yahoo": {"label": "Yahoo Mail", "imap_host": "imap.mail.yahoo.com", "imap_port": 993, "imap_security": "ssl",
              "smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465, "smtp_security": "ssl"},
    "proton": {"label": "Proton Mail (Bridge)", "imap_host": "127.0.0.1", "imap_port": 1143, "imap_security": "starttls",
               "smtp_host": "127.0.0.1", "smtp_port": 1025, "smtp_security": "starttls"},
    "other": {"label": "Other", "imap_host": "", "imap_port": 993, "imap_security": "ssl",
              "smtp_host": "", "smtp_port": 587, "smtp_security": "starttls"},
}


def _get(db, user_id: int, key: str) -> Optional[str]:
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return vault.unseal(key, row["value"]) if row else None


def _set(db, user_id: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, vault.seal(key, value)))


def load_settings(db, user_id: int) -> dict:
    s = {k[5:]: _get(db, user_id, k) for k in KEYS}
    s["enabled"] = s["enabled"] == "1"
    s["imap_port"] = int(s["imap_port"] or 993)
    s["smtp_port"] = int(s["smtp_port"] or 587)
    s["imap_security"] = s["imap_security"] or "ssl"
    s["smtp_security"] = s["smtp_security"] or "starttls"
    s["folder"] = s["folder"] or "INBOX"
    s["from_address"] = s["from_address"] or (s["username"] if s["username"] and "@" in s["username"] else None)
    return s


def _demo() -> bool:
    import demo
    return demo.ENABLED


# ==================== READING EMAIL ====================

def decode(value) -> str:
    """A header as readable text (handles =?utf-8?...?= encoding)."""
    if value is None:
        return ""
    try:
        return str(email.header.make_header(email.header.decode_header(str(value))))
    except (UnicodeDecodeError, LookupError, email.errors.HeaderParseError):
        return str(value)


def _clean_header(value: str) -> str:
    """No line breaks in anything that goes back into a header (stops header injection)."""
    return re.sub(r"[\r\n]+", " ", value or "").strip()


def html_to_text(markup: str) -> str:
    """Plain text from an HTML email. Scripts, styles and images are dropped; nothing is rendered."""
    text = re.sub(r"(?is)<(script|style|head|title)[^>]*>.*?</\1>", " ", markup)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|blockquote|table)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def body_text(msg: email.message.Message) -> str:
    """The message's text: its plain-text part, or its HTML part turned into text."""
    plain = rich = None
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            text = (part.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        if kind == "text/plain" and plain is None:
            plain = text
        elif kind == "text/html" and rich is None:
            rich = text
    text = plain if plain is not None and plain.strip() else html_to_text(rich or "")
    return text[:MAX_BODY_CHARS]


def attachments(msg: email.message.Message) -> List[str]:
    return [decode(p.get_filename()) for p in msg.walk() if p.get_content_disposition() == "attachment" and p.get_filename()]


def _address(value) -> dict:
    name, addr = parseaddr(decode(value))
    return {"name": name or None, "email": addr.lower() or None}


def _date(value) -> Optional[str]:
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, IndexError):
        return None


class Mailbox:
    """One person's mailbox over IMAP. Use as a context manager."""

    def __init__(self, s: dict):
        self.s = s
        self.imap = None
        self.gmail = False

    def __enter__(self):
        s = self.s
        if not (s["imap_host"] and s["username"] and s["password"]):
            raise MailError("Email isn't set up yet")
        try:
            if s["imap_security"] == "ssl":
                self.imap = imaplib.IMAP4_SSL(s["imap_host"], s["imap_port"], ssl_context=ssl.create_default_context(),
                                              timeout=TIMEOUT)
            else:
                self.imap = imaplib.IMAP4(s["imap_host"], s["imap_port"], timeout=TIMEOUT)
                if s["imap_security"] == "starttls":
                    self.imap.starttls(ssl_context=ssl.create_default_context())
            self.imap.login(s["username"], s["password"])
        except imaplib.IMAP4.error as e:
            raise MailError(f"The mail server rejected the login. Check the username and app password. ({_short(e)})") from e
        except (OSError, ssl.SSLError, socket.timeout) as e:
            raise MailError(f"Couldn't reach the mail server: {_short(e)}") from e
        self.gmail = "X-GM-EXT-1" in [c.decode() if isinstance(c, bytes) else str(c) for c in self.imap.capabilities]
        return self

    def __exit__(self, *exc):
        try:
            self.imap.logout()
        except Exception:
            pass

    def _select(self, readonly=True):
        typ, _ = self.imap.select(_quote(self.s["folder"]), readonly=readonly)
        if typ != "OK":
            raise MailError(f"There's no folder called {self.s['folder']}")

    def _search(self, which: str) -> List[bytes]:
        if which == "important":
            if self.gmail:
                typ, data = self.imap.uid("SEARCH", "X-GM-RAW", '"is:important OR is:starred"')
            else:
                typ, data = self.imap.uid("SEARCH", "FLAGGED")
        else:
            typ, data = self.imap.uid("SEARCH", "UNSEEN")
        if typ != "OK":
            raise MailError("The mail server couldn't search the folder")
        return (data[0] or b"").split()

    def list(self, which: str, limit: int = 25) -> dict:
        """The newest `limit` unread or important messages: who from, subject, date and flags."""
        self._select()
        uids = self._search(which)
        total = len(uids)
        uids = uids[-limit:]
        out = []
        if uids:
            typ, data = self.imap.uid("FETCH", b",".join(uids),
                                      "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            if typ != "OK":
                raise MailError("The mail server couldn't fetch the messages")
            for item in data:
                if not isinstance(item, tuple):
                    continue
                meta = item[0].decode(errors="replace")
                uid = re.search(r"UID (\d+)", meta)
                if not uid:
                    continue
                flags = re.search(r"FLAGS \(([^)]*)\)", meta)
                flags = flags.group(1).split() if flags else []
                headers = email.message_from_bytes(item[1], policy=email.policy.compat32)
                out.append({"uid": int(uid.group(1)), "from": _address(headers["From"]), "subject": decode(headers["Subject"]),
                            "date": _date(headers["Date"]), "unread": "\\Seen" not in flags,
                            "flagged": "\\Flagged" in flags})
        out.sort(key=lambda m: m["date"] or "", reverse=True)
        return {"messages": out, "total": total}

    def get(self, uid: int) -> dict:
        self._select()
        typ, data = self.imap.uid("FETCH", str(uid), "(FLAGS BODY.PEEK[])")
        raw = next((x for x in data if isinstance(x, tuple)), None) if typ == "OK" else None
        if not raw:
            raise MailError("That message isn't in the folder any more")
        flags = re.search(r"FLAGS \(([^)]*)\)", raw[0].decode(errors="replace"))
        flags = flags.group(1).split() if flags else []
        msg = email.message_from_bytes(raw[1], policy=email.policy.compat32)
        return {
            "uid": uid,
            "from": _address(msg["From"]),
            "reply_to": _address(msg["Reply-To"]) if msg["Reply-To"] else None,
            "to": [{"name": n or None, "email": a.lower()} for n, a in getaddresses([decode(v) for v in msg.get_all("To", [])]) if a],
            "cc": [{"name": n or None, "email": a.lower()} for n, a in getaddresses([decode(v) for v in msg.get_all("Cc", [])]) if a],
            "subject": decode(msg["Subject"]),
            "date": _date(msg["Date"]),
            "message_id": _clean_header(msg["Message-ID"] or ""),
            "references": _clean_header(msg["References"] or ""),
            "text": body_text(msg),
            "attachments": attachments(msg),
            "unread": "\\Seen" not in flags,
            "flagged": "\\Flagged" in flags,
            "answered": "\\Answered" in flags,
        }

    def set_flags(self, uid: int, seen: Optional[bool] = None, flagged: Optional[bool] = None, answered: bool = False):
        self._select(readonly=False)
        for flag, on in (("\\Seen", seen), ("\\Flagged", flagged), ("\\Answered", True if answered else None)):
            if on is not None:
                typ, _ = self.imap.uid("STORE", str(uid), "+FLAGS" if on else "-FLAGS", f"({flag})")
                if typ != "OK":
                    raise MailError("The mail server didn't accept the change")

    def save_sent(self, raw: bytes):
        """Keep a copy of a sent reply in the Sent folder (Gmail does this by itself)."""
        if self.gmail:
            return
        typ, folders = self.imap.list()
        sent = None
        for line in folders or []:
            text = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
            name = re.search(r'"([^"]+)"$|(\S+)$', text)
            name = name.group(1) or name.group(2) if name else None
            if "\\Sent" in text or (name and name.split("/")[-1].split(".")[-1].lower() in ("sent", "sent items", "sent messages")):
                sent = name
                if "\\Sent" in text:
                    break
        if sent:
            self.imap.append(_quote(sent), "\\Seen", imaplib.Time2Internaldate(time.time()), raw)


def _quote(folder: str) -> str:
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _short(e: Exception) -> str:
    text = str(e)
    if isinstance(e.args[0] if e.args else None, bytes):
        text = e.args[0].decode(errors="replace")
    return text[:200]


# ==================== SENDING ====================

def build_reply(s: dict, original: dict, body: str, reply_all: bool) -> EmailMessage:
    to = original.get("reply_to") or original["from"]
    if not to or not to.get("email"):
        raise MailError("This message has no address to reply to")
    sender = s["from_address"]
    if not sender:
        raise MailError("Set the address to send from in your email settings")
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((_clean_header(s["from_name"] or ""), sender)) if s["from_name"] else sender
    msg["To"] = email.utils.formataddr((_clean_header(to.get("name") or ""), to["email"])) if to.get("name") else to["email"]
    if reply_all:
        others = [a for a in original.get("to", []) + original.get("cc", [])
                  if a["email"] not in (sender.lower(), to["email"])]
        if others:
            msg["Cc"] = ", ".join(a["email"] for a in others)
    subject = _clean_header(original.get("subject") or "")
    msg["Subject"] = subject if re.match(r"(?i)re:", subject) else f"Re: {subject}"
    msg["Date"] = email.utils.formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    if original.get("message_id"):
        msg["In-Reply-To"] = original["message_id"]
        msg["References"] = f"{original.get('references', '')} {original['message_id']}".strip()
    when = original.get("date")
    quoted = "\n".join("> " + line for line in (original.get("text") or "").splitlines()[:200])
    intro = f"On {when[:10] if when else 'an earlier date'}, {to.get('name') or to['email']} wrote:"
    msg.set_content(f"{body.rstrip()}\n\n{intro}\n{quoted}\n")
    return msg


def send(s: dict, msg: EmailMessage):
    if not (s["smtp_host"] and s["username"] and s["password"]):
        raise MailError("Sending isn't set up: add the outgoing (SMTP) server in your email settings")
    context = ssl.create_default_context()
    try:
        if s["smtp_security"] == "ssl":
            server = smtplib.SMTP_SSL(s["smtp_host"], s["smtp_port"], timeout=TIMEOUT, context=context)
        else:
            server = smtplib.SMTP(s["smtp_host"], s["smtp_port"], timeout=TIMEOUT)
            if s["smtp_security"] == "starttls":
                server.starttls(context=context)
        try:
            server.login(s["username"], s["password"])
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except smtplib.SMTPAuthenticationError as e:
        raise MailError("The outgoing mail server rejected the login. Check the app password.") from e
    except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
        raise MailError(f"The email couldn't be sent: {_short(e)}") from e


# ==================== THE DEMO'S MADE-UP INBOX ====================

_demo_lock = threading.Lock()
_demo_boxes: Dict[int, List[dict]] = {}


def _demo_box(user_id: int) -> List[dict]:
    """A made-up inbox, the same for everyone using the demo, reset when the demo is."""
    with _demo_lock:
        if user_id not in _demo_boxes:
            now = datetime.now(timezone.utc)
            samples = [
                ("Jordan Avery", "jordan.avery@example.com", "Friday?", 1, True, False,
                 "Hi! Are you free Friday evening? Same place as last time if that works.\n\nJ."),
                ("velvet.nights.fan", "vnf22@example.net", "Saw you're coming to Miami", 3, True, True,
                 "Hey, I've been a subscriber for a while. I saw you'll be in Miami next week. Any chance we could meet? "
                 "Happy to screen however you need."),
                ("Hotel Reservations", "reservations@example-hotel.com", "Your booking request", 7, True, False,
                 "Thank you for your request. A room is available for the dates you asked about. Reply to confirm."),
                ("Riley Chen", "riley.c@example.org", "Second reference", 20, False, True,
                 "Here's my second reference: Sam at the agency, sam@example.org. Let me know if you need anything else."),
                ("Clinic", "results@example-clinic.com", "Your results are ready", 30, False, True,
                 "Your recent test results are ready. Log in to the patient portal to view them."),
                ("Ad site", "noreply@example-ads.com", "Your listing renews in 3 days", 50, True, False,
                 "Your listing will renew automatically in 3 days. No action needed."),
            ]
            _demo_boxes[user_id] = [{
                "uid": i + 1, "from": {"name": name, "email": addr}, "subject": subject,
                "date": (now - timedelta(hours=hours)).isoformat(timespec="seconds"), "unread": unread, "flagged": flagged,
                "answered": False, "text": text, "to": [{"name": None, "email": "you@example.com"}], "cc": [],
                "reply_to": None, "message_id": f"<demo-{i + 1}@example.com>", "references": "", "attachments": [],
            } for i, (name, addr, subject, hours, unread, flagged, text) in enumerate(samples)]
        return _demo_boxes[user_id]


def reset_demo_inbox():
    with _demo_lock:
        _demo_boxes.clear()


# ==================== API ====================

_cache: Dict[tuple, tuple] = {}


def _forget(user_id: int):
    for key in [k for k in _cache if k[0] == user_id]:
        _cache.pop(key, None)


def _settings_or_fail(request: Request) -> dict:
    db = _get_db()
    try:
        s = load_settings(db, request.state.user["id"])
    finally:
        db.close()
    if not s["enabled"]:
        raise HTTPException(status_code=409, detail={"code": "not_set_up", "message": "Connect your email in settings first"})
    return s


def _fail(e: MailError):
    raise HTTPException(status_code=502, detail=str(e))


def _with_contacts(user_id: int, messages: List[dict]) -> List[dict]:
    """Mark which senders are already contacts."""
    addresses = {m["from"]["email"] for m in messages if m["from"].get("email")}
    if not addresses:
        return messages
    db = _get_db()
    try:
        found = {r["email"]: {"id": r["id"], "display_name": r["display_name"]} for r in db.execute(
            f"SELECT id, email, display_name FROM clients WHERE owner_id = ? AND email IN ({', '.join('?' * len(addresses))})",
            (user_id, *addresses))}
    finally:
        db.close()
    return [{**m, "contact": found.get(m["from"].get("email"))} for m in messages]


class MailSettings(BaseModel):
    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    imap_security: str = "ssl"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    username: str = ""
    password: Optional[str] = None      # blank or missing: keep the saved one
    from_name: Optional[str] = None
    from_address: Optional[str] = None
    folder: str = "INBOX"


def _public(s: dict) -> dict:
    return {**{k: v for k, v in s.items() if k != "password"}, "has_password": bool(s.get("password")), "demo": _demo(),
            "providers": PROVIDERS}


def _check(body: MailSettings):
    for security in (body.imap_security, body.smtp_security):
        if security not in ("ssl", "starttls", "none"):
            raise HTTPException(status_code=400, detail="Security must be ssl, starttls or none")
    for port in (body.imap_port, body.smtp_port):
        if not 1 <= port <= 65535:
            raise HTTPException(status_code=400, detail="Ports are numbers between 1 and 65535")
    for host in (body.imap_host, body.smtp_host):
        if host and not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+", host.strip()):
            raise HTTPException(status_code=400, detail="A server name is just a name, like imap.example.com")
    if body.from_address and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", body.from_address.strip()):
        raise HTTPException(status_code=400, detail="The send-from address doesn't look like an email address")


_SERVER_FIELDS = ("imap_host", "imap_port", "imap_security", "smtp_host", "smtp_port", "smtp_security", "username")


def _password_for(db, user_id: int, body: MailSettings) -> Optional[str]:
    """The password typed in, or else the saved one, but only for the same servers and username it was saved for.
    Otherwise anyone with a logged-in session could point the settings at their own server and collect it."""
    typed = (body.password or "").strip()
    if typed:
        return typed
    saved = load_settings(db, user_id)
    if not saved.get("password"):
        return None
    def norm(value) -> str:
        return str(value if value is not None else "").strip().lower()
    if any(norm(getattr(body, f)) != norm(saved.get(f)) for f in _SERVER_FIELDS):
        raise HTTPException(status_code=400, detail="The server or username changed, so enter the app password again")
    return saved["password"]


@router.get("/settings")
def get_settings(request: Request):
    db = _get_db()
    try:
        return _public(load_settings(db, request.state.user["id"]))
    finally:
        db.close()


@router.put("/settings")
def save_settings(body: MailSettings, request: Request):
    if _demo():
        raise HTTPException(status_code=403, detail="Email is turned off in the demo. Never enter real account details in a demo.")
    _check(body)
    user_id = request.state.user["id"]
    db = _get_db()
    try:
        password = _password_for(db, user_id, body)
        if body.enabled and not (body.imap_host.strip() and body.username.strip() and password):
            raise HTTPException(status_code=400, detail="Fill in the incoming server, username and app password first")
        values = {"enabled": "1" if body.enabled else "0", "imap_host": body.imap_host.strip(), "imap_port": str(body.imap_port),
                  "imap_security": body.imap_security, "smtp_host": body.smtp_host.strip(), "smtp_port": str(body.smtp_port),
                  "smtp_security": body.smtp_security, "username": body.username.strip(), "password": password,
                  "from_name": _clean_header(body.from_name or "") or None,
                  "from_address": (body.from_address or "").strip() or None, "folder": body.folder.strip() or "INBOX"}
        for key, value in values.items():
            _set(db, user_id, f"mail_{key}", value)
        db.commit()
        _forget(user_id)
        return _public(load_settings(db, user_id))
    finally:
        db.close()


@router.post("/test")
def test_settings(body: MailSettings, request: Request):
    """Log in to the incoming and outgoing servers with these details, without saving them."""
    if _demo():
        raise HTTPException(status_code=403, detail="Email is turned off in the demo. Never enter real account details in a demo.")
    _check(body)
    db = _get_db()
    try:
        password = _password_for(db, request.state.user["id"], body)
    finally:
        db.close()
    s = {**body.model_dump(), "password": password or ""}
    try:
        with Mailbox(s) as box:
            box._select()
            unread = len(box._search("unread"))
    except MailError as e:
        raise HTTPException(status_code=400, detail=f"Incoming mail: {e}")
    if s["smtp_host"]:
        try:
            server = (smtplib.SMTP_SSL(s["smtp_host"], s["smtp_port"], timeout=TIMEOUT, context=ssl.create_default_context())
                      if s["smtp_security"] == "ssl" else smtplib.SMTP(s["smtp_host"], s["smtp_port"], timeout=TIMEOUT))
            if s["smtp_security"] == "starttls":
                server.starttls(context=ssl.create_default_context())
            server.login(s["username"], s["password"])
            server.quit()
        except (smtplib.SMTPException, OSError, ssl.SSLError) as e:
            raise HTTPException(status_code=400, detail=f"Incoming mail works, but sending doesn't: {_short(e)}")
    return {"ok": True, "unread": unread}


@router.get("/messages")
def list_messages(request: Request, which: str = Query("unread", description="unread or important"),
                  limit: int = Query(25, ge=1, le=MAX_LIST), fresh: bool = False):
    if which not in ("unread", "important"):
        raise HTTPException(status_code=400, detail="which must be unread or important")
    user_id = request.state.user["id"]
    if _demo():
        box = _demo_box(user_id)
        chosen = [m for m in box if (m["unread"] if which == "unread" else m["flagged"])]
        listed = [{k: m[k] for k in ("uid", "from", "subject", "date", "unread", "flagged")} for m in chosen]
        return {"messages": _with_contacts(user_id, listed[:limit]), "total": len(chosen), "demo": True}
    s = _settings_or_fail(request)
    key = (user_id, which, limit)
    cached = _cache.get(key)
    if cached and not fresh and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    try:
        with Mailbox(s) as box:
            result = box.list(which, limit)
    except MailError as e:
        _fail(e)
    result = {**result, "messages": _with_contacts(user_id, result["messages"]), "demo": False}
    _cache[key] = (time.time(), result)
    return result


@router.get("/messages/{uid}")
def get_message(uid: int, request: Request):
    user_id = request.state.user["id"]
    if _demo():
        found = next((m for m in _demo_box(user_id) if m["uid"] == uid), None)
        if not found:
            raise HTTPException(status_code=404, detail="Message not found")
        return _with_contacts(user_id, [dict(found)])[0]
    s = _settings_or_fail(request)
    try:
        with Mailbox(s) as box:
            return _with_contacts(user_id, [box.get(uid)])[0]
    except MailError as e:
        _fail(e)


class Flags(BaseModel):
    unread: Optional[bool] = None
    flagged: Optional[bool] = None


@router.post("/messages/{uid}/flags")
def set_flags(uid: int, body: Flags, request: Request):
    user_id = request.state.user["id"]
    if _demo():
        found = next((m for m in _demo_box(user_id) if m["uid"] == uid), None)
        if not found:
            raise HTTPException(status_code=404, detail="Message not found")
        if body.unread is not None:
            found["unread"] = body.unread
        if body.flagged is not None:
            found["flagged"] = body.flagged
        return {"ok": True}
    s = _settings_or_fail(request)
    try:
        with Mailbox(s) as box:
            box.set_flags(uid, seen=None if body.unread is None else not body.unread, flagged=body.flagged)
    except MailError as e:
        _fail(e)
    _forget(user_id)
    return {"ok": True}


class Reply(BaseModel):
    body: str
    reply_all: bool = False


@router.post("/messages/{uid}/reply")
def reply(uid: int, body: Reply, request: Request):
    """Send a reply from your own account. It's quoted underneath, threaded, and kept in your Sent folder."""
    if not body.body.strip():
        raise HTTPException(status_code=400, detail="Write something first")
    if len(body.body) > 50_000:
        raise HTTPException(status_code=400, detail="That reply is too long")
    user_id = request.state.user["id"]
    if _demo():
        found = next((m for m in _demo_box(user_id) if m["uid"] == uid), None)
        if not found:
            raise HTTPException(status_code=404, detail="Message not found")
        found["answered"] = True
        found["unread"] = False
        return {"ok": True, "sent_to": found["from"]["email"], "demo": True}
    s = _settings_or_fail(request)
    try:
        with Mailbox(s) as box:
            original = box.get(uid)
            msg = build_reply(s, original, body.body, body.reply_all)
            send(s, msg)
            box.set_flags(uid, seen=True, answered=True)
            try:
                box.save_sent(msg.as_bytes())
            except Exception:
                pass   # the reply went; a missing copy in Sent isn't worth failing over
    except MailError as e:
        _fail(e)
    _forget(user_id)
    return {"ok": True, "sent_to": msg["To"], "demo": False}
