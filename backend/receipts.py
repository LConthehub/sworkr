"""
Discreet receipts for clients.

A receipt shows a neutral business name, a neutral line ("Consulting services" by default), the amount, the
date, how it was paid and a number (R-2026-001). Nothing on it says sworkr or what the work was; the person
chooses every word in Settings and can change any line on a single receipt.

Each receipt is saved as it was issued (name, wording, amount), so printing it again later looks the same
even after the settings change. Numbers run per person per year; deleting one leaves a gap, as it should.
"""

from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter()
_get_db: Optional[Callable] = None

SETTINGS = {                              # key -> default
    "receipt_business": "",
    "receipt_service": "Consulting services",
    "receipt_contact": "",
    "receipt_footer": "Thank you.",
    "receipt_prefix": "R",
}
LIMITS = {"receipt_business": 120, "receipt_service": 120, "receipt_contact": 300, "receipt_footer": 300, "receipt_prefix": 8}


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_settings(db, owner: int) -> dict:
    rows = {r["key"]: r["value"] for r in db.execute(
        f"SELECT key, value FROM user_settings WHERE user_id = ? AND key IN ({','.join('?' * len(SETTINGS))})",
        (owner, *SETTINGS))}
    return {k[len("receipt_"):]: (rows[k] if rows.get(k) is not None else d) for k, d in SETTINGS.items()}


class ReceiptSettings(BaseModel):
    business: str = ""
    service: str = ""
    contact: str = ""
    footer: str = ""
    prefix: str = "R"


@router.get("/api/receipts/settings")
def get_settings(request: Request):
    db = _get_db()
    try:
        return load_settings(db, request.state.user["id"])
    finally:
        db.close()


@router.put("/api/receipts/settings")
def save_settings(body: ReceiptSettings, request: Request):
    owner = request.state.user["id"]
    values = body.model_dump()
    values["prefix"] = "".join(c for c in values["prefix"].strip().upper() if c.isalnum()) or "R"
    db = _get_db()
    try:
        for short, value in values.items():
            key = "receipt_" + short
            db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
                       "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
                       (owner, key, (value or "").strip()[:LIMITS[key]]))
        db.commit()
        return load_settings(db, owner)
    finally:
        db.close()


class ReceiptIn(BaseModel):
    appointment_id: Optional[int] = None
    billed_to: Optional[str] = None       # optional: whatever name the client wants on it
    description: Optional[str] = None     # empty: the default line from settings
    amount: Optional[float] = None        # empty: what the booking says was paid
    currency: Optional[str] = None
    date: Optional[str] = None            # "YYYY-MM-DD"; empty: the booking's date, or today
    method: Optional[str] = None          # how it was paid; empty: the booking's payment method
    note: Optional[str] = None


def _row(r) -> dict:
    d = dict(r)
    d.pop("owner_id", None)
    return d


@router.get("/api/receipts")
def list_receipts(request: Request, appointment_id: Optional[int] = Query(None)):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        sql, args = "SELECT * FROM receipts WHERE owner_id = ?", [owner]
        if appointment_id is not None:
            sql += " AND appointment_id = ?"
            args.append(appointment_id)
        return [_row(r) for r in db.execute(sql + " ORDER BY year DESC, seq DESC LIMIT 500", args)]
    finally:
        db.close()


@router.post("/api/receipts", status_code=201)
def create_receipt(body: ReceiptIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        s = load_settings(db, owner)
        appt = None
        if body.appointment_id is not None:
            appt = db.execute("SELECT scheduled_date, amount_paid, rate, payment_method, currency FROM appointments "
                              "WHERE id = ? AND owner_id = ?", (body.appointment_id, owner)).fetchone()
            if not appt:
                raise HTTPException(status_code=404, detail="Booking not found")
        amount = body.amount
        if amount is None and appt:
            amount = appt["amount_paid"] or appt["rate"]
        if amount is None or not 0 < amount < 1e9:
            raise HTTPException(status_code=400, detail="How much was paid?")
        day = (body.date or (appt["scheduled_date"][:10] if appt else "") or datetime.now(timezone.utc).date().isoformat())
        try:
            year = datetime.strptime(day, "%Y-%m-%d").year
        except ValueError:
            raise HTTPException(status_code=400, detail="The date looks like 2026-06-01")
        method = (body.method if body.method is not None else (appt["payment_method"] if appt else "")) or ""
        currency = (body.currency or (appt["currency"] if appt else None) or "USD").upper()[:3]
        seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM receipts WHERE owner_id = ? AND year = ?",
                         (owner, year)).fetchone()[0]
        number = f"{s['prefix']}-{year}-{seq:03d}"
        cur = db.execute(
            "INSERT INTO receipts (owner_id, appointment_id, year, seq, number, issued_on, billed_to, description, amount, "
            "currency, method, note, business, contact, footer, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (owner, body.appointment_id, year, seq, number, day, (body.billed_to or "").strip()[:120] or None,
             (body.description or "").strip()[:200] or s["service"] or "Services", round(amount, 2), currency,
             method.strip()[:60] or None, (body.note or "").strip()[:300] or None,
             s["business"] or None, s["contact"] or None, s["footer"] or None, _now()))
        db.commit()
        return _row(db.execute("SELECT * FROM receipts WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        db.close()


@router.get("/api/receipts/{receipt_id}")
def get_receipt(receipt_id: int, request: Request):
    db = _get_db()
    try:
        r = db.execute("SELECT * FROM receipts WHERE id = ? AND owner_id = ?", (receipt_id, request.state.user["id"])).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Receipt not found")
        return _row(r)
    finally:
        db.close()


@router.delete("/api/receipts/{receipt_id}", status_code=204)
def delete_receipt(receipt_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM receipts WHERE id = ? AND owner_id = ?", (receipt_id, request.state.user["id"]))
        db.commit()
    finally:
        db.close()
