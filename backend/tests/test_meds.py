"""Tests for birth control and regular meds.
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

import main  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="module")
def admin():
    c = TestClient(main.app)
    if c.post("/api/auth/setup", json={"username": "owner", "password": PASSWORD}).status_code != 201:
        assert c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
    return c


@pytest.fixture
def api(admin):
    name = "m-" + uuid.uuid4().hex[:8]
    assert admin.post("/api/users", json={"username": name, "password": PASSWORD}).status_code == 201
    c = TestClient(main.app)
    assert c.post("/api/auth/login", json={"username": name, "password": PASSWORD}).status_code == 200
    return c


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def place(api, name="The House", kind="brothel"):
    return ok(api.post("/api/income-sources", json={"name": name, "kind": kind}), 201)

TODAY = date.today()


def med(api, **fields):
    return ok(api.post("/api/meds", json={"name": "Mine", **fields}), 201)


def test_a_daily_pill_is_logged_once_a_day_and_gets_no_task(api):
    pill = med(api, name="Pill", method="pill", started_on=TODAY.isoformat())
    assert pill["status"]["taken_today"] is False and pill["task_id"] is None
    after = ok(api.post(f"/api/meds/{pill['id']}/log", json={"kind": "taken"}), 201)
    again = ok(api.post(f"/api/meds/{pill['id']}/log", json={"kind": "taken"}), 201)
    assert after["status"]["taken_today"] and len([l for l in again["recent"] if l["kind"] == "taken"]) == 1


def test_a_patch_and_a_shot_are_due_from_the_last_change(api):
    patch = med(api, name="Patch", method="patch", started_on=(TODAY - timedelta(days=3)).isoformat())
    assert patch["status"]["next"] == {"what": "Change the patch", "on": (TODAY + timedelta(days=4)).isoformat()}
    changed = ok(api.post(f"/api/meds/{patch['id']}/log", json={"kind": "changed"}), 201)
    assert changed["status"]["next"]["on"] == (TODAY + timedelta(days=7)).isoformat()
    task = next(t for t in ok(api.get("/api/tasks")) if t["id"] == changed["task_id"])
    assert task["title"] == "Health reminder" and task["due_date"] == (TODAY + timedelta(days=7)).isoformat()

    shot = med(api, name="Depo", method="shot", started_on=TODAY.isoformat(), discreet=False)
    assert shot["status"]["next"]["on"] == (TODAY + timedelta(days=84)).isoformat()
    assert next(t for t in ok(api.get("/api/tasks")) if t["id"] == shot["task_id"])["title"] == "Next shot (Depo)"


def test_a_ring_is_three_weeks_in_and_one_out(api):
    ring = med(api, name="Ring", method="ring", started_on=(TODAY - timedelta(days=22)).isoformat())
    assert ring["status"]["ring"] == "out"
    assert ring["status"]["next"] == {"what": "Put a new ring in", "on": (TODAY + timedelta(days=6)).isoformat()}
    # Putting the new one in early starts the next three weeks today.
    ring = ok(api.post(f"/api/meds/{ring['id']}/log", json={"kind": "changed"}), 201)
    assert ring["status"]["ring"] == "in"
    assert ring["status"]["next"] == {"what": "Take the ring out", "on": (TODAY + timedelta(days=21)).isoformat()}


def test_an_implant_and_a_refill_remind_whichever_is_first(api):
    implant = med(api, name="Implant", method="implant", replace_by=(TODAY + timedelta(days=900)).isoformat(),
                  refill_every_days=30, started_on=TODAY.isoformat(), cost=25)
    task = next(t for t in ok(api.get("/api/tasks")) if t["id"] == implant["task_id"])
    assert task["due_date"] == (TODAY + timedelta(days=30)).isoformat()     # the refill comes first
    ok(api.post(f"/api/meds/{implant['id']}/log", json={"kind": "refilled", "date": TODAY.isoformat()}), 201)
    spent = [e for e in ok(api.get("/api/expenses")) if e["category"] == "health"]
    assert [(e["description"], e["amount"]) for e in spent] == [("Health refill", 25)]
    # Stopping it removes its reminder.
    ok(api.put(f"/api/meds/{implant['id']}", json={"name": "Implant", "method": "implant", "active": False}))
    assert implant["task_id"] not in [t["id"] for t in ok(api.get("/api/tasks", params={"status": "all"}))]


def test_meds_are_private(api, admin):
    pill = med(api, method="pill")
    assert pill["id"] not in [m["id"] for m in ok(admin.get("/api/meds"))]
    assert admin.post(f"/api/meds/{pill['id']}/log", json={"kind": "taken"}).status_code == 404
    assert admin.put(f"/api/meds/{pill['id']}", json={"name": "x"}).status_code == 404


# ---------- injections: site rotation and dose steps ----------

def test_injections_rotate_sites_and_follow_the_dose_plan(api):
    start = TODAY - timedelta(days=30)          # 4 weeks and 2 days in: the second step
    m = med(api, name="GLP-1", method="injection", every_days=7, started_on=start.isoformat(),
            sites=["Left belly", "Right belly", "Left thigh"],
            doses=[{"dose": "0.25 mg", "weeks": 4}, {"dose": "0.5 mg", "weeks": 4}, {"dose": "1 mg"}])
    assert (m["status"]["next_site"], m["status"]["dose"]) == ("Left belly", "0.5 mg")
    assert m["status"]["next"] == {"what": "Next injection", "on": (start + timedelta(days=7)).isoformat()}

    m = ok(api.post(f"/api/meds/{m['id']}/log", json={"kind": "changed"}), 201)
    assert (m["recent"][0]["site"], m["recent"][0]["dose"]) == ("Left belly", "0.5 mg")   # filled in from the plan
    assert m["status"]["next_site"] == "Right belly"
    assert m["status"]["next"]["on"] == (TODAY + timedelta(days=7)).isoformat()
    # Choosing another site carries the rotation on from there.
    m = ok(api.post(f"/api/meds/{m['id']}/log", json={"kind": "changed", "site": "Left thigh", "dose": "0.5 mg"}), 201)
    assert m["status"]["next_site"] == "Left belly"


def test_dose_steps_past_the_plan_stay_on_the_last_dose():
    import meds
    steps = [{"dose": "2 mg", "weeks": 1}, {"dose": "4 mg", "weeks": 1}]
    start = date(2044, 1, 1)
    assert meds.dose_on(steps, start, date(2044, 1, 3)) == "2 mg"
    assert meds.dose_on(steps, start, date(2044, 1, 9)) == "4 mg"
    assert meds.dose_on(steps, start, date(2044, 6, 1)) == "4 mg"
    assert meds.next_site([], None) is None


def test_injection_settings_are_checked(api):
    assert api.post("/api/meds", json={"name": "T", "method": "injection", "every_days": 500}).status_code == 400
    assert api.post("/api/meds", json={"name": "T", "method": "injection", "doses": [{"dose": ""}]}).status_code == 400
    pill = med(api, name="Pill", method="pill", sites=["Left belly"])
    assert pill["sites"] == []                    # only injections keep sites
