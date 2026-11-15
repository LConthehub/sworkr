# Sworkr: start here

Sworkr is a private manager for independent work: clients and screening, a calendar, money, taxes and a
safety check-in. This copy runs on your own computer. Nothing is sent anywhere, and nobody else has an
account on it, including whoever gave you this copy.

## Set it up (about 10 minutes, once)

1. **Install Docker Desktop** from <https://www.docker.com/products/docker-desktop/> and open it. It's the free
   program sworkr runs inside. Wait until it says *Engine running*.
2. **Unzip this folder** somewhere you'll keep it, for example `Documents\sworkr`.
3. **Start sworkr.**
   - Windows: double-click `start.bat`.
   - Mac: right-click `start.command`, choose *Open*, then *Open* again (macOS asks the first time).
   - Linux: `sh start.command`.

   The first start downloads what it needs and takes a few minutes.
4. Your browser opens <http://localhost:8080>. **Create your account.** That first account is yours and is
   the admin. Use a password of 12 or more characters and keep it somewhere safe.

A new copy contains a few made-up clients and bookings so you can look around. Remove them under
**Account → Data & users → Example data** when you're ready.

## Do these three things on day one

1. **Turn on backups.** *Account → Data & users → Backups*: choose a passphrase and tick automatic daily
   backups. Files land in the `backups` folder here. Copy them to a USB stick or cloud drive now and then;
   without the passphrase nobody can read them, and neither can you, so write it down.
2. **Turn on two-step sign-in.** *Account → Security & privacy → Two-step sign-in*, with an authenticator
   app. Save the recovery codes it gives you on paper.
3. **Encrypt your computer's disk** (BitLocker on Windows, FileVault on a Mac) and use a locked user
   account. Sworkr's own database is not encrypted on disk yet, so the disk has to be.

## Using it day to day

- Sworkr keeps running in the background and comes back when Docker Desktop starts. Just open
  <http://localhost:8080>.
- To stop it: `stop.bat` (Windows) or `stop.command` (Mac, Linux). Your data stays.
- **Only this computer can open it.** That's deliberate. Don't open the port to your network or the internet
  to reach it from a phone; ask for help setting that up safely first (it needs https and passkeys).
- *Account → Security & privacy → Discreet mode* gives the browser tab a plain name and a panic switch
  (press Esc three times).

## Updating to a newer copy

1. Run stop.
2. Unzip the new copy **over the old folder** (replace the files). Keep the `backups` folder.
3. Run start. Your data is kept, and sworkr upgrades it by itself, saving a copy first.

## If something goes wrong

- **"Docker Desktop isn't running"**: open Docker Desktop and wait for *Engine running*.
- **Forgot your password**: open a terminal in this folder and run
  `docker compose -f docker-compose.prod.yml exec api python manage.py reset-password`
- **Lost your phone and your recovery codes**:
  `docker compose -f docker-compose.prod.yml exec api python manage.py turn-off-two-step <username>`
- **Never run** `docker compose down -v` or delete the `sworkr_sworkr_data` volume in Docker Desktop: that is
  your data.
- **After restoring a backup on a different computer**, sworkr asks again for the app passwords you had
  saved (calendar, mail, content library, backup passphrase) and for a fresh authenticator-app setup.
  That is on purpose: they are locked with a key that never leaves the computer they were saved on.

`README.md` has the full details: every feature, CSV import and export, restoring a backup, and settings.
