# Sworkr

A small management app for tracking clients, appointments and expenses.

- **Backend:** FastAPI + SQLite (`backend/`), served on port **8008**
- **Frontend:** React + Vite + Tailwind (`frontend/`), served on port **5173**

## Running it

Requires Docker Desktop.

```bash
docker compose up --build
```

Then open <http://localhost:5173>.

Both containers reload automatically when you save a file: the backend via
`uvicorn --reload`, the frontend via Vite hot reload. The Vite dev server
forwards `/api` requests to the backend.

### First login

On first launch there are no accounts, so the app asks you to create one. That
first account becomes the admin. After that, the setup endpoint is locked and
everyone has to sign in. Passwords must be at least 8 characters.

## Features

| Page | Route | What it does |
|---|---|---|
| Calendar | `/` | Schedule appointments and update their status (scheduled / completed / cancelled) |
| Clients | `/clients` | Client profiles with contact details, bio and tags |
| Expenses | `/expenses` | Log expenses by category, with a summary |
| Account | `/account` | Change password, log out |

There is also a global search across clients, appointments and expenses.

## Data

The SQLite database is stored at `$DATA_DIR/sworkr.db`. Under Docker,
`DATA_DIR=/data` lives in the named volume `sworkr_data`, so your data
survives restarts and rebuilds.

> Running `docker compose down -v` **deletes** that volume and all your data.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `backend/data` | Where the SQLite database is kept |
| `COOKIE_SECURE` | `0` | Set to `1` when served over HTTPS so the login cookie is only sent over TLS |
| `API_PROXY_TARGET` | `http://localhost:8008` | Where the Vite dev server sends `/api` requests |

## Running without Docker

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --port 8008 --reload
```

```bash
cd frontend
npm install
npm run dev
```

## Tests

The backend tests run inside Docker, with the same Python and library versions as the app.
They use a throwaway database, so they never touch real data.

```bash
docker compose run --rm tests
```

## API

The interactive API docs are at <http://localhost:8008/docs> while the
backend is running. Everything under `/api` requires being logged in, except
health, login, logout, auth status and first-time setup.
