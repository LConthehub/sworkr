"""
Club pay: how a strip club (or any venue paid by the dance) pays you, which varies enormously from club to club.
One setting per club, saved on the workplace as JSON:

  status          "contractor" (you pay the house) or "employee" (they pay you a wage, often plus tips)
  hourly_wage     for employees
  house_fees      the fee by the time you arrive: [{"until": "21:00", "fee": 40}, {"until": null, "fee": 80}].
                  The first row whose time you arrived before applies; a row with no time is "after that".
  dance_price     what a dance costs the customer
  dance_house     what the house keeps of each dance ("dance_house_kind": "amount" or "percent")
  vip_house_percent  the house's share of VIP / private room money
  tip_outs        [{"label": "DJ", "kind": "amount" | "percent", "value": 20}]; a percent is of what you made
                  that shift before tip-outs

A shift (arrival time, hours, dances, VIP money, tips, fines) is worked out into a statement: what you made,
what the house and the staff took, and what you take home. The page logs it as income (gross and fees).
"""

import json
import re
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
_get_db: Optional[Callable] = None
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


class FeeRow(BaseModel):
    until: Optional[str] = None      # "HH:MM", or None for "any later time"
    fee: float = 0


class TipOut(BaseModel):
    label: str
    kind: str = "amount"             # amount | percent
    value: float = 0


class ClubPay(BaseModel):
    status: str = "contractor"
    hourly_wage: Optional[float] = None
    house_fees: List[FeeRow] = []
    dance_price: Optional[float] = None
    dance_house: Optional[float] = None
    dance_house_kind: str = "amount"
    vip_house_percent: Optional[float] = None
    tip_outs: List[TipOut] = []


class ShiftIn(BaseModel):
    arrived: Optional[str] = None    # "HH:MM", local time
    hours: float = 0
    dances: int = 0
    vip: float = 0                   # VIP / private room money you were paid, before the house's share
    tips: float = 0                  # stage and floor tips
    fines: float = 0                 # late, missed stage, no-show for a set...


def check(pay: ClubPay) -> ClubPay:
    if pay.status not in ("contractor", "employee"):
        raise HTTPException(status_code=400, detail="Contractor or employee")
    if pay.dance_house_kind not in ("amount", "percent"):
        raise HTTPException(status_code=400, detail="The house's cut of a dance is an amount or a percent")
    for v in (pay.hourly_wage, pay.dance_price, pay.dance_house, pay.vip_house_percent):
        if v is not None and not 0 <= v < 1e6:
            raise HTTPException(status_code=400, detail="Amounts must be 0 or more")
    if pay.vip_house_percent is not None and pay.vip_house_percent > 100:
        raise HTTPException(status_code=400, detail="The house's VIP share is at most 100%")
    for row in pay.house_fees:
        if row.until is not None and not TIME.match(row.until):
            raise HTTPException(status_code=400, detail="House fee times look like 21:00")
        if not 0 <= row.fee < 1e6:
            raise HTTPException(status_code=400, detail="House fees must be 0 or more")
    for t in pay.tip_outs:
        t.label = (t.label or "").strip()[:40] or "Tip-out"
        if t.kind not in ("amount", "percent") or not 0 <= t.value < 1e6 or (t.kind == "percent" and t.value > 100):
            raise HTTPException(status_code=400, detail="Each tip-out is an amount, or a percent up to 100")
    # Times in order, the open-ended row last.
    pay.house_fees.sort(key=lambda r: (r.until is None, r.until or ""))
    return pay


def house_fee(rows: List[FeeRow], arrived: Optional[str]) -> float:
    """The fee for arriving at `arrived`: the first row whose time you arrived before; else the open-ended
    row; with no arrival time, the first row (the earliest, usually cheapest)."""
    if not rows:
        return 0.0
    if not arrived:
        return rows[0].fee
    for row in rows:
        if row.until is None or arrived < row.until:
            return row.fee
    return rows[-1].fee      # arrived after every time, and no open-ended row: the last one


def shift_statement(pay: ClubPay, shift: ShiftIn) -> dict:
    r2 = lambda x: round(x + 0.0, 2)  # noqa: E731
    dances = max(shift.dances, 0)
    dance_money = dances * (pay.dance_price or 0)
    if pay.dance_house_kind == "percent":
        dance_house = dance_money * (pay.dance_house or 0) / 100
    else:
        dance_house = dances * (pay.dance_house or 0)
    vip_house = shift.vip * (pay.vip_house_percent or 0) / 100
    wage = (pay.hourly_wage or 0) * max(shift.hours, 0) if pay.status == "employee" else 0
    gross = dance_money + shift.vip + shift.tips + wage
    fee = house_fee(pay.house_fees, shift.arrived) if pay.status == "contractor" else 0
    before_tip_outs = gross - dance_house - vip_house - fee
    tip_outs = [{"label": t.label, "amount": r2(t.value if t.kind == "amount" else max(before_tip_outs, 0) * t.value / 100)}
                for t in pay.tip_outs]
    taken = dance_house + vip_house + fee + sum(t["amount"] for t in tip_outs) + shift.fines
    lines = [("House fee", fee), ("House's cut of dances", dance_house), ("House's VIP share", vip_house)]
    lines += [(f"Tip-out: {t['label']}", t["amount"]) for t in tip_outs]
    lines += [("Fines", shift.fines)]
    return {
        "dance_money": r2(dance_money), "vip": r2(shift.vip), "tips": r2(shift.tips), "wage": r2(wage),
        "gross": r2(gross),
        "taken": [{"label": label, "amount": r2(amount)} for label, amount in lines if amount],
        "fees": r2(taken),
        "take_home": r2(gross - taken),
    }


def load(row_value: Optional[str]) -> Optional[dict]:
    try:
        return json.loads(row_value) if row_value else None
    except ValueError:
        return None


def save(db, source_id: int, owner_id: int, body) -> None:
    """Save body.club_pay on a workplace, but only if the request included it."""
    if "club_pay" not in body.model_fields_set:
        return
    value = None
    if body.club_pay is not None:
        value = json.dumps(check(ClubPay(**body.club_pay)).model_dump())
    db.execute("UPDATE income_sources SET club_pay = ? WHERE id = ? AND owner_id = ?", (value, source_id, owner_id))


@router.post("/api/income-sources/{source_id}/club-shift")
def preview_shift(source_id: int, body: ShiftIn, request: Request):
    """Work out a shift at this club: what you made, what was taken, what you take home. Nothing is saved."""
    if body.arrived and not TIME.match(body.arrived):
        raise HTTPException(status_code=400, detail="The arrival time looks like 21:00")
    if min(body.hours, body.vip, body.tips, body.fines, body.dances) < 0:
        raise HTTPException(status_code=400, detail="Amounts must be 0 or more")
    db = _get_db()
    try:
        r = db.execute("SELECT club_pay FROM income_sources WHERE id = ? AND owner_id = ?",
                       (source_id, request.state.user["id"])).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Workplace not found")
        pay = ClubPay(**(load(r["club_pay"]) or {}))
        return shift_statement(pay, body)
    finally:
        db.close()
