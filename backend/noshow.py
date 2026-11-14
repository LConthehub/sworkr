"""
Deposits, cancellations and no-shows.

A cancelled booking says who cancelled it: the client (in time or late), the client simply not turning up
(a no-show), or you. A late cancellation or a no-show can carry a cancellation fee: what the client owes for
it. Any deposit already paid is the booking's amount paid, and counts towards the fee.

Your policy (a deposit percentage, how late a cancellation counts as late, and the fees for late cancellations
and no-shows) suggests the fee; you can always change it. Each client's record (no-shows and late
cancellations) is shown on their page and warned about before booking them again.
"""

from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/booking-policy")
_get_db: Optional[Callable] = None
REASONS = ("client", "late", "no_show", "me")   # client cancelled in time, late, didn't turn up, you cancelled
DEFAULTS = {"deposit_percent": 0.0, "late_cancel_hours": 24.0, "late_cancel_fee_percent": 50.0, "no_show_fee_percent": 100.0}


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


class PolicyIn(BaseModel):
    deposit_percent: float = 0
    late_cancel_hours: float = 24
    late_cancel_fee_percent: float = 50
    no_show_fee_percent: float = 100


def policy(db, owner_id: int) -> dict:
    out = dict(DEFAULTS)
    for r in db.execute("SELECT key, value FROM user_settings WHERE user_id = ? AND key LIKE 'policy_%'", (owner_id,)):
        key = r["key"][len("policy_"):]
        if key in out:
            try:
                out[key] = float(r["value"])
            except (TypeError, ValueError):
                pass
    return out


def reason_for(cancelled_at: datetime, starts_at: datetime, said: str, late_hours: float) -> str:
    """'client' becomes 'late' when the client cancelled within the late window before the booking."""
    if said == "client" and (starts_at - cancelled_at).total_seconds() < late_hours * 3600:
        return "late"
    return said


def suggested_fee(pol: dict, reason: str, rate: Optional[float]) -> Optional[float]:
    if not rate or reason not in ("late", "no_show"):
        return None
    percent = pol["no_show_fee_percent"] if reason == "no_show" else pol["late_cancel_fee_percent"]
    return round(rate * percent / 100, 2) or None


def record(db, owner_id: int, client_id: int) -> dict:
    """How reliable a client has been: bookings, kept, no-shows, late and in-time cancellations."""
    r = db.execute("""
        SELECT COUNT(*) AS bookings,
               SUM(status = 'completed') AS kept,
               SUM(status = 'cancelled' AND cancel_reason = 'no_show') AS no_shows,
               SUM(status = 'cancelled' AND cancel_reason = 'late') AS late,
               SUM(status = 'cancelled' AND cancel_reason = 'client') AS cancelled,
               COALESCE(SUM(CASE WHEN status = 'cancelled' AND cancellation_fee > COALESCE(amount_paid, 0)
                                 THEN cancellation_fee - COALESCE(amount_paid, 0) END), 0) AS fees_owed
        FROM appointments WHERE owner_id = ? AND kind = 'client' AND (client_id = ? OR second_client_id = ?)
    """, (owner_id, client_id, client_id)).fetchone()
    return {k: (r[k] or 0) for k in r.keys()}


def warning(name: str, rec: dict) -> Optional[str]:
    parts = []
    if rec["no_shows"]:
        parts.append(f"didn't turn up {rec['no_shows']} time{'s' if rec['no_shows'] != 1 else ''}")
    if rec["late"]:
        parts.append(f"cancelled late {rec['late']} time{'s' if rec['late'] != 1 else ''}")
    if not parts:
        return None
    owed = f", and still owes ${rec['fees_owed']:.2f} in cancellation fees" if rec["fees_owed"] else ""
    return f"{name} {' and '.join(parts)} (of {rec['bookings']} bookings){owed}"


@router.get("")
def get_policy(request: Request):
    db = _get_db()
    try:
        return policy(db, request.state.user["id"])
    finally:
        db.close()


@router.put("")
def save_policy(body: PolicyIn, request: Request):
    for name in ("deposit_percent", "late_cancel_fee_percent", "no_show_fee_percent"):
        if not 0 <= getattr(body, name) <= 100:
            raise HTTPException(status_code=400, detail="Percentages must be between 0 and 100")
    if not 0 <= body.late_cancel_hours <= 24 * 14:
        raise HTTPException(status_code=400, detail="Late means somewhere between 0 hours and 2 weeks before")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        for key, value in body.model_dump().items():
            db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
                       "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, f"policy_{key}", str(value)))
        db.commit()
        return policy(db, owner)
    finally:
        db.close()


def now() -> datetime:
    return datetime.now(timezone.utc)
