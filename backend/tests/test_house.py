"""Tests for a workplace's own rules (outdates, shifts, the doctor's day, storage), bins, and each person's own
home-screen name and icon.
Run with:  docker compose run --rm tests"""
import os
import sys
import tempfile
import uuid
from datetime import date, timedelta

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="sworkr-test-"))
os.environ["SEED_DB"] = "0"
os.environ["CALENDAR_SYNC"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import house  # noqa: E402
import main  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


def new_user(admin):
    name = "h-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    return new_user(admin)


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The Ranch", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)


def stay(api, first, last, source_id):
    end = date.fromisoformat(last) + timedelta(days=1)
    return ok(api.post("/api/tours", json={"kind": "tour", "name": "Stint", "start_date": first, "end_date": last,
                                           "starts_at": f"{first}T00:00:00Z", "ends_at": f"{end.isoformat()}T00:00:00Z",
                                           "source_id": source_id}), 201)


# ---------- the guide and the rules ----------

def test_the_guide_asks_until_a_house_is_set_up(api):
    ranch, club, fans = place(api), place(api, "Club V", "club"), place(api, "FanSite", "platform")
    listing = ok(api.get("/api/house-rules"))
    assert [p["name"] for p in listing["places"]] == ["Club V", "The Ranch"]            # a platform has no house rules
    assert [p["name"] for p in listing["to_set_up"]] == ["The Ranch"]                   # only houses and agencies are guided
    by = {p["name"]: p for p in listing["places"]}
    assert by["The Ranch"]["todo"] == ["the doctor's day", "outdates", "shifts", "storage"]
    assert by["Club V"]["todo"] == ["shifts", "storage"]

    rules = ok(api.put(f"/api/income-sources/{ranch['id']}/rules", json={
        "doctor_weekday": 2, "outdates_allowed": True, "outdate_rules": "Two hours at least. The house keeps half. Sign out at the office.",
        "shift_pattern": "varied", "shifts": [{"label": "Days", "start": "05:00", "end": "17:00"}, {"label": "Nights", "start": "17:00", "end": "5:00"}],
        "storage_allowed": True, "storage_rules": "One bin, 60 days, $20 a month after that.", "other_rules": "No phones on the floor."}))
    assert rules["todo"] == [] and rules["doctor_weekday"] == 2 and rules["has_doctor_charge"]
    assert [s["text"] for s in rules["shifts"]] == ["Days (5am to 5pm)", "Nights (5pm to 5am)"]
    assert ok(api.get("/api/house-rules"))["to_set_up"] == []
    # The doctor's day went onto a doctor charge, so tests on a stay land on it.
    charges = [c for c in ok(api.get("/api/place-charges")) if c["source_id"] == ranch["id"]]
    assert len(charges) == 1 and charges[0]["label"] == "Doctor" and charges[0]["weekday"] == 2 and charges[0]["test_type"] == "weekly"
    # Saying it again moves the day; it doesn't add a second charge.
    ok(api.put(f"/api/income-sources/{ranch['id']}/rules", json={"doctor_weekday": 3, "shift_pattern": "none"}))
    charges = [c for c in ok(api.get("/api/place-charges")) if c["source_id"] == ranch["id"]]
    assert len(charges) == 1 and charges[0]["weekday"] == 3
    assert ok(api.get(f"/api/income-sources/{ranch['id']}/rules"))["shifts"] == []

    # "No doctor here" is an answer too.
    agency = place(api, "The Agency", "agency")
    r = ok(api.put(f"/api/income-sources/{agency['id']}/rules", json={"no_doctor": True, "outdates_allowed": False,
                                                                     "shift_pattern": "none", "storage_allowed": False}))
    assert r["todo"] == [] and r["doctor_weekday"] is None and not r["has_doctor_charge"]

    assert api.put(f"/api/income-sources/{ranch['id']}/rules", json={"shift_pattern": "fixed"}).status_code == 400          # no shift given
    assert api.put(f"/api/income-sources/{ranch['id']}/rules", json={"shift_pattern": "fixed", "shifts": [{"start": "25:00", "end": "5:00"}]}).status_code == 400
    assert api.put(f"/api/income-sources/{ranch['id']}/rules", json={"doctor_weekday": 9}).status_code == 400
    assert api.put(f"/api/income-sources/{fans['id'] + 9999}/rules", json={}).status_code == 404


def test_rules_are_private_to_their_owner(admin, api):
    ranch = place(api)
    other = new_user(admin)
    assert other.get(f"/api/income-sources/{ranch['id']}/rules").status_code == 404
    assert other.put(f"/api/income-sources/{ranch['id']}/rules", json={"outdates_allowed": True}).status_code == 404


# ---------- outdates on a client's profile ----------

def test_outdates_show_on_profiles_once_a_house_allows_them(api):
    ranch = place(api)
    client = ok(api.post("/api/clients", json={"name": "Regular Ray"}), 201)
    assert ok(api.get(f"/api/clients/{client['id']}/profile"))["outdates_possible"] is False
    ok(api.put(f"/api/income-sources/{ranch['id']}/rules", json={"outdates_allowed": True}))
    p = ok(api.get(f"/api/clients/{client['id']}/profile"))
    assert p["outdates_possible"] is True and p["outdates"] is None
    p = ok(api.put(f"/api/clients/{client['id']}/profile", json={"outdates": "yes", "outdate_notes": "Dinner in town, then back."}))
    assert p["outdates"] == "yes" and p["outdate_notes"] == "Dinner in town, then back."
    assert ok(api.put(f"/api/clients/{client['id']}/profile", json={"outdates": "sometimes"}))["outdates"] is None


# ---------- shifts ----------

def test_a_shift_knows_what_is_inside_it():
    assert house.in_shift("06:00", "05:00", "17:00") and not house.in_shift("17:00", "05:00", "17:00")
    assert house.in_shift("23:30", "17:00", "05:00") and house.in_shift("04:59", "17:00", "05:00")     # runs past midnight
    assert not house.in_shift("12:00", "17:00", "05:00")
    assert house.shift_text({"label": None, "start": "05:30", "end": "17:00"}) == "5:30am to 5pm"


def test_booking_outside_the_shift_on_a_stay_is_warned_about(api):
    ranch = place(api)
    ok(api.put(f"/api/income-sources/{ranch['id']}/rules", json={
        "shift_pattern": "varied", "shifts": [{"label": "Days", "start": "05:00", "end": "17:00"}, {"label": "Nights", "start": "17:00", "end": "05:00"}]}))
    tour = stay(api, "2046-05-04", "2046-05-10", ranch["id"])
    assert ok(api.get(f"/api/tours/{tour['id']}/shift")) == {"shift": None}
    client = ok(api.post("/api/clients", json={"name": "Party guest"}), 201)

    def warn(when, tz_offset=0):
        r = api.post("/api/appointments", params={"warn": True, "tz_offset": tz_offset},
                     json={"client_id": client["id"], "service_type": "Party", "duration_minutes": 60, "scheduled_date": when})
        return [w["message"] for w in r.json()["detail"]["warnings"] if w["type"] == "shift"] if r.status_code == 409 else []
    assert warn("2046-05-06T20:00:00Z") == []                                      # no shift chosen for the stay yet
    s = ok(api.put(f"/api/tours/{tour['id']}/shift", json={"label": "Days", "start": "05:00", "end": "17:00"}))
    assert s["shift"]["text"] == "Days (5am to 5pm)"
    assert warn("2046-05-06T20:00:00Z") == ["This is outside your shift at The Ranch: Days (5am to 5pm)"]
    assert warn("2046-05-06T10:00:00Z") == []
    assert warn("2046-05-06T20:00:00Z", tz_offset=480) == []                       # 8pm UTC is noon in Nevada
    assert warn("2046-05-20T20:00:00Z") == []                                      # after the stay

    ok(api.put(f"/api/tours/{tour['id']}/shift", json={"label": "Nights", "start": "17:00", "end": "05:00"}))
    assert warn("2046-05-06T23:00:00Z") == [] and warn("2046-05-07T03:00:00Z") == []
    assert len(warn("2046-05-06T12:00:00Z")) == 1
    assert warn("2046-05-11T03:00:00Z") == []                                      # the last night runs into the next morning
    assert len(warn("2046-05-11T12:00:00Z")) == 0                                  # the stay is over by then
    assert api.put(f"/api/tours/{tour['id']}/shift", json={"start": "05:00"}).status_code == 400
    assert ok(api.put(f"/api/tours/{tour['id']}/shift", json={})) == {"shift": None}
    assert api.get(f"/api/tours/{tour['id'] + 9999}/shift").status_code == 404


# ---------- bins ----------

def test_a_bin_keeps_its_list_and_a_label(admin, api):
    ranch = place(api)
    ok(api.put(f"/api/income-sources/{ranch['id']}/rules", json={"storage_allowed": True, "storage_rules": "One bin, 60 days."}))
    left = (date.today() - timedelta(days=12)).isoformat()
    b = ok(api.post("/api/bins", json={"label": "Blue tote", "source_id": ranch["id"], "where_kept": "Storage room, top shelf", "stored_on": left,
                                       "items": [{"label": "Red heels", "quantity": 2}, {"label": "Curling iron"}, {"label": "  "}]}), 201)
    assert [(i["label"], i["quantity"]) for i in b["items"]] == [("Red heels", 2), ("Curling iron", 1)]
    assert b["pieces"] == 3 and b["days_stored"] == 12 and b["place"] == "The Ranch" and b["storage_rules"] == "One bin, 60 days."

    found = ok(api.get("/api/bins/find", params={"q": "heel"}))
    assert [(f["item"], f["bin"], f["place"]) for f in found] == [("Red heels", "Blue tote", "The Ranch")]

    label = ok(api.get(f"/api/bins/{b['id']}/label", params={"origin": "https://my.example"}))
    assert label["url"] == f"https://my.example/bins/{b['code']}" and label["qr"].startswith("data:image/svg+xml")
    assert "Red heels" not in label["url"]                                         # the code holds a link, never the list
    assert api.get(f"/api/bins/{b['id']}/label", params={"origin": "javascript:alert(1)"}).status_code == 400
    assert ok(api.get(f"/api/bins/code/{b['code']}"))["label"] == "Blue tote"

    # Someone else scanning the label gets nothing, even signed in to the same sworkr.
    other = new_user(admin)
    assert other.get(f"/api/bins/code/{b['code']}").status_code == 404
    assert TestClient(main.app).get(f"/api/bins/code/{b['code']}").status_code == 401
    assert ok(other.get("/api/bins")) == []

    b = ok(api.put(f"/api/bins/{b['id']}", json={"label": "Blue tote", "items": [{"label": "Curling iron"}]}))
    assert b["pieces"] == 1 and b["place"] is None and len(ok(api.get("/api/bins"))) == 1
    assert api.post("/api/bins", json={"label": " "}).status_code == 400
    assert api.delete(f"/api/bins/{b['id']}").status_code == 204
    assert ok(api.get("/api/bins")) == [] and ok(api.get("/api/bins/find", params={"q": "iron"})) == []


# ---------- everyone's own home-screen name and icon ----------

def test_each_person_has_their_own_home_screen_name_and_icon(admin, api):
    import base64
    import io
    from PIL import Image

    def picture(colour):
        buf = io.BytesIO()
        Image.new("RGB", (200, 300), colour).save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    def pixel(response):
        return Image.open(io.BytesIO(response.content)).getpixel((5, 5))

    anyone = TestClient(main.app)
    ok(admin.put("/api/branding", json={"name": "Planner", "icon": picture((0, 0, 200))}))
    mine = ok(api.get("/api/branding"))
    assert mine["name"] == "Planner" and mine["own"] is False and mine["key"]           # the shared one, until they choose
    mine = ok(api.put("/api/branding", json={"name": "Recipes", "icon": picture((200, 0, 0))}))
    assert mine["name"] == "Recipes" and mine["own"] is True and mine["custom_icon"] is True
    key = mine["key"]

    # With their key the phone gets theirs; without it, the shared one.
    m = anyone.get("/api/branding/manifest.json", params={"k": key}).json()
    assert m["name"] == "Recipes" and all(i["src"].endswith(f"?k={key}") for i in m["icons"])
    assert anyone.get("/api/branding/manifest.json").json()["name"] == "Planner"
    assert pixel(anyone.get("/api/branding/icon-180.png", params={"k": key})) == (200, 0, 0)
    assert pixel(anyone.get("/api/branding/icon-180.png")) == (0, 0, 200)
    assert anyone.get("/api/branding/manifest.json", params={"k": "not-a-key"}).json()["name"] == "Planner"

    # Going back to the shared one.
    mine = ok(api.put("/api/branding", json={"name": "", "reset_icon": True}))
    assert mine["name"] == "Planner" and mine["own"] is False
    assert pixel(anyone.get("/api/branding/icon-180.png", params={"k": key})) == (0, 0, 200)
    ok(admin.put("/api/branding", json={"name": "", "reset_icon": True}))
    assert anyone.get("/api/branding/manifest.json").json()["name"] == "Sworkr"
