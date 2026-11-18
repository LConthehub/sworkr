"""
Dates worth seeing on the calendar that aren't appointments or tasks: a document running out, a license due
for renewal, the next patch, ring, shot, implant or refill, an allowance due, and (with tax reminders on) the
estimated tax due dates, and public holidays for the country the person chose (worked out on this computer
by the `holidays` library: no holiday calendar is fetched from anyone). Their reminder tasks show up earlier;
these mark the day itself.

Meds marked discreet show only as "Health".
"""

import json
from datetime import date
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


@router.get("/api/calendar/dates")
def calendar_dates(request: Request, start: date = Query(...), end: date = Query(..., description="inclusive")):
    if (end - start).days > 400 or end < start:
        raise HTTPException(status_code=400, detail="Ask for at most about a year")
    owner = request.state.user["id"]
    lo, hi = start.isoformat(), end.isoformat()
    out = []
    db = _get_db()
    try:
        for r in db.execute("SELECT name, expires_on FROM documents WHERE owner_id = ? AND expires_on BETWEEN ? AND ?", (owner, lo, hi)):
            out.append({"date": r["expires_on"], "kind": "document", "label": f"{r['name']} runs out"})
        for r in db.execute("""SELECT c.label, c.renews_on, s.name FROM place_charges c JOIN income_sources s ON s.id = c.source_id
                               WHERE c.owner_id = ? AND c.renews_on BETWEEN ? AND ?""", (owner, lo, hi)):
            out.append({"date": r["renews_on"], "kind": "document", "label": f"Renew {r['label']} ({r['name']})"})
        for r in db.execute("""SELECT a.next_due, c.display_name, a.amount FROM arrangements a JOIN clients c ON c.id = a.client_id
                               WHERE a.owner_id = ? AND a.active = 1 AND a.next_due BETWEEN ? AND ?""", (owner, lo, hi)):
            out.append({"date": r["next_due"], "kind": "money", "label": f"Allowance due from {r['display_name']}"})

        import meds
        for r in db.execute("SELECT * FROM med_schedules WHERE owner_id = ? AND active = 1", (owner,)):
            med = dict(r)
            if med["method"] in ("pill", "daily"):
                st = meds.status(db, med)
                due = [(st["refill_on"], f"Refill {med['name']}")] if st["refill_on"] else []
            else:
                st = meds.status(db, med)
                due = [(st["next"]["on"], st["next"]["what"])] if st["next"] else []
                if st["refill_on"]:
                    due.append((st["refill_on"], f"Refill {med['name']}"))
            for day, what in due:
                if day and lo <= day <= hi:
                    out.append({"date": day, "kind": "health", "label": "Health" if med["discreet"] else what})

        row = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = 'tax_reminder_tasks'", (owner,)).fetchone()
        if row and row["value"] and json.loads(row["value"]):
            import taxes
            for year in range(start.year - 1, end.year + 1):
                for q in (1, 2, 3, 4):
                    due = taxes.due_date(year, q).isoformat()
                    if lo <= due <= hi:
                        out.append({"date": due, "kind": "money", "label": f"Estimated tax due ({year} Q{q})"})
        for day, name in holidays_between(db, owner, start, end):
            out.append({"date": day.isoformat(), "kind": "holiday", "label": name})
        out.sort(key=lambda m: (m["date"], m["kind"], m["label"]))
        return out
    finally:
        db.close()


# ==================== HOLIDAYS ====================

from pydantic import BaseModel  # noqa: E402


def _setting(db, owner: int, key: str) -> Optional[str]:
    r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = ?", (owner, key)).fetchone()
    return r["value"] if r else None


def holidays_between(db, owner: int, start: date, end: date):
    country = _setting(db, owner, "holiday_country")
    if not country:
        return []
    import holidays as hol
    try:
        days = hol.country_holidays(country, subdiv=_setting(db, owner, "holiday_subdiv") or None,
                                    years=range(start.year, end.year + 1))
    except (NotImplementedError, KeyError, ValueError):
        return []
    return sorted((d, n) for d, n in days.items() if start <= d <= end)


def _countries() -> list:
    """Country codes with their states or provinces. The browser turns the codes into names in the person's language."""
    import holidays as hol
    # The library lists each country under its 2-letter and its 3-letter code: the 2-letter one is enough.
    return [{"code": code, "subdivisions": list(subdivs)} for code, subdivs in sorted(hol.list_supported_countries().items())
            if len(code) == 2]


class HolidaySettings(BaseModel):
    country: Optional[str] = None
    subdivision: Optional[str] = None


@router.get("/api/holidays/settings")
def get_holiday_settings(request: Request):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return {"country": _setting(db, owner, "holiday_country"), "subdivision": _setting(db, owner, "holiday_subdiv"),
                "countries": _countries()}
    finally:
        db.close()


@router.put("/api/holidays/settings")
def save_holiday_settings(body: HolidaySettings, request: Request):
    import holidays as hol
    supported = hol.list_supported_countries()
    country = (body.country or "").strip().upper() or None
    subdiv = (body.subdivision or "").strip().upper() or None
    if country and country not in supported:
        raise HTTPException(status_code=400, detail="That country isn't in the holiday list")
    if subdiv and (not country or subdiv not in [s.upper() for s in supported[country]]):
        raise HTTPException(status_code=400, detail="That state or province isn't in the list for this country")
    owner = request.state.user["id"]
    db = _get_db()
    try:
        for key, value in (("holiday_country", country), ("holiday_subdiv", subdiv if country else None)):
            db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, ?) "
                       "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value", (owner, key, value))
        db.commit()
        return {"country": country, "subdivision": subdiv if country else None}
    finally:
        db.close()
