# Sworkr roadmap

Ideas and decisions, so nothing is lost between work sessions. Newest decisions first.

## Principles (2026-11-16)
- Privacy first, "seize the means": your data stays with you. Encourage self-hosting the other services too
  (Nextcloud or Synology for files and calendar, ntfy for notifications, a local AI model).
- Keep anything insider-only off public pages (site, demo). Coded names only inside the private app.
- Publicly, say "fan sites" or "OF", never the full platform name.
- Docker is the preferred install on Windows, Mac and Linux. No separate standalone Mac app.

## Docker install (decided 2026-11-16, not done yet)
- One `docker-compose.yml` for users (simple), `restart: unless-stopped`.
- Default port **8008**.
- Publish a prebuilt image (e.g. on GitHub Container Registry) so install is a `docker compose up -d` or a
  `docker run` with no building. Update the setup builder (site/setup.js) and docs to match.
- Make Docker the main download on sworkr.com for every system.

## Licence
- Business Source License 1.1 (LICENSE): free for individual workers and groups of up to 5 workers;
  companies (agencies, brothels, clubs, platforms, hosts) need a commercial licence; each version becomes
  AGPL-3.0 four years after release. Have a lawyer check the wording before launch.
- GitHub: user will link the account; scan history for secrets before the first public push.

## In progress
- Strip club accounting: contractor or employee, house fees by arrival time, dances with the house's cut,
  VIP share, tip-outs, fines, a shift statement.

## Next
- Tour pack lists from templates, with a budget against actual spending.
- Meal and snack planner (optional), feeding groceries into the pack list and budget.
- Social: post to Bluesky and Mastodon; Reddit posting with the person's own app key; import stats from
  platforms' CSV exports.
- Saved replies for inquiries.
- Discreet receipts for clients.
- Wipe everything: password, type a phrase, 10-second countdown you can cancel.
- Automatic off-site backups (Nextcloud, Synology, WebDAV).
- Bad-date list export (import exists). No sharing between workers (legal risk).
- Meds: injection site rotation and dose titration (GLP-1, hormones, testosterone, estradiol), with a log.
- Website review page by page with the owner (home page: questions pending).

## Bigger ideas
- Local AI: an optional assistant that talks to a model running on your own machine (LM Studio, llama.cpp,
  Ollama: all speak the OpenAI-style API on localhost). Cloud AI only as an explicit opt-in, clearly marked,
  off by default. Ideas: draft replies to inquiries, summarise a client's notes, sort expenses, write post captions.
- Translations: Spanish, Russian, French first. Later.
