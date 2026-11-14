"""
Sworkr Management Service - Backend
FastAPI application: clients (with screening), appointments (with income and safety check-in),
expenses, search, accounts.
Run with: docker compose up --build
"""

import os
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, List, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, PrivateAttr

import auth
import backup
import calendar_sync
import collab
import contacts
import cycle
import content
import csv_io
import currencies
import finance
import arrangements
import calendar_dates
import blocklist
import signin
import taxes
import noshow
import documents
import meds
import personas
import places
import demo
import mail
import migrations
import safety
import tasks

# The interactive API docs (/docs, /redoc, /openapi.json) map out every endpoint. They're off unless
# ENABLE_API_DOCS=1, so a copy of sworkr that's reachable from the internet doesn't advertise itself.
_API_DOCS = os.environ.get("ENABLE_API_DOCS", "0") == "1"
app = FastAPI(title="Sworkr Management Service", version="2.0.0",
              docs_url="/docs" if _API_DOCS else None, redoc_url="/redoc" if _API_DOCS else None,
              openapi_url="/openapi.json" if _API_DOCS else None)

# Send cookies only over HTTPS. COOKIE_SECURE=1 forces it; otherwise it's on whenever the request came
# in over HTTPS through a reverse proxy (Caddy, nginx) that says so in X-Forwarded-Proto.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

COLOR_PALETTE = ["#fc4c9c", "#e67eb6", "#a73178", "#542b5c", "#4b86a6"]
MAX_REPEATS = 52


# ==================== ENUMS & MODELS ====================

class AppointmentStatus(str, Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ScreeningStatus(str, Enum):
    UNSCREENED = "unscreened"
    PENDING = "pending"
    VERIFIED = "verified"
    DECLINED = "declined"


class LocationType(str, Enum):
    INCALL = "incall"
    OUTCALL = "outcall"
    OTHER = "other"


class AppointmentKind(str, Enum):
    CLIENT = "client"
    TEST = "test"         # a health test (weekly, monthly or yearly); its cost is an expense


class TestType(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


TEST_LABELS = {"weekly": "Weekly test", "monthly": "Monthly test", "yearly": "Yearly test"}


class TourKind(str, Enum):
    TOUR = "tour"
    TIME_OFF = "time_off"


class TimeOffType(str, Enum):
    DAY_OFF = "day_off"
    VACATION = "vacation"


class WorkStyle(str, Enum):
    TOURS = "tours"
    FULL_TIME = "full_time"
    BOTH = "both"


# Input models (what the API accepts)
class ClientIn(BaseModel):
    name: Optional[str] = None              # optional: sometimes a handle is all that's known
    handles: List[contacts.Handle] = []     # social media handles
    display_handle: Optional[int] = None    # show them by this handle (its position in `handles`)
    industry: Optional[str] = None          # the line of work they're in
    role: str = "client"                    # client, partner (another worker), crew (photographer, driver…) or other
    couple_with: Optional[int] = None       # the other half of a couple (another contact)
    contact_phone: Optional[str] = None
    email: Optional[str] = None
    bio: Optional[str] = None
    tags: List[str] = []
    is_active: bool = True
    screening_status: ScreeningStatus = ScreeningStatus.UNSCREENED
    screening_notes: Optional[str] = None
    references: Optional[str] = None
    do_not_see: bool = False
    do_not_see_reason: Optional[str] = None
    birthday: Optional[date] = None
    drink_preferences: Optional[str] = None
    food_preferences: Optional[str] = None
    persona_id: Optional[int] = None        # which of your names they know you by
    _handles: list = PrivateAttr(default_factory=list)   # worked out by _validate_client
    _display: str = PrivateAttr(default="")


class AppointmentIn(BaseModel):
    client_id: Optional[int] = None       # every client appointment has one; a health test has none
    service_type: str = ""
    duration_minutes: int
    scheduled_date: datetime
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
    notes: Optional[str] = None
    rate: Optional[float] = None          # the agreed price
    amount_paid: float = 0                # received so far (a deposit, or all of it)
    payment_method: Optional[str] = None
    location_type: Optional[LocationType] = None
    location: Optional[str] = None
    safety_checkin: bool = False          # alert the trusted contact if not checked in afterwards
    kind: AppointmentKind = AppointmentKind.CLIENT
    test_type: Optional[TestType] = None  # health tests only
    cost: Optional[float] = None          # health tests only: what the test costs (becomes an expense)
    tour_id: Optional[int] = None         # health tests only: the tour its cost belongs to
    second_client_id: Optional[int] = None  # a couple booked together: the other person


class AppointmentCreate(AppointmentIn):
    # Extra start times for a repeating appointment. The browser works these out in local time,
    # so "every Tuesday at 7pm" stays at 7pm when the clocks change.
    repeat_dates: List[datetime] = []


class ExpenseIn(BaseModel):
    client_id: Optional[int] = None
    description: str
    amount: float
    category: str = "other"            # one of the user's expense categories (see finance.py)
    date: Optional[datetime] = None
    notes: Optional[str] = None
    tour_id: Optional[int] = None
    currency: str = currencies.DEFAULT


class TourIn(BaseModel):
    """A tour, or time off (a day off or a vacation). Dates are the worker's local calendar days;
    starts_at / ends_at are the same days as exact times (local midnight to the midnight after end_date)."""
    kind: TourKind = TourKind.TOUR
    time_off_type: Optional[TimeOffType] = None
    name: Optional[str] = None
    location: Optional[str] = None
    start_date: date
    end_date: date
    starts_at: datetime
    ends_at: datetime
    room_rent_per_day: Optional[float] = None
    notes: Optional[str] = None
    source_id: Optional[int] = None      # a stay at one of your places: its daily/weekly charges are logged


class Credentials(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class NewUser(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class NewPassword(BaseModel):
    password: str


class AccountSettings(BaseModel):
    idle_minutes: Optional[int] = None
    work_style: Optional[WorkStyle] = None


class NoteIn(BaseModel):
    body: str


# Output models (what the API returns)
class Client(ClientIn):
    display_name: str                       # what they're shown as everywhere
    couple_name: Optional[str] = None
    id: int
    created_at: datetime
    updated_at: datetime


class Appointment(AppointmentIn):
    id: int
    client_name: Optional[str] = None
    client_do_not_see: bool = False
    payment_status: str = "none"          # none | unpaid | partial | paid
    checked_in_at: Optional[datetime] = None
    alert_sent_at: Optional[datetime] = None
    series_id: Optional[str] = None
    my_amount_paid: Optional[float] = None   # what's yours after partners' shares
    partner_names: Optional[str] = None
    cancel_reason: Optional[str] = None      # client | late | no_show | me (cancelled ones)
    cancellation_fee: Optional[float] = None # what the client owes for a late cancellation or no-show
    created_at: datetime
    updated_at: datetime


class Expense(ExpenseIn):
    id: int
    date: datetime
    client_name: Optional[str] = None
    tour_name: Optional[str] = None
    test_type: Optional[str] = None       # set when a health test created this expense
    appointment_id: Optional[int] = None
    source: Optional[str] = None          # 'tour_room' when sworkr made it from a tour's room & board
    my_amount: Optional[float] = None     # your part of the cost after partners' shares
    partner_names: Optional[str] = None


class Tour(TourIn):
    id: int
    created_at: datetime
    updated_at: datetime


# ==================== DATABASE SETUP ====================

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
DB_PATH = os.path.join(DATA_DIR, "sworkr.db")


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def db_conn():
    """One connection per request, always closed afterwards, even when the request fails."""
    db = get_db()
    try:
        yield db
    finally:
        db.close()


DbDep = Annotated[sqlite3.Connection, Depends(db_conn)]


def current_user(request: Request) -> dict:
    """The logged-in user. The login check itself happens in the require_login middleware."""
    return request.state.user


UserDep = Annotated[dict, Depends(current_user)]


def require_admin(request: Request) -> dict:
    if not request.state.user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Only an admin account can do this")
    return request.state.user


AdminDep = Annotated[dict, Depends(require_admin)]


def init_db():
    """Create or upgrade the database. See migrations.py."""
    migrations.run(DB_PATH)


def to_utc_iso(dt: datetime) -> str:
    """Store every timestamp as UTC with an explicit offset. Naive input is treated as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def now_iso() -> str:
    return to_utc_iso(datetime.now(timezone.utc))


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def tag_colors(tags: List[str]) -> List[dict]:
    return [{"label": t, "color": COLOR_PALETTE[sum(map(ord, t)) % len(COLOR_PALETTE)]} for t in tags]


def split_tags(value: Optional[str]) -> List[str]:
    return [t.strip() for t in value.split(",")] if value else []


def like_term(text: str) -> str:
    """A 'contains' pattern for LIKE. Pair it with ESCAPE so % and _ in the text are matched literally."""
    escaped = text.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def clean(text: Optional[str]) -> Optional[str]:
    text = (text or "").strip()
    return text or None


# ==================== HELPERS ====================
# Every lookup takes the owner's user id: one user can never read or change another user's records.

def client_row(row, tags: List[str]) -> dict:
    data = dict(row)
    data["tags"] = tags
    data["handles"] = contacts.handles_from_db(data.get("handles"))
    data["references"] = data.pop("references_text", None)
    data["do_not_see"] = bool(data.get("do_not_see"))
    return data


def get_client_by_id(db, client_id: int, owner_id: int) -> Optional[dict]:
    row = db.execute("""SELECT c.*, (SELECT cw.display_name FROM clients cw WHERE cw.id = c.couple_with) AS couple_name FROM clients c WHERE c.id = ? AND c.owner_id = ?""",
                     (client_id, owner_id)).fetchone()
    if not row:
        return None
    tags = [r["tag_name"] for r in db.execute(
        "SELECT tag_name FROM client_tags WHERE client_id = ? ORDER BY tag_name", (client_id,))]
    return client_row(row, tags)


def link_couple(db, client_id: int, other_id: Optional[int], owner_id: int):
    """Make two contacts a couple (both ways), or unlink this one. Each contact is in at most one couple."""
    if other_id is not None:
        if other_id == client_id or not get_client_by_id(db, other_id, owner_id):
            raise HTTPException(status_code=400, detail="Choose another of your contacts as the other half of the couple")
    old = db.execute("SELECT couple_with FROM clients WHERE id = ?", (client_id,)).fetchone()
    for person in {client_id, other_id, old[0] if old else None} - {None}:
        db.execute("UPDATE clients SET couple_with = NULL WHERE couple_with = ? AND owner_id = ?", (person, owner_id))
    db.execute("UPDATE clients SET couple_with = NULL WHERE id IN (?, ?) AND owner_id = ?", (client_id, other_id or -1, owner_id))
    if other_id is not None:
        db.execute("UPDATE clients SET couple_with = ? WHERE id = ? AND owner_id = ?", (other_id, client_id, owner_id))
        db.execute("UPDATE clients SET couple_with = ? WHERE id = ? AND owner_id = ?", (client_id, other_id, owner_id))


def set_client_tags(db, client_id: int, tags: List[str]):
    db.execute("DELETE FROM client_tags WHERE client_id = ?", (client_id,))
    for tag in {t.lower().strip() for t in tags if t.strip()}:
        db.execute("INSERT INTO client_tags (client_id, tag_name) VALUES (?, ?)", (client_id, tag))


def payment_status(rate: Optional[float], amount_paid: Optional[float]) -> str:
    paid = amount_paid or 0
    if rate is None:
        return "paid" if paid > 0 else "none"
    if paid <= 0:
        return "unpaid" if rate > 0 else "paid"
    return "paid" if paid >= rate else "partial"


APPOINTMENT_SELECT = """
    SELECT a.*, c.display_name || IFNULL(' & ' || c2.display_name, '') AS client_name,
           MAX(IFNULL(c.do_not_see, 0), IFNULL(c2.do_not_see, 0)) AS client_do_not_see,
           (SELECT x.tour_id FROM expenses x WHERE x.appointment_id = a.id LIMIT 1) AS tour_id,
           a.amount_paid - """ + collab.partner_share_sql('appointment', 'a.amount_paid', 'a.id') + """ AS my_amount_paid,
           """ + collab.partner_names_sql('appointment', 'a.id') + """ AS partner_names
    FROM appointments a LEFT JOIN clients c ON a.client_id = c.id LEFT JOIN clients c2 ON a.second_client_id = c2.id
"""


def appointment_row(row) -> dict:
    data = dict(row)
    data["safety_checkin"] = bool(data.get("safety_checkin"))
    data["client_do_not_see"] = bool(data.get("client_do_not_see"))
    data["payment_status"] = payment_status(data.get("rate"), data.get("amount_paid"))
    return data


def get_appointment_by_id(db, appointment_id: int, owner_id: int) -> Optional[dict]:
    row = db.execute(APPOINTMENT_SELECT + " WHERE a.id = ? AND a.owner_id = ?", (appointment_id, owner_id)).fetchone()
    return appointment_row(row) if row else None


EXPENSE_SELECT = """
    SELECT e.*, c.display_name AS client_name, t.name AS tour_name, ap.test_type AS test_type,
           e.amount - """ + collab.partner_share_sql('expense', 'e.amount', 'e.id') + """ AS my_amount,
           """ + collab.partner_names_sql('expense', 'e.id') + """ AS partner_names
    FROM expenses e
    LEFT JOIN clients c ON e.client_id = c.id
    LEFT JOIN tours t ON e.tour_id = t.id
    LEFT JOIN appointments ap ON e.appointment_id = ap.id
"""


def get_expense_by_id(db, expense_id: int, owner_id: int) -> Optional[dict]:
    row = db.execute(EXPENSE_SELECT + " WHERE e.id = ? AND e.owner_id = ?", (expense_id, owner_id)).fetchone()
    return dict(row) if row else None


def get_tour_by_id(db, tour_id: int, owner_id: int) -> Optional[dict]:
    row = db.execute("SELECT * FROM tours WHERE id = ? AND owner_id = ?", (tour_id, owner_id)).fetchone()
    return dict(row) if row else None


def get_user_setting(db, user_id: int, key: str, default: Optional[str] = None) -> Optional[str]:
    row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (user_id, key)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_user_setting(db, user_id: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (user_id, key, value))


# ==================== AUTH ====================

PUBLIC_PATHS = {"/api/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login", "/api/auth/logout",
                "/api/auth/login/code", "/api/auth/login/code/resend", "/api/auth/passkey/begin", "/api/auth/passkey/finish"}


def is_background(request: Request) -> bool:
    """Requests the page makes on a timer (polling). They don't count as the user being active."""
    return request.headers.get("x-background") == "1"


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Every /api route needs a valid session, except the few listed in PUBLIC_PATHS."""
    path = request.url.path.rstrip("/") or "/"
    if path.startswith("/api") and path not in PUBLIC_PATHS:
        db = get_db()
        try:
            user = auth.user_for_token(db, request.cookies.get(auth.SESSION_COOKIE),
                                       touch=not is_background(request))
        finally:
            db.close()
        if not user:
            return JSONResponse({"detail": "Not logged in"}, status_code=401)
        request.state.user = user
    return await call_next(request)


def _is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return COOKIE_SECURE or request.url.scheme == "https" or forwarded == "https"


def _client_ip(request: Request) -> str:
    """The visitor's address. Behind a reverse proxy it's the first X-Forwarded-For entry (the proxy sets it)."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",   # client details must not linger in browser or proxy caches
}


@app.middleware("http")
async def security_guard(request: Request, call_next):
    """
    Runs before everything else (it's registered last, so it's the outermost layer).
    - Refuses changes (POST, PUT, DELETE) to /api that another website started. Browsers say where a request
      came from in Sec-Fetch-Site; only sworkr's own pages ("same-origin") or a typed-in request ("none") may
      change anything. "same-site" is refused too: other apps on the same domain shouldn't be able to act here.
    - Adds headers that stop the API's answers being cached, sniffed or framed.
    """
    if request.url.path.startswith("/api") and request.method not in SAFE_METHODS:
        site = request.headers.get("sec-fetch-site")
        if site in ("cross-site", "same-site"):
            return JSONResponse({"detail": "Request blocked: it came from another website"}, status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/api"):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
    return response


def _set_session_cookie(response: Response, token: str, request: Request):
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=_is_https(request), path="/",
    )


def _validate_new_credentials(username: str, password: str):
    if not (2 <= len(username) <= 50) or not username.replace("_", "").replace(".", "").replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Username must be 2–50 letters, numbers, dots, dashes or underscores")
    if len(password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {auth.MIN_PASSWORD_LENGTH} characters")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/auth/status")
def auth_status(request: Request, db: DbDep):
    setup_required = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    user = auth.user_for_token(db, request.cookies.get(auth.SESSION_COOKIE), touch=not is_background(request))
    status = {"setup_required": setup_required, "user": user, "demo": demo.ENABLED}
    if demo.ENABLED:
        # The demo's shared login is shown on the login page on purpose: the demo holds only made-up data.
        status["demo_login"] = {"username": demo.USERNAME, "password": demo.PASSWORD}
    return status


@app.post("/api/auth/setup", status_code=201)
def auth_setup(creds: Credentials, request: Request, response: Response, db: DbDep):
    """Create the first (admin) account. Only works while no accounts exist."""
    username = creds.username.strip().lower()
    _validate_new_credentials(username, creds.password)
    db.execute("BEGIN IMMEDIATE")
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        db.rollback()
        raise HTTPException(status_code=403, detail="Setup has already been completed")
    cur = db.execute(
        "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, ?)",
        (username, auth.hash_password(creds.password), now_iso()),
    )
    user_id = cur.lastrowid
    # Anything already in the database (the sample data) now belongs to this first account.
    for table in ("clients", "appointments", "expenses", "client_notes", "tours"):
        db.execute(f"UPDATE {table} SET owner_id = ? WHERE owner_id IS NULL", (user_id,))
    db.commit()
    _set_session_cookie(response, auth.create_session(db, user_id), request)
    return {"id": user_id, "username": username, "is_admin": True}


@app.post("/api/auth/login")
def auth_login(creds: Credentials, request: Request, response: Response, db: DbDep):
    username = creds.username.strip().lower()
    ip = _client_ip(request)
    # Failures are counted per username and per visitor, so guessing many usernames from one place slows down too.
    wait = max(auth.throttle.seconds_locked(username), auth.ip_throttle.seconds_locked(ip))
    if wait:
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {wait} seconds.")
    user = auth.check_login(db, username, creds.password)
    if not user:
        auth.throttle.failure(username)
        auth.ip_throttle.failure(ip)
        raise HTTPException(status_code=401, detail="Wrong username or password")
    auth.throttle.success(username)
    auth.ip_throttle.success(ip)
    if signin.two_step_on(db, user["id"]):
        # The password was right; the session waits for the emailed code (POST /api/auth/login/code).
        return signin.start_login_code(db, user)
    _set_session_cookie(response, auth.create_session(db, user["id"]), request)
    return {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"])}


@app.post("/api/auth/logout", status_code=204)
def auth_logout(request: Request, response: Response, db: DbDep):
    auth.delete_session(db, request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")


@app.post("/api/auth/change-password", status_code=204)
def auth_change_password(body: PasswordChange, request: Request, db: DbDep):
    user = request.state.user
    if demo.ENABLED:
        raise HTTPException(status_code=403, detail="Changing the password is turned off in the demo, so everyone can keep logging in.")
    if len(body.new_password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {auth.MIN_PASSWORD_LENGTH} characters")
    if not auth.check_login(db, user["username"], body.current_password):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(body.new_password), user["id"]))
    db.commit()
    # Log out every other device, keep this one.
    auth.delete_user_sessions(db, user["id"], keep_token=request.cookies.get(auth.SESSION_COOKIE))


# ==================== ACCOUNT SETTINGS ====================

def _account_settings(db, user_id: int) -> dict:
    return {
        "idle_minutes": auth.idle_minutes_for(db, user_id),
        "idle_choices": list(auth.IDLE_CHOICES),
        "work_style": get_user_setting(db, user_id, "work_style", WorkStyle.BOTH.value),
    }


@app.get("/api/account/settings")
def get_account_settings(user: UserDep, db: DbDep):
    return _account_settings(db, user["id"])


@app.put("/api/account/settings")
def save_account_settings(body: AccountSettings, user: UserDep, db: DbDep):
    """Change any of the settings. Ones left out stay as they are."""
    if body.idle_minutes is not None:
        if body.idle_minutes not in auth.IDLE_CHOICES:
            raise HTTPException(status_code=400, detail="Pick one of the listed auto-logout times")
        set_user_setting(db, user["id"], "idle_minutes", str(body.idle_minutes))
    if body.work_style is not None:
        set_user_setting(db, user["id"], "work_style", body.work_style.value)
    db.commit()
    return _account_settings(db, user["id"])


# ==================== USERS (admin) ====================

@app.get("/api/users")
def list_users(admin: AdminDep, db: DbDep):
    return [{"id": r["id"], "username": r["username"], "is_admin": bool(r["is_admin"]), "created_at": r["created_at"],
             "clients": r["clients"]}
            for r in db.execute("""
                SELECT u.*, (SELECT COUNT(*) FROM clients c WHERE c.owner_id = u.id) AS clients
                FROM users u ORDER BY u.id
            """)]


@app.post("/api/users", status_code=201)
def create_user(body: NewUser, admin: AdminDep, db: DbDep):
    """Add another login. Each user has their own separate clients, appointments and expenses."""
    username = body.username.strip().lower()
    _validate_new_credentials(username, body.password)
    try:
        cur = db.execute(
            "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?)",
            (username, auth.hash_password(body.password), int(body.is_admin), now_iso()))
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That username is taken")
    db.commit()
    return {"id": cur.lastrowid, "username": username, "is_admin": body.is_admin}


@app.post("/api/users/{user_id}/password", status_code=204)
def set_user_password(user_id: int, body: NewPassword, admin: AdminDep, db: DbDep):
    if len(body.password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {auth.MIN_PASSWORD_LENGTH} characters")
    if not db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        raise HTTPException(status_code=404, detail="User not found")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(body.password), user_id))
    db.commit()
    if user_id != admin["id"]:
        auth.delete_user_sessions(db, user_id)


@app.delete("/api/users/{user_id}", status_code=204)
def delete_user(user_id: int, admin: AdminDep, db: DbDep):
    """Remove a login and everything that belongs to it."""
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="You can't delete the account you're logged in with")
    if not db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        raise HTTPException(status_code=404, detail="User not found")
    appointment_ids = [r[0] for r in db.execute("SELECT id FROM appointments WHERE owner_id = ?", (user_id,))]
    db.execute("DELETE FROM appointments WHERE owner_id = ?", (user_id,))
    db.execute("DELETE FROM expenses WHERE owner_id = ?", (user_id,))
    db.execute("DELETE FROM tours WHERE owner_id = ?", (user_id,))
    for table in ("cycle_entries", "posts", "settlements", "splits", "split_records", "split_agreements",
                  "tasks", "goal_entries", "goals", "income", "income_sources", "expense_categories"):
        db.execute(f"DELETE FROM {table} WHERE owner_id = ?", (user_id,))
    db.execute("DELETE FROM client_notes WHERE owner_id = ?", (user_id,))
    db.execute("DELETE FROM client_tags WHERE client_id IN (SELECT id FROM clients WHERE owner_id = ?)", (user_id,))
    db.execute("DELETE FROM clients WHERE owner_id = ?", (user_id,))
    db.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    for appointment_id in appointment_ids:
        calendar_sync.queue_appointment(appointment_id)


# ==================== CLIENTS ====================

def _validate_client(client: ClientIn):
    client.name = clean(client.name)
    if client.role in ("co-worker", "coworker", "collaborator"):
        client.role = "partner"          # shown as "co-worker", stored as "partner"
    if client.role not in collab.ROLES:
        raise HTTPException(status_code=400, detail="Role must be client, co-worker, crew or other")
    client._handles = contacts.clean_handles(client.handles)
    client._display = contacts.display_name(client.name, client._handles, client.display_handle)
    if client.display_handle is not None and not (0 <= client.display_handle < len(client._handles)):
        client.display_handle = None


def _client_values(client: ClientIn) -> tuple:
    """Call _validate_client first: it works out the handles and the display name."""
    return (client.name, client._display, contacts.handles_json(client._handles), client.display_handle,
            client.role, clean(client.industry), clean(client.contact_phone), client.email.strip().lower() if clean(client.email) else None,
            clean(client.bio), int(client.is_active), client.screening_status.value, clean(client.screening_notes),
            clean(client.references), int(client.do_not_see), clean(client.do_not_see_reason),
            client.birthday.isoformat() if client.birthday else None,
            clean(client.drink_preferences), clean(client.food_preferences))


@app.post("/api/clients", response_model=Client, status_code=201)
def create_client(client: ClientIn, user: UserDep, db: DbDep):
    _validate_client(client)
    now = now_iso()
    try:
        cur = db.execute("""
            INSERT INTO clients (name, display_name, handles, display_handle, role, industry, contact_phone, email, bio,
                                 is_active, screening_status, screening_notes, references_text, do_not_see,
                                 do_not_see_reason, birthday, drink_preferences, food_preferences, owner_id,
                                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*_client_values(client), user["id"], now, now))
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A client with that email already exists")
    set_client_tags(db, cur.lastrowid, client.tags)
    if client.couple_with is not None:
        link_couple(db, cur.lastrowid, client.couple_with, user["id"])
    personas.assign(db, "clients", cur.lastrowid, user["id"], client)
    db.commit()
    return get_client_by_id(db, cur.lastrowid, user["id"])


@app.get("/api/clients", response_model=List[Client])
def list_clients(
    user: UserDep,
    db: DbDep,
    is_active: Optional[int] = Query(None, ge=0, le=1),
    search: Optional[str] = None,
    tag_filter: Optional[str] = None,
    screening: Optional[ScreeningStatus] = None,
    do_not_see: Optional[int] = Query(None, ge=0, le=1),
    role: Optional[str] = Query(None, description="client, partner, crew or other"),
    persona_id: Optional[int] = Query(None, description="only contacts who know you by this persona (0: by none)"),
    sort: str = Query("recent", description="recent or name"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
):
    conditions, params = ["c.owner_id = ?"], [user["id"]]

    if is_active is not None:
        conditions.append("c.is_active = ?")
        params.append(is_active)
    if search and search.strip():
        conditions.append("(LOWER(c.display_name) LIKE ? ESCAPE '\\' OR LOWER(IFNULL(c.display_name, '')) LIKE ? ESCAPE '\\'"
                          " OR LOWER(IFNULL(c.email, '')) LIKE ? ESCAPE '\\' OR LOWER(IFNULL(c.contact_phone, '')) LIKE ? ESCAPE '\\'"
                          " OR LOWER(IFNULL(c.handles, '')) LIKE ? ESCAPE '\\' OR LOWER(IFNULL(c.industry, '')) LIKE ? ESCAPE '\\')")
        term = like_term(search)
        params.extend([term] * 6)
    if tag_filter:
        conditions.append("EXISTS (SELECT 1 FROM client_tags t2 WHERE t2.client_id = c.id AND t2.tag_name = ?)")
        params.append(tag_filter.lower().strip())
    if screening:
        conditions.append("c.screening_status = ?")
        params.append(screening.value)
    if do_not_see is not None:
        conditions.append("c.do_not_see = ?")
        params.append(do_not_see)
    if role:
        conditions.append("c.role = ?")
        params.append(role)
    if persona_id is not None:
        if persona_id == 0:
            conditions.append("c.persona_id IS NULL")
        else:
            conditions.append("c.persona_id = ?")
            params.append(persona_id)

    order = "c.display_name COLLATE NOCASE, c.id" if sort == "name" else "c.created_at DESC, c.id DESC"
    query = f"""
        SELECT c.*, GROUP_CONCAT(ct.tag_name) AS tags, (SELECT cw.display_name FROM clients cw WHERE cw.id = c.couple_with) AS couple_name
        FROM clients c LEFT JOIN client_tags ct ON c.id = ct.client_id
        WHERE {' AND '.join(conditions)}
        GROUP BY c.id
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """
    params.extend([limit, (page - 1) * limit])
    return [client_row(row, split_tags(row["tags"])) for row in db.execute(query, params)]


@app.get("/api/clients/{client_id}", response_model=Client)
def get_client(client_id: int, user: UserDep, db: DbDep):
    client = get_client_by_id(db, client_id, user["id"])
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@app.get("/api/clients/{client_id}/summary")
def get_client_summary(client_id: int, user: UserDep, db: DbDep):
    """Everything about one client: their details, appointment history, money and dated notes."""
    client = get_client_by_id(db, client_id, user["id"])
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    appointments = [appointment_row(r) for r in db.execute(
        APPOINTMENT_SELECT + " WHERE (a.client_id = ? OR a.second_client_id = ?) AND a.owner_id = ? ORDER BY a.scheduled_date DESC",
        (client_id, client_id, user["id"]))]
    now = now_iso()
    done = [a for a in appointments if a["status"] == "completed"]
    upcoming = sorted((a for a in appointments if a["status"] == "scheduled" and a["scheduled_date"] >= now),
                      key=lambda a: a["scheduled_date"])
    owed = sum(max((a["rate"] or 0) - (a["amount_paid"] or 0), 0) for a in done) \
        + sum(max((a.get("cancellation_fee") or 0) - (a["amount_paid"] or 0), 0) for a in appointments if a["status"] == "cancelled")
    reliability = noshow.record(db, user["id"], client_id)
    notes = [dict(r) for r in db.execute(
        "SELECT id, body, created_at FROM client_notes WHERE client_id = ? AND owner_id = ? ORDER BY created_at DESC, id DESC",
        (client_id, user["id"]))]
    return {
        "client": client,
        "stats": {
            "appointments": len(appointments),
            "completed": len(done),
            "cancelled": sum(a["status"] == "cancelled" for a in appointments),
            "upcoming": len(upcoming),
            "total_paid": round(sum(a["amount_paid"] or 0 for a in appointments), 2),
            "outstanding": round(owed, 2),
            "first_seen": min((a["scheduled_date"] for a in done), default=None),
            "last_seen": max((a["scheduled_date"] for a in done), default=None),
            "next_appointment": upcoming[0]["scheduled_date"] if upcoming else None,
            "no_shows": reliability["no_shows"],
            "late_cancellations": reliability["late"],
            "fees_owed": round(reliability["fees_owed"], 2),
        },
        "appointments": appointments,
        "notes": notes,
    }


@app.post("/api/clients/{client_id}/notes", status_code=201)
def add_client_note(client_id: int, note: NoteIn, user: UserDep, db: DbDep):
    if not get_client_by_id(db, client_id, user["id"]):
        raise HTTPException(status_code=404, detail="Client not found")
    if not note.body.strip():
        raise HTTPException(status_code=400, detail="The note is empty")
    now = now_iso()
    cur = db.execute("INSERT INTO client_notes (client_id, owner_id, body, created_at) VALUES (?, ?, ?, ?)",
                     (client_id, user["id"], note.body.strip(), now))
    db.commit()
    return {"id": cur.lastrowid, "body": note.body.strip(), "created_at": now}


@app.delete("/api/clients/{client_id}/notes/{note_id}", status_code=204)
def delete_client_note(client_id: int, note_id: int, user: UserDep, db: DbDep):
    db.execute("DELETE FROM client_notes WHERE id = ? AND client_id = ? AND owner_id = ?",
               (note_id, client_id, user["id"]))
    db.commit()


@app.put("/api/clients/{client_id}", response_model=Client)
def update_client(client_id: int, client: ClientIn, user: UserDep, db: DbDep):
    _validate_client(client)
    if not get_client_by_id(db, client_id, user["id"]):
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        db.execute("""
            UPDATE clients SET name = ?, display_name = ?, handles = ?, display_handle = ?, role = ?, industry = ?, contact_phone = ?, email = ?, bio = ?, is_active = ?, screening_status = ?,
                               screening_notes = ?, references_text = ?, do_not_see = ?, do_not_see_reason = ?,
                               birthday = ?, drink_preferences = ?, food_preferences = ?, updated_at = ?
            WHERE id = ? AND owner_id = ?
        """, (*_client_values(client), now_iso(), client_id, user["id"]))
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A client with that email already exists")
    set_client_tags(db, client_id, client.tags)
    link_couple(db, client_id, client.couple_with, user["id"])
    personas.assign(db, "clients", client_id, user["id"], client)
    db.commit()
    calendar_sync.queue_client(client_id)
    return get_client_by_id(db, client_id, user["id"])


@app.delete("/api/clients/{client_id}", status_code=204)
def delete_client(client_id: int, user: UserDep, db: DbDep):
    if not get_client_by_id(db, client_id, user["id"]):
        return
    appointment_ids = [r[0] for r in db.execute("SELECT id FROM appointments WHERE client_id = ?", (client_id,))]
    for appointment_id in appointment_ids:
        collab.forget(db, "appointment", appointment_id)
    db.execute("DELETE FROM client_tags WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM client_notes WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM appointments WHERE client_id = ?", (client_id,))
    db.execute("UPDATE expenses SET client_id = NULL WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    db.commit()
    for appointment_id in appointment_ids:
        calendar_sync.queue_appointment(appointment_id)


# ==================== APPOINTMENTS ====================

def _is_amount(value: Optional[float]) -> bool:
    # Written this way so NaN and infinity are rejected too.
    return value is None or 0 <= value < float("inf")


def _validate_appointment(db, appointment: AppointmentIn, owner_id: int) -> Optional[dict]:
    """Checks the appointment and returns its client (None for a health test, which has no client).
    A health test is tidied up here: no client, rate, payment or safety check-in, and a standard title."""
    if appointment.duration_minutes <= 0:
        raise HTTPException(status_code=400, detail="Duration must be more than 0 minutes")
    if appointment.kind == AppointmentKind.TEST:
        if not appointment.test_type:
            raise HTTPException(status_code=400, detail="Choose which test this is: weekly, monthly or yearly")
        if not _is_amount(appointment.cost):
            raise HTTPException(status_code=400, detail="Cost must be 0 or more")
        if appointment.tour_id is not None:
            tour = get_tour_by_id(db, appointment.tour_id, owner_id)
            if not tour or tour["kind"] != TourKind.TOUR.value:
                raise HTTPException(status_code=400, detail="Tour does not exist")
        appointment.client_id = None
        appointment.second_client_id = None
        appointment.service_type = TEST_LABELS[appointment.test_type.value]
        appointment.rate = None
        appointment.amount_paid = 0
        appointment.payment_method = None
        appointment.safety_checkin = False
        return None
    appointment.test_type = None
    appointment.cost = None
    appointment.tour_id = None
    if appointment.client_id is None:
        raise HTTPException(status_code=400, detail="Choose a client")
    client = get_client_by_id(db, appointment.client_id, owner_id)
    if not client:
        raise HTTPException(status_code=400, detail="Client does not exist")
    if appointment.second_client_id is not None:
        second = get_client_by_id(db, appointment.second_client_id, owner_id)
        if not second or appointment.second_client_id == appointment.client_id:
            raise HTTPException(status_code=400, detail="The second person must be another of your contacts")
        if second["do_not_see"] and not client["do_not_see"]:   # warn about either of them
            client = {**client, "display_name": second["display_name"], "do_not_see": True,
                      "do_not_see_reason": second.get("do_not_see_reason")}
    if not appointment.service_type.strip():
        raise HTTPException(status_code=400, detail="Service type is required")
    if not _is_amount(appointment.rate):
        raise HTTPException(status_code=400, detail="Rate must be 0 or more")
    if not _is_amount(appointment.amount_paid):
        raise HTTPException(status_code=400, detail="Amount paid must be 0 or more")
    return client


def find_overlaps(db, owner_id: int, start: datetime, minutes: int, exclude_id: Optional[int] = None) -> List[dict]:
    """Other appointments (not cancelled) whose time overlaps start .. start + minutes."""
    start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=minutes)
    rows = db.execute(
        APPOINTMENT_SELECT + """
        WHERE a.owner_id = ? AND a.status != 'cancelled' AND a.scheduled_date < ? AND a.scheduled_date >= ?
        ORDER BY a.scheduled_date
        """, (owner_id, to_utc_iso(end), to_utc_iso(start - timedelta(days=7))))
    found = []
    for row in rows:
        if row["id"] == exclude_id:
            continue
        other_start = parse_iso(row["scheduled_date"])
        if other_start + timedelta(minutes=row["duration_minutes"]) > start:
            found.append(dict(row))
    return found


TIME_OFF_LABELS = {"day_off": "a day off", "vacation": "a vacation"}


def time_off_during(db, owner_id: int, start: datetime, minutes: int) -> List[dict]:
    """Time off (days off, vacations) that overlaps start .. start + minutes."""
    start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=minutes)
    return [dict(r) for r in db.execute(
        "SELECT * FROM tours WHERE owner_id = ? AND kind = 'time_off' AND starts_at < ? AND ends_at > ?",
        (owner_id, to_utc_iso(end), to_utc_iso(start)))]


def _time_off_message(off: dict) -> str:
    what = TIME_OFF_LABELS.get(off["time_off_type"], "time off")
    days = off["start_date"] if off["end_date"] == off["start_date"] else f"{off['start_date']} to {off['end_date']}"
    named = f" ({off['name']})" if off.get("name") else ""
    return f"You marked {days} as {what}{named}"


def _booking_warnings(db, owner_id: int, client: Optional[dict], starts: List[datetime], minutes: int,
                      exclude_id: Optional[int] = None, tz_offset: int = 0) -> List[dict]:
    """Things worth a second look before saving. `client` is None for a health test."""
    warnings = []
    if client and client["do_not_see"]:
        reason = f": {client['do_not_see_reason']}" if client.get("do_not_see_reason") else ""
        warnings.append({"type": "do_not_see", "message": f"{client['display_name']} is marked DO NOT SEE{reason}"})
    if client:
        unreliable = noshow.warning(client["display_name"], noshow.record(db, owner_id, client["id"]))
        if unreliable:
            warnings.append({"type": "unreliable", "message": unreliable})
        found = blocklist.matches_for_client(db, owner_id, client)
        if found:
            warnings.append({"type": "bad_date", "severity": found[0]["severity"],
                             "message": blocklist.warning_text(client["display_name"], found)})
    for start in starts:
        if client:
            period = cycle.booking_warning(db, owner_id, start, tz_offset)
            if period:
                warnings.append({"type": "period", "starts_at": to_utc_iso(start), "message": period})
            for off in time_off_during(db, owner_id, start, minutes):
                warnings.append({"type": "time_off", "starts_at": to_utc_iso(start), "message": _time_off_message(off)})
        for other in find_overlaps(db, owner_id, start, minutes, exclude_id):
            who = other["client_name"] or other["service_type"] or "another appointment"
            warnings.append({
                "type": "overlap",
                "appointment_id": other["id"],
                "starts_at": other["scheduled_date"],
                "duration_minutes": other["duration_minutes"],
                "client_name": other["client_name"],
                "service_type": other["service_type"],
                "message": f"Overlaps with {who}",
            })
    return warnings


def _stop_if_warned(warnings: List[dict], warn: bool):
    if warnings and warn:
        raise HTTPException(status_code=409, detail={
            "code": "needs_confirmation",
            "message": "Check this before saving",
            "warnings": warnings[:20],
        })


def _appointment_values(a: AppointmentIn) -> tuple:
    # amount_paid must stay at index 6: create_appointment zeroes it for repeats.
    return (a.client_id, a.service_type.strip(), a.duration_minutes, a.status.value, clean(a.notes),
            a.rate, a.amount_paid or 0, clean(a.payment_method),
            a.location_type.value if a.location_type else None, clean(a.location), int(a.safety_checkin),
            a.kind.value, a.test_type.value if a.test_type else None, a.cost, a.second_client_id)


_KEEP = object()


def _sync_test_expense(db, appointment_id: int, owner_id: int, tour_id=_KEEP):
    """A health test with a cost has exactly one 'medical' expense, kept in step with it.
    A cancelled test, one without a cost, or a client appointment has none."""
    appt = get_appointment_by_id(db, appointment_id, owner_id)
    existing = db.execute("SELECT id, tour_id FROM expenses WHERE appointment_id = ? AND owner_id = ?",
                          (appointment_id, owner_id)).fetchone()
    if not appt or appt["kind"] != AppointmentKind.TEST.value or appt["status"] == "cancelled" or appt["cost"] is None:
        db.execute("DELETE FROM expenses WHERE appointment_id = ? AND owner_id = ?", (appointment_id, owner_id))
        return
    if tour_id is _KEEP:
        tour_id = existing["tour_id"] if existing else None
    if existing:
        db.execute("""
            UPDATE expenses SET description = ?, amount = ?, category = 'medical', date = ?, tour_id = ?
            WHERE id = ? AND owner_id = ?
        """, (appt["service_type"], appt["cost"], appt["scheduled_date"], tour_id, existing["id"], owner_id))
    else:
        db.execute("""
            INSERT INTO expenses (description, amount, category, date, owner_id, created_at, tour_id, appointment_id)
            VALUES (?, ?, 'medical', ?, ?, ?, ?, ?)
        """, (appt["service_type"], appt["cost"], appt["scheduled_date"], owner_id, now_iso(), tour_id, appointment_id))


def log_health_test(db, owner_id: int, when: datetime, test_type: str, cost: float, label: str,
                    tour_id: Optional[int] = None) -> int:
    """A health test paid as a place's charge (a house doctor): a test appointment with its cost, which
    makes its 'medical' expense. Done if it's in the past."""
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    status = "completed" if when <= datetime.now(timezone.utc) else "scheduled"
    now = now_iso()
    cur = db.execute("""
        INSERT INTO appointments (service_type, duration_minutes, status, kind, test_type, cost, scheduled_date,
                                  owner_id, created_at, updated_at)
        VALUES (?, 30, ?, 'test', ?, ?, ?, ?, ?, ?)
    """, (label, status, test_type, cost, to_utc_iso(when), owner_id, now, now))
    _sync_test_expense(db, cur.lastrowid, owner_id, tour_id)
    return cur.lastrowid   # (the caller sends it to calendar sync once it's committed)


def _remember_test_cost(db, owner_id: int, appointment: AppointmentIn):
    """The next test of the same kind starts with this cost filled in."""
    if appointment.kind == AppointmentKind.TEST and appointment.test_type and appointment.cost is not None:
        set_user_setting(db, owner_id, f"test_cost_{appointment.test_type.value}", str(appointment.cost))


@app.post("/api/appointments", response_model=Appointment, status_code=201)
def create_appointment(appointment: AppointmentCreate, user: UserDep, db: DbDep,
                       warn: bool = Query(False, description="If there are warnings, answer 409 with them instead of saving"),
                       tz_offset: int = Query(0, ge=-840, le=840, description="The browser's getTimezoneOffset(), for day-based warnings")):
    """
    Create an appointment, or a repeating series when repeat_dates is given.
    With warn=true, a do-not-see client or an overlapping booking is answered with 409 and the list of
    warnings, and nothing is saved. The app does this first, shows the warnings, then saves without it.
    """
    client = _validate_appointment(db, appointment, user["id"])
    if len(appointment.repeat_dates) > MAX_REPEATS:
        raise HTTPException(status_code=400, detail=f"An appointment can repeat at most {MAX_REPEATS} times")
    if appointment.kind == AppointmentKind.TEST and appointment.repeat_dates:
        raise HTTPException(status_code=400, detail="A health test can't repeat. Add each test on its own day.")
    starts = [appointment.scheduled_date, *appointment.repeat_dates]
    if appointment.status != AppointmentStatus.CANCELLED:
        if warn:
            _stop_if_warned(_booking_warnings(db, user["id"], client, starts, appointment.duration_minutes,
                                              tz_offset=tz_offset), warn)

    now = now_iso()
    series_id = uuid.uuid4().hex if appointment.repeat_dates else None
    values = _appointment_values(appointment)
    ids = []
    for index, start in enumerate(starts):
        # A deposit or payment belongs to the first appointment, not to every repeat.
        row = values if index == 0 else (*values[:6], 0, *values[7:])
        cur = db.execute("""
            INSERT INTO appointments (client_id, service_type, duration_minutes, status, notes, rate, amount_paid,
                                      payment_method, location_type, location, safety_checkin,
                                      kind, test_type, cost, second_client_id,
                                      scheduled_date, series_id, owner_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (*row, to_utc_iso(start), series_id, user["id"], now, now))
        ids.append(cur.lastrowid)
    for appointment_id in ids:
        _sync_test_expense(db, appointment_id, user["id"], appointment.tour_id)
    _remember_test_cost(db, user["id"], appointment)
    db.commit()
    for appointment_id in ids:
        calendar_sync.queue_appointment(appointment_id)
    return get_appointment_by_id(db, ids[0], user["id"])


@app.get("/api/appointments", response_model=List[Appointment])
def list_appointments(
    user: UserDep,
    db: DbDep,
    client_id: Optional[int] = None,
    status: Optional[AppointmentStatus] = None,
    service_type: Optional[str] = None,
    start: Optional[datetime] = Query(None, description="Only appointments at or after this time"),
    end: Optional[datetime] = Query(None, description="Only appointments before this time"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=1000),
):
    conditions, params = ["a.owner_id = ?"], [user["id"]]
    if client_id is not None:
        conditions.append("a.client_id = ?")
        params.append(client_id)
    if status:
        conditions.append("a.status = ?")
        params.append(status.value)
    if service_type:
        conditions.append("a.service_type = ?")
        params.append(service_type)
    if start:
        conditions.append("a.scheduled_date >= ?")
        params.append(to_utc_iso(start))
    if end:
        conditions.append("a.scheduled_date < ?")
        params.append(to_utc_iso(end))

    query = APPOINTMENT_SELECT + f"""
        WHERE {' AND '.join(conditions)}
        ORDER BY a.scheduled_date ASC, a.id ASC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, (page - 1) * limit])
    return [appointment_row(r) for r in db.execute(query, params)]


@app.get("/api/appointments/service-types", response_model=List[str])
def list_service_types(user: UserDep, db: DbDep):
    return [r[0] for r in db.execute(
        "SELECT service_type FROM appointments WHERE owner_id = ? GROUP BY service_type ORDER BY COUNT(*) DESC LIMIT 50",
        (user["id"],))]


@app.get("/api/appointments/test-costs")
def last_test_costs(user: UserDep, db: DbDep):
    """What each kind of health test cost last time, to fill in the next one."""
    out = {}
    for t in TestType:
        value = get_user_setting(db, user["id"], f"test_cost_{t.value}")
        out[t.value] = float(value) if value not in (None, "") else None
    return out


@app.get("/api/appointments/{appointment_id}", response_model=Appointment)
def get_appointment(appointment_id: int, user: UserDep, db: DbDep):
    appt = get_appointment_by_id(db, appointment_id, user["id"])
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


@app.put("/api/appointments/{appointment_id}", response_model=Appointment)
def update_appointment(appointment_id: int, appointment: AppointmentIn, user: UserDep, db: DbDep,
                       warn: bool = Query(False, description="If there are warnings, answer 409 with them instead of saving"),
                       tz_offset: int = Query(0, ge=-840, le=840)):
    existing = get_appointment_by_id(db, appointment_id, user["id"])
    if not existing:
        raise HTTPException(status_code=404, detail="Appointment not found")
    client = _validate_appointment(db, appointment, user["id"])

    # Only ask again when something that matters for the warnings actually changed.
    new_start = to_utc_iso(appointment.scheduled_date)
    rebooked = (new_start != to_utc_iso(parse_iso(existing["scheduled_date"]))
                or appointment.duration_minutes != existing["duration_minutes"]
                or appointment.client_id != existing["client_id"]
                or (existing["status"] == "cancelled" and appointment.status != AppointmentStatus.CANCELLED))
    if warn and rebooked and appointment.status != AppointmentStatus.CANCELLED:
        _stop_if_warned(_booking_warnings(db, user["id"], client, [appointment.scheduled_date],
                                          appointment.duration_minutes, exclude_id=appointment_id, tz_offset=tz_offset), warn)

    checked_in_at = existing["checked_in_at"]
    if appointment.status == AppointmentStatus.COMPLETED and not checked_in_at:
        checked_in_at = now_iso()   # marking it done counts as checking in
    # If the time moved, an alert that was already sent no longer applies.
    alert_sent_at = existing["alert_sent_at"] if not rebooked else None
    if rebooked and appointment.status == AppointmentStatus.SCHEDULED:
        checked_in_at = None

    db.execute("""
        UPDATE appointments
        SET client_id = ?, service_type = ?, duration_minutes = ?, status = ?, notes = ?, rate = ?, amount_paid = ?,
            payment_method = ?, location_type = ?, location = ?, safety_checkin = ?,
            kind = ?, test_type = ?, cost = ?, second_client_id = ?,
            scheduled_date = ?, checked_in_at = ?, alert_sent_at = ?, alert_error = NULL, updated_at = ?
        WHERE id = ? AND owner_id = ?
    """, (*_appointment_values(appointment), new_start, checked_in_at, alert_sent_at, now_iso(),
          appointment_id, user["id"]))
    _sync_test_expense(db, appointment_id, user["id"], appointment.tour_id)
    _remember_test_cost(db, user["id"], appointment)
    db.commit()
    calendar_sync.queue_appointment(appointment_id)
    return get_appointment_by_id(db, appointment_id, user["id"])


@app.put("/api/appointments/{appointment_id}/status", response_model=Appointment)
def update_appointment_status(
    appointment_id: int, status: AppointmentStatus, user: UserDep, db: DbDep,
    cancel_reason: Optional[str] = Query(None, description="When cancelling: client, no_show or me ('client' becomes 'late' inside the late window)"),
    cancellation_fee: Optional[float] = Query(None, description="What the client owes for it; left out: suggested from your policy"),
):
    existing = get_appointment_by_id(db, appointment_id, user["id"])
    if not existing:
        raise HTTPException(status_code=404, detail="Appointment not found")
    now = now_iso()
    checked_in_at = existing["checked_in_at"]
    if status == AppointmentStatus.COMPLETED and not checked_in_at:
        checked_in_at = now
    reason, fee = None, None
    if status == AppointmentStatus.CANCELLED and cancel_reason:
        if cancel_reason not in noshow.REASONS:
            raise HTTPException(status_code=400, detail="cancel_reason must be client, late, no_show or me")
        if cancellation_fee is not None and not _is_amount(cancellation_fee):
            raise HTTPException(status_code=400, detail="The cancellation fee must be 0 or more")
        pol = noshow.policy(db, user["id"])
        reason = noshow.reason_for(noshow.now(), parse_iso(existing["scheduled_date"]), cancel_reason, pol["late_cancel_hours"])
        fee = cancellation_fee if cancellation_fee is not None else noshow.suggested_fee(pol, reason, existing["rate"])
    db.execute("UPDATE appointments SET status = ?, checked_in_at = ?, cancel_reason = ?, cancellation_fee = ?, updated_at = ? "
               "WHERE id = ? AND owner_id = ?",
               (status.value, checked_in_at, reason, fee, now, appointment_id, user["id"]))
    _sync_test_expense(db, appointment_id, user["id"])
    db.commit()
    calendar_sync.queue_appointment(appointment_id)
    return get_appointment_by_id(db, appointment_id, user["id"])


@app.post("/api/appointments/{appointment_id}/check-in", response_model=Appointment)
def check_in(appointment_id: int, user: UserDep, db: DbDep):
    """Say "I'm safe" after an appointment, which stops the alert to the trusted contact."""
    if not get_appointment_by_id(db, appointment_id, user["id"]):
        raise HTTPException(status_code=404, detail="Appointment not found")
    db.execute("UPDATE appointments SET checked_in_at = ? WHERE id = ? AND owner_id = ?",
               (now_iso(), appointment_id, user["id"]))
    db.commit()
    return get_appointment_by_id(db, appointment_id, user["id"])


@app.post("/api/appointments/{appointment_id}/mark-paid", response_model=Appointment)
def mark_paid(appointment_id: int, user: UserDep, db: DbDep):
    """Record that the full rate has been received; for a cancelled booking with a fee, the fee."""
    existing = get_appointment_by_id(db, appointment_id, user["id"])
    if not existing:
        raise HTTPException(status_code=404, detail="Appointment not found")
    due = existing["cancellation_fee"] if existing["status"] == "cancelled" and existing.get("cancellation_fee") else existing["rate"]
    if due is None:
        raise HTTPException(status_code=400, detail="Set a rate on this appointment first")
    db.execute("UPDATE appointments SET amount_paid = MAX(COALESCE(amount_paid, 0), ?), updated_at = ? WHERE id = ? AND owner_id = ?",
               (due, now_iso(), appointment_id, user["id"]))
    db.commit()
    return get_appointment_by_id(db, appointment_id, user["id"])


@app.delete("/api/appointments/{appointment_id}", status_code=204)
def delete_appointment(appointment_id: int, user: UserDep, db: DbDep,
                       scope: str = Query("one", description="'one', or 'following' for this and later repeats")):
    existing = get_appointment_by_id(db, appointment_id, user["id"])
    if not existing:
        return
    ids = [appointment_id]
    if scope == "following" and existing["series_id"]:
        ids = [r[0] for r in db.execute(
            "SELECT id FROM appointments WHERE owner_id = ? AND series_id = ? AND scheduled_date >= ?",
            (user["id"], existing["series_id"], existing["scheduled_date"]))]
    for one_id in ids:
        collab.forget(db, "appointment", one_id)
        db.execute("DELETE FROM expenses WHERE appointment_id = ? AND owner_id = ?", (one_id, user["id"]))
        db.execute("DELETE FROM appointments WHERE id = ? AND owner_id = ?", (one_id, user["id"]))
    db.commit()
    for one_id in ids:
        calendar_sync.queue_appointment(one_id)


# ==================== EXPENSES ====================

def _validate_expense(db, expense: ExpenseIn, owner_id: int):
    if not expense.description.strip():
        raise HTTPException(status_code=400, detail="Description is required")
    if not (0 <= expense.amount < float("inf")):
        raise HTTPException(status_code=400, detail="Amount must be 0 or more")
    if expense.client_id is not None and not get_client_by_id(db, expense.client_id, owner_id):
        raise HTTPException(status_code=400, detail="Client does not exist")
    expense.category = finance.check_category(db, owner_id, expense.category)
    expense.currency = currencies.check(expense.currency)
    if expense.tour_id is not None:
        tour = get_tour_by_id(db, expense.tour_id, owner_id)
        if not tour or tour["kind"] != TourKind.TOUR.value:
            raise HTTPException(status_code=400, detail="Tour does not exist")


def _refuse_if_managed(expense: dict):
    """Room & board made from a tour, and the cost of a health test, are changed where they come from."""
    if expense.get("source") == "tour_room":
        raise HTTPException(status_code=400, detail="This room & board comes from a tour. Change it on the tour instead.")
    if expense.get("appointment_id"):
        raise HTTPException(status_code=400, detail="This is the cost of a health test. Change the test on the calendar instead.")


@app.post("/api/expenses", response_model=Expense, status_code=201)
def create_expense(expense: ExpenseIn, user: UserDep, db: DbDep):
    now = now_iso()
    _validate_expense(db, expense, user["id"])
    cur = db.execute("""
        INSERT INTO expenses (client_id, description, amount, category, date, notes, owner_id, created_at, tour_id, currency)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (expense.client_id, expense.description, expense.amount, expense.category,
          (to_utc_iso(expense.date) if expense.date else now), expense.notes, user["id"], now, expense.tour_id,
          expense.currency))
    db.commit()
    return get_expense_by_id(db, cur.lastrowid, user["id"])


@app.get("/api/expenses", response_model=List[Expense])
def list_expenses(
    user: UserDep,
    db: DbDep,
    client_id: Optional[int] = None,
    category: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    start: Optional[datetime] = Query(None, description="Only expenses dated at or after this time"),
    end: Optional[datetime] = Query(None, description="Only expenses dated before this time"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
):
    conditions, params = ["e.owner_id = ?"], [user["id"]]
    if client_id is not None:
        conditions.append("e.client_id = ?")
        params.append(client_id)
    if category and category != "all":
        conditions.append("e.category = ?")
        params.append(category)
    if min_amount is not None:
        conditions.append("e.amount >= ?")
        params.append(min_amount)
    if max_amount is not None:
        conditions.append("e.amount <= ?")
        params.append(max_amount)
    if start:
        conditions.append("e.date >= ?")
        params.append(to_utc_iso(start))
    if end:
        conditions.append("e.date < ?")
        params.append(to_utc_iso(end))

    query = EXPENSE_SELECT + f"""
        WHERE {' AND '.join(conditions)}
        ORDER BY e.date DESC, e.id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, (page - 1) * limit])
    return [dict(r) for r in db.execute(query, params)]


@app.get("/api/expenses/summary")
def get_expense_summary(user: UserDep, db: DbDep):
    category_summary = [
        {"category": r["category"], "total": round(r["total"], 2), "count": r["count"]}
        for r in db.execute("""
            SELECT category, SUM(amount) AS total, COUNT(*) AS count
            FROM expenses WHERE owner_id = ? GROUP BY category ORDER BY total DESC
        """, (user["id"],))
    ]
    top_clients = [
        {"name": r["name"], "total_spent": round(r["total_spent"], 2), "expense_count": r["expense_count"]}
        for r in db.execute("""
            SELECT c.display_name AS name, SUM(e.amount) AS total_spent, COUNT(e.id) AS expense_count
            FROM expenses e JOIN clients c ON e.client_id = c.id
            WHERE e.owner_id = ?
            GROUP BY c.id ORDER BY total_spent DESC LIMIT 20
        """, (user["id"],))
    ]
    expense_count = sum(c["count"] for c in category_summary)
    overall_total = round(sum(c["total"] for c in category_summary), 2)
    return {
        "category_summary": category_summary,
        "top_clients": top_clients,
        "overall_total": overall_total,
        "expense_count": expense_count,
        "average": round(overall_total / expense_count, 2) if expense_count else 0,
    }


@app.put("/api/expenses/{expense_id}", response_model=Expense)
def update_expense(expense_id: int, expense: ExpenseIn, user: UserDep, db: DbDep):
    existing = get_expense_by_id(db, expense_id, user["id"])
    if not existing:
        raise HTTPException(status_code=404, detail="Expense not found")
    _refuse_if_managed(existing)
    _validate_expense(db, expense, user["id"])
    db.execute("""
        UPDATE expenses SET client_id = ?, description = ?, amount = ?, category = ?, date = ?, notes = ?, tour_id = ?
        WHERE id = ? AND owner_id = ?
    """, (expense.client_id, expense.description, expense.amount, expense.category,
          to_utc_iso(expense.date) if expense.date else existing["date"], expense.notes, expense.tour_id,
          expense_id, user["id"]))
    db.commit()
    return get_expense_by_id(db, expense_id, user["id"])


@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, user: UserDep, db: DbDep):
    existing = get_expense_by_id(db, expense_id, user["id"])
    if existing:
        _refuse_if_managed(existing)
        collab.forget(db, "expense", expense_id)
    db.execute("DELETE FROM expenses WHERE id = ? AND owner_id = ?", (expense_id, user["id"]))
    db.commit()


# ==================== TOURS AND TIME OFF ====================
# One table holds both. A tour is a working trip: everything booked during its days counts toward it,
# plus room & board for each day. Time off (a day off or a vacation) warns when a client is booked then,
# and is left out of "working days" when earnings are compared.

MAX_PERIOD_DAYS = 366
MAX_COMPARE_DAYS = 3 * 366


def _period_days(start: date, end: date) -> int:
    return (end - start).days + 1


def _date_range(start: date, end: date):
    for i in range(_period_days(start, end)):
        yield start + timedelta(days=i)


def _validate_tour(db, tour: TourIn, owner_id: int, exclude_id: Optional[int] = None):
    if tour.end_date < tour.start_date:
        raise HTTPException(status_code=400, detail="The last day can't be before the first day")
    if _period_days(tour.start_date, tour.end_date) > MAX_PERIOD_DAYS:
        raise HTTPException(status_code=400, detail="That's longer than a year. Split it into shorter periods.")
    if tour.ends_at <= tour.starts_at:
        raise HTTPException(status_code=400, detail="The end must be after the start")
    if tour.kind == TourKind.TOUR:
        if not clean(tour.name):
            raise HTTPException(status_code=400, detail="Give the tour a name, like the city")
        if not _is_amount(tour.room_rent_per_day):
            raise HTTPException(status_code=400, detail="Room & board must be 0 or more")
        if tour.source_id is not None and not finance.get_source(db, tour.source_id, owner_id):
            raise HTTPException(status_code=400, detail="That place doesn't exist")
        tour.time_off_type = None
    else:
        tour.time_off_type = tour.time_off_type or TimeOffType.DAY_OFF
        tour.room_rent_per_day = None
        tour.source_id = None
    # Tours don't overlap other tours (so every booking belongs to at most one), and time off doesn't
    # overlap other time off. A day off in the middle of a tour is fine.
    clash = db.execute("""
        SELECT name, start_date, end_date FROM tours
        WHERE owner_id = ? AND kind = ? AND id IS NOT ? AND starts_at < ? AND ends_at > ?
        ORDER BY starts_at LIMIT 1
    """, (owner_id, tour.kind.value, exclude_id, to_utc_iso(tour.ends_at), to_utc_iso(tour.starts_at))).fetchone()
    if clash:
        what = "another tour" if tour.kind == TourKind.TOUR else "time off you already have"
        named = f" ({clash['name']})" if clash["name"] else ""
        raise HTTPException(status_code=400,
                            detail=f"These days overlap {what}{named}, {clash['start_date']} to {clash['end_date']}")


def _tour_values(tour: TourIn) -> tuple:
    return (tour.kind.value, tour.time_off_type.value if tour.time_off_type else None, clean(tour.name),
            clean(tour.location), tour.start_date.isoformat(), tour.end_date.isoformat(),
            to_utc_iso(tour.starts_at), to_utc_iso(tour.ends_at), tour.room_rent_per_day, clean(tour.notes),
            tour.source_id)


def _sync_room_rent(db, tour_id: int, owner_id: int):
    """One 'room_rent' expense for each day of the tour, made again whenever the tour changes."""
    old_ids = [r[0] for r in db.execute(
        "SELECT id FROM expenses WHERE tour_id = ? AND owner_id = ? AND source = 'tour_room'", (tour_id, owner_id))]
    db.execute("DELETE FROM expenses WHERE tour_id = ? AND owner_id = ? AND source = 'tour_room'", (tour_id, owner_id))
    tour = get_tour_by_id(db, tour_id, owner_id)
    if not tour or tour["kind"] != TourKind.TOUR.value or not tour["room_rent_per_day"]:
        collab.copy_split(db, owner_id, old_ids, [])
        return
    new_ids = []
    first = parse_iso(tour["starts_at"])
    days = _period_days(date.fromisoformat(tour["start_date"]), date.fromisoformat(tour["end_date"]))
    now = now_iso()
    for i in range(days):
        # Midday of each day, so it lands on the right day whatever the time zone.
        cur = db.execute("""
            INSERT INTO expenses (description, amount, category, date, owner_id, created_at, tour_id, source)
            VALUES (?, ?, 'room_rent', ?, ?, ?, ?, 'tour_room')
        """, (f"Room & board – {tour['name']}", tour["room_rent_per_day"],
              to_utc_iso(first + timedelta(days=i, hours=12)), owner_id, now, tour_id))
        new_ids.append(cur.lastrowid)
    collab.copy_split(db, owner_id, old_ids, new_ids)


STAY_CADENCES = ("per_day", "per_week", "per_month", "per_stay")


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year, month = d.year + month // 12, month % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue


def _stay_days(cadence: str, start: date, end: date) -> List[date]:
    """The days in a stay that a charge falls on: every day, every 7th day from the first, the same day each
    month, or just the first day."""
    days = list(_date_range(start, end))
    if cadence == "per_day":
        return days
    if cadence == "per_week":
        return days[::7]
    if cadence == "per_month":
        out, i = [], 0
        while (d := _add_months(start, i)) <= end:
            out.append(d)
            i += 1
        return out
    return days[:1]


def _clear_stay_charges(db, tour_id: int, owner_id: int) -> List[int]:
    """Remove what a stay logged by itself. Returns the health tests removed (for calendar sync)."""
    tests = [r[0] for r in db.execute("SELECT id FROM appointments WHERE from_tour_id = ? AND owner_id = ?", (tour_id, owner_id))]
    db.execute("DELETE FROM expenses WHERE tour_id = ? AND owner_id = ? AND source = 'stay_charge'", (tour_id, owner_id))
    if tests:
        marks = ",".join("?" * len(tests))
        db.execute(f"DELETE FROM expenses WHERE owner_id = ? AND appointment_id IN ({marks})", (owner_id, *tests))
        db.execute(f"DELETE FROM appointments WHERE owner_id = ? AND id IN ({marks})", (owner_id, *tests))
    return tests


def sync_stay_charges(db, tour_id: int, owner_id: int) -> List[int]:
    """A tour at one of your places logs that place's charges with an amount that come by the day, week, month
    or stay: room & board each day, the house doctor each week (as a health test). Made again whenever the tour
    or the place's charges change. Returns the health tests removed and added (for calendar sync)."""
    old_ids = [r[0] for r in db.execute(
        "SELECT id FROM expenses WHERE tour_id = ? AND owner_id = ? AND source = 'stay_charge' ORDER BY id", (tour_id, owner_id))]
    touched = _clear_stay_charges(db, tour_id, owner_id)
    tour = get_tour_by_id(db, tour_id, owner_id)
    if not tour or tour["kind"] != TourKind.TOUR.value or not tour.get("source_id"):
        collab.copy_split(db, owner_id, old_ids, [])
        return touched
    first = parse_iso(tour["starts_at"])
    start, end = date.fromisoformat(tour["start_date"]), date.fromisoformat(tour["end_date"])
    now = now_iso()
    new_ids = []
    for charge in places.charges_for(db, owner_id, tour["source_id"]):
        if charge["amount"] is None or charge["cadence"] not in STAY_CADENCES:
            continue
        for d in _stay_days(charge["cadence"], start, end):
            # Midday of the day, so it lands on the right day whatever the time zone.
            when = first + timedelta(days=(d - start).days, hours=12)
            description = f"{charge['label']} – {tour['name']}"
            if charge["test_type"]:
                test_id = log_health_test(db, owner_id, when, charge["test_type"], charge["amount"], description, tour_id)
                db.execute("UPDATE appointments SET from_tour_id = ? WHERE id = ?", (tour_id, test_id))
                touched.append(test_id)
            else:
                cur = db.execute("""
                    INSERT INTO expenses (description, amount, category, date, owner_id, created_at, tour_id, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'stay_charge')
                """, (description, charge["amount"], charge["category"], to_utc_iso(when), owner_id, now, tour_id))
                new_ids.append(cur.lastrowid)
    collab.copy_split(db, owner_id, old_ids, new_ids)
    return touched


def sync_stays_at_place(db, owner_id: int, source_id: int) -> List[int]:
    """Every stay at a place, after its charges changed."""
    touched = []
    for (tour_id,) in db.execute("SELECT id FROM tours WHERE owner_id = ? AND source_id = ?", (owner_id, source_id)).fetchall():
        touched += sync_stay_charges(db, tour_id, owner_id)
    return touched


def _days_off_in(db, owner_id: int, start: date, end: date) -> set:
    """The calendar days between start and end (inclusive) that are marked as time off."""
    days = set()
    for r in db.execute("""
        SELECT start_date, end_date FROM tours
        WHERE owner_id = ? AND kind = 'time_off' AND start_date <= ? AND end_date >= ?
    """, (owner_id, end.isoformat(), start.isoformat())):
        first = max(start, date.fromisoformat(r["start_date"]))
        last = min(end, date.fromisoformat(r["end_date"]))
        days.update(_date_range(first, last))
    return days


def _tour_appointments(db, owner_id: int, tour: dict) -> List[dict]:
    """Everything booked during the tour, plus health tests whose cost was put on this tour."""
    return [appointment_row(r) for r in db.execute(APPOINTMENT_SELECT + """
        WHERE a.owner_id = ? AND (
              (a.scheduled_date >= ? AND a.scheduled_date < ?)
           OR a.id IN (SELECT appointment_id FROM expenses WHERE tour_id = ? AND appointment_id IS NOT NULL))
        ORDER BY a.scheduled_date, a.id
    """, (owner_id, tour["starts_at"], tour["ends_at"], tour["id"]))]


def _tour_expenses(db, owner_id: int, tour: dict) -> List[dict]:
    """Expenses put on this tour, plus expenses on no tour that are dated during it."""
    return [dict(r) for r in db.execute(EXPENSE_SELECT + """
        WHERE e.owner_id = ? AND (e.tour_id = ? OR (e.tour_id IS NULL AND e.date >= ? AND e.date < ?))
        ORDER BY e.date, e.id
    """, (owner_id, tour["id"], tour["starts_at"], tour["ends_at"]))]


def _mine(row: dict, key: str, whole: float) -> float:
    """Your part of a booking, income or cost: what's left after partners' shares."""
    value = row.get(key)
    return whole if value is None else value


def _money_figures(appointments: List[dict], expenses: List[dict], days: int, days_off: int,
                   income_rows: Optional[List[dict]] = None) -> dict:
    """Income, expenses by kind, and profit for a set of appointments, expenses and other income
    (payouts, tips, shifts: received, after the venue's or platform's fees)."""
    booked = [a for a in appointments if a.get("kind", "client") == "client"]
    live = [a for a in booked if a["status"] != "cancelled"]
    booking_income = sum(_mine(a, "my_amount_paid", a["amount_paid"] or 0) for a in booked)
    other_income = sum(_mine(r, "my_net", r["gross"] - r["fees"]) for r in (income_rows or []) if r["status"] == "received")
    expenses = [{**e, "amount": _mine(e, "my_amount", e["amount"])} for e in expenses]
    income = booking_income + other_income
    room_rent = sum(e["amount"] for e in expenses if e["category"] == "room_rent")
    tests = sum(e["amount"] for e in expenses if e["category"] == "medical")
    tests_by_type = {t.value: 0.0 for t in TestType}
    for e in expenses:
        if e["category"] == "medical" and e.get("test_type") in tests_by_type:
            tests_by_type[e["test_type"]] += e["amount"]
    total_expenses = sum(e["amount"] for e in expenses)
    profit = income - total_expenses
    working_days = max(days - days_off, 0)
    return {
        "income": round(income, 2),
        "booking_income": round(booking_income, 2),
        "other_income": round(other_income, 2),
        "booked": round(sum(a["rate"] or 0 for a in live), 2),
        "owed": round(sum(max((a["rate"] or 0) - (a["amount_paid"] or 0), 0)
                          for a in booked if a["status"] == "completed")
                      + sum(max((a.get("cancellation_fee") or 0) - (a["amount_paid"] or 0), 0)
                            for a in booked if a["status"] == "cancelled"), 2),
        "appointments": len(live),
        "completed": sum(a["status"] == "completed" for a in booked),
        "room_rent": round(room_rent, 2),
        "tests": round(tests, 2),
        "tests_by_type": {k: round(v, 2) for k, v in tests_by_type.items()},
        "other_expenses": round(total_expenses - room_rent - tests, 2),
        "expenses": round(total_expenses, 2),
        "profit": round(profit, 2),
        "days": days,
        "days_off": days_off,
        "working_days": working_days,
        "profit_per_day": round(profit / working_days, 2) if working_days else None,
        "income_per_appointment": round(booking_income / len(live), 2) if live else None,
    }


def tour_figures(db, owner_id: int, tour: dict, appointments=None, expenses=None, income_rows=None) -> dict:
    start, end = date.fromisoformat(tour["start_date"]), date.fromisoformat(tour["end_date"])
    appointments = _tour_appointments(db, owner_id, tour) if appointments is None else appointments
    expenses = _tour_expenses(db, owner_id, tour) if expenses is None else expenses
    if income_rows is None:
        income_rows = finance.income_between(db, owner_id, tour["starts_at"], tour["ends_at"])
    return _money_figures(appointments, expenses, _period_days(start, end), len(_days_off_in(db, owner_id, start, end)),
                          income_rows)


@app.post("/api/tours", response_model=Tour, status_code=201)
def create_tour(tour: TourIn, user: UserDep, db: DbDep):
    _validate_tour(db, tour, user["id"])
    now = now_iso()
    cur = db.execute("""
        INSERT INTO tours (kind, time_off_type, name, location, start_date, end_date, starts_at, ends_at,
                           room_rent_per_day, notes, source_id, owner_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (*_tour_values(tour), user["id"], now, now))
    _sync_room_rent(db, cur.lastrowid, user["id"])
    tests = sync_stay_charges(db, cur.lastrowid, user["id"])
    db.commit()
    calendar_sync.queue_item("period", cur.lastrowid, user["id"])
    for appointment_id in tests:
        calendar_sync.queue_appointment(appointment_id)
    return get_tour_by_id(db, cur.lastrowid, user["id"])


@app.get("/api/tours", response_model=List[Tour])
def list_tours(
    user: UserDep,
    db: DbDep,
    kind: Optional[TourKind] = None,
    start: Optional[datetime] = Query(None, description="Only periods still going at or after this time"),
    end: Optional[datetime] = Query(None, description="Only periods that began before this time"),
):
    conditions, params = ["owner_id = ?"], [user["id"]]
    if kind:
        conditions.append("kind = ?")
        params.append(kind.value)
    if start:
        conditions.append("ends_at > ?")
        params.append(to_utc_iso(start))
    if end:
        conditions.append("starts_at < ?")
        params.append(to_utc_iso(end))
    return [dict(r) for r in db.execute(
        f"SELECT * FROM tours WHERE {' AND '.join(conditions)} ORDER BY starts_at, id", params)]


@app.get("/api/tours/summary")
def tours_summary(user: UserDep, db: DbDep):
    """Every tour with its money, for comparing tours with each other. Newest first."""
    tours = [dict(r) for r in db.execute(
        "SELECT * FROM tours WHERE owner_id = ? AND kind = 'tour' ORDER BY starts_at DESC, id DESC", (user["id"],))]
    return [{**t, "figures": tour_figures(db, user["id"], t)} for t in tours]


@app.get("/api/tours/{tour_id}", response_model=Tour)
def get_tour(tour_id: int, user: UserDep, db: DbDep):
    tour = get_tour_by_id(db, tour_id, user["id"])
    if not tour:
        raise HTTPException(status_code=404, detail="Not found")
    return tour


@app.get("/api/tours/{tour_id}/summary")
def get_tour_summary(tour_id: int, user: UserDep, db: DbDep):
    tour = get_tour_by_id(db, tour_id, user["id"])
    if not tour:
        raise HTTPException(status_code=404, detail="Not found")
    appointments = _tour_appointments(db, user["id"], tour)
    expenses = _tour_expenses(db, user["id"], tour)
    income_rows = finance.income_between(db, user["id"], tour["starts_at"], tour["ends_at"], status=None)
    return {"tour": tour, "figures": tour_figures(db, user["id"], tour, appointments, expenses, income_rows),
            "appointments": appointments, "expenses": expenses, "income": income_rows,
            "statement": stay_statement(db, user["id"], tour, appointments, expenses, income_rows)}


def stay_statement(db, owner_id: int, tour: dict, appointments: List[dict], expenses: List[dict],
                   income_rows: List[dict]) -> Optional[dict]:
    """For a stay at a place: what you earned there, the house's share, what it charged you, and so what you
    should be paid. To check against the house's own settlement sheet."""
    if not tour.get("source_id"):
        return None
    place = finance.get_source(db, tour["source_id"], owner_id)
    if not place:
        return None
    here = [r for r in income_rows if r["source_id"] == place["id"]]
    bookings = [a for a in appointments if a.get("kind", "client") == "client" and a["status"] == "completed"]
    gross = sum(r["gross"] for r in here) + sum(a["rate"] or 0 for a in bookings)
    house_share = sum(r["fees"] for r in here)
    if bookings and place["fee_percent"]:
        house_share += sum(a["rate"] or 0 for a in bookings) * place["fee_percent"] / 100
    charged = [e for e in expenses if e.get("source") in ("stay_charge", "place_charge", "tour_room") or e.get("appointment_id")]
    lines = {}
    for e in charged:
        label = e["description"].rsplit(" – ", 1)[0]
        line = lines.setdefault(label, {"label": label, "count": 0, "total": 0.0})
        line["count"] += 1
        line["total"] += e["amount"]
    charges = sorted(({**v, "total": round(v["total"], 2)} for v in lines.values()), key=lambda v: -v["total"])
    charges_total = sum(c["total"] for c in charges)
    return {
        "place": {"id": place["id"], "name": place["name"], "kind": place["kind"], "fee_percent": place["fee_percent"]},
        "gross": round(gross, 2),
        "house_share": round(house_share, 2),
        "charges": charges,
        "charges_total": round(charges_total, 2),
        "take_home": round(gross - house_share - charges_total, 2),
        "received": round(sum(r["gross"] - r["fees"] for r in here if r["status"] == "received"), 2),
    }


@app.put("/api/tours/{tour_id}", response_model=Tour)
def update_tour(tour_id: int, tour: TourIn, user: UserDep, db: DbDep):
    existing = get_tour_by_id(db, tour_id, user["id"])
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")
    if existing["kind"] != tour.kind.value:
        raise HTTPException(status_code=400, detail="A tour can't be turned into time off, or the other way round")
    _validate_tour(db, tour, user["id"], exclude_id=tour_id)
    db.execute("""
        UPDATE tours SET kind = ?, time_off_type = ?, name = ?, location = ?, start_date = ?, end_date = ?,
                         starts_at = ?, ends_at = ?, room_rent_per_day = ?, notes = ?, source_id = ?, updated_at = ?
        WHERE id = ? AND owner_id = ?
    """, (*_tour_values(tour), now_iso(), tour_id, user["id"]))
    _sync_room_rent(db, tour_id, user["id"])
    tests = sync_stay_charges(db, tour_id, user["id"])
    db.commit()
    calendar_sync.queue_item("period", tour_id, user["id"])
    for appointment_id in tests:
        calendar_sync.queue_appointment(appointment_id)
    return get_tour_by_id(db, tour_id, user["id"])


@app.delete("/api/tours/{tour_id}", status_code=204)
def delete_tour(tour_id: int, user: UserDep, db: DbDep):
    """Remove a tour or time off. Its generated room & board goes too; other expenses stay, on no tour."""
    if not get_tour_by_id(db, tour_id, user["id"]):
        return
    db.execute("DELETE FROM expenses WHERE tour_id = ? AND owner_id = ? AND source = 'tour_room'", (tour_id, user["id"]))
    tests = _clear_stay_charges(db, tour_id, user["id"])
    db.execute("UPDATE expenses SET tour_id = NULL WHERE tour_id = ? AND owner_id = ?", (tour_id, user["id"]))
    db.execute("DELETE FROM tours WHERE id = ? AND owner_id = ?", (tour_id, user["id"]))
    db.commit()
    calendar_sync.queue_item("period", tour_id, user["id"])
    for appointment_id in tests:
        calendar_sync.queue_appointment(appointment_id)


# ==================== EARNINGS BY MONTH OR WEEK ====================

@app.get("/api/earnings/compare")
def compare_earnings(
    user: UserDep,
    db: DbDep,
    start: datetime = Query(..., description="From this time (the browser's local midnight)"),
    end: datetime = Query(..., description="Up to this time"),
    by: str = Query("month", description="month or week (weeks start on Sunday)"),
    tz_offset: int = Query(0, ge=-840, le=840, description="The browser's getTimezoneOffset()"),
):
    """
    Income, expenses and profit for each month or week, with days off and profit per working day.
    This is how someone who works full time (not on tours) compares one stretch of work with another.
    """
    if by not in ("month", "week"):
        raise HTTPException(status_code=400, detail="by must be month or week")
    shift = timedelta(minutes=tz_offset)
    local = lambda value: (parse_iso(value) if isinstance(value, str) else value) - shift  # noqa: E731
    first_day = local(start if start.tzinfo else start.replace(tzinfo=timezone.utc)).date()
    last_day = (local(end if end.tzinfo else end.replace(tzinfo=timezone.utc)) - timedelta(microseconds=1)).date()
    if last_day < first_day:
        raise HTTPException(status_code=400, detail="The end must be after the start")
    if _period_days(first_day, last_day) > MAX_COMPARE_DAYS:
        raise HTTPException(status_code=400, detail="Compare at most three years at a time")

    def bucket(day: date) -> str:
        if by == "month":
            return day.strftime("%Y-%m")
        return (day - timedelta(days=(day.weekday() + 1) % 7)).isoformat()   # the Sunday that starts the week

    buckets = {}
    for day in _date_range(first_day, last_day):
        b = buckets.setdefault(bucket(day), {"key": bucket(day), "start_date": day.isoformat(), "days": 0,
                                             "appointments": [], "expenses": [], "income": []})
        b["days"] += 1
        b["end_date"] = day.isoformat()
    days_off = _days_off_in(db, user["id"], first_day, last_day)

    range_params = (user["id"], to_utc_iso(start), to_utc_iso(end))
    for a in db.execute(APPOINTMENT_SELECT + " WHERE a.owner_id = ? AND a.scheduled_date >= ? AND a.scheduled_date < ?",
                        range_params):
        key = bucket(local(a["scheduled_date"]).date())
        if key in buckets:
            buckets[key]["appointments"].append(appointment_row(a))
    for e in db.execute(EXPENSE_SELECT + " WHERE e.owner_id = ? AND e.date >= ? AND e.date < ?", range_params):
        key = bucket(local(e["date"]).date())
        if key in buckets:
            buckets[key]["expenses"].append(dict(e))
    for r in finance.income_between(db, user["id"], to_utc_iso(start), to_utc_iso(end)):
        key = bucket(local(r["date"]).date())
        if key in buckets:
            buckets[key]["income"].append(r)

    rows = []
    for b in buckets.values():
        off = sum(1 for d in _date_range(date.fromisoformat(b["start_date"]), date.fromisoformat(b["end_date"]))
                  if d in days_off)
        rows.append({"key": b["key"], "start_date": b["start_date"], "end_date": b["end_date"],
                     "figures": _money_figures(b["appointments"], b["expenses"], b["days"], off, b["income"])})
    return {"by": by, "rows": rows}


# ==================== SEARCH ====================

def _search_clients(db, q, owner_id):
    term = like_term(q)
    rows = db.execute("""
        SELECT c.*, GROUP_CONCAT(ct.tag_name) AS tags
        FROM clients c LEFT JOIN client_tags ct ON c.id = ct.client_id
        WHERE c.owner_id = ? AND (
              LOWER(c.display_name) LIKE ? ESCAPE '\\' OR LOWER(IFNULL(c.handles, '')) LIKE ? ESCAPE '\\'
           OR LOWER(IFNULL(c.industry, '')) LIKE ? ESCAPE '\\' OR LOWER(IFNULL(c.email, '')) LIKE ? ESCAPE '\\'
           OR LOWER(IFNULL(c.contact_phone, '')) LIKE ? ESCAPE '\\'
           OR EXISTS (SELECT 1 FROM client_tags t2 WHERE t2.client_id = c.id AND t2.tag_name LIKE ? ESCAPE '\\'))
        GROUP BY c.id
    """, (owner_id, *[term] * 6))
    out = []
    for r in rows:
        d = client_row(r, split_tags(r["tags"]))
        d["tag_colors"] = tag_colors(d["tags"])
        d["entity_type"] = "client"
        out.append(d)
    return out


def _search_appointments(db, q, owner_id):
    term = like_term(q)
    rows = db.execute(APPOINTMENT_SELECT + """
        WHERE a.owner_id = ? AND (
              LOWER(a.service_type) LIKE ? ESCAPE '\\' OR LOWER(IFNULL(a.notes, '')) LIKE ? ESCAPE '\\'
           OR LOWER(IFNULL(a.location, '')) LIKE ? ESCAPE '\\' OR LOWER(IFNULL(c.display_name, '')) LIKE ? ESCAPE '\\')
    """, (owner_id, term, term, term, term))
    return [{**appointment_row(r), "entity_type": "appointment"} for r in rows]


def _search_expenses(db, q, owner_id):
    term = like_term(q)
    rows = db.execute("""
        SELECT e.*, c.display_name AS client_name
        FROM expenses e LEFT JOIN clients c ON e.client_id = c.id
        WHERE e.owner_id = ? AND (
              LOWER(e.description) LIKE ? ESCAPE '\\' OR LOWER(e.category) LIKE ? ESCAPE '\\'
           OR LOWER(IFNULL(c.display_name, '')) LIKE ? ESCAPE '\\')
    """, (owner_id, term, term, term))
    return [{**dict(r), "entity_type": "expense"} for r in rows]


@app.get("/api/search")
def search_all(
    user: UserDep,
    db: DbDep,
    q: str = Query(..., description="Search term"),
    entity_type: str = Query("all", description="all, clients, appointments, or expenses"),
):
    searchers = {
        "clients": _search_clients,
        "appointments": _search_appointments,
        "expenses": _search_expenses,
    }
    if entity_type != "all" and entity_type not in searchers:
        raise HTTPException(status_code=400, detail="entity_type must be all, clients, appointments, or expenses")
    if not q.strip():
        results = []  # a blank search finds nothing, rather than matching every record
    elif entity_type == "all":
        results = [r for fn in searchers.values() for r in fn(db, q, user["id"])]
    else:
        results = searchers[entity_type](db, q, user["id"])
    return {"entity_type": entity_type, "count": len(results), "results": results}


# ==================== SAMPLE DATA ====================

SAMPLE_CLIENTS = [
    ("Maria Johnson", "+1-555-0101", "maria@example.com", "Regular, prefers mornings", ["regular", "verified"]),
    ("James Chen", "+1-555-0102", "jchen@example.com", "Referred by a friend", ["new", "verified"]),
    ("Elena Rodriguez", "+1-555-0103", "elena@example.com", "Books monthly", ["regular"]),
    ("David Kim", "+1-555-0104", "dkim@example.com", "Travel bookings only", ["travel", "verified"]),
    ("Sofia Martinez", "+1-555-0105", "sofia@example.com", "Prefers text contact", ["regular", "text-only"]),
]
SAMPLE_EXPENSES = [
    (None, "Massage table", 350.00, "equipment"),
    (None, "Ad listing renewal", 120.00, "marketing"),
    (3, "Rideshare to hotel", 80.00, "travel"),
    (None, "Linen service", 45.00, "cleaning"),
    (None, "Wardrobe", 250.00, "other"),
]


def seed_db():
    """Add sample data to a brand-new database, once. It can be removed from the Account page."""
    db = get_db()
    try:
        seeded = db.execute("SELECT value FROM settings WHERE key = 'seeded'").fetchone()
        if seeded or db.execute("SELECT 1 FROM clients LIMIT 1").fetchone() \
                or db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return
        now = now_iso()
        ids = []
        for name, phone, email, bio, tags in SAMPLE_CLIENTS:
            cur = db.execute("""
                INSERT INTO clients (name, display_name, contact_phone, email, bio, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, name, phone, email, bio, now, now))
            ids.append(cur.lastrowid)
            set_client_tags(db, cur.lastrowid, tags)

        base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        for client_index, service, duration, days, rate in [
            (1, "Individual Session", 60, 1, 300), (2, "Consultation", 45, 2, 150),
            (0, "Individual Session", 90, 3, 450), (3, "Overnight", 720, 5, 2000),
            (4, "Individual Session", 60, 6, 300),
        ]:
            db.execute("""
                INSERT INTO appointments (client_id, service_type, duration_minutes, scheduled_date, status, rate,
                                          created_at, updated_at)
                VALUES (?, ?, ?, ?, 'scheduled', ?, ?, ?)
            """, (ids[client_index], service, duration, to_utc_iso(base + timedelta(days=days, hours=2)), rate, now, now))

        for client_index, desc, amount, cat in SAMPLE_EXPENSES:
            db.execute("""
                INSERT INTO expenses (client_id, description, amount, category, date, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ids[client_index] if client_index is not None else None, desc, amount, cat, now, now))
        db.execute("INSERT INTO settings (key, value) VALUES ('seeded', '1') "
                   "ON CONFLICT(key) DO UPDATE SET value = '1'")
        db.commit()
    finally:
        db.close()


def _sample_client_ids(db, owner_id: int) -> List[int]:
    emails = [c[2] for c in SAMPLE_CLIENTS]
    return [r[0] for r in db.execute(
        f"SELECT id FROM clients WHERE owner_id = ? AND email IN ({', '.join('?' * len(emails))})",
        (owner_id, *emails))]


def _sample_expense_ids(db, owner_id: int) -> List[int]:
    ids = []
    for _, desc, amount, cat in SAMPLE_EXPENSES:
        ids += [r[0] for r in db.execute(
            "SELECT id FROM expenses WHERE owner_id = ? AND description = ? AND amount = ? AND category = ?",
            (owner_id, desc, amount, cat))]
    return ids


@app.get("/api/sample-data")
def sample_data_status(user: UserDep, db: DbDep):
    clients = _sample_client_ids(db, user["id"])
    expenses = _sample_expense_ids(db, user["id"])
    return {"present": bool(clients or expenses), "clients": len(clients), "expenses": len(expenses)}


@app.delete("/api/sample-data")
def remove_sample_data(user: UserDep, db: DbDep):
    """Delete the example clients (with their appointments and notes) and the example expenses."""
    clients = _sample_client_ids(db, user["id"])
    expenses = _sample_expense_ids(db, user["id"])
    appointment_ids = []
    for client_id in clients:
        appointment_ids += [r[0] for r in db.execute("SELECT id FROM appointments WHERE client_id = ?", (client_id,))]
        db.execute("DELETE FROM client_tags WHERE client_id = ?", (client_id,))
        db.execute("DELETE FROM client_notes WHERE client_id = ?", (client_id,))
        db.execute("DELETE FROM appointments WHERE client_id = ?", (client_id,))
        db.execute("UPDATE expenses SET client_id = NULL WHERE client_id = ?", (client_id,))
        db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    for expense_id in expenses:
        db.execute("DELETE FROM expenses WHERE id = ? AND owner_id = ?", (expense_id, user["id"]))
    db.commit()
    for appointment_id in appointment_ids:
        calendar_sync.queue_appointment(appointment_id)
    return {"clients": len(clients), "appointments": len(appointment_ids), "expenses": len(expenses)}


# ==================== OTHER MODULES + STARTUP ====================

app.include_router(calendar_sync.router)
app.include_router(csv_io.router)
app.include_router(backup.router)
app.include_router(safety.router)
app.include_router(finance.router)
app.include_router(tasks.router)
app.include_router(mail.router)
app.include_router(collab.router)
app.include_router(content.router)
app.include_router(cycle.router)
app.include_router(places.router)
app.include_router(personas.router)
app.include_router(blocklist.router)
app.include_router(meds.router)
app.include_router(documents.router)
app.include_router(noshow.router)
app.include_router(taxes.router)
app.include_router(signin.router)
app.include_router(arrangements.router)
app.include_router(calendar_dates.router)

init_db()
if os.environ.get("SEED_DB", "1") == "1":
    seed_db()
finance.setup(get_db)
tasks.setup(get_db)
mail.setup(get_db)
collab.setup(get_db)
content.setup(get_db)
cycle.setup(get_db)
places.setup(get_db, log_health_test, sync_stays_at_place)
personas.setup(get_db)
blocklist.setup(get_db)
meds.setup(get_db)
documents.setup(get_db)
noshow.setup(get_db)
taxes.setup(get_db)
signin.setup(get_db, _set_session_cookie)
arrangements.setup(get_db)
calendar_dates.setup(get_db)
csv_io.setup(get_db, after_client_import=lambda ids: [calendar_sync.queue_client(i) for i in ids])
# BACKGROUND_JOBS=0 (the tests) keeps the background threads from starting.
_background = os.environ.get("BACKGROUND_JOBS", os.environ.get("CALENDAR_SYNC", "1")) == "1"
calendar_sync.start(get_db, background=_background)
backup.start(get_db, background=_background)
safety.start(get_db, background=_background)
demo.start(app, get_db)   # does nothing unless DEMO_MODE=1


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8008, reload=True)
