"""
Bank transactions through SimpleFIN Bridge (simplefin.org): an independent service the person signs up to and
connects their bank on. sworkr never sees the bank password.

1. The person pastes a setup token from SimpleFIN Bridge. It's a base64 "claim" address; claiming it once (a POST)
   returns an access address with its own login in it. That access address is sealed with vault.
2. Fetching asks the access address for recent transactions. Each lands here once (by the bank's id), as "new".
3. The person reviews them: add as an expense (with a category), add as income, or ignore. Nothing is added to
   their money by itself.
"""

import base64
import binascii
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import finance
import vault

router = APIRouter(prefix="/api/bank")
_get_db: Optional[Callable] = None
TRANSPORT: Optional[httpx.BaseTransport] = None   # tests put a pretend bridge here
SECRET = "simplefin_access"
FETCH_DAYS = 60


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(db, owner: int, key: str) -> Optional[str]:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (owner, key)).fetchone()
    return vault.unseal(key, r["value"]) if r else None


def _set(db, owner: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, key, vault.seal(key, value)))


def _client() -> httpx.Client:
    return httpx.Client(timeout=60, transport=TRANSPORT, follow_redirects=False)


def _split_access(access: str):
    """The access address carries its login (https://user:pass@host/path): split it out for basic auth."""
    p = urlsplit(access)
    if p.scheme != "https" or not p.hostname or not p.username:
        raise HTTPException(status_code=400, detail="SimpleFIN sent an access address sworkr doesn't understand")
    netloc = p.hostname + (f":{p.port}" if p.port else "")
    return urlunsplit(("https", netloc, p.path.rstrip("/"), "", "")), (p.username, p.password or "")


def _demo() -> bool:
    import demo
    return demo.ENABLED


@router.get("/status")
def status(request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        last = _get(db, owner, "simplefin_last_fetch")
        accounts = [dict(r) for r in db.execute(
            "SELECT DISTINCT account_id, account_name FROM bank_transactions WHERE owner_id = ? ORDER BY account_name", (owner,))]
        new = db.execute("SELECT COUNT(*) FROM bank_transactions WHERE owner_id = ? AND status = 'new'", (owner,)).fetchone()[0]
        return {"connected": bool(_get(db, owner, SECRET)), "last_fetch": last, "accounts": accounts, "new": new}
    finally:
        db.close()


class ConnectIn(BaseModel):
    setup_token: str


@router.post("/connect")
def connect(body: ConnectIn, request: Request):
    """Claim the setup token once and keep the access address it gives back (sealed)."""
    if _demo():
        raise HTTPException(status_code=403, detail="Some features are only available in the full version.")
    token = "".join(body.setup_token.split())
    try:
        claim = base64.b64decode(token + "=" * (-len(token) % 4), validate=False).decode().strip()
    except (binascii.Error, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="That doesn't look like a SimpleFIN setup token")
    if not claim.startswith("https://"):
        raise HTTPException(status_code=400, detail="That doesn't look like a SimpleFIN setup token")
    with _client() as http:
        try:
            r = http.post(claim, content=b"")
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Couldn't reach SimpleFIN")
    if r.status_code == 403:
        raise HTTPException(status_code=400, detail="That setup token was already used, or it's wrong. Make a new one in SimpleFIN Bridge.")
    if r.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"SimpleFIN answered {r.status_code}")
    access = r.text.strip()
    _split_access(access)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _set(db, owner, SECRET, access)
        db.commit()
    finally:
        db.close()
    return {"connected": True}


@router.delete("/connect", status_code=204)
def disconnect(request: Request):
    """Forget the access address. Transactions already brought in stay."""
    db = _get_db()
    try:
        _set(db, request.state.user["id"], SECRET, None)
        db.commit()
    finally:
        db.close()


def _amount(text) -> Optional[float]:
    try:
        return round(float(text), 2)
    except (TypeError, ValueError):
        return None


@router.post("/fetch")
def fetch(request: Request):
    """Bring in the last two months of transactions. Ones already here are skipped."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        access = _get(db, owner, SECRET)
        if not access:
            raise HTTPException(status_code=409, detail="Connect SimpleFIN first")
        base, auth = _split_access(access)
        start = int(time.time()) - FETCH_DAYS * 86400
        with _client() as http:
            try:
                r = http.get(f"{base}/accounts", params={"start-date": start}, auth=auth)
            except httpx.HTTPError:
                raise HTTPException(status_code=502, detail="Couldn't reach SimpleFIN")
        if r.status_code in (401, 403):
            raise HTTPException(status_code=400, detail="SimpleFIN refused the saved access: connect it again")
        if r.status_code >= 300:
            raise HTTPException(status_code=502, detail=f"SimpleFIN answered {r.status_code}")
        data = r.json()
        added = 0
        for acct in data.get("accounts", []):
            name = " · ".join(x for x in ((acct.get("org") or {}).get("name"), acct.get("name")) if x)[:120]
            for t in acct.get("transactions", []):
                amount = _amount(t.get("amount"))
                if amount is None or not t.get("id"):
                    continue
                posted = t.get("posted") or t.get("transacted_at")
                day = datetime.fromtimestamp(int(posted), timezone.utc).date().isoformat() if posted else None
                cur = db.execute("""
                    INSERT OR IGNORE INTO bank_transactions (owner_id, account_id, account_name, txn_id, day, amount, description,
                                                             pending, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
                """, (owner, str(acct.get("id"))[:120], name or None, str(t["id"])[:200], day, amount,
                      (t.get("description") or t.get("payee") or "")[:200] or None, int(bool(t.get("pending"))), _now()))
                added += cur.rowcount
        _set(db, owner, "simplefin_last_fetch", _now())
        db.commit()
        return {"added": added, "messages": [str(e)[:200] for e in data.get("errors", [])]}
    finally:
        db.close()


@router.get("/transactions")
def transactions(request: Request, status: str = Query("new")):
    if status not in ("new", "added", "ignored", "all"):
        raise HTTPException(status_code=400, detail="new, added, ignored or all")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        sql, args = "SELECT * FROM bank_transactions WHERE owner_id = ?", [owner]
        if status != "all":
            sql += " AND status = ?"
            args.append(status)
        rows = []
        for r in db.execute(sql + " ORDER BY day DESC, id DESC LIMIT 500", args):
            d = dict(r)
            d.pop("owner_id", None)
            d["pending"] = bool(d["pending"])
            rows.append(d)
        return rows
    finally:
        db.close()


class UseIn(BaseModel):
    action: str                         # expense, income, ignore, restore
    category: Optional[str] = None      # for an expense: a category key
    description: Optional[str] = None


@router.post("/transactions/{txn_row}")
def use_transaction(txn_row: int, body: UseIn, request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        t = db.execute("SELECT * FROM bank_transactions WHERE id = ? AND owner_id = ?", (txn_row, owner)).fetchone()
        if not t:
            raise HTTPException(status_code=404, detail="Transaction not found")
        what = (body.description or t["description"] or "Bank transaction").strip()[:200]
        when = f"{t['day'] or datetime.now(timezone.utc).date().isoformat()}T12:00:00+00:00"
        if body.action in ("expense", "income") and t["status"] != "new":
            raise HTTPException(status_code=400, detail="This one was already dealt with")
        if body.action == "expense":
            category = body.category or "other"
            if category not in finance.category_lookup(db, owner).values():
                raise HTTPException(status_code=400, detail="Unknown category")
            cur = db.execute("INSERT INTO expenses (description, amount, category, date, notes, owner_id, created_at, currency) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?, 'USD')", (what, abs(t["amount"]), category, when,
                                                                     f"From {t['account_name'] or 'the bank'}", owner, _now()))
            db.execute("UPDATE bank_transactions SET status = 'added', expense_id = ? WHERE id = ?", (cur.lastrowid, txn_row))
        elif body.action == "income":
            cur = db.execute("INSERT INTO income (date, description, kind, gross, fees, status, owner_id, created_at, updated_at, "
                             "payment_method) VALUES (?, ?, 'other', ?, 0, 'received', ?, ?, ?, 'Bank transfer')",
                             (when, what, abs(t["amount"]), owner, _now(), _now()))
            db.execute("UPDATE bank_transactions SET status = 'added', income_id = ? WHERE id = ?", (cur.lastrowid, txn_row))
        elif body.action == "ignore":
            db.execute("UPDATE bank_transactions SET status = 'ignored' WHERE id = ?", (txn_row,))
        elif body.action == "restore":
            if t["status"] != "ignored":
                raise HTTPException(status_code=400, detail="Only an ignored one can be brought back")
            db.execute("UPDATE bank_transactions SET status = 'new' WHERE id = ?", (txn_row,))
        else:
            raise HTTPException(status_code=400, detail="expense, income, ignore or restore")
        db.commit()
        return dict(db.execute("SELECT id, status, expense_id, income_id FROM bank_transactions WHERE id = ?", (txn_row,)).fetchone())
    finally:
        db.close()
