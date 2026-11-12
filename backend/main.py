"""
Sworkr Management Service - Backend
FastAPI application with client profiles, appointments, expenses, and tag system.
Run with: docker compose up --build
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, List, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import auth

app = FastAPI(title="Sworkr Management Service", version="1.0.0")

# Send cookies only over HTTPS when deployed behind TLS (set COOKIE_SECURE=1).
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"

COLOR_PALETTE = ["#fc4c9c", "#e67eb6", "#a73178", "#542b5c", "#4b86a6"]


# ==================== ENUMS & MODELS ====================

class AppointmentStatus(str, Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ExpenseCategory(str, Enum):
    EQUIPMENT = "equipment"
    MARKETING = "marketing"
    TRAVEL = "travel"
    CLEANING = "cleaning"
    OTHER = "other"


# Input models (what the API accepts)
class ClientIn(BaseModel):
    name: str
    contact_phone: Optional[str] = None
    email: Optional[str] = None
    bio: Optional[str] = None
    tags: List[str] = []
    is_active: bool = True


class AppointmentIn(BaseModel):
    client_id: int
    service_type: str
    duration_minutes: int
    scheduled_date: datetime
    status: AppointmentStatus = AppointmentStatus.SCHEDULED
    notes: Optional[str] = None


class ExpenseIn(BaseModel):
    client_id: Optional[int] = None
    description: str
    amount: float
    category: ExpenseCategory = ExpenseCategory.OTHER
    date: Optional[datetime] = None
    notes: Optional[str] = None


class Credentials(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


# Output models (what the API returns)
class Client(ClientIn):
    id: int
    created_at: datetime
    updated_at: datetime


class Appointment(AppointmentIn):
    id: int
    client_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class Expense(ExpenseIn):
    id: int
    date: datetime
    client_name: Optional[str] = None


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


def init_db():
    conn = get_db()
    conn.executescript("""
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
    """)
    migrate_naive_timestamps(conn)
    conn.commit()
    conn.close()


TIMESTAMP_COLUMNS = {
    "clients": ["created_at", "updated_at"],
    "appointments": ["scheduled_date", "created_at", "updated_at"],
    "expenses": ["date", "created_at"],
}


def migrate_naive_timestamps(conn):
    """Older versions stored UTC times without a timezone. Mark them as UTC explicitly."""
    for table, cols in TIMESTAMP_COLUMNS.items():
        for col in cols:
            conn.execute(f"""
                UPDATE {table} SET {col} = {col} || '+00:00'
                WHERE {col} IS NOT NULL AND {col} NOT LIKE '%+%' AND {col} NOT LIKE '%Z'
                  AND substr({col}, 11, 1) = 'T' AND length({col}) >= 19
            """)


def to_utc_iso(dt: datetime) -> str:
    """Store every timestamp as UTC with an explicit offset. Naive input is treated as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def now_iso() -> str:
    return to_utc_iso(datetime.now(timezone.utc))


def tag_colors(tags: List[str]) -> List[dict]:
    return [{"label": t, "color": COLOR_PALETTE[sum(map(ord, t)) % len(COLOR_PALETTE)]} for t in tags]


def split_tags(value: Optional[str]) -> List[str]:
    return [t.strip() for t in value.split(",")] if value else []


def like_term(text: str) -> str:
    """A 'contains' pattern for LIKE. Pair it with ESCAPE so % and _ in the text are matched literally."""
    escaped = text.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# ==================== HELPERS ====================

def get_client_by_id(db, client_id: int) -> Optional[dict]:
    row = db.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["tags"] = [r["tag_name"] for r in db.execute(
        "SELECT tag_name FROM client_tags WHERE client_id = ?", (client_id,))]
    return result


def set_client_tags(db, client_id: int, tags: List[str]):
    db.execute("DELETE FROM client_tags WHERE client_id = ?", (client_id,))
    for tag in {t.lower().strip() for t in tags if t.strip()}:
        db.execute("INSERT INTO client_tags (client_id, tag_name) VALUES (?, ?)", (client_id, tag))


def get_appointment_by_id(db, appointment_id: int) -> Optional[dict]:
    row = db.execute("""
        SELECT a.*, c.name AS client_name
        FROM appointments a LEFT JOIN clients c ON a.client_id = c.id
        WHERE a.id = ?
    """, (appointment_id,)).fetchone()
    return dict(row) if row else None


def get_expense_by_id(db, expense_id: int) -> Optional[dict]:
    row = db.execute("""
        SELECT e.*, c.name AS client_name
        FROM expenses e LEFT JOIN clients c ON e.client_id = c.id
        WHERE e.id = ?
    """, (expense_id,)).fetchone()
    return dict(row) if row else None


# ==================== AUTH ====================

PUBLIC_PATHS = {"/api/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login", "/api/auth/logout"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Every /api route needs a valid session, except the few listed in PUBLIC_PATHS."""
    path = request.url.path.rstrip("/") or "/"
    if path.startswith("/api") and path not in PUBLIC_PATHS:
        db = get_db()
        try:
            user = auth.user_for_token(db, request.cookies.get(auth.SESSION_COOKIE))
        finally:
            db.close()
        if not user:
            return JSONResponse({"detail": "Not logged in"}, status_code=401)
        request.state.user = user
    return await call_next(request)


def _set_session_cookie(response: Response, token: str):
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/",
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
    user = auth.user_for_token(db, request.cookies.get(auth.SESSION_COOKIE))
    return {"setup_required": setup_required, "user": user}


@app.post("/api/auth/setup", status_code=201)
def auth_setup(creds: Credentials, response: Response, db: DbDep):
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
    db.commit()
    _set_session_cookie(response, auth.create_session(db, cur.lastrowid))
    return {"id": cur.lastrowid, "username": username, "is_admin": True}


@app.post("/api/auth/login")
def auth_login(creds: Credentials, response: Response, db: DbDep):
    username = creds.username.strip().lower()
    wait = auth.throttle.seconds_locked(username)
    if wait:
        raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {wait} seconds.")
    user = auth.check_login(db, username, creds.password)
    if not user:
        auth.throttle.failure(username)
        raise HTTPException(status_code=401, detail="Wrong username or password")
    auth.throttle.success(username)
    _set_session_cookie(response, auth.create_session(db, user["id"]))
    return {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"])}


@app.post("/api/auth/logout", status_code=204)
def auth_logout(request: Request, response: Response, db: DbDep):
    auth.delete_session(db, request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")


@app.post("/api/auth/change-password", status_code=204)
def auth_change_password(body: PasswordChange, request: Request, db: DbDep):
    user = request.state.user
    if len(body.new_password) < auth.MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {auth.MIN_PASSWORD_LENGTH} characters")
    if not auth.check_login(db, user["username"], body.current_password):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(body.new_password), user["id"]))
    db.commit()
    # Log out every other device, keep this one.
    auth.delete_user_sessions(db, user["id"], keep_token=request.cookies.get(auth.SESSION_COOKIE))


# ==================== CLIENTS ====================

@app.post("/api/clients", response_model=Client, status_code=201)
def create_client(client: ClientIn, db: DbDep):
    if not client.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    now = now_iso()
    try:
        cur = db.execute("""
            INSERT INTO clients (name, contact_phone, email, bio, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (client.name, client.contact_phone, client.email.lower() if client.email else None,
              client.bio, int(client.is_active), now, now))
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A client with that email already exists")
    set_client_tags(db, cur.lastrowid, client.tags)
    db.commit()
    return get_client_by_id(db, cur.lastrowid)


@app.get("/api/clients", response_model=List[Client])
def list_clients(
    db: DbDep,
    is_active: Optional[int] = Query(None, ge=0, le=1),
    search: Optional[str] = None,
    tag_filter: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
):
    conditions, params = [], []

    if is_active is not None:
        conditions.append("c.is_active = ?")
        params.append(is_active)
    if search and search.strip():
        conditions.append("(LOWER(c.name) LIKE ? ESCAPE '\\' OR LOWER(c.email) LIKE ? ESCAPE '\\')")
        term = like_term(search)
        params.extend([term, term])
    if tag_filter:
        conditions.append("EXISTS (SELECT 1 FROM client_tags t2 WHERE t2.client_id = c.id AND t2.tag_name = ?)")
        params.append(tag_filter.lower().strip())

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT c.*, GROUP_CONCAT(ct.tag_name) AS tags
        FROM clients c LEFT JOIN client_tags ct ON c.id = ct.client_id
        {where}
        GROUP BY c.id
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, (page - 1) * limit])

    clients = []
    for row in db.execute(query, params):
        data = dict(row)
        data["tags"] = split_tags(data.get("tags"))
        clients.append(data)
    return clients


@app.get("/api/clients/{client_id}", response_model=Client)
def get_client(client_id: int, db: DbDep):
    client = get_client_by_id(db, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@app.put("/api/clients/{client_id}", response_model=Client)
def update_client(client_id: int, client: ClientIn, db: DbDep):
    if not client.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    if not get_client_by_id(db, client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        db.execute("""
            UPDATE clients SET name = ?, contact_phone = ?, email = ?, bio = ?, is_active = ?, updated_at = ?
            WHERE id = ?
        """, (client.name, client.contact_phone, client.email.lower() if client.email else None,
              client.bio, int(client.is_active), now_iso(), client_id))
    except sqlite3.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A client with that email already exists")
    set_client_tags(db, client_id, client.tags)
    db.commit()
    return get_client_by_id(db, client_id)


@app.delete("/api/clients/{client_id}", status_code=204)
def delete_client(client_id: int, db: DbDep):
    db.execute("DELETE FROM client_tags WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM appointments WHERE client_id = ?", (client_id,))
    db.execute("UPDATE expenses SET client_id = NULL WHERE client_id = ?", (client_id,))
    db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    db.commit()


# ==================== APPOINTMENTS ====================

def _validate_appointment(db, appointment: AppointmentIn):
    if not get_client_by_id(db, appointment.client_id):
        raise HTTPException(status_code=400, detail="Client does not exist")
    if appointment.duration_minutes <= 0:
        raise HTTPException(status_code=400, detail="Duration must be more than 0 minutes")
    if not appointment.service_type.strip():
        raise HTTPException(status_code=400, detail="Service type is required")


@app.post("/api/appointments", response_model=Appointment, status_code=201)
def create_appointment(appointment: AppointmentIn, db: DbDep):
    now = now_iso()
    _validate_appointment(db, appointment)
    cur = db.execute("""
        INSERT INTO appointments (client_id, service_type, duration_minutes, scheduled_date, status, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (appointment.client_id, appointment.service_type.strip(), appointment.duration_minutes,
          to_utc_iso(appointment.scheduled_date), appointment.status.value, appointment.notes, now, now))
    db.commit()
    return get_appointment_by_id(db, cur.lastrowid)


@app.get("/api/appointments", response_model=List[Appointment])
def list_appointments(
    db: DbDep,
    client_id: Optional[int] = None,
    status: Optional[AppointmentStatus] = None,
    service_type: Optional[str] = None,
    start: Optional[datetime] = Query(None, description="Only appointments at or after this time"),
    end: Optional[datetime] = Query(None, description="Only appointments before this time"),
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=1000),
):
    conditions, params = [], []
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

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT a.*, c.name AS client_name
        FROM appointments a LEFT JOIN clients c ON a.client_id = c.id
        {where}
        ORDER BY a.scheduled_date ASC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, (page - 1) * limit])
    return [dict(r) for r in db.execute(query, params)]


@app.get("/api/appointments/service-types", response_model=List[str])
def list_service_types(db: DbDep):
    return [r[0] for r in db.execute(
        "SELECT service_type FROM appointments GROUP BY service_type ORDER BY COUNT(*) DESC LIMIT 50")]


@app.get("/api/appointments/{appointment_id}", response_model=Appointment)
def get_appointment(appointment_id: int, db: DbDep):
    appt = get_appointment_by_id(db, appointment_id)
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


@app.put("/api/appointments/{appointment_id}", response_model=Appointment)
def update_appointment(appointment_id: int, appointment: AppointmentIn, db: DbDep):
    if not get_appointment_by_id(db, appointment_id):
        raise HTTPException(status_code=404, detail="Appointment not found")
    _validate_appointment(db, appointment)
    db.execute("""
        UPDATE appointments
        SET client_id = ?, service_type = ?, duration_minutes = ?, scheduled_date = ?, status = ?, notes = ?, updated_at = ?
        WHERE id = ?
    """, (appointment.client_id, appointment.service_type.strip(), appointment.duration_minutes,
          to_utc_iso(appointment.scheduled_date), appointment.status.value, appointment.notes, now_iso(), appointment_id))
    db.commit()
    return get_appointment_by_id(db, appointment_id)


@app.put("/api/appointments/{appointment_id}/status", response_model=Appointment)
def update_appointment_status(appointment_id: int, status: AppointmentStatus, db: DbDep):
    if not get_appointment_by_id(db, appointment_id):
        raise HTTPException(status_code=404, detail="Appointment not found")
    db.execute("UPDATE appointments SET status = ?, updated_at = ? WHERE id = ?",
               (status.value, now_iso(), appointment_id))
    db.commit()
    return get_appointment_by_id(db, appointment_id)


@app.delete("/api/appointments/{appointment_id}", status_code=204)
def delete_appointment(appointment_id: int, db: DbDep):
    db.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))
    db.commit()


# ==================== EXPENSES ====================

def _validate_expense(db, expense: ExpenseIn):
    if not expense.description.strip():
        raise HTTPException(status_code=400, detail="Description is required")
    # Written this way so NaN and infinity are rejected too.
    if not (0 <= expense.amount < float("inf")):
        raise HTTPException(status_code=400, detail="Amount must be 0 or more")
    if expense.client_id is not None and not get_client_by_id(db, expense.client_id):
        raise HTTPException(status_code=400, detail="Client does not exist")


@app.post("/api/expenses", response_model=Expense, status_code=201)
def create_expense(expense: ExpenseIn, db: DbDep):
    now = now_iso()
    _validate_expense(db, expense)
    cur = db.execute("""
        INSERT INTO expenses (client_id, description, amount, category, date, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (expense.client_id, expense.description, expense.amount, expense.category.value,
          (to_utc_iso(expense.date) if expense.date else now), expense.notes, now))
    db.commit()
    return get_expense_by_id(db, cur.lastrowid)


@app.get("/api/expenses", response_model=List[Expense])
def list_expenses(
    db: DbDep,
    client_id: Optional[int] = None,
    category: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(100, ge=1, le=500),
):
    conditions, params = [], []
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

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT e.*, c.name AS client_name
        FROM expenses e LEFT JOIN clients c ON e.client_id = c.id
        {where}
        ORDER BY e.date DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, (page - 1) * limit])
    return [dict(r) for r in db.execute(query, params)]


@app.get("/api/expenses/summary")
def get_expense_summary(db: DbDep):
    category_summary = [
        {"category": r["category"], "total": round(r["total"], 2), "count": r["count"]}
        for r in db.execute("""
            SELECT category, SUM(amount) AS total, COUNT(*) AS count
            FROM expenses GROUP BY category ORDER BY total DESC
        """)
    ]
    top_clients = [
        {"name": r["name"], "total_spent": round(r["total_spent"], 2), "expense_count": r["expense_count"]}
        for r in db.execute("""
            SELECT c.name, SUM(e.amount) AS total_spent, COUNT(e.id) AS expense_count
            FROM expenses e JOIN clients c ON e.client_id = c.id
            GROUP BY c.id ORDER BY total_spent DESC LIMIT 20
        """)
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
def update_expense(expense_id: int, expense: ExpenseIn, db: DbDep):
    existing = get_expense_by_id(db, expense_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Expense not found")
    _validate_expense(db, expense)
    db.execute("""
        UPDATE expenses SET client_id = ?, description = ?, amount = ?, category = ?, date = ?, notes = ?
        WHERE id = ?
    """, (expense.client_id, expense.description, expense.amount, expense.category.value,
          to_utc_iso(expense.date) if expense.date else existing["date"], expense.notes, expense_id))
    db.commit()
    return get_expense_by_id(db, expense_id)


@app.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, db: DbDep):
    db.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    db.commit()


# ==================== SEARCH ====================

def _search_clients(db, q):
    term = like_term(q)
    rows = db.execute("""
        SELECT c.*, GROUP_CONCAT(ct.tag_name) AS tags
        FROM clients c LEFT JOIN client_tags ct ON c.id = ct.client_id
        WHERE LOWER(c.name) LIKE ? ESCAPE '\\' OR LOWER(IFNULL(c.email, '')) LIKE ? ESCAPE '\\'
           OR EXISTS (SELECT 1 FROM client_tags t2 WHERE t2.client_id = c.id AND t2.tag_name LIKE ? ESCAPE '\\')
        GROUP BY c.id
    """, (term, term, term))
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = split_tags(d.get("tags"))
        d["tag_colors"] = tag_colors(d["tags"])
        d["entity_type"] = "client"
        out.append(d)
    return out


def _search_appointments(db, q):
    term = like_term(q)
    rows = db.execute("""
        SELECT a.*, c.name AS client_name
        FROM appointments a LEFT JOIN clients c ON a.client_id = c.id
        WHERE LOWER(a.service_type) LIKE ? ESCAPE '\\' OR LOWER(IFNULL(a.notes, '')) LIKE ? ESCAPE '\\'
           OR LOWER(IFNULL(c.name, '')) LIKE ? ESCAPE '\\'
    """, (term, term, term))
    return [{**dict(r), "entity_type": "appointment"} for r in rows]


def _search_expenses(db, q):
    term = like_term(q)
    rows = db.execute("""
        SELECT e.*, c.name AS client_name
        FROM expenses e LEFT JOIN clients c ON e.client_id = c.id
        WHERE LOWER(e.description) LIKE ? ESCAPE '\\' OR LOWER(e.category) LIKE ? ESCAPE '\\'
           OR LOWER(IFNULL(c.name, '')) LIKE ? ESCAPE '\\'
    """, (term, term, term))
    return [{**dict(r), "entity_type": "expense"} for r in rows]


@app.get("/api/search")
def search_all(
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
        results = [r for fn in searchers.values() for r in fn(db, q)]
    else:
        results = searchers[entity_type](db, q)
    return {"entity_type": entity_type, "count": len(results), "results": results}


# ==================== SEED DATA ====================

def seed_db():
    """Add sample data the first time the database is created."""
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM clients").fetchone()[0] > 0:
        db.close()
        return

    now = now_iso()
    clients = [
        ("Maria Johnson", "+1-555-0101", "maria@example.com", "Regular, prefers mornings", ["regular", "verified"]),
        ("James Chen", "+1-555-0102", "jchen@example.com", "Referred by a friend", ["new", "verified"]),
        ("Elena Rodriguez", "+1-555-0103", "elena@example.com", "Books monthly", ["regular"]),
        ("David Kim", "+1-555-0104", "dkim@example.com", "Travel bookings only", ["travel", "verified"]),
        ("Sofia Martinez", "+1-555-0105", "sofia@example.com", "Prefers text contact", ["regular", "text-only"]),
    ]
    ids = []
    for name, phone, email, bio, tags in clients:
        cur = db.execute("""
            INSERT INTO clients (name, contact_phone, email, bio, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, phone, email, bio, now, now))
        ids.append(cur.lastrowid)
        set_client_tags(db, cur.lastrowid, tags)

    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    appointments = [
        (ids[1], "Individual Session", 60, 1),
        (ids[2], "Consultation", 45, 2),
        (ids[0], "Individual Session", 90, 3),
        (ids[3], "Overnight", 720, 5),
        (ids[4], "Individual Session", 60, 6),
    ]
    for client_id, service, duration, days in appointments:
        db.execute("""
            INSERT INTO appointments (client_id, service_type, duration_minutes, scheduled_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'scheduled', ?, ?)
        """, (client_id, service, duration, to_utc_iso(base + timedelta(days=days, hours=2)), now, now))

    expenses = [
        (None, "Massage table", 350.00, "equipment"),
        (None, "Ad listing renewal", 120.00, "marketing"),
        (ids[3], "Rideshare to hotel", 80.00, "travel"),
        (None, "Linen service", 45.00, "cleaning"),
        (None, "Wardrobe", 250.00, "other"),
    ]
    for client_id, desc, amount, cat in expenses:
        db.execute("""
            INSERT INTO expenses (client_id, description, amount, category, date, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (client_id, desc, amount, cat, now, now))

    db.commit()
    db.close()


init_db()
if os.environ.get("SEED_DB", "1") == "1":
    seed_db()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8008, reload=True)
