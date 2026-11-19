"""
A quick daily wellness log (sleep, water, food, energy) and how it lines up with money.

Optional and private, like the period tracker. Each day has at most one entry. The comparison puts each logged
day next to what you earned that day, then shows the average for better and worse days (enough sleep or not,
enough water or not...). It's a pattern to notice, not a rule: few days logged means little to go on.

Apple Health can't be read by a website or a self-hosted app (only by an iPhone app); importing its export file
is a later step.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/wellness")
_get_db: Optional[Callable] = None


def setup(get_db: Callable):
    global _get_db
    _get_db = get_db


class DayIn(BaseModel):
    day: date
    sleep_hours: Optional[float] = None
    water_glasses: Optional[int] = None
    food: Optional[int] = None        # 1 (poor) .. 5 (great)
    energy: Optional[int] = None      # 1 .. 5
    note: Optional[str] = None


def _check(body: DayIn) -> DayIn:
    if body.sleep_hours is not None and not 0 <= body.sleep_hours <= 24:
        raise HTTPException(status_code=400, detail="Sleep is 0 to 24 hours")
    if body.water_glasses is not None and not 0 <= body.water_glasses <= 50:
        raise HTTPException(status_code=400, detail="Water is 0 to 50 glasses")
    for k in ("food", "energy"):
        v = getattr(body, k)
        if v is not None and not 1 <= v <= 5:
            raise HTTPException(status_code=400, detail="Food and energy are 1 to 5")
    body.note = (body.note or "").strip()[:500] or None
    return body


def _rows(db, owner: int, since: str) -> List[dict]:
    return [dict(r) for r in db.execute(
        "SELECT day, sleep_hours, water_glasses, food, energy, note FROM wellness_days WHERE owner_id = ? AND day >= ? ORDER BY day DESC",
        (owner, since))]


@router.get("")
def list_days(request: Request, days: int = Query(30, ge=1, le=730)):
    owner = request.state.user["id"]
    db = _get_db()
    try:
        return _rows(db, owner, (date.today() - timedelta(days=days - 1)).isoformat())
    finally:
        db.close()


@router.put("")
def save_day(body: DayIn, request: Request):
    _check(body)
    owner = request.state.user["id"]
    db = _get_db()
    try:
        db.execute("""
            INSERT INTO wellness_days (owner_id, day, sleep_hours, water_glasses, food, energy, note, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, day) DO UPDATE SET sleep_hours = excluded.sleep_hours, water_glasses = excluded.water_glasses,
                food = excluded.food, energy = excluded.energy, note = excluded.note, updated_at = excluded.updated_at
        """, (owner, body.day.isoformat(), body.sleep_hours, body.water_glasses, body.food, body.energy, body.note,
              datetime.now(timezone.utc).isoformat(timespec="seconds")))
        db.commit()
        return dict(db.execute(
            "SELECT day, sleep_hours, water_glasses, food, energy, note FROM wellness_days WHERE owner_id = ? AND day = ?",
            (owner, body.day.isoformat())).fetchone())
    finally:
        db.close()


def earned_by_day(db, owner: int, since: str) -> dict:
    """What came in each day: paid bookings plus other income received, after fees."""
    out = {}
    for r in db.execute("SELECT substr(scheduled_date, 1, 10) AS d, SUM(amount_paid) AS v FROM appointments "
                        "WHERE owner_id = ? AND kind = 'client' AND status != 'cancelled' AND scheduled_date >= ? GROUP BY d", (owner, since)):
        out[r["d"]] = out.get(r["d"], 0) + (r["v"] or 0)
    for r in db.execute("SELECT substr(date, 1, 10) AS d, SUM(gross - fees) AS v FROM income "
                        "WHERE owner_id = ? AND status = 'received' AND date >= ? GROUP BY d", (owner, since)):
        out[r["d"]] = out.get(r["d"], 0) + (r["v"] or 0)
    return out


RULES = [  # (title, field, test for "better", label better, label worse)
    ("Sleep", "sleep_hours", lambda v: v >= 7, "7 hours or more", "less than 7"),
    ("Water", "water_glasses", lambda v: v >= 6, "6 glasses or more", "fewer than 6"),
    ("Food", "food", lambda v: v >= 4, "ate well (4–5)", "ate less well (1–3)"),
    ("Energy", "energy", lambda v: v >= 4, "high energy (4–5)", "lower energy (1–3)"),
]


@router.get("/vs-money")
def versus_money(request: Request, days: int = Query(180, ge=14, le=730)):
    """Average earned on better days and worse days, for each thing logged."""
    owner = request.state.user["id"]
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    db = _get_db()
    try:
        logged = _rows(db, owner, since)
        earned = earned_by_day(db, owner, since)
        out = []
        for title, field, better, yes, no in RULES:
            groups = {"better": [], "worse": []}
            for d in logged:
                if d[field] is not None:
                    groups["better" if better(d[field]) else "worse"].append(earned.get(d["day"], 0))
            avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
            out.append({"title": title, "better_label": yes, "worse_label": no,
                        "better_days": len(groups["better"]), "worse_days": len(groups["worse"]),
                        "better_avg": avg(groups["better"]), "worse_avg": avg(groups["worse"])})
        return {"days_logged": len(logged), "comparisons": out}
    finally:
        db.close()


class OnOff(BaseModel):
    enabled: bool


@router.get("/settings")
def get_settings(request: Request):
    db = _get_db()
    try:
        r = db.execute("SELECT value FROM user_settings WHERE user_id = ? AND key = 'wellness_on'", (request.state.user["id"],)).fetchone()
        return {"enabled": bool(r and r["value"] == "1")}
    finally:
        db.close()


@router.put("/settings")
def save_settings(body: OnOff, request: Request):
    db = _get_db()
    try:
        db.execute("INSERT INTO user_settings (user_id, key, value) VALUES (?, 'wellness_on', ?) "
                   "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
                   (request.state.user["id"], "1" if body.enabled else "0"))
        db.commit()
        return {"enabled": body.enabled}
    finally:
        db.close()


# ==================== APPLE HEALTH IMPORT ====================
# The Health app's "Export All Health Data" gives export.zip with apple_health_export/export.xml in it.
# Only sleep and water are read. The file is read as it streams, so a large export doesn't fill memory.

import os  # noqa: E402
import tempfile  # noqa: E402
import zipfile  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402

MAX_EXPORT = 2 * 1024 ** 3        # 2 GB: years of a watch's data
ASLEEP = ("HKCategoryValueSleepAnalysisAsleep", "HKCategoryValueSleepAnalysisAsleepUnspecified",
          "HKCategoryValueSleepAnalysisAsleepCore", "HKCategoryValueSleepAnalysisAsleepDeep",
          "HKCategoryValueSleepAnalysisAsleepREM")
TO_ML = {"mL": 1, "ml": 1, "L": 1000, "l": 1000, "fl_oz_us": 29.5735, "fl_oz_imp": 28.4131, "cup_us": 236.588}


def _when(text: str) -> datetime:
    # "2026-05-01 07:12:00 -0700": the local wall-clock date is what counts.
    return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")


def read_health_export(stream) -> dict:
    """{day: {"sleep_hours": h, "water_glasses": n}} from an export.xml stream."""
    sleep, water = {}, {}            # sleep: day -> source -> hours (the longest source wins); water: day -> ml
    for _, el in ET.iterparse(stream, events=("end",)):
        if el.tag != "Record":
            if el.tag != "HealthData":
                el.clear()
            continue
        kind = el.get("type")
        try:
            if kind == "HKCategoryTypeIdentifierSleepAnalysis" and el.get("value") in ASLEEP:
                start, end = _when(el.get("startDate")), _when(el.get("endDate"))
                day = end.date().isoformat()
                src = el.get("sourceName") or "?"
                sleep.setdefault(day, {})[src] = sleep.get(day, {}).get(src, 0) + (end - start).total_seconds() / 3600
            elif kind == "HKQuantityTypeIdentifierDietaryWater":
                ml = float(el.get("value")) * TO_ML.get(el.get("unit"), 0)
                day = _when(el.get("startDate")).date().isoformat()
                water[day] = water.get(day, 0) + ml
        except (TypeError, ValueError):
            pass
        el.clear()
    out = {}
    for day, sources in sleep.items():
        hours = max(sources.values())
        if 0 < hours <= 24:
            out.setdefault(day, {})["sleep_hours"] = round(hours, 1)
    for day, ml in water.items():
        if ml > 0:
            out.setdefault(day, {})["water_glasses"] = min(50, round(ml / 250))
    return out


@router.post("/import-apple-health")
async def import_apple_health(request: Request):
    """The export.zip (or export.xml) as the request body. Fills in sleep and water; food and energy are left alone."""
    owner = request.state.user["id"]
    fd, path = tempfile.mkstemp(prefix="health-", suffix=".upload")
    size = 0
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_EXPORT:
                    raise HTTPException(status_code=413, detail="That file is too big (2 GB at most)")
                f.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="The file is empty")
        try:
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as z:
                    name = next((n for n in z.namelist() if n.endswith("export.xml") and "cda" not in n.lower()), None)
                    if not name:
                        raise HTTPException(status_code=400, detail="There's no export.xml in that zip: is it the Health app's export?")
                    with z.open(name) as stream:
                        days = read_health_export(stream)
            else:
                with open(path, "rb") as stream:
                    days = read_health_export(stream)
        except ET.ParseError:
            raise HTTPException(status_code=400, detail="That file couldn't be read as a Health export")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    db = _get_db()
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for day, v in days.items():
            db.execute("""
                INSERT INTO wellness_days (owner_id, day, sleep_hours, water_glasses, updated_at) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(owner_id, day) DO UPDATE SET
                    sleep_hours = COALESCE(excluded.sleep_hours, wellness_days.sleep_hours),
                    water_glasses = COALESCE(excluded.water_glasses, wellness_days.water_glasses),
                    updated_at = excluded.updated_at
            """, (owner, day, v.get("sleep_hours"), v.get("water_glasses"), now))
        db.commit()
        return {"days": len(days), "sleep_days": sum(1 for v in days.values() if "sleep_hours" in v),
                "water_days": sum(1 for v in days.values() if "water_glasses" in v)}
    finally:
        db.close()
