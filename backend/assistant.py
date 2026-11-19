"""
An optional assistant for questions about your own numbers: statistics and search, not writing.

It talks to a model you run yourself (LM Studio, llama.cpp's server, Ollama: all speak the OpenAI-style API).
Addresses on this computer or your own network are allowed as they are. Anything else (a cloud AI) needs an
explicit "yes, send my numbers out" tick, and it's off by default.

What the model gets: totals only (money by month, expenses by category, bookings, where clients came from, the
client base in counts). Never client names, contact details or notes. It's told to answer from those numbers
alone, to say when they don't hold the answer, and not to write messages, captions or posts: the creative part
stays the worker's.
"""

import ipaddress
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import vault

log = logging.getLogger("sworkr.assistant")
router = APIRouter(prefix="/api/assistant")
_get_db: Optional[Callable] = None
TRANSPORT: Optional[httpx.BaseTransport] = None   # tests put a pretend model here
TIMEOUT = 120
DEFAULT_URL = "http://host.docker.internal:1234/v1"   # LM Studio on the computer running Docker
SECRET = "ai_key"

SYSTEM = (
    "You help a self-employed worker understand their own business numbers. Answer ONLY from the JSON facts you "
    "are given. If the facts don't contain the answer, say so plainly. Be brief and concrete, with the numbers. "
    "Do not write messages, captions, posts, bios or replies for anyone, even if asked: say that's theirs to write. "
    "Money is in US dollars unless the facts say otherwise."
)


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


def _get(db, owner: int, key: str) -> Optional[str]:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (owner, key)).fetchone()
    return vault.unseal(key, r["value"]) if r else None


def _set(db, owner: int, key: str, value: Optional[str]):
    db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, key, vault.seal(key, value)))


def is_local(url: str) -> bool:
    """This computer, your own network, or your Tailscale network."""
    host = (urlsplit(url).hostname or "").lower()
    if host in ("localhost", "host.docker.internal") or host.endswith((".local", ".lan", ".home.arpa", ".ts.net", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or (ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"))


def load_settings(db, owner: int) -> dict:
    return {
        "enabled": _get(db, owner, "ai_enabled") == "1",
        "url": _get(db, owner, "ai_url") or DEFAULT_URL,
        "model": _get(db, owner, "ai_model") or "",
        "cloud_ok": _get(db, owner, "ai_cloud_ok") == "1",
        "key_saved": bool(_get(db, owner, SECRET)),
    }


class SettingsIn(BaseModel):
    enabled: bool = False
    url: str = DEFAULT_URL
    model: str = ""
    cloud_ok: bool = False            # yes, I know my numbers leave this computer
    key: Optional[str] = None         # blank: keep the saved one
    clear_key: bool = False


def _demo() -> bool:
    import demo
    return demo.ENABLED


@router.get("/settings")
def get_settings(request: Request):
    db = _get_db()
    try:
        return {**load_settings(db, request.state.user["id"]), "local": None}
    finally:
        db.close()


@router.put("/settings")
def save_settings(body: SettingsIn, request: Request):
    if _demo():
        raise HTTPException(status_code=403, detail="Some features are only available in the full version.")
    url = body.url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="The address starts with http:// or https://")
    if not is_local(url) and not body.cloud_ok:
        raise HTTPException(status_code=400, detail="That address isn't on your computer or network. Tick the box to allow "
                                                    "a cloud AI, knowing your numbers will leave this computer.")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        _set(db, owner, "ai_enabled", "1" if body.enabled else "0")
        _set(db, owner, "ai_url", url)
        _set(db, owner, "ai_model", body.model.strip()[:120])
        _set(db, owner, "ai_cloud_ok", "1" if body.cloud_ok else "0")
        if body.clear_key:
            _set(db, owner, SECRET, None)
        elif (body.key or "").strip():
            _set(db, owner, SECRET, body.key.strip())
        db.commit()
        return load_settings(db, owner)
    finally:
        db.close()


def _client(db, owner: int) -> httpx.Client:
    key = _get(db, owner, SECRET)
    return httpx.Client(timeout=TIMEOUT, transport=TRANSPORT, follow_redirects=False,
                        headers={"Authorization": f"Bearer {key}"} if key else {})


@router.post("/test")
def test(request: Request):
    """Reach the model server and list its models."""
    owner = request.state.user["id"]
    db = _get_db()
    try:
        s = load_settings(db, owner)
        with _client(db, owner) as http:
            try:
                r = http.get(f"{s['url']}/models")
            except httpx.HTTPError:
                raise HTTPException(status_code=502, detail=f"Couldn't reach {s['url']}. Is the model server running?")
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"The model server answered {r.status_code}")
        models = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
        return {"models": models}
    finally:
        db.close()


# ==================== THE FACTS ====================

def _months_back(today: date, n: int) -> str:
    y, m = today.year, today.month - n
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}-01"


def facts(db, owner: int, today: Optional[date] = None) -> dict:
    """Totals only: no names, contact details or notes."""
    today = today or date.today()
    since = _months_back(today, 11)
    by_month = {}
    for r in db.execute("SELECT substr(scheduled_date, 1, 7) AS m, COUNT(*) AS n, COALESCE(SUM(amount_paid), 0) AS paid "
                        "FROM appointments WHERE owner_id = ? AND kind = 'client' AND status != 'cancelled' "
                        "AND scheduled_date >= ? GROUP BY m", (owner, since)):
        by_month.setdefault(r["m"], {})["bookings"] = r["n"]
        by_month[r["m"]]["booking_income"] = round(r["paid"], 2)
    for r in db.execute("SELECT substr(date, 1, 7) AS m, COALESCE(SUM(gross - fees), 0) AS kept FROM income "
                        "WHERE owner_id = ? AND status = 'received' AND date >= ? GROUP BY m", (owner, since)):
        by_month.setdefault(r["m"], {})["other_income"] = round(r["kept"], 2)
    for r in db.execute("SELECT substr(date, 1, 7) AS m, COALESCE(SUM(amount), 0) AS spent FROM expenses "
                        "WHERE owner_id = ? AND date >= ? GROUP BY m", (owner, since)):
        by_month.setdefault(r["m"], {})["expenses"] = round(r["spent"], 2)
    year_start = f"{today.year}-01-01"
    categories = {r["label"] or r["category"]: round(r["total"], 2) for r in db.execute(
        "SELECT e.category, c.label, SUM(e.amount) AS total FROM expenses e "
        "LEFT JOIN expense_categories c ON c.owner_id = e.owner_id AND c.key = e.category "
        "WHERE e.owner_id = ? AND e.date >= ? GROUP BY e.category ORDER BY total DESC LIMIT 20", (owner, year_start))}
    sources = {r["found_via"]: r["n"] for r in db.execute(
        "SELECT COALESCE(found_via, 'not noted') AS found_via, COUNT(*) AS n FROM clients WHERE owner_id = ? AND role = 'client' "
        "GROUP BY found_via ORDER BY n DESC LIMIT 12", (owner,))}
    services = {r["service_type"]: {"bookings": r["n"], "paid": round(r["paid"], 2)} for r in db.execute(
        "SELECT service_type, COUNT(*) AS n, COALESCE(SUM(amount_paid), 0) AS paid FROM appointments "
        "WHERE owner_id = ? AND kind = 'client' AND status != 'cancelled' AND scheduled_date >= ? "
        "GROUP BY service_type ORDER BY paid DESC LIMIT 12", (owner, since))}
    clients = db.execute("SELECT COUNT(*) FROM clients WHERE owner_id = ? AND role = 'client' AND is_active = 1", (owner,)).fetchone()[0]
    week = (today + timedelta(days=7)).isoformat()
    ahead = db.execute("SELECT COUNT(*) FROM appointments WHERE owner_id = ? AND kind = 'client' AND status = 'scheduled' "
                       "AND scheduled_date >= ? AND scheduled_date < ?", (owner, today.isoformat(), week)).fetchone()[0]
    return {
        "today": today.isoformat(),
        "by_month_last_12": dict(sorted(by_month.items())),
        "expenses_by_category_this_year": categories,
        "bookings_by_service_last_12_months": services,
        "clients_by_how_they_found_you": sources,
        "active_clients": clients,
        "bookings_in_the_next_7_days": ahead,
    }


class AskIn(BaseModel):
    question: str


@router.post("/ask")
def ask(body: AskIn, request: Request):
    question = (body.question or "").strip()[:1000]
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        s = load_settings(db, owner)
        if not s["enabled"]:
            raise HTTPException(status_code=409, detail="Turn the assistant on in Settings → Connections → Assistant")
        if not is_local(s["url"]) and not s["cloud_ok"]:
            raise HTTPException(status_code=409, detail="The assistant's address isn't local, and a cloud AI isn't allowed")
        data = facts(db, owner)
        payload = {"messages": [{"role": "system", "content": SYSTEM},
                                {"role": "user", "content": f"Facts:\n{json.dumps(data)}\n\nQuestion: {question}"}],
                   "temperature": 0.2}
        if s["model"]:
            payload["model"] = s["model"]
        with _client(db, owner) as http:
            try:
                r = http.post(f"{s['url']}/chat/completions", json=payload)
            except httpx.HTTPError:
                raise HTTPException(status_code=502, detail="Couldn't reach the model server. Is it running?")
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"The model server answered {r.status_code}")
        try:
            answer = r.json()["choices"][0]["message"]["content"].strip()
        except (ValueError, KeyError, IndexError, TypeError):
            raise HTTPException(status_code=502, detail="The model server sent something unexpected")
        return {"answer": answer, "facts": data}
    finally:
        db.close()
