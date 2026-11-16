# Sworkr: start here

Sworkr is a private manager for independent work: clients, screening and inquiries, a calendar, money, rates and
taxes, content and ad planning, custom orders, health tests on your own schedule, and a safety check-in. This copy runs on your own computer. Nothing is sent anywhere, and nobody else has an
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
   backups. Files land in the `backups` folder here. Without the passphrase nobody can read them, and
   neither can you, so write it down. That folder is on this computer, so also get copies off it: fill in
   *Copies off this computer* on the same page if you have a Nextcloud (or other WebDAV) account, or copy
   the files to a USB stick now and then. To get everything back later, use *Restore a backup* there.
2. **Turn on two-step sign-in.** *Account → Security & privacy → Two-step sign-in*, with an authenticator
   app. Save the recovery codes it gives you on paper.
3. **Encrypt your computer's disk** (BitLocker on Windows, FileVault on a Mac) and use a locked user
   account. Sworkr encrypts its own database file, but its key is kept on this computer too, so the disk and a
   locked account are what keep a stolen or borrowed computer from opening it.

## Using it day to day

- Sworkr keeps running in the background and comes back when Docker Desktop starts. Just open
  <http://localhost:8080>.
- To stop it: `stop.bat` (Windows) or `stop.command` (Mac, Linux). Your data stays.
- **Only this computer can open it.** That's deliberate. Don't open the port to your network or the internet;
  to use it from your phone, follow *Account → Connections → On your phone* instead.
- *Account → Security & privacy → Discreet mode* gives the browser tab a plain name and a panic switch
  (press Esc three times).

## What's where

- **Dashboard**: what needs doing today. *Customize* (top right) hides cards and changes their order.
- **Calendar**: bookings, tours, time off and health tests, with your planning on the same days: posts to put up, shoots, and the day each ad runs out (tick which kinds to show). *Posts* and *Shoots* at the top hold the full lists. A booking can carry a tip.
- **Contacts**: clients and collaborators, the people who've inquired and how far each got, and regulars who've gone quiet.
- **Content**: your library, promoting (campaigns, ads, your platforms) and custom orders.
- **Money**: income and expenses, comparisons, your rate card and deposits, goals, splits and taxes (with a CSV download).
  Each workplace has its own house rules: its share, any cuts it takes, and whether the office holds your cash.
- **The + $ button** on every page logs cash in, a tip, or cash out in two taps.
- **Account**: how you work, health tests, security, reminders, connections (email, calendar, content folder) and your data.

## On a phone

Sworkr works in a phone's browser and can sit on the home screen like an app, with no app store involved.
*Account → Connections → On your phone* walks you through it: a free app called Tailscale links your phone and
this computer privately (nothing is opened to the internet), then you add sworkr to the home screen and add a
passkey on the phone. This computer has to be on for the phone to reach it.

## Your data is encrypted

Sworkr's database file is encrypted (AES-256). The key is kept apart from it, in Docker's `sworkr_sworkr_keys`
volume. **Without that key the database can't be opened**, so:

- never delete the `sworkr_sworkr_keys` volume, just as you never delete `sworkr_sworkr_data`;
- keep encrypted backups turned on. A backup opens with your backup passphrase alone, on any computer, so it
  is how you get your data back if this computer or its key is ever lost.

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
- **Never run** `docker compose down -v` or delete the `sworkr_sworkr_data` or `sworkr_sworkr_keys` volume in
  Docker Desktop: they are your data and the key that opens it.
- **After restoring a backup on a different computer**, sworkr asks again for the app passwords you had
  saved (calendar, mail, content library, backup passphrase) and for a fresh authenticator-app setup.
  That is on purpose: they are locked with a key that never leaves the computer they were saved on.

`README.md` has the full details: every feature, CSV import and export, restoring a backup, and settings.
