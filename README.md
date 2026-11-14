# Sworkr

A private management app for independent work: clients and screening, a calendar, income and
expenses, and a safety check-in.

- **Backend:** FastAPI + SQLite (`backend/`), port **8008**
- **Frontend:** React + Vite + Tailwind (`frontend/`), port **5173**

## Running it

Requires Docker Desktop.

```bash
docker compose up --build
```

Then open <http://localhost:5173>. Both containers reload when you save a file.

For everyday use there is a faster built version (same data):

```bash
docker compose -f docker-compose.prod.yml up --build -d     # then open http://localhost:8080
docker compose -f docker-compose.prod.yml down              # stop
```

Don't run both at once.

**Only this computer can open sworkr.** The ports are bound to `127.0.0.1`, so other devices on
your network can't reach it. To use it from a phone you would need to put it behind HTTPS on
purpose; don't just open the port.

### First login

On first launch there are no accounts, so the app asks you to create one. That account is the
admin. Passwords must be at least 8 characters.

A new database starts with a few example clients, appointments and expenses. Remove them under
**Account → Example data**.

## What's in it

| Page | Route | What it does |
|---|---|---|
| Dashboard | `/` | This week's bookings, tasks, unread email and savings goals at a glance |
| Calendar | `/calendar` | Month, week, day and list views. Add, edit, repeat, complete or cancel appointments, tours and time off |
| Contacts | `/contacts` | Clients, co-workers and crew, with screening status and a "do not see" flag. CSV import/export |
| Contact page | `/contacts/:id` | One contact's details, visit history, money paid and owed, and dated notes |
| Content | `/content` | Browse your photo/video library (Nextcloud, WebDAV or a mounted folder) and plan posts |
| Money | `/money` | Income, expenses and profit, what's still owed, compare periods and tours, goals, splits, tax-year export |
| Account | `/account` | Password, auto log-out, email, content library, calendar sync, safety check-in, backups, users |

There is also a global search (press `/`) across clients, appointments and expenses.

### Appointments

- **Rate and payment.** Each appointment can have a rate and the amount paid so far. Income on the
  Money page is what has actually been paid, counted in the month of the appointment.
- **Where.** Incall / outcall and an address.
- **Warnings.** Booking a client marked *do not see*, or a time that overlaps another booking,
  shows a warning first. You can still save.
- **Repeats.** Weekly, every two weeks or monthly, up to 52 times. Each repeat is its own
  appointment afterwards; deleting offers "this and later repeats".

### Screening

Each client has a screening status (not screened, pending, verified, declined), references,
screening notes and a **do not see** flag with a reason.

### Safety check-in

Tick **Safety check-in** on an appointment. When it has started, a banner with an **I'm safe**
button shows on every page. If the appointment ends and you haven't checked in (or marked it
completed) within the waiting time, sworkr emails your trusted contact.

Set it up under **Account → Safety check-in**, then send a test email. It needs an email account
to send from: copy `.env.example` to `.env`, fill in the `SMTP_*` settings, and restart.

Know the limits: the alert is sent by this computer, so it only works while sworkr is running and
online. An alert missed while the computer was off is sent when it comes back, up to a day late.
Treat it as a backup, not your only safety plan.

### Accounts and privacy

- **Auto log-out.** Unused for two hours (changeable under Account) and you're logged out.
- **More users.** The admin can add logins under **Account → Users**. Every user has their own
  completely separate clients, appointments, expenses and settings.
- **Forgot the password?** On the computer sworkr runs on:
  `docker compose exec api python manage.py reset-password`

### Nextcloud calendar sync

Appointments can be copied into a calendar called **sworkr** in your Nextcloud, so they
reach your phone. Set it up on the Account page (admin account only):

1. In Nextcloud, go to *Settings → Security → Devices & sessions*, type `sworkr`, and click
   *Create new app password*.
2. In sworkr, enter your Nextcloud address, your Nextcloud username and that app password.
   Click *Test connection*, tick *Sync appointments to Nextcloud*, and *Save*.

Changes are pushed in the background a moment after you save them. A full sync runs at
startup, on *Sync now*, and every hour, and it also removes events whose appointment was
deleted. Sync goes one way: edits made to these events in Nextcloud are replaced at the
next sync. *Discreet calendar entries* shows just "Appointment", with no client name or notes.

The app password is stored in sworkr's database. To revoke it, delete it in Nextcloud
under *Devices & sessions*.

Only the appointments of the admin who set sync up are copied; other users' never are.

### CSV import and export

The Clients and Money pages have **Export CSV** and **Import CSV** buttons. The files
open in Excel, Numbers and Google Sheets.

- **Clients:** `id, name, email, phone, tags, notes, active, created, screening, do_not_see, do_not_see_reason,
  references, screening_notes`. Only `name` is required. `screening` is one of unscreened, pending, verified, declined.
  Rows are matched to existing clients by `id`, then by email. A match is updated, and
  columns missing from the file are left as they are. Anything else is added as a new client.
- **Expenses:** `id, date, description, amount, category, client, client_email, notes`.
  `client` is the client's name; `client_email` picks the right one if two share a name.
  Rows with an `id` update that expense. A row identical to an existing expense is skipped,
  so importing the same file twice doesn't add duplicates.
- Dates can be `2026-03-05` or `3/5/2026` (month first). Amounts can include `$` and commas.
  Category is one of equipment, marketing, travel, cleaning, other.
- An import is all or nothing: if any row has a problem, nothing is saved and every problem
  is listed with its line number.

To edit in bulk: export, change the file, and import it again.

The **Export for taxes** button on the Money page makes one file per year with every payment
received and every expense, plus totals.

## Data and backups

The SQLite database is at `$DATA_DIR/sworkr.db`. Under Docker that is the named volume
`sworkr_data`, which survives restarts and rebuilds.

> Running `docker compose down -v` **deletes** that volume and all your data.

**Back it up.** Under **Account → Backups** (admin):

- *Download backup* gives you one encrypted `.swbak` file. Without its passphrase nobody can read it.
- *Automatic daily backups* writes one every day into the `backups/` folder here and keeps the
  newest 14. That folder is on the same disk, so copy the files somewhere else now and then.

Restore one (this replaces what's in sworkr; the current database is kept as a copy first):

```bash
docker compose exec api python manage.py restore-backup /backups/sworkr-2026-01-31-120000.swbak
docker compose restart api
```

The database file itself is **not** encrypted on disk. Anyone who can log in to this computer as
you can copy it. Use disk encryption (BitLocker on Windows) and a locked user account.

### Upgrades

The database carries a version number. When sworkr starts with a newer version of the code it
upgrades the database automatically, after saving a copy next to it as
`sworkr.before-v<N>.db`. Schema changes go in `backend/migrations.py`.

## Maintenance commands

```bash
docker compose exec api python manage.py list-users
docker compose exec api python manage.py reset-password [username]
docker compose exec api python manage.py backup /backups
docker compose exec api python manage.py restore-backup /backups/<file>
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `backend/data` | Where the SQLite database is kept |
| `BACKUP_DIR` | `/backups` | Where automatic backups are written |
| `BACKUP_KEEP` | `14` | How many automatic backups to keep |
| `SESSION_IDLE_MINUTES` | `120` | Default auto log-out time (each user can change theirs) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_SECURITY` | | Email account for safety alerts. Put these in `.env` |
| `COOKIE_SECURE` | `0` | Set to `1` when served over HTTPS |
| `API_PROXY_TARGET` | `http://localhost:8008` | Where the Vite dev server sends `/api` requests |
| `BACKGROUND_JOBS` | `1` | Set to `0` to not start the background workers (the tests do this) |

## Tests

The backend tests run inside Docker, with the same Python and library versions as the app.
They use a throwaway database, so they never touch real data.

```bash
docker compose run --rm tests
```

## API

The interactive API docs are at <http://localhost:8008/docs> while the backend is running.
Everything under `/api` requires being logged in, except health, login, logout, auth status and
first-time setup. Every record belongs to the user who created it.
