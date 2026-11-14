"""CSV import/export tests. Run with:  docker compose run --rm tests"""
import csv
import io
import os
import sys
import tempfile
import uuid

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def api():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def tag():
    return uuid.uuid4().hex[:8]  # keeps each test's records apart in the shared test database


def rows_of(response):
    assert response.status_code == 200, response.text
    assert response.content.startswith("﻿".encode())  # BOM, for Excel
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def upload(api, kind, text, encoding="utf-8", **params):
    return api.post(f"/api/csv/{kind}", content=text.encode(encoding), params=params,
                    headers={"Content-Type": "text/csv"})


def client_named(api, name):
    return [c for c in api.get("/api/clients", params={"search": name, "limit": 200}).json() if c["name"] == name]


# ---------- clients ----------

def test_csv_needs_login():
    anon = TestClient(main.app)
    assert anon.get("/api/csv/clients").status_code == 401
    assert anon.post("/api/csv/clients", content=b"name\nX").status_code == 401


def test_export_import_round_trip_changes_nothing(api):
    t = tag()
    api.post("/api/clients", json={"name": f"Round {t}", "email": f"round{t}@example.com", "contact_phone": "+1 555",
                                   "bio": "Likes mornings, \"quiet\" room\nsecond line", "tags": ["vip", "regular"],
                                   "is_active": False})
    exported = api.get("/api/csv/clients")
    mine = [r for r in rows_of(exported) if r["name"] == f"Round {t}"][0]
    assert mine["tags"] in ("regular, vip", "vip, regular") and mine["active"] == "no"

    r = upload(api, "clients", exported.content.decode("utf-8-sig"))
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 0 and r.json()["updated"] >= 1
    after = client_named(api, f"Round {t}")[0]
    assert after["bio"] == "Likes mornings, \"quiet\" room\nsecond line"
    assert sorted(after["tags"]) == ["regular", "vip"] and after["is_active"] is False


def test_import_new_clients_with_other_column_names_and_semicolons(api):
    t = tag()
    text = f"Full Name;E-mail;Mobile;Tags;Comments\nAna {t};ana{t}@example.com;555-1;new, text-only;Hi\n"
    r = upload(api, "clients", text)
    assert r.json() == {"created": 1, "updated": 0, "skipped": 0}
    ana = client_named(api, f"Ana {t}")[0]
    assert ana["email"] == f"ana{t}@example.com" and ana["contact_phone"] == "555-1"
    assert sorted(ana["tags"]) == ["new", "text-only"] and ana["bio"] == "Hi" and ana["is_active"]


def test_import_reads_excel_windows_encoding(api):
    t = tag()
    r = upload(api, "clients", f"name\nJosé {t}\n", encoding="cp1252")
    assert r.status_code == 200 and client_named(api, f"José {t}")


def test_matching_by_email_updates_and_missing_columns_are_kept(api):
    t = tag()
    api.post("/api/clients", json={"name": f"Keep {t}", "email": f"keep{t}@example.com",
                                   "contact_phone": "555-0", "bio": "keep me", "tags": ["a"]})
    r = upload(api, "clients", f"name,email\nKept {t},KEEP{t}@example.com\n")
    assert r.json()["updated"] == 1 and r.json()["created"] == 0
    c = client_named(api, f"Kept {t}")[0]
    assert c["contact_phone"] == "555-0" and c["bio"] == "keep me" and c["tags"] == ["a"]


def test_one_bad_row_means_nothing_is_imported(api):
    t = tag()
    text = f"name,email\nGood {t},good{t}@example.com\n,missing@example.com\nBad {t},not-an-email\n"
    r = upload(api, "clients", text)
    assert r.status_code == 400
    errors = r.json()["detail"]["errors"]
    assert any("Line 3: give a name or at least one handle" in e for e in errors)
    assert any("Line 4" in e and "isn't an email" in e for e in errors)
    assert not client_named(api, f"Good {t}")


def test_same_email_twice_in_a_file_is_an_error(api):
    t = tag()
    r = upload(api, "clients", f"name,email\nA {t},dup{t}@example.com\nB {t},dup{t}@example.com\n")
    assert r.status_code == 400 and "also on line 2" in r.json()["detail"]["errors"][0]


def test_spreadsheet_formulas_are_neutralized_on_export(api):
    t = tag()
    api.post("/api/clients", json={"name": f"=HYPERLINK(\"x\") {t}"})
    mine = [r for r in rows_of(api.get("/api/csv/clients")) if t in r["name"]][0]
    assert mine["name"].startswith("'=")
    # ...and come back as typed when the file is imported again.
    upload(api, "clients", f"id,name\n{mine['id']},{mine['name'].replace(chr(34), chr(34) * 2).join(chr(34) * 2)}\n")
    assert client_named(api, f"=HYPERLINK(\"x\") {t}")


def test_unrecognised_columns_are_explained(api):
    r = upload(api, "clients", "foo,bar\n1,2\n")
    assert r.status_code == 400 and "name" in r.json()["detail"]


# ---------- expenses ----------

def test_expense_import_matches_clients_and_reads_us_formats(api):
    t = tag()
    api.post("/api/clients", json={"name": f"Payer {t}", "email": f"payer{t}@example.com"})
    text = (f"date,description,amount,category,client\n"
            f"3/5/2026,Hotel {t},\"$1,234.50\",Travel,Payer {t}\n"
            f"2026-03-06,Soap {t},12,cleaning,\n")
    r = upload(api, "expenses", text, tz_offset=480)  # US Pacific (UTC-8)
    assert r.json() == {"created": 2, "updated": 0, "skipped": 0}, r.text
    rows = {e["description"]: e for e in api.get("/api/expenses", params={"limit": 500}).json()}
    hotel = rows[f"Hotel {t}"]
    assert hotel["amount"] == 1234.5 and hotel["category"] == "travel" and hotel["client_name"] == f"Payer {t}"
    assert hotel["date"].startswith("2026-03-05T20:00")  # noon Pacific
    assert rows[f"Soap {t}"]["client_id"] is None

    # Importing the same file again doesn't add them twice.
    again = upload(api, "expenses", text, tz_offset=480)
    assert again.json() == {"created": 0, "updated": 0, "skipped": 2}

    # Exported dates are in the viewer's time zone.
    exported = {r["description"]: r for r in rows_of(api.get("/api/csv/expenses", params={"tz_offset": 480}))}
    assert exported[f"Hotel {t}"]["date"] == "2026-03-05" and exported[f"Hotel {t}"]["amount"] == "1234.50"
    assert exported[f"Hotel {t}"]["client_email"] == f"payer{t}@example.com"


def test_expense_export_import_round_trip_updates_by_id(api):
    t = tag()
    api.post("/api/expenses", json={"description": f"Ad {t}", "amount": 20, "category": "marketing"})
    exported = rows_of(api.get("/api/csv/expenses"))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=exported[0].keys())
    writer.writeheader()
    for row in exported:
        if row["description"] == f"Ad {t}":
            row["amount"] = "25.00"
        writer.writerow(row)
    r = upload(api, "expenses", out.getvalue())
    assert r.json()["created"] == 0 and r.json()["updated"] == len(exported)
    ad = [e for e in api.get("/api/expenses", params={"limit": 500}).json() if e["description"] == f"Ad {t}"][0]
    assert ad["amount"] == 25


def test_expense_problems_are_listed(api):
    t = tag()
    text = (f"date,description,amount,category,client\n"
            f"yesterday,A {t},5,other,\n"
            f"2026-01-01,B {t},-5,other,\n"
            f"2026-01-01,C {t},5,food,\n"
            f"2026-01-01,D {t},5,other,Nobody {t}\n")
    r = upload(api, "expenses", text)
    assert r.status_code == 400
    errors = " | ".join(r.json()["detail"]["errors"])
    assert "Line 2: date 'yesterday'" in errors and "Line 3: amount '-5'" in errors
    assert "Line 4: category 'food'" in errors and f"Line 5: there's no client called 'Nobody {t}'" in errors
    assert not [e for e in api.get("/api/expenses", params={"limit": 500}).json() if t in e["description"]]
