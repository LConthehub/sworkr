"""The demo reset fills an empty database with working sample data. Run with:  docker compose run --rm tests
It runs in a separate process with its own throwaway database, because a demo reset wipes everything."""
import json
import os
import subprocess
import sys
import tempfile

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = r"""
import json
from fastapi.testclient import TestClient
import demo, main

demo.PASSWORD = "demo-password-1"
demo.ENABLED = True        # set here, not in the environment, so no background reset thread runs alongside
for _ in range(2):                      # a second reset replaces the first, it doesn't add to it
    demo.reset(main.app, main.get_db)

c = TestClient(main.app)
out = {"status": c.get("/api/auth/status").json()}
out["admin_login"] = c.post("/api/auth/login", json={"username": "demo-admin", "password": "demo-password-1"}).status_code
out["login"] = c.post("/api/auth/login", json={"username": "demo", "password": "demo-password-1"}).status_code
out["clients"] = len(c.get("/api/clients", params={"limit": 200}).json())
out["tours"] = [(t["name"], t["figures"]["room_rent"] > 0, t["figures"]["income"]) for t in c.get("/api/tours/summary").json()]
out["time_off"] = len(c.get("/api/tours", params={"kind": "time_off"}).json())
expenses = c.get("/api/expenses", params={"limit": 500}).json()
out["categories"] = sorted({e["category"] for e in expenses})
out["tests"] = sum(1 for e in expenses if e["category"] == "medical")
out["users_page"] = c.get("/api/users").status_code
out["partners"] = {p["display_name"]: p["balance"] for p in c.get("/api/partners").json()}
out["goals"] = sorted(g["name"] for g in c.get("/api/goals").json())
out["income"] = len(c.get("/api/income").json())
out["sources"] = sorted(s["name"] for s in c.get("/api/income-sources").json())
out["change_password"] = c.post("/api/auth/change-password", json={"current_password": "demo-password-1", "new_password": "something-else"}).status_code
print("RESULT" + json.dumps(out))
"""


def test_demo_reset_builds_a_complete_sample():
    env = {**os.environ, "DATA_DIR": tempfile.mkdtemp(prefix="sworkr-demo-test-"), "SEED_DB": "0",
           "BACKGROUND_JOBS": "0", "DEMO_MODE": "0"}
    proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.split("RESULT", 1)[1])

    assert out["status"]["demo"] is True and out["status"]["setup_required"] is False
    assert out["status"]["demo_login"] == {"username": "demo", "password": "demo-password-1"}
    assert out["admin_login"] == 401          # nobody knows the admin password
    assert out["login"] == 200
    assert out["clients"] == 12
    assert {name for name, _, _ in out["tours"]} == {"Chicago", "Denver", "Miami"}
    assert all(has_rent for _, has_rent, _ in out["tours"])
    assert any(income > 0 for _, _, income in out["tours"])
    assert out["time_off"] == 3
    assert {"medical", "room_rent", "travel", "marketing"} <= set(out["categories"])
    assert out["tests"] == 6
    assert out["users_page"] == 403           # the demo login isn't an admin
    assert set(out["partners"]) == {"Jade", "Ruby"} and all(isinstance(v, float) for v in out["partners"].values())
    assert out["goals"] == ["Emergency fund", "New camera", "Retirement goal", "Taxes"]
    assert out["income"] == 23 and out["sources"] == ["Club Velvet", "Fansly", "OnlyFans", "The Velvet Room"]
    assert out["change_password"] == 403


def test_the_demo_refuses_passkeys_and_bad_date_lists(monkeypatch):
    import demo
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(demo, "ENABLED", True)
    c = TestClient(main.app)
    name = "dm-" + __import__("uuid").uuid4().hex[:6]
    owner = TestClient(main.app)
    if owner.post("/api/auth/setup", json={"username": "owner", "password": "correct-horse-battery"}).status_code != 201:
        owner.post("/api/auth/login", json={"username": "owner", "password": "correct-horse-battery"})
    owner.post("/api/users", json={"username": name, "password": "correct-horse-battery"})
    c.post("/api/auth/login", json={"username": name, "password": "correct-horse-battery"})
    assert c.post("/api/account/passkeys/begin", headers={"Origin": "http://localhost"}).status_code == 403
    assert c.post("/api/blocklist", json={"phone": "5551234567"}).status_code == 403
    assert c.post("/api/blocklist/import", json={"csv": "phone\n5551234567\n", "list_name": "x", "mapping": {"phone": "phone"}}).status_code == 403
