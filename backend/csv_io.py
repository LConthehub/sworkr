"""
CSV export and import for clients and expenses.

Export:  GET  /api/csv/clients     GET  /api/csv/expenses
Import:  POST /api/csv/clients     POST /api/csv/expenses   (the CSV file is the request body)

Files open in Excel, Numbers and Google Sheets. An exported file can be edited and imported again:
- Clients are matched by `id`, then by email. A match is updated; anything else is added.
- Expenses are matched by `id`. Without an id, a row identical to an existing expense
  (same date, description, amount, category and client) is skipped instead of added twice.
An import is all or nothing: if any row has a problem, nothing is saved and every problem is listed.
"""

import csv
import io
import re

import contacts
import marketing
import finance
from datetime import date, datetime, timedelta, timezone
from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_ERRORS_SHOWN = 20

CLIENT_COLUMNS = ["id", "name", "email", "phone", "tags", "notes", "active", "created",
                  "screening", "do_not_see", "do_not_see_reason", "references", "screening_notes",
                  "birthday", "drinks", "food", "handles", "industry", "shown_as", "role", "found_via"]
SCREENING = ("unscreened", "pending", "verified", "declined")
EXPENSE_COLUMNS = ["id", "date", "description", "amount", "category", "client", "client_email", "notes"]

# Other names people (or other apps) use for the same columns.
ALIASES = {
    "contact_phone": "phone", "telephone": "phone", "mobile": "phone", "phone number": "phone",
    "e-mail": "email", "email address": "email",
    "bio": "notes", "note": "notes", "comments": "notes",
    "is_active": "active", "status": "active",
    "full name": "name",
    "client_name": "client", "client email": "client_email",
    "cost": "amount", "total": "amount", "price": "amount",
    "created_at": "created",
    "screening_status": "screening", "screened": "screening",
    "dns": "do_not_see", "do not see": "do_not_see", "blacklist": "do_not_see", "blacklisted": "do_not_see",
    "do not see reason": "do_not_see_reason", "reference": "references", "refs": "references",
    "screening notes": "screening_notes",
    "date of birth": "birthday", "dob": "birthday", "drink": "drinks", "drink_preferences": "drinks",
    "food_preferences": "food",
    "social": "handles", "social media": "handles", "socials": "handles", "handle": "handles",
    "found via": "found_via", "source": "found_via", "referred by": "found_via", "work": "industry", "job": "industry", "occupation": "industry", "display_name": "shown_as", "known as": "shown_as",
}

_get_db: Optional[Callable] = None
_after_client_import: Callable = lambda client_ids: None


def setup(get_db: Callable, after_client_import: Callable = None):
    global _get_db, _after_client_import
    _get_db = get_db
    if after_client_import:
        _after_client_import = after_client_import


router = APIRouter(prefix="/api/csv")


class ImportProblems(Exception):
    def __init__(self, errors: List[str]):
        self.errors = errors


# ==================== HELPERS ====================

def _safe_cell(value) -> str:
    """Spreadsheets run cells that start with = + - @ as formulas. Neutralize text that does."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _csv_response(rows: List[list], header: List[str], name: str) -> Response:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    stamp = datetime.now().strftime("%Y-%m-%d")
    # The byte-order mark makes Excel read accents and other non-English letters correctly.
    return Response(content="﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="sworkr-{name}-{stamp}.csv"'})


def _local_date(value: str, offset_minutes: int) -> str:
    """A stored UTC time as a calendar date in the viewer's time zone."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(timezone.utc) - timedelta(minutes=offset_minutes)).strftime("%Y-%m-%d")


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):  # Excel on Windows often saves "CSV" as cp1252
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail="Couldn't read the file. Save it as CSV (UTF-8) and try again.")


def _read_rows(text: str, known: List[str]) -> List[dict]:
    """Rows as dicts keyed by our column names. Accepts comma, semicolon or tab separated files."""
    first_line = text.split("\n", 1)[0]
    delimiter = max((",", ";", "\t"), key=first_line.count)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise HTTPException(status_code=400, detail="The file is empty")
    columns = []
    for name in header:
        key = name.strip().lstrip("﻿").lower()
        key = ALIASES.get(key, key)
        columns.append(key if key in known else None)
    if not any(columns):
        raise HTTPException(status_code=400,
                            detail=f"None of the column names were recognised. Use these: {', '.join(known)}")
    rows = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue  # blank line
        row = {col: values[i].strip() if i < len(values) else "" for i, col in enumerate(columns) if col}
        row["_line"] = reader.line_num
        rows.append(row)
    return rows


def _unformula(text: str) -> str:
    """Undo _safe_cell, so exported text comes back exactly."""
    return text[1:] if text[:2] in ("'=", "'+", "'-", "'@") else text


def _parse_bool(text: str, line: int, errors: list, column: str = "active", blank: bool = True) -> bool:
    value = text.strip().lower()
    if value == "":
        return blank
    if value in ("yes", "y", "true", "1", "active"):
        return True
    if value in ("no", "n", "false", "0", "inactive"):
        return False
    errors.append(f"Line {line}: {column} must be yes or no, not '{text}'")
    return blank


def _parse_amount(text: str, line: int, errors: list) -> Optional[float]:
    cleaned = re.sub(r"[\s$€£,]", "", text)
    if re.fullmatch(r"\d+(\.\d+)?", cleaned) is None:
        errors.append(f"Line {line}: amount '{text}' isn't a number of 0 or more")
        return None
    return round(float(cleaned), 2)


DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y", "%B %d, %Y")


def _parse_date(text: str, line: int, errors: list, offset_minutes: int) -> Optional[str]:
    """A date as noon in the viewer's time zone, stored as UTC, so it shows as the same day everywhere."""
    text = text.strip()
    if not text:
        errors.append(f"Line {line}: date is missing")
        return None
    day = None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None or "T" in text or " " in text:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
        day = dt
    except ValueError:
        for fmt in DATE_FORMATS:
            try:
                day = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if day is None:
        errors.append(f"Line {line}: date '{text}' isn't a date like 2026-03-05 or 3/5/2026")
        return None
    noon_utc = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc) + timedelta(minutes=offset_minutes)
    return noon_utc.isoformat(timespec="seconds")


async def _body(request: Request) -> str:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="The file is too big (5 MB at most)")
        chunks.append(chunk)
    return _decode(b"".join(chunks))


def _problems(errors: List[str]):
    shown = errors[:MAX_ERRORS_SHOWN]
    if len(errors) > MAX_ERRORS_SHOWN:
        shown.append(f"…and {len(errors) - MAX_ERRORS_SHOWN} more")
    raise HTTPException(status_code=400, detail={"message": "Nothing was imported. Fix these and try again:",
                                                 "errors": shown})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _owner(request: Request) -> int:
    """Exports and imports only ever touch the logged-in user's own records."""
    return request.state.user["id"]


# ==================== CLIENTS ====================

@router.get("/clients")
def export_clients(request: Request, tz_offset: int = Query(0, ge=-840, le=840)):
    db = _get_db()
    try:
        rows = []
        for c in db.execute("""
            SELECT c.*, GROUP_CONCAT(t.tag_name, ', ') AS tags
            FROM clients c LEFT JOIN client_tags t ON t.client_id = c.id
            WHERE c.owner_id = ?
            GROUP BY c.id ORDER BY c.display_name COLLATE NOCASE, c.id
        """, (_owner(request),)):
            rows.append([c["id"], _safe_cell(c["name"] or ""), _safe_cell(c["email"]), _safe_cell(c["contact_phone"]),
                         _safe_cell(c["tags"]), _safe_cell(c["bio"]), "yes" if c["is_active"] else "no",
                         _local_date(c["created_at"], tz_offset),
                         c["screening_status"], "yes" if c["do_not_see"] else "no",
                         _safe_cell(c["do_not_see_reason"]), _safe_cell(c["references_text"]),
                         _safe_cell(c["screening_notes"]), c["birthday"] or "",
                         _safe_cell(c["drink_preferences"]), _safe_cell(c["food_preferences"]),
                         _safe_cell(contacts.handles_text(contacts.handles_from_db(c["handles"]))),
                         _safe_cell(c["industry"]), _safe_cell(c["display_name"]), "co-worker" if c["role"] == "partner" else c["role"],
                         _safe_cell(c["found_via"])])
    finally:
        db.close()
    return _csv_response(rows, CLIENT_COLUMNS, "clients")


@router.post("/clients")
async def import_clients(request: Request):
    rows = _read_rows(await _body(request), CLIENT_COLUMNS)
    db = _get_db()
    try:
        result = _import_clients(db, rows, _owner(request))
    except ImportProblems as p:
        db.rollback()
        _problems(p.errors)
    finally:
        db.close()
    _after_client_import(result.pop("_changed"))
    return result


def _import_clients(db, rows, owner_id):
    errors, seen_emails, seen_ids = [], {}, {}
    by_id = {r["id"]: dict(r) for r in db.execute("SELECT id, email FROM clients WHERE owner_id = ?", (owner_id,))}
    by_email = {r["email"].lower(): r["id"] for r in db.execute(
        "SELECT id, email FROM clients WHERE owner_id = ? AND email IS NOT NULL", (owner_id,))}
    plan = []
    for row in rows:
        line = row["_line"]
        name = _unformula(row.get("name", ""))
        email = _unformula(row.get("email", "")).lower() or None
        handles = contacts.parse_handles_text(_unformula(row["handles"])) if "handles" in row else None
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            errors.append(f"Line {line}: '{email}' isn't an email address")
        if email in seen_emails:
            errors.append(f"Line {line}: {email} is also on line {seen_emails[email]}")
        elif email:
            seen_emails[email] = line
        target = None
        if row.get("id"):
            if not row["id"].isdigit():
                errors.append(f"Line {line}: id '{row['id']}' isn't a number (leave it empty for new clients)")
            elif int(row["id"]) in by_id:
                target = int(row["id"])
            # an id that doesn't exist here (e.g. from another sworkr) is treated as a new client
        if target is None and email:
            target = by_email.get(email)
        if target is not None:
            if target in seen_ids:
                errors.append(f"Line {line}: this is the same client as line {seen_ids[target]}")
            seen_ids[target] = line
            other = by_email.get(email) if email else None
            if other is not None and other != target:
                errors.append(f"Line {line}: another client already has the email {email}")
        if not name and not handles and target is None:
            errors.append(f"Line {line}: give a name or at least one handle")
        # Only columns that are in the file. When updating, a column the file leaves out stays as it is.
        fields = {"name": name or None}
        if handles is not None:
            fields["handles"] = contacts.handles_json(handles)
        if "industry" in row:
            fields["industry"] = _unformula(row["industry"]) or None
        if "found_via" in row:
            fields["found_via"] = marketing.clean_found_via(_unformula(row["found_via"]))
        if "role" in row:
            role = row["role"].strip().lower() or "client"
            role = "partner" if role in ("co-worker", "coworker", "collaborator") else role   # shown as "co-worker", stored as "partner"
            if role not in ("client", "partner", "crew", "other"):
                errors.append(f"Line {line}: role '{row['role']}' must be client, co-worker, crew or other")
            fields["role"] = role
        if "email" in row:
            fields["email"] = email
        if "phone" in row:
            fields["contact_phone"] = _unformula(row["phone"]) or None
        if "notes" in row:
            fields["bio"] = _unformula(row["notes"]) or None
        if "active" in row:
            fields["is_active"] = int(_parse_bool(row["active"], line, errors))
        if "screening" in row:
            screening = row["screening"].strip().lower() or "unscreened"
            if screening not in SCREENING:
                errors.append(f"Line {line}: screening '{row['screening']}' must be one of {', '.join(SCREENING)}")
            fields["screening_status"] = screening
        if "do_not_see" in row:
            fields["do_not_see"] = int(_parse_bool(row["do_not_see"], line, errors, "do_not_see", blank=False))
        if "do_not_see_reason" in row:
            fields["do_not_see_reason"] = _unformula(row["do_not_see_reason"]) or None
        if "references" in row:
            fields["references_text"] = _unformula(row["references"]) or None
        if "screening_notes" in row:
            fields["screening_notes"] = _unformula(row["screening_notes"]) or None
        if "birthday" in row:
            birthday = row["birthday"].strip()
            if birthday:
                try:
                    birthday = date.fromisoformat(birthday).isoformat()
                except ValueError:
                    errors.append(f"Line {line}: birthday '{birthday}' must be a date like 1990-04-23")
            fields["birthday"] = birthday or None
        if "drinks" in row:
            fields["drink_preferences"] = _unformula(row["drinks"]) or None
        if "food" in row:
            fields["food_preferences"] = _unformula(row["food"]) or None
        tags = None
        if "tags" in row:
            tags = {t.strip().lower() for t in re.split(r"[,;]", _unformula(row["tags"])) if t.strip()}
        plan.append((target, fields, tags))
    if errors:
        raise ImportProblems(errors)

    created = updated = 0
    changed = []
    now = _now_iso()
    for target, fields, tags in plan:
        # What they're shown as follows from their name and handles, merged with what's already saved.
        old = dict(db.execute("SELECT name, handles, display_handle FROM clients WHERE id = ?", (target,)).fetchone()
                   ) if target is not None else {"name": None, "handles": None, "display_handle": None}
        merged = {**old, **{k: v for k, v in fields.items() if k in ("name", "handles")}}
        merged_handles = contacts.handles_from_db(merged["handles"])
        if old["display_handle"] is not None and old["display_handle"] >= len(merged_handles):
            fields["display_handle"] = None
            old["display_handle"] = None
        try:
            fields["display_name"] = contacts.display_name(merged["name"], merged_handles, old["display_handle"])
        except Exception:
            fields["display_name"] = old.get("name") or "Unnamed"
        if target is None:
            fields = {"is_active": 1, **fields, "owner_id": owner_id, "created_at": now, "updated_at": now}
            cur = db.execute(f"INSERT INTO clients ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                             tuple(fields.values()))
            client_id, created = cur.lastrowid, created + 1
        else:
            fields = {**fields, "updated_at": now}
            db.execute(f"UPDATE clients SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ? AND owner_id = ?",
                       (*fields.values(), target, owner_id))
            client_id, updated = target, updated + 1
        if tags is not None:
            db.execute("DELETE FROM client_tags WHERE client_id = ?", (client_id,))
            for tag in tags:
                db.execute("INSERT INTO client_tags (client_id, tag_name) VALUES (?, ?)", (client_id, tag))
        changed.append(client_id)
    db.commit()
    return {"created": created, "updated": updated, "skipped": 0, "_changed": changed}


# ==================== EXPENSES ====================

@router.get("/expenses")
def export_expenses(request: Request, tz_offset: int = Query(0, ge=-840, le=840)):
    db = _get_db()
    try:
        rows = [[e["id"], _local_date(e["date"], tz_offset), _safe_cell(e["description"]), f"{e['amount']:.2f}",
                 _safe_cell(e["category_label"] or e["category"]), _safe_cell(e["client_name"]),
                 _safe_cell(e["client_email"]), _safe_cell(e["notes"])]
                for e in db.execute("""
                    SELECT e.*, c.name AS client_name, c.email AS client_email, k.label AS category_label
                    FROM expenses e LEFT JOIN clients c ON e.client_id = c.id
                    LEFT JOIN expense_categories k ON k.owner_id = e.owner_id AND k.key = e.category
                    WHERE e.owner_id = ?
                    ORDER BY e.date, e.id
                """, (_owner(request),))]
    finally:
        db.close()
    return _csv_response(rows, EXPENSE_COLUMNS, "expenses")


@router.post("/expenses")
async def import_expenses(request: Request, tz_offset: int = Query(0, ge=-840, le=840)):
    rows = _read_rows(await _body(request), EXPENSE_COLUMNS)
    db = _get_db()
    try:
        return _import_expenses(db, rows, tz_offset, _owner(request))
    except ImportProblems as p:
        db.rollback()
        _problems(p.errors)
    finally:
        db.close()


def _find_client(db, name: str, email: str, line: int, errors: list, owner_id: int) -> Optional[int]:
    if email:
        row = db.execute("SELECT id FROM clients WHERE owner_id = ? AND email = ?", (owner_id, email.lower())).fetchone()
        if row:
            return row["id"]
        if not name:
            errors.append(f"Line {line}: no client has the email {email}")
            return None
    if not name:
        return None
    matches = db.execute("SELECT id FROM clients WHERE owner_id = ? AND name = ? COLLATE NOCASE",
                         (owner_id, name)).fetchall()
    if len(matches) == 1:
        return matches[0]["id"]
    if not matches:
        errors.append(f"Line {line}: there's no client called '{name}' (add them first, or leave client empty)")
    else:
        errors.append(f"Line {line}: more than one client is called '{name}'. Add their email in client_email.")
    return None


def _import_expenses(db, rows, tz_offset, owner_id):
    errors, plan = [], []
    # Room & board made from a tour and the cost of a health test are only changed where they come from.
    existing_ids = {r[0] for r in db.execute(
        "SELECT id FROM expenses WHERE owner_id = ? AND source IS NULL AND appointment_id IS NULL", (owner_id,))}
    categories = finance.category_lookup(db, owner_id)   # the user's own categories, by key or by name
    for row in rows:
        line = row["_line"]
        description = _unformula(row.get("description", ""))
        if not description:
            errors.append(f"Line {line}: description is missing")
        amount = _parse_amount(row.get("amount", ""), line, errors)
        typed = _unformula(row.get("category") or "").strip()
        category = categories.get(typed.lower() or "other")
        if category is None:
            errors.append(f"Line {line}: category '{typed}' isn't one of your expense categories (add it on the Money page first)")
        date = _parse_date(row.get("date", ""), line, errors, tz_offset)
        client_id = _find_client(db, _unformula(row.get("client", "")), _unformula(row.get("client_email", "")),
                                 line, errors, owner_id)
        target = None
        if row.get("id"):
            if not row["id"].isdigit():
                errors.append(f"Line {line}: id '{row['id']}' isn't a number (leave it empty for new expenses)")
            elif int(row["id"]) in existing_ids:
                target = int(row["id"])
        plan.append((target, client_id, description, amount, category, date,
                     _unformula(row.get("notes", "")) or None, "notes" in row))
    if errors:
        raise ImportProblems(errors)

    created = updated = skipped = 0
    now = _now_iso()
    for target, client_id, description, amount, category, date, notes, has_notes in plan:
        if target is not None:
            db.execute(f"""
                UPDATE expenses SET client_id = ?, description = ?, amount = ?, category = ?, date = ?
                {", notes = ?" if has_notes else ""} WHERE id = ? AND owner_id = ?
            """, (client_id, description, amount, category, date, *([notes] if has_notes else []), target, owner_id))
            updated += 1
            continue
        duplicate = db.execute("""
            SELECT 1 FROM expenses
            WHERE owner_id = ? AND description = ? AND ROUND(amount, 2) = ? AND category = ? AND client_id IS ?
              AND substr(date, 1, 10) = substr(?, 1, 10)
        """, (owner_id, description, amount, category, client_id, date)).fetchone()
        if duplicate:
            skipped += 1
            continue
        db.execute("""
            INSERT INTO expenses (client_id, description, amount, category, date, notes, owner_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (client_id, description, amount, category, date, notes, owner_id, now))
        created += 1
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}
