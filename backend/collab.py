"""
Working with partners (other workers), kept privately in your own login: nothing here is shared with anyone.

- A booking, an income or an expense can be split with partners. Each partner gets a percentage or a fixed
  amount, worked out on the money actually received (or paid, for a cost). Whoever handled the money (you, or
  one of the partners) is recorded, so sworkr knows who owes whom.
- Split agreements are reusable defaults ("Jade & me: bookings 50/50, content 60/40, costs 50/50").
- Each partner has a running balance: positive means they owe you, negative means you owe them. Settle-up
  payments bring it back to zero.
- Your own figures (Money, Compare, goals) count only your share.
"""

import datetime as dt
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()
_get_db: Optional[Callable] = None

RECORD_TYPES = ("appointment", "income", "expense")
TABLES = {"appointment": "appointments", "income": "income", "expense": "expenses"}
ROLES = ("client", "partner", "crew", "other")


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _owner(request: Request) -> int:
    return request.state.user["id"]


# ==================== SHARES (used by the money figures) ====================

def partner_share_sql(record_type: str, base: str, record_id: str) -> str:
    """SQL for the total that partners get from one record, worked out on `base` (money received or paid)."""
    # Never more than the money itself: shares that add up to more are scaled down (see party_shares).
    total = (f"(SELECT SUM(CASE WHEN s.share_type = 'percent' THEN s.share_value / 100.0 * ({base}) "
             f"ELSE MIN(s.share_value, ({base})) END) FROM splits s "
             f"WHERE s.record_type = '{record_type}' AND s.record_id = {record_id})")
    return f"IFNULL(MAX(MIN({total}, ({base})), 0), 0)"


def partner_names_sql(record_type: str, record_id: str) -> str:
    return (f"(SELECT GROUP_CONCAT(pc.display_name, ', ') FROM splits s JOIN clients pc ON pc.id = s.partner_id "
            f"WHERE s.record_type = '{record_type}' AND s.record_id = {record_id})")


def share_of(base: float, share_type: str, value: float) -> float:
    base = max(base or 0, 0)
    return value / 100.0 * base if share_type == "percent" else min(value, base)


def party_shares(base: float, parties) -> Dict[int, float]:
    """Each partner's share of `base`. A percentage and fixed amounts can add up to more than the money received
    (50% + $500 of $800); then every share is scaled down in proportion, so together they're exactly the money
    and your own share is 0, never negative."""
    base = max(base or 0, 0)
    shares = {p["partner_id"]: share_of(base, p["share_type"], p["share_value"]) for p in parties}
    total = sum(shares.values())
    if total > base and total > 0:
        shares = {k: v * base / total for k, v in shares.items()}
    return shares


def forget(db, record_type: str, record_id: int):
    """A booking, income or expense was deleted: its split goes too."""
    db.execute("DELETE FROM splits WHERE record_type = ? AND record_id = ?", (record_type, record_id))
    db.execute("DELETE FROM split_records WHERE record_type = ? AND record_id = ?", (record_type, record_id))


def copy_split(db, owner_id: int, from_ids: List[int], to_ids: List[int]):
    """Generated expenses (a tour's daily room & board) are made again when the tour changes: keep their split."""
    template = None
    for expense_id in from_ids:
        head = db.execute("SELECT * FROM split_records WHERE record_type = 'expense' AND record_id = ?", (expense_id,)).fetchone()
        if head:
            parties = db.execute("SELECT partner_id, share_type, share_value FROM splits "
                                 "WHERE record_type = 'expense' AND record_id = ?", (expense_id,)).fetchall()
            template = (dict(head), [dict(p) for p in parties])
            break
    for expense_id in from_ids:
        forget(db, "expense", expense_id)
    if not template:
        return
    head, parties = template
    for expense_id in to_ids:
        _write(db, owner_id, "expense", expense_id, head["handled_by"], head["agreement_id"], parties)


def _write(db, owner_id, record_type, record_id, handled_by, agreement_id, parties):
    forget(db, record_type, record_id)
    if not parties:
        return
    db.execute("INSERT INTO split_records (owner_id, record_type, record_id, handled_by, agreement_id) VALUES (?, ?, ?, ?, ?)",
               (owner_id, record_type, record_id, handled_by, agreement_id))
    for p in parties:
        db.execute("INSERT INTO splits (owner_id, record_type, record_id, partner_id, share_type, share_value) "
                   "VALUES (?, ?, ?, ?, ?, ?)", (owner_id, record_type, record_id, p["partner_id"], p["share_type"], p["share_value"]))


# ==================== SPLITS ON A RECORD ====================

class Party(BaseModel):
    partner_id: int
    share_type: str = "percent"     # percent | amount
    share_value: float


class SplitIn(BaseModel):
    handled_by: Optional[int] = None    # who collected the money (or paid the cost); None = you
    agreement_id: Optional[int] = None
    parties: List[Party] = []


def _record(db, record_type: str, record_id: int, owner_id: int) -> Optional[dict]:
    if record_type not in RECORD_TYPES:
        raise HTTPException(status_code=404, detail="Not found")
    row = db.execute(f"SELECT * FROM {TABLES[record_type]} WHERE id = ? AND owner_id = ?", (record_id, owner_id)).fetchone()
    return dict(row) if row else None


def _base(record_type: str, r: dict) -> float:
    """The money a split is worked out on: received for a booking or income, paid for an expense."""
    if record_type == "appointment":
        return r.get("amount_paid") or 0
    if record_type == "income":
        return (r["gross"] - r["fees"]) if r["status"] == "received" else 0
    return r["amount"]


def _owned_contacts(db, owner_id: int, ids) -> set:
    ids = list(set(ids))
    if not ids:
        return set()
    return {r[0] for r in db.execute(
        f"SELECT id FROM clients WHERE owner_id = ? AND id IN ({', '.join('?' * len(ids))})", (owner_id, *ids))}


def split_view(db, record_type: str, record_id: int, owner_id: int) -> dict:
    record = _record(db, record_type, record_id, owner_id)
    head = db.execute("SELECT handled_by, agreement_id FROM split_records WHERE record_type = ? AND record_id = ?",
                      (record_type, record_id)).fetchone()
    parties = [dict(r) for r in db.execute("""
        SELECT s.partner_id, s.share_type, s.share_value, c.display_name AS partner_name
        FROM splits s JOIN clients c ON c.id = s.partner_id
        WHERE s.record_type = ? AND s.record_id = ? ORDER BY s.id
    """, (record_type, record_id))]
    base = _base(record_type, record) if record else 0
    shares = party_shares(base, parties)
    asked = sum(share_of(base, p["share_type"], p["share_value"]) for p in parties)
    for p in parties:
        p["amount"] = round(shares[p["partner_id"]], 2)
    return {"record_type": record_type, "record_id": record_id, "handled_by": head["handled_by"] if head else None,
            "agreement_id": head["agreement_id"] if head else None, "parties": parties, "base": round(base, 2),
            "mine": round(max(base, 0) - sum(shares.values()), 2),
            # The shares added up to more than the money, so each was scaled down to fit.
            "scaled_down": asked > max(base, 0) + 0.005}


@router.get("/api/splits/{record_type}/{record_id}")
def get_split(record_type: str, record_id: int, request: Request):
    db = _get_db()
    try:
        if not _record(db, record_type, record_id, _owner(request)):
            raise HTTPException(status_code=404, detail="Not found")
        return split_view(db, record_type, record_id, _owner(request))
    finally:
        db.close()


@router.put("/api/splits/{record_type}/{record_id}")
def save_split(record_type: str, record_id: int, body: SplitIn, request: Request):
    """Set (or, with no parties, remove) who shares this booking, income or cost, and who handled the money."""
    owner = _owner(request)
    db = _get_db()
    try:
        if not _record(db, record_type, record_id, owner):
            raise HTTPException(status_code=404, detail="Not found")
        ids = [p.partner_id for p in body.parties]
        if len(ids) != len(set(ids)):
            raise HTTPException(status_code=400, detail="Each collaborator can only be listed once")
        if _owned_contacts(db, owner, ids) != set(ids):
            raise HTTPException(status_code=400, detail="That collaborator doesn't exist")
        for p in body.parties:
            if p.share_type not in ("percent", "amount") or not (0 <= p.share_value < float("inf")):
                raise HTTPException(status_code=400, detail="Each share is a percentage or an amount of 0 or more")
        if sum(p.share_value for p in body.parties if p.share_type == "percent") > 100.0001:
            raise HTTPException(status_code=400, detail="The collaborators' percentages add up to more than 100%")
        if body.handled_by is not None and body.handled_by not in ids:
            raise HTTPException(status_code=400, detail="Whoever handled the money must be one of the collaborators (or you)")
        if body.agreement_id is not None and not db.execute(
                "SELECT 1 FROM split_agreements WHERE id = ? AND owner_id = ?", (body.agreement_id, owner)).fetchone():
            raise HTTPException(status_code=400, detail="That agreement doesn't exist")
        _write(db, owner, record_type, record_id, body.handled_by, body.agreement_id, [p.model_dump() for p in body.parties])
        db.commit()
        return split_view(db, record_type, record_id, owner)
    finally:
        db.close()


# ==================== AGREEMENTS ====================

class AgreementParty(BaseModel):
    partner_id: int
    booking_pct: float = 0
    content_pct: float = 0
    costs_pct: float = 0


class AgreementIn(BaseModel):
    name: str
    notes: Optional[str] = None
    active: bool = True
    parties: List[AgreementParty]


def _agreements(db, owner_id: int, agreement_id: Optional[int] = None) -> List[dict]:
    sql = "SELECT * FROM split_agreements WHERE owner_id = ?"
    params = [owner_id]
    if agreement_id is not None:
        sql += " AND id = ?"
        params.append(agreement_id)
    out = []
    for a in db.execute(sql + " ORDER BY active DESC, name COLLATE NOCASE", params):
        parties = [dict(r) for r in db.execute("""
            SELECT p.partner_id, p.booking_pct, p.content_pct, p.costs_pct, c.display_name AS partner_name
            FROM agreement_parties p JOIN clients c ON c.id = p.partner_id WHERE p.agreement_id = ? ORDER BY c.display_name
        """, (a["id"],))]
        mine = {k: round(100 - sum(p[f"{k}_pct"] for p in parties), 2) for k in ("booking", "content", "costs")}
        out.append({**dict(a), "active": bool(a["active"]), "parties": parties, "mine": mine})
    return out


def _check_agreement(db, owner_id: int, body: AgreementIn):
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Give the agreement a name")
    if not body.parties:
        raise HTTPException(status_code=400, detail="Add at least one collaborator")
    ids = [p.partner_id for p in body.parties]
    if len(ids) != len(set(ids)) or _owned_contacts(db, owner_id, ids) != set(ids):
        raise HTTPException(status_code=400, detail="Each collaborator must exist and be listed once")
    for k in ("booking_pct", "content_pct", "costs_pct"):
        values = [getattr(p, k) for p in body.parties]
        if any(not 0 <= v <= 100 for v in values) or sum(values) > 100.0001:
            raise HTTPException(status_code=400, detail="Collaborators' shares must be 0–100% and add up to 100% at most")


def _save_parties(db, agreement_id: int, parties: List[AgreementParty]):
    db.execute("DELETE FROM agreement_parties WHERE agreement_id = ?", (agreement_id,))
    for p in parties:
        db.execute("INSERT INTO agreement_parties (agreement_id, partner_id, booking_pct, content_pct, costs_pct) VALUES (?, ?, ?, ?, ?)",
                   (agreement_id, p.partner_id, p.booking_pct, p.content_pct, p.costs_pct))


@router.get("/api/agreements")
def list_agreements(request: Request):
    db = _get_db()
    try:
        return _agreements(db, _owner(request))
    finally:
        db.close()


@router.post("/api/agreements", status_code=201)
def create_agreement(body: AgreementIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        _check_agreement(db, owner, body)
        now = _now()
        cur = db.execute("INSERT INTO split_agreements (owner_id, name, notes, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                         (owner, body.name.strip(), (body.notes or "").strip() or None, int(body.active), now, now))
        _save_parties(db, cur.lastrowid, body.parties)
        db.commit()
        return _agreements(db, owner, cur.lastrowid)[0]
    finally:
        db.close()


@router.put("/api/agreements/{agreement_id}")
def update_agreement(agreement_id: int, body: AgreementIn, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        if not _agreements(db, owner, agreement_id):
            raise HTTPException(status_code=404, detail="Agreement not found")
        _check_agreement(db, owner, body)
        db.execute("UPDATE split_agreements SET name = ?, notes = ?, active = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                   (body.name.strip(), (body.notes or "").strip() or None, int(body.active), _now(), agreement_id, owner))
        _save_parties(db, agreement_id, body.parties)
        db.commit()
        return _agreements(db, owner, agreement_id)[0]
    finally:
        db.close()


@router.delete("/api/agreements/{agreement_id}", status_code=204)
def delete_agreement(agreement_id: int, request: Request):
    """Splits already made with it stay as they are."""
    owner = _owner(request)
    db = _get_db()
    try:
        if _agreements(db, owner, agreement_id):
            db.execute("UPDATE split_records SET agreement_id = NULL WHERE agreement_id = ? AND owner_id = ?", (agreement_id, owner))
            db.execute("DELETE FROM split_agreements WHERE id = ? AND owner_id = ?", (agreement_id, owner))
            db.commit()
    finally:
        db.close()


# ==================== WHO OWES WHOM ====================

def _describe(db, record_type: str, r: dict) -> str:
    if record_type == "appointment":
        who = db.execute("SELECT display_name FROM clients WHERE id = ?", (r["client_id"],)).fetchone() if r.get("client_id") else None
        return f"{r['service_type']}" + (f" with {who[0]}" if who else "")
    if record_type == "income":
        source = db.execute("SELECT name FROM income_sources WHERE id = ?", (r["source_id"],)).fetchone() if r.get("source_id") else None
        return (r.get("description") or r["kind"].capitalize()) + (f" ({source[0]})" if source else "")
    return r["description"]


def ledger(db, owner_id: int, partner_id: int) -> dict:
    """Everything shared with one partner, what each item means for who owes whom, and the balance.
    A positive amount or balance means the partner owes you; negative means you owe them."""
    entries = []
    for head in db.execute("""
        SELECT DISTINCT r.* FROM split_records r JOIN splits s ON s.record_type = r.record_type AND s.record_id = r.record_id
        WHERE r.owner_id = ? AND s.partner_id = ?
    """, (owner_id, partner_id)).fetchall():
        record = _record(db, head["record_type"], head["record_id"], owner_id)
        if not record:
            continue
        kind = head["record_type"]
        base = _base(kind, record)
        parties = db.execute("SELECT partner_id, share_type, share_value FROM splits WHERE record_type = ? AND record_id = ?",
                             (kind, head["record_id"])).fetchall()
        shares = party_shares(base, parties)
        mine = base - sum(shares.values())
        theirs = shares.get(partner_id, 0)
        handled = head["handled_by"]
        if kind == "expense":
            effect = theirs if handled is None else (-mine if handled == partner_id else 0)
            why = ("You paid; their share" if handled is None else "They paid; your share" if handled == partner_id
                   else "Paid by another collaborator")
        else:
            effect = -theirs if handled is None else (mine if handled == partner_id else 0)
            why = ("You were paid; their share" if handled is None else "They were paid; your share" if handled == partner_id
                   else "Paid to another collaborator")
        when = record.get("scheduled_date") or record.get("date")
        entries.append({"type": kind, "id": head["record_id"], "date": when, "description": _describe(db, kind, record),
                        "total": round(base, 2), "their_share": round(theirs, 2), "your_share": round(mine, 2),
                        "effect": round(effect, 2), "why": why, "pending": kind == "income" and record["status"] != "received"})
    for s in db.execute("SELECT * FROM settlements WHERE owner_id = ? AND partner_id = ?", (owner_id, partner_id)):
        effect = s["amount"] if s["direction"] == "paid_them" else -s["amount"]
        entries.append({"type": "settlement", "id": s["id"], "date": s["date"], "description": s["note"] or "Settled up",
                        "total": s["amount"], "their_share": None, "your_share": None, "effect": round(effect, 2),
                        "why": "You paid them" if s["direction"] == "paid_them" else "They paid you", "pending": False})
    entries.sort(key=lambda e: e["date"] or "", reverse=True)
    return {"balance": round(sum(e["effect"] for e in entries), 2), "entries": entries}


@router.get("/api/partners")
def list_partners(request: Request):
    """Your partners (contacts with the partner role, or anyone you've split with) and where you stand with each."""
    owner = _owner(request)
    db = _get_db()
    try:
        rows = db.execute("""
            SELECT id, display_name, role, industry FROM clients
            WHERE owner_id = ? AND (role = 'partner' OR id IN (SELECT partner_id FROM splits WHERE owner_id = ?)
                                    OR id IN (SELECT partner_id FROM settlements WHERE owner_id = ?))
            ORDER BY display_name COLLATE NOCASE
        """, (owner, owner, owner)).fetchall()
        out = []
        for r in rows:
            book = ledger(db, owner, r["id"])
            out.append({**dict(r), "balance": book["balance"], "shared": sum(1 for e in book["entries"] if e["type"] != "settlement")})
        return out
    finally:
        db.close()


@router.get("/api/partners/{partner_id}/ledger")
def partner_ledger(partner_id: int, request: Request):
    owner = _owner(request)
    db = _get_db()
    try:
        partner = db.execute("SELECT id, display_name FROM clients WHERE id = ? AND owner_id = ?", (partner_id, owner)).fetchone()
        if not partner:
            raise HTTPException(status_code=404, detail="Collaborator not found")
        return {"partner": dict(partner), **ledger(db, owner, partner_id)}
    finally:
        db.close()


class SettlementIn(BaseModel):
    amount: float
    direction: str            # paid_them | they_paid
    date: Optional[dt.date] = None   # (dt.date: a field called `date` would hide the type)
    note: Optional[str] = None


@router.post("/api/partners/{partner_id}/settlements", status_code=201)
def add_settlement(partner_id: int, body: SettlementIn, request: Request):
    owner = _owner(request)
    if body.direction not in ("paid_them", "they_paid"):
        raise HTTPException(status_code=400, detail="direction must be paid_them or they_paid")
    if not (0 < body.amount < float("inf")):
        raise HTTPException(status_code=400, detail="Enter an amount")
    db = _get_db()
    try:
        if not db.execute("SELECT 1 FROM clients WHERE id = ? AND owner_id = ?", (partner_id, owner)).fetchone():
            raise HTTPException(status_code=404, detail="Collaborator not found")
        db.execute("INSERT INTO settlements (owner_id, partner_id, date, amount, direction, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (owner, partner_id, (body.date or date.today()).isoformat(), round(body.amount, 2), body.direction,
                    (body.note or "").strip() or None, _now()))
        db.commit()
        return ledger(db, owner, partner_id)
    finally:
        db.close()


@router.delete("/api/settlements/{settlement_id}", status_code=204)
def delete_settlement(settlement_id: int, request: Request):
    db = _get_db()
    try:
        db.execute("DELETE FROM settlements WHERE id = ? AND owner_id = ?", (settlement_id, _owner(request)))
        db.commit()
    finally:
        db.close()
