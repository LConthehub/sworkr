"""
Demo mode: a copy of sworkr filled with made-up data, for showing colleagues.

Turned on with DEMO_MODE=1 (see docker-compose.demo.yml). Then:
- The database is wiped and refilled with sample clients, appointments, tours, time off, health tests and
  expenses, dated around today, whenever it's empty and again every night, so testers can change anything.
- Testers log in as DEMO_USERNAME / DEMO_PASSWORD, an ordinary (non-admin) account. The admin account gets a
  random password nobody knows, so backups, calendar sync and user management can't be reached.
- Changing the demo password is turned off, so one tester can't lock the others out.

Never point DEMO_MODE at a real database: a reset deletes everything in it.
"""

import logging
import os
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone

import auth

log =logging.getLogger("sworkr.demo")

ENABLED = os.environ.get("DEMO_MODE", "0") == "1"
USERNAME = os.environ.get("DEMO_USERNAME", "demo").strip().lower()
PASSWORD = os.environ.get("DEMO_PASSWORD", "")
RESET_HOUR_UTC = int(os.environ.get("DEMO_RESET_HOUR_UTC", "9"))   # 9:00 UTC is the middle of the night in the Americas

TABLES = ("sessions", "user_settings", "client_notes", "client_tags", "expenses", "appointments", "tours", "clients", "users")


def _wipe(get_db):
    db = get_db()
    try:
        for table in TABLES:
            db.execute(f"DELETE FROM {table}")
        db.execute("DELETE FROM settings WHERE key != 'seeded'")
        db.execute("DELETE FROM sqlite_sequence")   # ids start from 1 again
        db.execute("INSERT INTO settings (key, value) VALUES ('demo_reset_at', ?) "
                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                   (datetime.now(timezone.utc).isoformat(timespec="seconds"),))
        db.commit()
    finally:
        db.close()


def reset(app, get_db):
    """Delete everything and fill the database with fresh sample data, through the app's own API."""
    if not PASSWORD or len(PASSWORD) < auth.MIN_PASSWORD_LENGTH:
        raise RuntimeError(f"DEMO_PASSWORD must be set (at least {auth.MIN_PASSWORD_LENGTH} characters) when DEMO_MODE=1")
    from fastapi.testclient import TestClient   # only needed here

    _wipe(get_db)
    import mail
    mail.reset_demo_inbox()
    admin = TestClient(app)
    _ok(admin.post("/api/auth/setup", json={"username": "demo-admin", "password": secrets.token_urlsafe(24)}))
    _ok(admin.post("/api/users", json={"username": USERNAME, "password": PASSWORD}))
    api = TestClient(app)
    _ok(api.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD}))
    _fill(api)
    for c in (admin, api):
        c.post("/api/auth/logout")
    log.warning("Demo data was reset")


def _ok(response):
    if response.status_code >= 300:
        raise RuntimeError(f"Demo setup failed: {response.request.method} {response.request.url} "
                           f"{response.status_code} {response.text[:300]}")
    return response.json() if response.content else None


def _fill(api):
    today = datetime.now(timezone.utc).date()

    def day(offset: int) -> date:
        return today + timedelta(days=offset)

    def at(offset: int, hour: int, minute: int = 0) -> str:
        """A time `offset` days from today. Hours are UTC: 1-3 am UTC is the evening across the Americas."""
        d = day(offset)
        return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc).isoformat()

    def period(first: int, last: int, **fields):
        start, end = day(first), day(last)
        return _ok(api.post("/api/tours", json={
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "starts_at": f"{start.isoformat()}T00:00:00Z", "ends_at": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
            **fields}))

    def birthday(year: int, offset: int) -> str:
        d = day(offset)
        return f"{year}-{d.month:02d}-{min(d.day, 28):02d}"

    # ---------- clients ----------
    people = [
        dict(name="Jordan Avery", contact_phone="+1-555-0141", email="jordan.avery@example.com", tags=["regular", "dinner"],
             industry="Finance", handles=[{"platform": "Telegram", "handle": "javery_88"}],
             screening_status="verified", references="Referred by Casey (verified 2024)", birthday=birthday(1979, 4),
             drink_preferences="Old fashioned with rye, no cherry", food_preferences="Steak, medium rare. Hates cilantro.",
             bio="Books monthly, always on time. Prefers texts after 6pm."),
        dict(name="Morgan Ellis", contact_phone="+1-555-0172", email="m.ellis@example.com", tags=["regular", "travel"],
             industry="Tech", handles=[{"platform": "X (Twitter)", "handle": "morgan_builds"}],
             screening_status="verified", birthday=birthday(1985, 40), drink_preferences="Champagne, dry",
             food_preferences="Sushi, vegetarian options", bio="Meets on tours in Chicago and Miami."),
        dict(name="Riley Chen", contact_phone="+1-555-0193", tags=["new"], screening_status="pending",
             screening_notes="Sent ID and one reference, waiting to hear back", drink_preferences="Sparkling water, no alcohol",
             bio="Found through the ad. First booking pending screening."),
        dict(name="Taylor Brooks", email="tbrooks@example.com", tags=["regular", "overnight"], screening_status="verified",
             industry="Medicine",
             birthday=birthday(1990, 120), drink_preferences="Red wine (Pinot Noir)", food_preferences="Italian, no shellfish",
             bio="Overnights only. Generous tipper."),
        dict(name="Casey Morgan", contact_phone="+1-555-0115", tags=["regular"], screening_status="verified",
             birthday=birthday(1972, 200), drink_preferences="Gin and tonic", food_preferences="Loves dessert"),
        dict(name="Sam Patel", contact_phone="+1-555-0188", email="sam.p@example.com", tags=["travel"], industry="Law",
             screening_status="verified", drink_preferences="Whiskey neat", bio="Business traveller, books in Denver."),
        dict(name="Alex Rivera", contact_phone="+1-555-0126", tags=["new"], screening_status="unscreened",
             bio="Asked about rates, hasn't sent screening info."),
        dict(name="Drew Hollis", contact_phone="+1-555-0164", screening_status="declined", do_not_see=True,
             do_not_see_reason="Pushed boundaries and refused to screen", bio="Do not book."),
    ]
    for p, via in zip(people, ("Referral", "X", "Tryst", "Tryst", "Eros", "Tryst", "X", "Tryst")):
        p["found_via"] = via
    clients = {p["name"].split()[0]: _ok(api.post("/api/clients", json=p)) for p in people}
    # Sometimes a handle is all you know.
    _ok(api.post("/api/clients", json={
        "handles": [{"platform": "Instagram", "handle": "velvet.nights.fan"}, {"platform": "OnlyFans", "handle": "vnf_22"}],
        "display_handle": 0, "tags": ["fan"], "screening_status": "unscreened", "industry": "Unknown",
        "bio": "Big spender on OnlyFans, asking to meet in Miami. No real name yet."}))
    for who, body in [("Jordan", "Mentioned a work trip to Miami next month - may want to book there."),
                      ("Jordan", "Paid in cash, brought flowers."),
                      ("Taylor", "Asked to move next overnight to a Friday."),
                      ("Riley", "Reference #1 confirmed by text.")]:
        _ok(api.post(f"/api/clients/{clients[who]['id']}/notes", json={"body": body}))

    # ---------- tours and time off ----------
    chicago = period(-42, -37, kind="tour", name="Chicago", location="River North hotel", room_rent_per_day=185,
                     notes="Busy Friday and Saturday. Hotel gym was great.")
    denver = period(-16, -12, kind="tour", name="Denver", location="Downtown", room_rent_per_day=140)
    miami = period(9, 13, kind="tour", name="Miami", location="South Beach", room_rent_per_day=230,
                   notes="Book flights by next week.")
    period(-28, -24, kind="time_off", time_off_type="vacation", name="Beach week")
    period(-14, -14, kind="time_off", time_off_type="day_off")
    period(3, 3, kind="time_off", time_off_type="day_off")

    # ---------- appointments ----------
    def book(who, offset, hour, service, minutes, rate, paid=None, status=None, **extra):
        past = offset < 0
        body = {"client_id": clients[who]["id"], "service_type": service, "duration_minutes": minutes,
                "scheduled_date": at(offset, hour), "rate": rate,
                "amount_paid": rate if paid is None and past else (paid or 0),
                "status": status or ("completed" if past else "scheduled"), "payment_method": "Cash", **extra}
        return _ok(api.post("/api/appointments", json=body))

    # Chicago tour
    book("Morgan", -42, 2, "Dinner date", 180, 900)
    book("Jordan", -41, 1, "Dinner date", 180, 900, location_type="outcall", location="The Langham")
    book("Sam", -40, 3, "Two hours", 120, 700)
    book("Taylor", -39, 2, "Overnight", 720, 2500)
    book("Morgan", -38, 1, "Two hours", 120, 700, paid=350)        # still owed half
    # Denver tour (one cancellation, and one booked on the day off was moved)
    book("Sam", -16, 2, "Dinner date", 180, 850)
    book("Casey", -15, 1, "One hour", 60, 400)
    book("Jordan", -13, 2, "Two hours", 120, 650, status="cancelled", paid=0)
    book("Casey", -12, 3, "Two hours", 120, 650)
    # At home
    for offset, who, service, minutes, rate in [(-80, "Jordan", "Dinner date", 180, 800), (-73, "Casey", "One hour", 60, 350),
                                                (-60, "Taylor", "Overnight", 720, 2200), (-55, "Jordan", "Two hours", 120, 600),
                                                (-33, "Casey", "One hour", 60, 350), (-20, "Jordan", "Dinner date", 180, 800),
                                                (-8, "Taylor", "Two hours", 120, 600), (-5, "Casey", "One hour", 60, 350),
                                                (-2, "Jordan", "Two hours", 120, 600)]:
        book(who, offset, 2, service, minutes, rate)
    book("Casey", -1, 1, "One hour", 60, 350, paid=0)                 # done, not paid yet
    # Coming up
    book("Jordan", 1, 2, "Dinner date", 180, 800, paid=200, safety_checkin=True, notes="Deposit received")
    book("Taylor", 5, 1, "Overnight", 720, 2200)
    book("Morgan", 10, 2, "Dinner date", 180, 950, paid=300, location_type="incall")
    book("Jordan", 11, 1, "Two hours", 120, 700, location_type="outcall", location="Faena Hotel")
    book("Riley", 12, 3, "One hour", 60, 450, notes="Only if screening clears")
    for week in range(3, 7):
        book("Casey", 7 * week - 4, 2, "One hour", 60, 350)

    # ---------- health tests ----------
    def test(test_type, offset, cost, tour=None):
        _ok(api.post("/api/appointments", json={
            "kind": "test", "test_type": test_type, "cost": cost, "duration_minutes": 30, "scheduled_date": at(offset, 16),
            "status": "completed" if offset < 0 else "scheduled", "tour_id": tour["id"] if tour else None,
            "location": "Downtown clinic"}))

    test("monthly", -43, 145, chicago)        # the day before the tour, put on the tour
    test("weekly", -40, 85, chicago)
    test("weekly", -15, 85, denver)
    test("yearly", -70, 320)
    test("monthly", 8, 145, miami)
    test("weekly", 10, 90, miami)

    # ---------- other expenses ----------
    for offset, description, amount, category, tour, notes in [
        (-44, "Flight to Chicago", 340, "travel", chicago, None),
        (-37, "Rideshares in Chicago", 96.5, "travel", chicago, None),
        (-17, "Flight to Denver", 260, "travel", denver, None),
        (-65, "Ad listing (monthly)", 120, "marketing", None, None),
        (-35, "Ad listing (monthly)", 120, "marketing", None, None),
        (-5, "Ad listing (monthly)", 120, "marketing", None, None),
        (-50, "Lingerie", 180, "wardrobe", None, None),
        (-30, "Linen service", 45, "cleaning", None, None),
        (-9, "Phone plan", 60, "other", None, "Work phone"),
        (2, "Flight to Miami", 310, "travel", miami, "Booked early"),
    ]:
        d = day(offset)
        _ok(api.post("/api/expenses", json={
            "description": description, "amount": amount, "category": category, "notes": notes,
            "date": f"{d.isoformat()}T12:00:00Z", "tour_id": tour["id"] if tour else None}))

    _ok(api.put("/api/safety", json={"contact_name": "Best friend", "contact_email": "friend@example.com", "grace_minutes": 60}))

    # ---------- how I work, workplaces and platforms, other income ----------
    _ok(api.put("/api/work-profile", json={"work_types": ["independent", "content", "dancer", "brothel", "sugar"]}))
    categories = {c["label"]: c["key"] for c in _ok(api.get("/api/expense-categories"))}
    sources = {s["name"]: s for s in _ok(api.get("/api/income-sources"))}
    _ok(api.put(f"/api/income-sources/{sources['Fansly']['id']}", json={
        "name": "Fansly", "kind": "platform", "fee_percent": 20, "archived": True, "work_type": "content",
        "notes": "Stopped posting here; kept for last year's figures"}))
    club = _ok(api.put(f"/api/income-sources/{sources['My club']['id']}", json={
        "name": "Club Velvet", "kind": "club", "fee_per_shift": 60, "work_type": "dancer",
        "payout_note": "Cash at the end of each shift",
        "club_pay": {"status": "contractor", "house_fees": [{"until": "21:00", "fee": 40}, {"until": None, "fee": 80}],
                     "dance_price": 20, "dance_house": 5, "dance_house_kind": "amount", "vip_house_percent": 50,
                     "tip_outs": [{"label": "DJ", "kind": "amount", "value": 20},
                                  {"label": "House mom", "kind": "percent", "value": 5}]}}))
    for offset, description, amount, category in [(-46, "Lace set", 120, "Lingerie & outfits"),
                                                  (-26, "Lash appointment", 85, "Makeup & beauty"),
                                                  (-11, "Verification site renewal", 40, "Ads & verification"),
                                                  (-57, "Ring light", 140, "Camera & lighting")]:
        d = day(offset)
        _ok(api.post("/api/expenses", json={"description": description, "amount": amount,
                                            "category": categories[category], "date": f"{d.isoformat()}T12:00:00Z"}))

    onlyfans = sources["OnlyFans"]["id"]
    for offset, kind, gross, description, status in [
        (-84, "subscription", 640, "Subscriptions", "received"), (-77, "sale", 180, "PPV set: red lace", "received"),
        (-63, "subscription", 710, "Subscriptions", "received"), (-49, "tips", 95, "Tips", "received"),
        (-35, "subscription", 760, "Subscriptions", "received"), (-28, "sale", 240, "Custom video", "received"),
        (-14, "subscription", 805, "Subscriptions", "received"), (-6, "sale", 150, "PPV set: beach", "received"),
        (-2, "subscription", 830, "Subscriptions (this payout is processing)", "pending"),
    ]:
        _ok(api.post("/api/income", json={
            "source_id": onlyfans, "date": at(offset, 18), "kind": kind, "gross": gross, "fees": round(gross * 0.2, 2),
            "description": description, "status": status,
            "payout_date": day(offset + 7).isoformat() if status == "pending" else day(offset + 2).isoformat()}))

    # Dancing: a shift most weeks at the club, house fee taken off.
    for offset, gross, note in [(-82, 640, None), (-75, 410, "Slow Tuesday"), (-61, 880, None), (-54, 520, None),
                                (-47, 95, "Quiet night: the house fee ate most of it"), (-33, 760, None),
                                (-19, 1020, "Convention in town"), (-12, 590, None), (-5, 700, None)]:
        _ok(api.post("/api/income", json={
            "source_id": club["id"], "date": at(offset, 6), "kind": "shift", "gross": gross, "fees": 60,
            "description": "Shift", "notes": note, "status": "received"}))

    # A few shifts at a brothel (the house keeps half). Its license is a document, paid to the county.
    house = _ok(api.put(f"/api/income-sources/{sources['My brothel']['id']}", json={
        "name": "Cheryl's Ranch", "kind": "brothel", "fee_percent": 50, "work_type": "brothel",
        "payout_note": "House keeps 50%, paid out at the end of each shift"}))
    for offset, gross in [(-68, 1400), (-40, 1100), (-26, 1650), (-9, 1300)]:
        _ok(api.post("/api/income", json={"source_id": house["id"], "date": at(offset, 7), "kind": "shift",
                                          "gross": gross, "fees": gross / 2, "description": "Shift", "status": "received"}))
    # What the house charges: room & board and its doctor.
    amounts = {"Room & board": 100, "Doctor": 60}
    for charge in _ok(api.get("/api/place-charges")):
        if charge["source_id"] == house["id"] and charge["label"] in amounts:
            renews = day(-72 + 365) if charge["cadence"] == "per_year" else None
            charge = _ok(api.put(f"/api/place-charges/{charge['id']}", json={
                "label": charge["label"], "cadence": charge["cadence"], "category": charge["category"],
                "test_type": charge["test_type"], "amount": amounts[charge["label"]],
                "renews_on": renews.isoformat() if renews else None}))
            if charge["cadence"] == "per_year":
                _ok(api.post(f"/api/place-charges/{charge['id']}/log", json={"date": f"{day(-72).isoformat()}T12:00:00Z"}))
    # The work card is paid to the county, not the house: a document that runs out in about ten months, renewed 72 days ago.
    card = _ok(api.post("/api/documents", json={"name": "County work card", "kind": "work_card", "expires_on": day(-72 + 365).isoformat(),
                                                "issued_on": day(-72).isoformat()}))
    _ok(api.post(f"/api/documents/{card['id']}/renewed", json={"expires_on": day(-72 + 365).isoformat(), "paid": 275, "paid_to": "County sheriff's office",
                                                               "paid_on": day(-72).isoformat()}))

    # ---------- working with partners ----------
    jade = _ok(api.post("/api/clients", json={
        "name": "Jade", "role": "partner", "industry": "Escort & content creator",
        "handles": [{"platform": "Instagram", "handle": "jade.after.dark"}, {"platform": "OnlyFans", "handle": "jadeafterdark"}],
        "bio": "Duo collaborator for bookings and collab content. Splits 50/50 on bookings, 60/40 to whoever posts."}))
    ruby = _ok(api.post("/api/clients", json={"name": "Ruby", "role": "partner", "bio": "Joins for parties at Cheryl's Ranch"}))
    _ok(api.post("/api/clients", json={"name": "Alex", "role": "partner", "industry": "Photographer", "email": "alex.photo@example.com",
                                       "bio": "Shoots our content sets. $250 a half day."}))
    duo = _ok(api.post("/api/agreements", json={"name": "Jade & me", "notes": "Agreed over coffee, Oct 2026", "parties": [
        {"partner_id": jade["id"], "booking_pct": 50, "content_pct": 40, "costs_pct": 50}]}))
    _ok(api.post("/api/agreements", json={"name": "Cheryl's Ranch party (three of us)", "parties": [
        {"partner_id": jade["id"], "booking_pct": 33.3}, {"partner_id": ruby["id"], "booking_pct": 33.3}]}))

    def split(kind, record_id, handled_by=None, parties=(), agreement=None):
        _ok(api.put(f"/api/splits/{kind}/{record_id}", json={"handled_by": handled_by, "agreement_id": agreement,
                                                             "parties": [{"partner_id": p, "share_value": v} for p, v in parties]}))

    duo_one = book("Morgan", -36, 2, "Duo dinner date", 180, 1600, notes="With Jade")
    split("appointment", duo_one["id"], parties=[(jade["id"], 50)], agreement=duo["id"])        # you were paid: you owe Jade
    duo_two = book("Taylor", -18, 1, "Duo overnight", 720, 3600, notes="With Jade")
    split("appointment", duo_two["id"], handled_by=jade["id"], parties=[(jade["id"], 50)], agreement=duo["id"])   # Jade was paid
    party = book("Sam", -4, 3, "Party (three of us)", 240, 2400)
    split("appointment", party["id"], handled_by=ruby["id"], parties=[(jade["id"], 33.3), (ruby["id"], 33.3)])
    shoot = _ok(api.post("/api/expenses", json={"description": "Photographer: collab shoot", "amount": 250,
                                                "category": categories["Photographers & shoots"], "date": f"{day(-21).isoformat()}T12:00:00Z"}))
    split("expense", shoot["id"], handled_by=jade["id"], parties=[(jade["id"], 50)], agreement=duo["id"])
    collab_sale = _ok(api.post("/api/income", json={"source_id": onlyfans, "date": at(-15, 19), "kind": "sale", "gross": 600,
                                                    "fees": 120, "description": "Collab set with Jade (PPV)", "status": "received"}))
    split("income", collab_sale["id"], parties=[(jade["id"], 40)], agreement=duo["id"])
    _ok(api.post(f"/api/partners/{jade['id']}/settlements", json={"amount": 800, "direction": "paid_them",
                                                                  "date": day(-30).isoformat(), "note": "Cash, after the dinner date"}))

    # ---------- posts (the demo's library is made up: see content.DemoLibrary) ----------
    for platform, offset, hour, status, caption, price, set_path, files, account in [
        ("OnlyFans", -12, 19, "posted", "Red lace is finally here ❤️ Full set in your DMs", 15, "2026-10 Red lace",
         ["2026-10 Red lace/01.jpg", "2026-10 Red lace/02.jpg", "2026-10 Red lace/03.jpg"], "@sunny"),
        ("X", -11, 17, "posted", "New set just dropped, link in bio 💋", None, "2026-10 Red lace", ["2026-10 Red lace/01.jpg"], "@sunny_xo"),
        ("OnlyFans", 0, 20, "scheduled", "Beach day ☀️ who wants the rest?", 12, "2026-10 Beach day",
         ["2026-10 Beach day/02.jpg", "2026-10 Beach day/04.jpg"], "@sunny"),
        ("Reddit", 1, 18, "ready", "First time posting here, be nice 😇", None, "Teasers", ["Teasers/01.jpg"], "u/sunny_days"),
        ("OnlyFans", 3, 21, "scheduled", "Collab with @jadeafterdark 👯 PPV unlock", 25, "2026-11 Collab with Jade",
         ["2026-11 Collab with Jade/01.jpg", "2026-11 Collab with Jade/05.mp4"], "@sunny"),
        ("X", 4, 17, "idea", "Office roleplay teaser?", None, "2026-11 Office roleplay", [], "@sunny_xo"),
    ]:
        _ok(api.post("/api/posts", json={
            "platform": platform, "account": account, "scheduled_at": at(offset, hour), "status": status, "caption": caption,
            "price": price, "set_path": set_path, "file_paths": files,
            "posted_at": at(offset, hour) if status == "posted" else None}))

    # ad renewals (every 3 days) and a tour announcement: not only for content creators
    _ok(api.post("/api/posts", json={
        "platform": "Tryst", "account": "Sunny", "scheduled_at": at(0, 10), "status": "scheduled",
        "caption": "Renew and bump my listing. Update the availability line.", "set_path": "Teasers", "file_paths": ["Teasers/01.jpg"],
        "repeat_dates": [at(3 * i, 10) for i in range(1, 6)]}))
    _ok(api.post("/api/posts", json={
        "platform": "X", "account": "@sunny_xo", "scheduled_at": at(5, 12), "status": "ready",
        "caption": "Miami, I'm coming 🌴 Booking now for my tour, screening required. Link in bio.",
        "set_path": "2026-10 Beach day", "file_paths": ["2026-10 Beach day/01.jpg"]}))

    # ---------- tasks ----------
    for title, offset, extra in [
        ("Book Miami hotel", 2, {"tour_id": miami["id"], "notes": "South Beach, near the clinic"}),
        ("Renew ad listing", 0, {}), ("Pick up dry cleaning", -1, {}),
        ("Send Jordan a thank-you text", 2, {"client_id": clients["Jordan"]["id"]}),
        ("Plan next photo shoot", None, {"notes": "Red set, golden hour"}),
        ("Check Riley's second reference", 1, {"client_id": clients["Riley"]["id"]}),
    ]:
        _ok(api.post("/api/tasks", json={"title": title, "due_date": day(offset).isoformat() if offset is not None else None, **extra}))
    done = _ok(api.post("/api/tasks", json={"title": "Get weekly test results", "due_date": day(-3).isoformat()}))
    _ok(api.post(f"/api/tasks/{done['id']}/done", json={"done": True}))

    # ---------- savings goals ----------
    def goal(body, entries):
        g = _ok(api.post("/api/goals", json=body))
        for offset, amount, note in entries:
            _ok(api.post(f"/api/goals/{g['id']}/entries", json={"amount": amount, "date": day(offset).isoformat(), "note": note}))

    goal({"name": "Taxes", "kind": "tax", "rule_type": "percent", "rule_amount": 25, "starts_on": day(-90).isoformat(),
          "color": "#4f46e5", "priority": 3, "notes": "25% is my own choice. Check with an accountant."},
         [(-60, 1800, "Set aside"), (-30, 1500, "Set aside"), (-20, -1200, "Paid estimated tax")])
    goal({"name": "Emergency fund", "target_amount": 6000, "target_date": day(180).isoformat(), "rule_type": "weekly",
          "rule_amount": 150, "starts_on": day(-56).isoformat(), "color": "#059669", "priority": 2},
         [(-56, 1000, "Starting balance"), (-42, 300, None), (-28, 300, None), (-14, 300, None)])
    goal({"name": "New camera", "target_amount": 1400, "target_date": day(60).isoformat(), "rule_type": "per_booking",
          "rule_amount": 25, "starts_on": day(-45).isoformat(), "color": "#db2777", "priority": 1,
          "notes": "For better content shoots"},
         [(-30, 250, None), (-10, 150, None)])
    # ---------- period tracker: an option, off as for everyone. Past periods are logged so that turning it
    # on in settings shows predictions straight away. ----------
    _ok(api.put("/api/cycle/settings", json={"enabled": False, "warn_on_booking": True, "show_fertile": False,
                                             "typical_cycle": 28, "typical_period": 5}))
    for first, last, flow in ((-78, -74, "medium"), (-50, -46, "heavy"), (-22, -18, "medium")):
        _ok(api.post("/api/cycle/entries", json={"start_date": day(first).isoformat(), "end_date": day(last).isoformat(), "flow": flow}))

    goal({"name": "Retirement goal", "target_amount": 25000, "color": "#0284c7", "notes": "Long term, a little at a time"},
         [(-80, 2000, None), (-40, 1000, None)])


    # ---------- personas: a working name for in-person work, another for content ----------
    scarlett = _ok(api.post("/api/personas", json={"name": "Scarlett", "color": "#db2777", "notes": "In person: escort and Cheryl's Ranch"}))
    kitty = _ok(api.post("/api/personas", json={"name": "Kitty Kam", "color": "#7c3aed", "notes": "Content and cam"}))
    for c in _ok(api.get("/api/clients", params={"role": "client", "limit": 200})):
        # A contact is saved whole, so send everything back with the persona added.
        _ok(api.put(f"/api/clients/{c['id']}", json={**c, "persona_id": scarlett["id"]}))
    for s in _ok(api.get("/api/income-sources")):
        persona = kitty if s["kind"] == "platform" else scarlett
        _ok(api.put(f"/api/income-sources/{s['id']}", json={**{k: s[k] for k in (
            "name", "kind", "fee_percent", "fee_per_shift", "token_value", "payout_note", "notes", "archived",
            "work_type")}, "persona_id": persona["id"],
            "gift_share_percent": 50 if s["kind"] == "brothel" else s["gift_share_percent"]}))

    # ---------- a stay at the brothel: its room & board and doctor are logged by themselves ----------
    stint = period(-34, -28, kind="tour", name="Cheryl's Ranch stint", source_id=house["id"],
                   notes="A week in residence. The house settles at the end.")
    for offset, gross in ((-33, 1200), (-31, 950), (-29, 1500)):
        _ok(api.post("/api/income", json={"source_id": house["id"], "date": at(offset, 7), "kind": "shift",
                                          "gross": gross, "fees": gross / 2, "description": "Shift", "status": "received"}))
    _ok(api.post("/api/income", json={"source_id": house["id"], "date": at(-30, 7), "kind": "gift", "gross": 800,
                                      "fees": 400, "description": "Designer bag (the house takes half its value)", "status": "received"}))

    # ---------- a sugar arrangement ----------
    robert = _ok(api.post("/api/clients", json={"name": "Robert", "bio": "Sugar arrangement since spring. Dinners and travel.",
                                                "persona_id": scarlett["id"]}))
    _ok(api.put(f"/api/clients/{robert['id']}/arrangement", json={
        "amount": 2000, "cadence": "monthly", "next_due": day(12).isoformat(), "notes": "Paid by bank transfer on the 1st-ish"}))
    for offset in (-48, -18):
        _ok(api.post("/api/income", json={"kind": "allowance", "client_id": robert["id"], "date": at(offset, 18),
                                          "gross": 2000, "description": "Allowance", "status": "received"}))

    # ---------- a no-show ----------
    noshow = _ok(api.post("/api/clients", json={"name": "Mike", "contact_phone": "+1-555-0177", "persona_id": scarlett["id"]}))
    missed = _ok(api.post("/api/appointments", json={"client_id": noshow["id"], "service_type": "Dinner date", "duration_minutes": 120,
                                                     "scheduled_date": at(-12, 2), "rate": 600, "amount_paid": 150}))
    _ok(api.put(f"/api/appointments/{missed['id']}/status", params={"status": "cancelled", "cancel_reason": "no_show",
                                                                     "cancellation_fee": 600}))
    _ok(api.put("/api/booking-policy", json={"deposit_percent": 25, "late_cancel_hours": 24,
                                             "late_cancel_fee_percent": 50, "no_show_fee_percent": 100}))

    # ---------- documents ----------
    _ok(api.post("/api/documents", json={"name": "Passport", "kind": "passport", "expires_on": day(500).isoformat()}))
    _ok(api.post("/api/documents", json={"name": "OnlyFans ID check", "kind": "verification", "persona_id": kitty["id"],
                                         "expires_on": day(40).isoformat(), "notes": "They ask again every year"}))

    # ---------- taxes: mileage and an estimated payment ----------
    for offset, miles, why in ((-60, 18.4, "Outcall"), (-41, 7.2, "Photo shoot"), (-25, 22.0, "Outcall"), (-9, 11.5, "Supply run")):
        _ok(api.post("/api/tax-summary/mileage", json={"date": day(offset).isoformat(), "miles": miles, "purpose": why}))
    _ok(api.put(f"/api/tax-summary/mileage/rate/{today.year}", json={"rate": 0.70}))
    past = [q for q in (1, 2, 3) if day(0) > _quarter_due(today.year, q)]
    for q in past:
        _ok(api.post("/api/tax-summary/payments", json={"year": today.year, "quarter": q, "amount": 900,
                                                         "paid_on": (_quarter_due(today.year, q) - timedelta(days=2)).isoformat(),
                                                         "note": "Paid at irs.gov"}))
    # ---------- marketing: campaigns, places to post, saved text, ads, inquiries ----------
    for label, body in (("Booking line", "Booking now, screening required. Link in bio."), ("Hashtags", "#miami #touring #companion"),
                        ("Checking in", "Hi! It's been a while. I have a little time next week if you'd like to catch up."),
                        ("Screening reply", "Thanks for getting in touch. To book I need your full name, a work link or two references, and a 25% deposit.")):
        _ok(api.post("/api/snippets", json={"label": label, "body": body}))
    _ok(api.post("/api/post-places", json={"platform": "Reddit", "name": "r/example_ads", "wait_days": 3,
                                           "rules": "Title starts with the city. One post every 3 days. Verified posters only."}))
    _ok(api.post("/api/post-places", json={"platform": "Telegram", "name": "My channel", "rules": "No prices in public posts."}))
    tour_push = _ok(api.post("/api/campaigns", json={"name": "Miami tour", "goal": "Fill 8 bookings before I land", "tour_id": miami["id"],
                                                     "start_date": day(-5).isoformat(), "end_date": day(13).isoformat()}))
    _ok(api.post("/api/posts", json={
        "platform": "X", "account": "@sunny_xo", "status": "posted", "scheduled_at": at(-4, 12), "posted_at": at(-4, 12),
        "caption": "Miami, see you soon. Booking now.", "campaign_id": tour_push["id"], "inquiries": 4}))
    _ok(api.post("/api/posts", json={
        "platform": "X", "account": "@sunny_xo", "status": "scheduled", "scheduled_at": at(2, 12), "campaign_id": tour_push["id"],
        "caption": "One week until Miami. A few evenings left.",
        "also": [{"platform": "Reddit", "place": "r/example_ads", "caption": "Miami: visiting next week", "scheduled_at": at(2, 14)},
                 {"platform": "Telegram", "place": "My channel"}]}))
    _ok(api.post("/api/posts", json={"platform": "Bluesky", "status": "ready", "scheduled_at": at(-1, 18), "campaign_id": tour_push["id"],
                                     "caption": "Miami dates are up."}))

    for site, extra in (("Tryst", dict(end_date=day(2).isoformat(), cost=60, renew_days=30,
                                       ad_text="Warm, witty and well travelled. Dinner dates and overnights. Screening required.")),
                        ("Eros", dict(title="Miami", city="Miami", end_date=day(14).isoformat(), cost=250, renew_days=30, tour_id=miami["id"])),
                        ("Slixa", dict(end_date=day(-2).isoformat(), cost=90, renew_days=30))):
        ad = _ok(api.post("/api/listings", json={"site": site, **extra}))
        if site != "Slixa":
            _ok(api.post(f"/api/listings/{ad['id']}/renew", json={"days": 0 + extra["renew_days"], "paid_on": day(-20).isoformat(),
                                                                  "log_expense": True}))
            _ok(api.put(f"/api/listings/{ad['id']}", json={"site": site, **extra}))      # the dates above are the ones to show

    for i, (name, via, stages, lost, wanted) in enumerate((
            ("@quiet_guy", "Tryst", ("replied", "screening"), None, "2 hours, dinner, Friday in Miami"),
            ("Marcus W", "Tryst", ("replied", "screening", "deposit", "booked"), None, "Overnight, the Saturday"),
            ("Dan P", "X", ("replied",), "Wanted a discount", "1 hour"),
            ("@late_night", "X", (), "Went quiet", "Asked for rates at 3am"),
            ("Theo", "Referral", ("replied", "screening", "deposit"), None, "Dinner date, Miami, the Thursday"),
            ("New person", "Eros", (), None, "90 minutes, incall"),
            ("Sam W", "Tryst", (), None, "Duo with Jade?"))):
        inquiry = _ok(api.post("/api/inquiries", json={"name": name, "found_via": via, "received_at": at(-(i + 1), 15),
                                                       "contact": f"+1-555-02{i:02d}", "wanted": wanted}))
        for stage in stages:
            _ok(api.post(f"/api/inquiries/{inquiry['id']}/stage", json={"stage": stage}))
        if lost:
            _ok(api.post(f"/api/inquiries/{inquiry['id']}/stage", json={"stage": "lost", "lost_reason": lost}))

    # ---------- custom content: a menu and a few orders ----------
    for label, price, notes in (("5 minute video", 100, None), ("10 minute video", 180, None), ("Say my name", 20, "add-on"),
                                ("Photo set (10)", 60, None), ("Rush, 24 hours", 40, "add-on")):
        _ok(api.post("/api/customs/menu", json={"label": label, "price": price, "notes": notes}))

    def custom(paid=0, delivered=False, **body):
        order = _ok(api.post("/api/customs", json={"source_id": onlyfans, "persona_id": kitty["id"], **body}))
        if paid:   # these sales are already in the OnlyFans payouts above, so they aren't logged a second time
            _ok(api.post(f"/api/customs/{order['id']}/payment", json={"amount": paid, "log_income": False}))
        if delivered:
            _ok(api.post(f"/api/customs/{order['id']}/delivered", json={"delivery_note": "Sent in DMs"}))

    custom(buyer="@newfan", title="Photo set (10)", price=60, requested_at=at(-1, 20))
    custom(120, buyer="@alex_k", title="5 minute video + Say my name", price=120, due_date=day(-1).isoformat(),
           details="Say 'Alex'. The red dress.", requested_at=at(-6, 20))
    custom(50, buyer="@mystery", title="10 minute video", price=180, due_date=day(4).isoformat(), status="to_make", requested_at=at(-3, 20))
    custom(100, True, buyer="@regular_sam", title="5 minute video", price=100, can_resell=True, requested_at=at(-14, 20))

    # ---------- a shoot being planned ----------
    shoot = _ok(api.post("/api/shoots", json={
        "title": "Red lace boudoir with Jade", "status": "booked", "shoot_date": day(6).isoformat(), "start_time": "14:00", "hours": 3,
        "concept": "Warm window light, slow and close. Two looks each, then together.", "location_name": "Studio 5",
        "location_address": "12 Mill St", "location_notes": "Ring the bell. Parking behind. Best light before 4.",
        "set_path": "2026-11 Collab with Jade", "persona_id": kitty["id"]}))
    _ok(api.post(f"/api/shoots/{shoot['id']}/people", json={"name": "Alex", "role": "photographer", "fee": 300, "confirmed": True}))
    _ok(api.post(f"/api/shoots/{shoot['id']}/people", json={
        "contact_id": jade["id"], "role": "co-star", "id_checked": True, "confirmed": True,
        "agreement": "Both can post it. Sales are 60/40 to whoever sells. Nothing goes out before the 1st."}))
    for kind, label, extra in (("goal", "3 pay-per-view sets", {}), ("goal", "10 teasers for X", {}), ("goal", "A 30 second trailer", {}),
                               ("shot", "On the bed, red lace, 20 photos", {}), ("shot", "Window light, robes, together", {}),
                               ("wardrobe", "Red lace set", {"done": True}), ("wardrobe", "Black robe", {}), ("wardrobe", "Ring light", {}),
                               ("prep", "Send Jade the release", {"due_date": day(2).isoformat()}), ("prep", "Pay the studio deposit", {"done": True}),
                               ("budget", "Studio hire", {"amount": 150}), ("budget", "Lingerie", {"amount": 80}),
                               ("marketing", "Teaser on X the day before", {"due_date": day(5).isoformat()}),
                               ("marketing", "Pay-per-view drop on OnlyFans", {"due_date": day(12).isoformat()})):
        _ok(api.post(f"/api/shoots/{shoot['id']}/items", json={"kind": kind, "label": label, **extra}))
    _ok(api.post(f"/api/shoots/{shoot['id']}/campaign"))
    _ok(api.post("/api/shoots", json={"title": "Beach day", "status": "idea", "concept": "Golden hour, the white set."}))

    # ---------- the rate card ----------
    for label, minutes, price, notes in (("One hour", 60, 450, None), ("Dinner date", 120, 800, "Dinner is on you"),
                                         ("Extended evening", 240, 1400, None), ("Overnight", 720, 3200, "8pm to 8am"),
                                         ("Duo with Jade", 60, 900, "Subject to her calendar")):
        _ok(api.post("/api/rates", json={"label": label, "minutes": minutes, "price": price, "notes": notes, "persona_id": scarlett["id"]}))

    # ---------- house rules at the brothel, and a price rule for regulars ----------
    for s in _ok(api.get("/api/income-sources")):
        if s["kind"] == "brothel":
            _ok(api.put(f"/api/income-sources/{s['id']}", json={
                **{k: s[k] for k in ("name", "kind", "fee_percent", "fee_per_shift", "token_value", "payout_note", "notes", "archived",
                                     "work_type", "persona_id", "gift_share_percent")},
                "tip_share_percent": 0, "holds_cash": True, "cash_limit": 20,
                # No sample house rules: insider terms stay off anything public, and the demo shows
                # "only in the full version" there instead.
                "cuts": []}))
    _ok(api.post("/api/rates/tag-rules", json={"tag": "regular", "kind": "percent", "value": 10}))

    # ---------- health tests on this person's own schedule ----------
    for kind in _ok(api.get("/api/test-kinds")):
        if kind["key"] == "weekly":      # where she works, the panel is every 14 days
            _ok(api.put(f"/api/test-kinds/{kind['id']}", json={"label": "Two-week panel", "every_days": 14, "cost": 85}))


def _quarter_due(year, quarter):
    import taxes
    return taxes.due_date(year, quarter)

def _last_reset(get_db):
    db = get_db()
    try:
        row = db.execute("SELECT value FROM settings WHERE key = 'demo_reset_at'").fetchone()
        has_users = db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        return (datetime.fromisoformat(row[0]) if row else None), bool(has_users)
    finally:
        db.close()


def _due(get_db) -> bool:
    last, has_users = _last_reset(get_db)
    if not has_users or last is None:
        return True
    now = datetime.now(timezone.utc)
    todays_reset = now.replace(hour=RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if todays_reset > now:
        todays_reset -= timedelta(days=1)
    return last < todays_reset


def _sync_password(get_db):
    """If DEMO_PASSWORD was changed in .env.demo, the existing demo account takes the new one at startup."""
    import auth
    db = get_db()
    try:
        row = db.execute("SELECT id, password_hash FROM users WHERE username = ?", (USERNAME,)).fetchone()
        if row and PASSWORD and not auth.verify_password(PASSWORD, row["password_hash"]):
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (auth.hash_password(PASSWORD), row["id"]))
            db.commit()
            log.warning("Demo password updated from DEMO_PASSWORD")
    finally:
        db.close()


def start(app, get_db):
    """Fill an empty demo database now, then keep checking (once a minute) for the nightly reset."""
    if not ENABLED:
        return
    try:
        _sync_password(get_db)
    except Exception:
        log.exception("Couldn't update the demo password")

    def loop():
        while True:
            try:
                if _due(get_db):
                    reset(app, get_db)
            except Exception:
                log.exception("Demo reset failed")
            time.sleep(60)

    threading.Thread(target=loop, name="demo-reset", daemon=True).start()
