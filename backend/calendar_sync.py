"""
One-way calendar sync, per person: sworkr -> a calendar account that speaks CalDAV (Nextcloud, iCloud,
Fastmail, and most others).

What goes over:
- Bookings and health tests, as events in a calendar called "sworkr".
- Tours and time off, as all-day events in the same calendar.
- Tasks, as to-dos in a list called "sworkr tasks" (where the account accepts them: iCloud doesn't).

Each person connects their own account on their settings page, with the account's address, username and an
app password. The calendar and task list are found the standard way (RFC 6764 / RFC 4791): the account's
"principal", then its "calendar home", where sworkr creates the two collections if they aren't there.

- Saving anything queues it; one background thread pushes changes, so a slow or offline server never slows
  sworkr down. A full sync runs at startup, after settings change, on "Sync now", and every hour; it also
  removes calendar entries whose sworkr record no longer exists.
- One way only: edits made in the calendar app are overwritten by the next sync.
"""

import logging
import queue
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

EVENTS_SLUG, EVENTS_NAME = "sworkr", "sworkr"
TASKS_SLUG, TASKS_NAME = "sworkr-tasks", "sworkr tasks"
EVENT_PREFIX = "sworkr-appointment-"   # kept from the first version, so existing events are recognised
PREFIXES = {"appointment": "sworkr-appointment-", "period": "sworkr-period-", "task": "sworkr-task-", "post": "sworkr-post-"}
FULL_SYNC_EVERY = 3600             # seconds
RETRY_AFTER_ERROR = 300            # seconds
NO_TASKS = "none"                  # saved as the task list's address when the account doesn't take to-dos

log = logging.getLogger("sworkr.calendar")
_get_db: Optional[Callable] = None


class SyncError(Exception):
    pass


Item = Tuple[str, int]            # ("appointment" | "period" | "task", id)


# ==================== SETTINGS (per person) ====================

SETTING_KEYS = ("cal_enabled", "cal_url", "cal_username", "cal_password", "cal_discreet", "cal_events_url",
                "cal_tasks_url", "cal_last_sync_at", "cal_last_error", "cal_last_error_at")


def get_setting(db, user_id: int, key: str) -> Optional[str]:
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return row["value"] if row else None


def set_setting(db, user_id: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, value))
    db.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_url(url: str) -> str:
    """Accept whatever gets pasted ('cloud.example.com', '.../index.php/apps/calendar/', 'caldav.icloud.com')."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("That doesn't look like a web address")
    # A Nextcloud page address: keep only the part before Nextcloud's own paths.
    path = re.split(r"/(?:index\.php|apps|remote\.php|login)(?:/|$)", parts.path, maxsplit=1)[0]
    return f"{parts.scheme}://{parts.netloc}{path.rstrip('/')}"


def same_server(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two addresses point at the same server (scheme, host and port)."""
    if not a or not b:
        return False
    pa, pb = urlsplit(a if "://" in a else "https://" + a), urlsplit(b if "://" in b else "https://" + b)
    return (pa.scheme.lower(), pa.netloc.lower()) == (pb.scheme.lower(), pb.netloc.lower())


def saved_password_for(db, user_id: int, url: str, username: str) -> Optional[str]:
    """The saved app password, but only for the server and username it was saved with. Without this, anyone with
    a logged-in session could point the settings at their own server and have sworkr send them the password."""
    password = get_setting(db, user_id, "cal_password")
    if not password or not url:
        return None
    if not same_server(url, get_setting(db, user_id, "cal_url")) or \
            username.strip().lower() != (get_setting(db, user_id, "cal_username") or "").strip().lower():
        raise HTTPException(status_code=400, detail="The server or username changed, so enter the app password again")
    return password


def enabled_users(db) -> List[int]:
    return [r[0] for r in db.execute("""
        SELECT e.user_id FROM user_settings e
        JOIN user_settings u ON u.user_id = e.user_id AND u.key = 'cal_url' AND IFNULL(u.value, '') != ''
        WHERE e.key = 'cal_enabled' AND e.value = '1'
        ORDER BY e.user_id
    """)]


# ==================== CALDAV ====================

NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav"}


def _propfind_body(*props: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            f'<d:prop>{"".join(props)}</d:prop></d:propfind>')


class CalDav:
    """A CalDAV account. `prepare()` finds (or creates) sworkr's calendar and task list."""

    def __init__(self, url: str, username: str, password: str, events_url: Optional[str] = None,
                 tasks_url: Optional[str] = None, transport: Optional[httpx.BaseTransport] = None):
        self.base = url.rstrip("/") + "/"
        self.http = httpx.Client(auth=(username, password), timeout=30, follow_redirects=True, transport=transport,
                                 headers={"User-Agent": "sworkr-calendar-sync"})
        self.events_url = events_url or None
        self.tasks_url = tasks_url or None

    def close(self):
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @property
    def tasks_supported(self) -> bool:
        return self.tasks_url not in (None, NO_TASKS)

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            r = self.http.request(method, urljoin(self.base, url), **kw)
        except httpx.HTTPError as e:
            raise SyncError(f"Couldn't reach the calendar server: {e}") from e
        if r.status_code == 401:
            raise SyncError("The calendar server rejected the username or app password")
        return r

    def _propfind(self, url: str, depth: str, *props: str):
        r = self._request("PROPFIND", url, headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
                          content=_propfind_body(*props))
        if r.status_code != 207:
            return r, None
        try:
            return r, ET.fromstring(r.content)
        except ET.ParseError:
            return r, None

    @staticmethod
    def _href(response: httpx.Response, root, path: str) -> Optional[str]:
        el = root.find(path, NS) if root is not None else None
        return urljoin(str(response.url), el.text.strip()) if el is not None and el.text else None

    def discover_home(self) -> str:
        """The account's calendar home: where its calendars live."""
        principal = None
        path = urlsplit(self.base).path.strip("/")
        candidates = [self.base] if path else [urljoin(self.base, "/.well-known/caldav"),
                                               urljoin(self.base, "/remote.php/dav/"), self.base]
        for candidate in candidates:
            try:
                r, root = self._propfind(candidate, "0", "<d:current-user-principal/>")
            except SyncError as e:
                if "rejected" in str(e):
                    raise
                continue
            principal = self._href(r, root, ".//d:current-user-principal/d:href")
            if principal:
                break
        if not principal:
            raise SyncError("Couldn't find a calendar account at that address. Check it (see the help below the form).")
        r, root = self._propfind(principal, "0", "<c:calendar-home-set/>")
        home = self._href(r, root, ".//c:calendar-home-set/d:href")
        if not home:
            raise SyncError("The server didn't say where its calendars are")
        return home if home.endswith("/") else home + "/"

    def _ensure(self, home: str, slug: str, name: str, component: str) -> Optional[str]:
        url = urljoin(home, slug + "/")
        r, _ = self._propfind(url, "0", "<d:resourcetype/>")
        if r.status_code == 207:
            return url
        r = self._request("MKCALENDAR", url, headers={"Content-Type": "application/xml; charset=utf-8"}, content=(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<c:mkcalendar xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:x="http://apple.com/ns/ical/">'
            f'<d:set><d:prop><d:displayname>{name}</d:displayname><x:calendar-color>#fc4c9c</x:calendar-color>'
            f'<c:supported-calendar-component-set><c:comp name="{component}"/></c:supported-calendar-component-set>'
            '</d:prop></d:set></c:mkcalendar>'))
        if r.status_code in (200, 201):
            return url
        # Couldn't create it here: use a calendar of that name if the person made one themselves.
        r, root = self._propfind(home, "1", "<d:displayname/>", "<d:resourcetype/>")
        for resp in (root.iterfind("d:response", NS) if root is not None else []):
            shown = resp.find(".//d:displayname", NS)
            if shown is not None and (shown.text or "").strip().lower() == name and resp.find(".//c:calendar", NS) is not None:
                return urljoin(str(r.url), resp.find("d:href", NS).text)
        return None

    def prepare(self):
        """Find or create the calendar and the task list (once; the addresses are remembered)."""
        if self.events_url and self.tasks_url:
            return
        home = self.discover_home()
        self.events_url = self.events_url or self._ensure(home, EVENTS_SLUG, EVENTS_NAME, "VEVENT")
        if not self.events_url:
            raise SyncError(f"Couldn't create the '{EVENTS_NAME}' calendar. Create a calendar called "
                            f"'{EVENTS_NAME}' in your calendar app, then press Sync now.")
        self.tasks_url = self.tasks_url or self._ensure(home, TASKS_SLUG, TASKS_NAME, "VTODO") or NO_TASKS

    def _collection(self, kind: str) -> Optional[str]:
        if kind == "task":
            return self.tasks_url if self.tasks_supported else None
        return self.events_url

    def _url(self, kind: str, item_id: int) -> Optional[str]:
        collection = self._collection(kind)
        return f"{collection}{PREFIXES[kind]}{item_id}.ics" if collection else None

    def list_items(self) -> Set[Item]:
        """Every sworkr item in the calendar and the task list."""
        found = set()
        for url in {self.events_url, self.tasks_url if self.tasks_supported else None} - {None}:
            r, root = self._propfind(url, "1", "<d:getetag/>")
            if root is None:
                raise SyncError(f"Couldn't list the sworkr calendar (HTTP {r.status_code})")
            for href in root.iterfind(".//d:response/d:href", NS):
                m = re.search(r"sworkr-(appointment|period|task|post)-(\d+)\.ics$", unquote(href.text or ""))
                if m:
                    found.add((m.group(1), int(m.group(2))))
        return found

    def put(self, kind: str, item_id: int, ics: bytes):
        url = self._url(kind, item_id)
        if not url:
            return   # the account doesn't take to-dos
        r = self._request("PUT", url, content=ics, headers={"Content-Type": "text/calendar; charset=utf-8"})
        if r.status_code not in (200, 201, 204):
            raise SyncError(f"{kind} {item_id}: HTTP {r.status_code}")

    def delete(self, kind: str, item_id: int):
        url = self._url(kind, item_id)
        if not url:
            return
        r = self._request("DELETE", url)
        if r.status_code not in (200, 204, 404):
            raise SyncError(f"removing {kind} {item_id}: HTTP {r.status_code}")


# ==================== ICALENDAR ====================

def _escape(text) -> str:
    return (str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def _fold(line: str) -> str:
    """iCalendar lines may be at most 75 bytes; longer ones continue on the next line after a space."""
    parts, current = [], ""
    for ch in line:
        if len((current + ch).encode()) > 75:
            parts.append(current)
            current = " " + ch
        else:
            current += ch
    parts.append(current)
    return "\r\n".join(parts)


def _utc_stamp(value) -> str:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _calendar(component: List[str]) -> bytes:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//sworkr//sworkr//EN", *component, "END:VCALENDAR"]
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode()


def appointment_ics(appt: dict, discreet: bool) -> bytes:
    start = datetime.fromisoformat(appt["scheduled_date"].replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=appt["duration_minutes"])
    if discreet:
        summary = "Appointment"
    else:
        summary = appt["service_type"] + (f" – {appt['client_name']}" if appt.get("client_name") else "")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{EVENT_PREFIX}{appt['id']}",
        f"DTSTAMP:{_utc_stamp(datetime.now(timezone.utc))}",
        f"LAST-MODIFIED:{_utc_stamp(appt['updated_at'])}",
        f"DTSTART:{_utc_stamp(start)}",
        f"DTEND:{_utc_stamp(end)}",
        f"SUMMARY:{_escape(summary)}",
        f"STATUS:{'CANCELLED' if appt['status'] == 'cancelled' else 'CONFIRMED'}",
    ]
    if not discreet:
        description = f"Status: {appt['status']}"
        if appt.get("notes"):
            description += f"\n\n{appt['notes']}"
        lines.append(f"DESCRIPTION:{_escape(description)}")
        where = " ".join(x for x in (appt.get("location_type"), appt.get("location")) if x)
        if where:
            lines.append(f"LOCATION:{_escape(where)}")
    return _calendar([*lines, "END:VEVENT"])


TIME_OFF = {"day_off": "Day off", "vacation": "Vacation"}


def period_ics(period: dict, discreet: bool) -> bytes:
    """A tour or time off, as an all-day event from its first day to its last."""
    last = date.fromisoformat(period["end_date"])
    if period["kind"] == "tour":
        summary = "Away" if discreet else f"Tour: {period['name']}"
    else:
        summary = TIME_OFF.get(period["time_off_type"], "Time off")
        if period.get("name") and not discreet:
            summary += f": {period['name']}"
    lines = [
        "BEGIN:VEVENT",
        f"UID:{PREFIXES['period']}{period['id']}",
        f"DTSTAMP:{_utc_stamp(datetime.now(timezone.utc))}",
        f"LAST-MODIFIED:{_utc_stamp(period['updated_at'])}",
        f"DTSTART;VALUE=DATE:{period['start_date'].replace('-', '')}",
        f"DTEND;VALUE=DATE:{(last + timedelta(days=1)).isoformat().replace('-', '')}",
        f"SUMMARY:{_escape(summary)}",
        "TRANSP:TRANSPARENT",
    ]
    if not discreet:
        if period.get("location"):
            lines.append(f"LOCATION:{_escape(period['location'])}")
        if period.get("notes"):
            lines.append(f"DESCRIPTION:{_escape(period['notes'])}")
    return _calendar([*lines, "END:VEVENT"])


def task_ics(task: dict, discreet: bool) -> bytes:
    lines = [
        "BEGIN:VTODO",
        f"UID:{PREFIXES['task']}{task['id']}",
        f"DTSTAMP:{_utc_stamp(datetime.now(timezone.utc))}",
        f"LAST-MODIFIED:{_utc_stamp(task['updated_at'])}",
        f"SUMMARY:{_escape('Task' if discreet else task['title'])}",
    ]
    if task.get("due_at"):
        lines.append(f"DUE:{_utc_stamp(task['due_at'])}")
    elif task.get("due_date"):
        lines.append(f"DUE;VALUE=DATE:{task['due_date'].replace('-', '')}")
    if task.get("done_at"):
        lines += ["STATUS:COMPLETED", f"COMPLETED:{_utc_stamp(task['done_at'])}", "PERCENT-COMPLETE:100"]
    else:
        lines.append("STATUS:NEEDS-ACTION")
    if not discreet:
        about = [f"With: {task['client_name']}" if task.get("client_name") else None,
                 f"Tour: {task['tour_name']}" if task.get("tour_name") else None, task.get("notes")]
        text = "\n".join(x for x in about if x)
        if text:
            lines.append(f"DESCRIPTION:{_escape(text)}")
    return _calendar([*lines, "END:VTODO"])


def post_ics(post: dict, discreet: bool) -> bytes:
    """A planned post, as a 15-minute reminder at its time. Posts without a time, and skipped ones, aren't sent."""
    when = post.get("posted_at") or post.get("scheduled_at")
    start = datetime.fromisoformat(when.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    done = post["status"] == "posted"
    summary = ("Posted" if done else "Post") + ("" if discreet else f": {post['platform']}" + (f" ({post['account']})" if post.get("account") else ""))
    lines = [
        "BEGIN:VEVENT",
        f"UID:{PREFIXES['post']}{post['id']}",
        f"DTSTAMP:{_utc_stamp(datetime.now(timezone.utc))}",
        f"LAST-MODIFIED:{_utc_stamp(post['updated_at'])}",
        f"DTSTART:{_utc_stamp(start)}",
        f"DTEND:{_utc_stamp(start + timedelta(minutes=15))}",
        f"SUMMARY:{_escape(summary)}",
        "TRANSP:TRANSPARENT",
    ]
    if not discreet and post.get("caption"):
        lines.append(f"DESCRIPTION:{_escape(post['caption'][:1000])}")
    return _calendar([*lines, "END:VEVENT"])


# ==================== WHAT TO SYNC ====================

def _appointment(db, appointment_id: int, owner_id: int) -> Optional[dict]:
    row = db.execute("""
        SELECT a.*, c.display_name || IFNULL(' & ' || c2.display_name, '') AS client_name
        FROM appointments a LEFT JOIN clients c ON a.client_id = c.id LEFT JOIN clients c2 ON a.second_client_id = c2.id
        WHERE a.id = ? AND a.owner_id = ?
    """, (appointment_id, owner_id)).fetchone()
    return dict(row) if row else None


def _period(db, period_id: int, owner_id: int) -> Optional[dict]:
    row = db.execute("SELECT * FROM tours WHERE id = ? AND owner_id = ?", (period_id, owner_id)).fetchone()
    return dict(row) if row else None


def _task(db, task_id: int, owner_id: int) -> Optional[dict]:
    row = db.execute("""
        SELECT t.*, c.display_name AS client_name, r.name AS tour_name
        FROM tasks t LEFT JOIN clients c ON t.client_id = c.id LEFT JOIN tours r ON t.tour_id = r.id
        WHERE t.id = ? AND t.owner_id = ?
    """, (task_id, owner_id)).fetchone()
    return dict(row) if row else None


def _post(db, post_id: int, owner_id: int) -> Optional[dict]:
    row = db.execute("""
        SELECT * FROM posts WHERE id = ? AND owner_id = ? AND status != 'skipped'
          AND COALESCE(posted_at, scheduled_at) IS NOT NULL
    """, (post_id, owner_id)).fetchone()
    return dict(row) if row else None


LOADERS = {"appointment": (_appointment, appointment_ics), "period": (_period, period_ics), "task": (_task, task_ics),
           "post": (_post, post_ics)}
TABLES = {"appointment": "appointments", "period": "tours", "task": "tasks", "post": "posts"}


def _everything(db, owner_id: int) -> Set[Item]:
    return {(kind, r[0]) for kind, table in TABLES.items()
            for r in db.execute(f"SELECT id FROM {table} WHERE owner_id = ?", (owner_id,))}


# ==================== BACKGROUND SYNC ====================

# Queue entries: (kind, id, owner id or None). kind "all" means a full sync (of that person, or of everyone).
_queue: "queue.Queue[tuple]" = queue.Queue()
_status = {"running": False}


def queue_item(kind: str, item_id: Optional[int], owner_id: Optional[int] = None):
    _queue.put((kind, item_id, owner_id))


def queue_appointment(appointment_id: int):
    queue_item("appointment", appointment_id)


def queue_client(client_id: int):
    """A contact's name is part of their bookings' titles."""
    queue_item("client", client_id)


def queue_full_sync(owner_id: Optional[int] = None):
    queue_item("all", None, owner_id)


def _connect(db, owner_id: int) -> CalDav:
    return CalDav(get_setting(db, owner_id, "cal_url") or "", get_setting(db, owner_id, "cal_username") or "",
                  get_setting(db, owner_id, "cal_password") or "", get_setting(db, owner_id, "cal_events_url"),
                  get_setting(db, owner_id, "cal_tasks_url"))


def _plan(db, batch: Iterable[tuple], users: List[int]) -> Tuple[Dict[int, Set[Item]], Set[int]]:
    """Which items to push for whom, and who needs a full sync."""
    per_user: Dict[int, Set[Item]] = {u: set() for u in users}
    full: Set[int] = set()
    for kind, item_id, owner in batch:
        if kind == "all":
            full |= {owner} if owner is not None else set(users)
            continue
        if kind == "client":
            for a in db.execute("SELECT id, owner_id FROM appointments WHERE client_id = ? OR second_client_id = ?", (item_id, item_id)):
                if a["owner_id"] in per_user:
                    per_user[a["owner_id"]].add(("appointment", a["id"]))
            for t in db.execute("SELECT id, owner_id FROM tasks WHERE client_id = ?", (item_id,)):
                if t["owner_id"] in per_user:
                    per_user[t["owner_id"]].add(("task", t["id"]))
            continue
        if owner is None:
            row = db.execute(f"SELECT owner_id FROM {TABLES[kind]} WHERE id = ?", (item_id,)).fetchone()
            owner = row[0] if row else None
        if owner is None:      # deleted: whoever had it removes it (ids are never reused, so this is safe)
            for u in users:
                per_user[u].add((kind, item_id))
        elif owner in per_user:
            per_user[owner].add((kind, item_id))
    return per_user, full & set(users)


def _sync_user(db, owner_id: int, items: Set[Item], full: bool):
    discreet = get_setting(db, owner_id, "cal_discreet") == "1"
    errors = []
    try:
        with _connect(db, owner_id) as dav:
            dav.prepare()
            for key, value in (("cal_events_url", dav.events_url), ("cal_tasks_url", dav.tasks_url)):
                if value and value != get_setting(db, owner_id, key):
                    set_setting(db, owner_id, key, value)
            if full:
                # Anything in the calendar that's no longer in sworkr goes, even if it was deleted
                # while sync was off or the server was unreachable.
                items = items | _everything(db, owner_id) | dav.list_items()
            for kind, item_id in sorted(items):
                try:
                    load, to_ics = LOADERS[kind]
                    record = load(db, item_id, owner_id)
                    if record:
                        dav.put(kind, item_id, to_ics(record, discreet))
                    else:
                        dav.delete(kind, item_id)
                except SyncError as e:
                    if "username or app password" in str(e):
                        raise
                    errors.append(str(e))
        if errors:
            raise SyncError(f"{len(errors)} item(s) didn't sync. First problem: {errors[0]}")
        set_setting(db, owner_id, "cal_last_sync_at", _now_iso())
        set_setting(db, owner_id, "cal_last_error", None)
    except Exception as e:  # keep the worker alive whatever happens
        log.warning("Calendar sync for user %s failed: %s", owner_id, e)
        set_setting(db, owner_id, "cal_last_error", str(e)[:500])
        set_setting(db, owner_id, "cal_last_error_at", _now_iso())


def run_sync(batch) -> None:
    """Push one batch of changes, for each person who has sync turned on."""
    db = _get_db()
    try:
        users = enabled_users(db)
        if not users:
            return
        per_user, full = _plan(db, batch, users)
        for owner_id in users:
            if per_user[owner_id] or owner_id in full:
                _sync_user(db, owner_id, per_user[owner_id], owner_id in full)
    except Exception as e:
        log.warning("Calendar sync failed: %s", e)
    finally:
        db.close()


def _any_failed() -> bool:
    db = _get_db()
    try:
        return bool(db.execute(
            "SELECT 1 FROM user_settings WHERE key = 'cal_last_error' AND IFNULL(value, '') != ''").fetchone())
    finally:
        db.close()


def _worker():
    while True:
        try:
            batch = {_queue.get(timeout=RETRY_AFTER_ERROR if _any_failed() else FULL_SYNC_EVERY)}
        except queue.Empty:
            batch = {("all", None, None)}  # hourly catch-up, or a retry after an error
        time.sleep(0.5)  # let a burst of edits arrive, then push them together
        while True:
            try:
                batch.add(_queue.get_nowait())
            except queue.Empty:
                break
        _status["running"] = True
        try:
            run_sync(batch)
        finally:
            _status["running"] = False


def start(get_db: Callable, background: bool = True):
    global _get_db
    _get_db = get_db
    if background:
        threading.Thread(target=_worker, name="calendar-sync", daemon=True).start()
        queue_full_sync()


# ==================== API ====================

router = APIRouter(prefix="/api/calendar-sync")


class SyncSettings(BaseModel):
    enabled: bool = False
    url: str = ""
    username: str = ""
    app_password: Optional[str] = None   # blank or missing: keep the saved one
    discreet: bool = False


class TestRequest(BaseModel):
    url: str
    username: str
    app_password: Optional[str] = None


def _demo() -> bool:
    import demo   # imported here: demo.py doesn't use this module, but keeps start-up order simple
    return demo.ENABLED


def _refuse_in_demo():
    if _demo():
        raise HTTPException(status_code=403, detail="Calendar sync is turned off in the demo. "
                                                    "Never enter real account details in a demo.")


def _status_payload(db, user_id: int) -> dict:
    tasks_url = get_setting(db, user_id, "cal_tasks_url")
    return {
        "enabled": get_setting(db, user_id, "cal_enabled") == "1",
        "url": get_setting(db, user_id, "cal_url") or "",
        "username": get_setting(db, user_id, "cal_username") or "",
        "has_password": bool(get_setting(db, user_id, "cal_password")),   # the password itself is never sent back
        "discreet": get_setting(db, user_id, "cal_discreet") == "1",
        "last_sync_at": get_setting(db, user_id, "cal_last_sync_at"),
        "last_error": get_setting(db, user_id, "cal_last_error"),
        "last_error_at": get_setting(db, user_id, "cal_last_error_at"),
        "tasks_supported": None if not tasks_url else tasks_url != NO_TASKS,
        "busy": _status["running"] or not _queue.empty(),
        "demo": _demo(),
    }


@router.get("")
def sync_status(request: Request):
    db = _get_db()
    try:
        return _status_payload(db, request.state.user["id"])
    finally:
        db.close()


@router.put("")
def save_settings(body: SyncSettings, request: Request):
    _refuse_in_demo()
    user_id = request.state.user["id"]
    try:
        url = normalize_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    username = body.username.strip()
    db = _get_db()
    try:
        password = (body.app_password or "").strip() or saved_password_for(db, user_id, url, username)
        if body.enabled and not (url and username and password):
            raise HTTPException(status_code=400, detail="Fill in the address, username and app password first")
        if (url, username) != (get_setting(db, user_id, "cal_url"), get_setting(db, user_id, "cal_username")):
            set_setting(db, user_id, "cal_events_url", None)   # a different account: find its calendars again
            set_setting(db, user_id, "cal_tasks_url", None)
        for key, value in (("cal_url", url), ("cal_username", username), ("cal_password", password),
                           ("cal_enabled", "1" if body.enabled else "0"),
                           ("cal_discreet", "1" if body.discreet else "0")):
            set_setting(db, user_id, key, value)
        set_setting(db, user_id, "cal_last_error", None)
        if body.enabled:
            queue_full_sync(user_id)
        return _status_payload(db, user_id)
    finally:
        db.close()


@router.post("/test")
def test_connection(body: TestRequest, request: Request):
    """Check the details without saving them."""
    _refuse_in_demo()
    user_id = request.state.user["id"]
    try:
        url = normalize_url(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db = _get_db()
    try:
        password = (body.app_password or "").strip() or saved_password_for(db, user_id, url, body.username) or ""
    finally:
        db.close()
    if not (url and body.username.strip() and password):
        raise HTTPException(status_code=400, detail="Fill in the address, username and app password first")
    try:
        with CalDav(url, body.username.strip(), password) as dav:
            home = dav.discover_home()
    except SyncError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "url": url, "calendar_home": home}


@router.post("/sync", status_code=202)
def sync_now(request: Request):
    _refuse_in_demo()
    queue_full_sync(request.state.user["id"])
    return {"queued": True}
