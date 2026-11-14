"""Email tests: reading, flags, replies and settings, against a stand-in mailbox; and the parts that turn emails
into safe plain text and build replies. Run with:  docker compose run --rm tests"""
import email
import email.policy
import os
import sys
import tempfile
import uuid

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import demo  # noqa: E402
import mail  # noqa: E402
import main  # noqa: E402

PASSWORD = "correct-horse-battery"
SETTINGS = {"enabled": True, "imap_host": "imap.example.com", "imap_port": 993, "imap_security": "ssl",
            "smtp_host": "smtp.example.com", "smtp_port": 587, "smtp_security": "starttls",
            "username": "me@example.com", "password": "app-password-123", "from_name": "Sunny"}


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    name = "m-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def message(uid, sender, subject, unread=True, flagged=False, text="Hello"):
    name, addr = sender
    return {"uid": uid, "from": {"name": name, "email": addr}, "subject": subject, "date": f"2046-01-0{uid}T10:00:00+00:00",
            "unread": unread, "flagged": flagged, "answered": False, "text": text, "to": [{"name": None, "email": "me@example.com"}],
            "cc": [{"name": None, "email": "friend@example.com"}], "reply_to": None, "message_id": f"<m{uid}@example.com>",
            "references": "", "attachments": []}


class FakeMailbox:
    """Stands in for mail.Mailbox: a little inbox in memory."""
    inbox = []
    fail = None
    sent_copies = []

    def __init__(self, settings):
        self.settings = settings

    def __enter__(self):
        if FakeMailbox.fail:
            raise mail.MailError(FakeMailbox.fail)
        return self

    def __exit__(self, *exc):
        pass

    def list(self, which, limit=25):
        chosen = [m for m in self.inbox if (m["unread"] if which == "unread" else m["flagged"])]
        return {"messages": [{k: m[k] for k in ("uid", "from", "subject", "date", "unread", "flagged")} for m in chosen][-limit:],
                "total": len(chosen)}

    def get(self, uid):
        found = next((m for m in self.inbox if m["uid"] == uid), None)
        if not found:
            raise mail.MailError("That message isn't in the folder any more")
        return dict(found)

    def set_flags(self, uid, seen=None, flagged=None, answered=False):
        m = next(m for m in self.inbox if m["uid"] == uid)
        if seen is not None:
            m["unread"] = not seen
        if flagged is not None:
            m["flagged"] = flagged
        if answered:
            m["answered"] = True

    def save_sent(self, raw):
        FakeMailbox.sent_copies.append(raw)


@pytest.fixture
def box(monkeypatch):
    FakeMailbox.inbox = [message(1, ("Jordan Avery", "jordan@example.com"), "Friday?"),
                         message(2, (None, "stranger@example.net"), "Hi", flagged=True),
                         message(3, ("Old News", "old@example.com"), "Read already", unread=False, flagged=True)]
    FakeMailbox.fail = None
    FakeMailbox.sent_copies = []
    sent = []
    monkeypatch.setattr(mail, "Mailbox", FakeMailbox)
    monkeypatch.setattr(mail, "send", lambda s, msg: sent.append(msg))
    mail._cache.clear()
    return sent


def connected(api):
    r = api.put("/api/mail/settings", json=SETTINGS)
    assert r.status_code == 200, r.text
    return api


# ---------- settings ----------

def test_settings_are_per_person_and_never_send_the_password_back(api, admin):
    s = connected(api).get("/api/mail/settings").json()
    assert s["enabled"] and s["has_password"] and s["from_address"] == "me@example.com"
    assert "app-password-123" not in str(s) and "gmail" in s["providers"]
    assert admin.get("/api/mail/settings").json()["has_password"] is False
    # Leaving the password empty keeps the saved one.
    assert api.put("/api/mail/settings", json={**SETTINGS, "password": ""}).json()["has_password"]


def test_settings_are_checked(api):
    for change in ({"imap_security": "maybe"}, {"imap_port": 0}, {"imap_host": "imap.example.com; rm -rf"},
                   {"from_address": "not an address"}, {"password": None, "username": ""}):
        assert api.put("/api/mail/settings", json={**SETTINGS, **change}).status_code == 400, change


def test_not_set_up_says_so(api):
    r = api.get("/api/mail/messages")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_set_up"


# ---------- reading ----------

def test_unread_and_important_lists_mark_known_contacts(api, box):
    connected(api)
    jordan = api.post("/api/clients", json={"name": "Jordan Avery", "email": "jordan@example.com"}).json()
    unread = api.get("/api/mail/messages", params={"which": "unread"}).json()
    assert [m["uid"] for m in unread["messages"]] == [1, 2] and unread["total"] == 2
    assert unread["messages"][0]["contact"] == {"id": jordan["id"], "display_name": "Jordan Avery"}
    assert unread["messages"][1]["contact"] is None
    important = api.get("/api/mail/messages", params={"which": "important", "fresh": True}).json()
    assert [m["uid"] for m in important["messages"]] == [2, 3]
    assert api.get("/api/mail/messages", params={"which": "spam"}).status_code == 400


def test_opening_and_flagging(api, box):
    connected(api)
    m = api.get("/api/mail/messages/1").json()
    assert m["text"] == "Hello" and m["unread"]             # opening doesn't mark it read
    assert api.post("/api/mail/messages/1/flags", json={"unread": False, "flagged": True}).status_code == 200
    assert FakeMailbox.inbox[0]["unread"] is False and FakeMailbox.inbox[0]["flagged"] is True
    assert [x["uid"] for x in api.get("/api/mail/messages").json()["messages"]] == [2]   # the list isn't stale


def test_server_problems_are_reported(api, box):
    connected(api)
    FakeMailbox.fail = "Couldn't reach the mail server: timed out"
    r = api.get("/api/mail/messages", params={"fresh": True})
    assert r.status_code == 502 and "timed out" in r.json()["detail"]


# ---------- replying ----------

def test_reply_is_threaded_quoted_and_saved(api, box):
    connected(api)
    r = api.post("/api/mail/messages/1/reply", json={"body": "Friday works!"})
    assert r.status_code == 200, r.text
    msg = box[0]
    assert msg["To"] == "Jordan Avery <jordan@example.com>" and msg["From"] == "Sunny <me@example.com>"
    assert msg["Subject"] == "Re: Friday?" and msg["In-Reply-To"] == "<m1@example.com>"
    assert msg["Cc"] is None
    text = msg.get_content()
    assert text.startswith("Friday works!") and "> Hello" in text
    assert FakeMailbox.inbox[0]["answered"] and not FakeMailbox.inbox[0]["unread"]
    assert len(FakeMailbox.sent_copies) == 1
    assert api.post("/api/mail/messages/1/reply", json={"body": "  "}).status_code == 400


def test_reply_all_copies_others_but_not_me(api, box):
    connected(api)
    api.post("/api/mail/messages/2/reply", json={"body": "Hi back", "reply_all": True})
    assert box[0]["Cc"] == "friend@example.com" and box[0]["To"] == "stranger@example.net"


def test_build_reply_never_lets_a_subject_add_headers():
    original = {"from": {"name": "X", "email": "x@example.com"}, "subject": "Hi\r\nBcc: victim@example.com",
                "message_id": "<a@b>", "text": "t", "to": [], "cc": []}
    msg = mail.build_reply({"from_address": "me@example.com", "from_name": None}, original, "ok", False)
    assert msg["Bcc"] is None and "\n" not in msg["Subject"]


# ---------- turning emails into safe text ----------

def test_html_email_becomes_plain_text_without_scripts_or_images():
    raw = (b"MIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\nSubject: =?utf-8?q?Caf=C3=A9?=\r\n\r\n"
           b"<html><head><style>p{}</style></head><body><script>alert(1)</script><p>Hello&nbsp;<b>there</b></p>"
           b"<img src='https://tracker.example/pixel.gif'><ul><li>one</li></ul></body></html>")
    msg = email.message_from_bytes(raw, policy=email.policy.compat32)
    text = mail.body_text(msg)
    assert "alert" not in text and "tracker" not in text and "<" not in text
    assert "Hello there" in text and "• one" in text
    assert mail.decode(msg["Subject"]) == "Café"


def test_plain_text_part_is_preferred():
    raw = (b"MIME-Version: 1.0\r\nContent-Type: multipart/alternative; boundary=x\r\n\r\n--x\r\n"
           b"Content-Type: text/plain\r\n\r\nPlain version\r\n--x\r\nContent-Type: text/html\r\n\r\n<p>HTML version</p>\r\n--x--\r\n")
    assert mail.body_text(email.message_from_bytes(raw, policy=email.policy.compat32)).strip() == "Plain version"


# ---------- the demo ----------

def test_the_demo_has_a_made_up_inbox_and_refuses_real_accounts(api, monkeypatch):
    monkeypatch.setattr(demo, "ENABLED", True)
    mail.reset_demo_inbox()
    assert api.put("/api/mail/settings", json=SETTINGS).status_code == 403
    assert api.post("/api/mail/test", json=SETTINGS).status_code == 403
    unread = api.get("/api/mail/messages").json()
    assert unread["demo"] and unread["total"] >= 3
    uid = unread["messages"][0]["uid"]
    assert api.post(f"/api/mail/messages/{uid}/flags", json={"unread": False}).status_code == 200
    assert uid not in [m["uid"] for m in api.get("/api/mail/messages").json()["messages"]]
    r = api.post(f"/api/mail/messages/{uid}/reply", json={"body": "Hi"}).json()
    assert r["ok"] and r["demo"]


def test_saved_password_is_never_sent_to_a_different_server(api, monkeypatch):
    """Someone with a logged-in session can't point the settings at their own server to collect the saved password."""
    connected(api)
    tried = []

    class Recorder(FakeMailbox):
        def __init__(self, settings):
            tried.append(settings)
    monkeypatch.setattr(mail, "Mailbox", Recorder)
    monkeypatch.setattr(mail.smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(OSError("no network in tests")))
    for change in ({"imap_host": "imap.attacker.example"}, {"smtp_host": "smtp.attacker.example"},
                   {"imap_security": "none"}, {"imap_port": 143}, {"username": "other@example.com"}):
        for call in (api.post, api.put):
            url = "/api/mail/test" if call == api.post else "/api/mail/settings"
            r = call(url, json={**SETTINGS, **change, "password": ""})
            assert r.status_code == 400 and "password again" in r.json()["detail"], (change, url)
    assert tried == []
    # The same servers still reuse it, and a typed password works anywhere.
    assert api.put("/api/mail/settings", json={**SETTINGS, "password": "", "imap_host": "IMAP.example.com "}).status_code == 200
    assert api.put("/api/mail/settings", json={**SETTINGS, "imap_host": "imap.new.example", "password": "new-pw"}).status_code == 200
