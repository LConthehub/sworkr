# Sworkr

**The back office for s work, on your own computer.** Clients and screening, bookings and deposits, tours and
workplaces, content and posting, money and taxes, health and safety: in one place that only you can open.

Made by a former s worker with ADHD: the tool I needed when I was working.

- **Private by design.** Everything stays on your computer, encrypted. There's no Sworkr company server, no
  account with us, and nothing is sent to us.
- **For every kind of work.** Independent, house or agency, dancing, cam, phone and chat, fan sites, performing,
  sugar, fetish, massage, selling online. Tick what you do and Sworkr shows the parts that fit.
- **Free for workers.** Free to run for yourself and small groups of workers. See [License](#license).

Website and full documentation: **[sworkr.com](https://sworkr.com)** · Try the demo: **[demo.sworkr.com](https://demo.sworkr.com)**

## Install

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows, Mac) or Docker (Linux,
a home server or a NAS). Never used it? You won't need to type commands.

1. Install Docker Desktop and open it once.
2. Download **[sworkr-start.zip](https://sworkr.com/downloads/sworkr-start.zip)** and unzip it somewhere you'll keep it.
3. Double-click **Start sworkr** (on a Mac the first time: right-click *Start sworkr.command*, choose *Open*;
   on Linux: `./start.sh`). If Docker Desktop is closed, it opens it and waits. The first start takes a few minutes.
4. Your browser opens Sworkr when it's ready. Make your account: the first one is yours, and it's the admin.

Prefer a terminal? Put [`docker-compose.yml`](docker-compose.yml) in a folder and run:

```bash
docker compose up -d
```

Then open <http://localhost:8008>. For other ports, a photo folder, or your own web address, the
[setup builder](https://sworkr.com/docs/install.html) writes the file for you.

On a phone: [use Tailscale](https://sworkr.com/docs/phone.html) (private, nothing opened to the internet), or
[your own web address](https://sworkr.com/docs/web-address.html).

## Update

Double-click **Update sworkr** (Linux: `./start.sh update`), or in the folder:

```bash
docker compose pull
docker compose up -d
```

Your records stay. Before any upgrade a copy of the database is saved next to it.

## Keep your records safe

- **Turn on backups** on day one: *Settings → Data & users → Backups*. Backups are encrypted with your passphrase
  and open on any computer. Keep a copy off this computer (a USB stick, or Nextcloud or any WebDAV storage).
- **Never run `docker compose down -v`.** The `-v` deletes your records and the key that opens them.
- The database is encrypted (SQLCipher, AES-256); its key is kept apart from it. Saved passwords are sealed with a
  second key. Use disk encryption on the computer too (BitLocker, FileVault).

More: [Privacy & backups](https://sworkr.com/docs/privacy-and-backups.html) ·
[Own your data](https://sworkr.com/docs/own-your-data.html) ·
[If something goes wrong](https://sworkr.com/docs/troubleshooting.html)

## Help

- Forgot your password: `docker compose exec sworkr python manage.py reset-password`
- Lost your phone and your recovery codes: `docker compose exec sworkr python manage.py turn-off-two-step <username>`
- Everything else: [sworkr.com/docs](https://sworkr.com/docs/)

## License

[Business Source License 1.1](LICENSE): free for individual workers and groups of up to five workers. Agencies,
houses, clubs, platforms and hosting companies need a commercial license. Each version becomes AGPL-3.0 four years
after its release.

---

## For developers

- **Backend:** Python, FastAPI, SQLite with SQLCipher (`backend/`). Numbered migrations in `backend/migrations.py`.
- **Frontend:** React, Vite, Tailwind (`frontend/`).
- **One container:** the root `Dockerfile` builds the pages and serves them with the API on port 8008. Images are
  published to `ghcr.io/lconthehub/sworkr` by `.github/workflows/image.yml`.

```bash
docker compose -f docker-compose.dev.yml up            # live-reloading dev servers
docker compose -f docker-compose.dev.yml run --rm tests  # the backend tests (a throwaway database)
```

The website (`site/`) is static: `python site/build_docs.py` writes the docs pages, and
`python site/build_downloads.py` makes `sworkr-start.zip`. Plans and decisions live in [ROADMAP.md](ROADMAP.md).

| Setting | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `/data` | The database |
| `KEY_DIR` | `/keys` | The keys that open it and the saved passwords |
| `BACKUP_DIR` | `/backups` | Automatic backups |
| `BACKUP_KEEP` | `14` | How many automatic backups to keep |
| `SESSION_IDLE_MINUTES` | `15` | Default auto log-out (each person can change theirs) |
| `PASSKEY_ORIGINS` | | The web address passkeys are made for, when not localhost |
| `SMTP_*` | | An email account for safety alerts and sign-in codes (in `.env`) |
