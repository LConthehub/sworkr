# Sworkr roadmap

Ideas and decisions, so nothing is lost between work sessions. Newest decisions first.

## Open questions for the owner
Answer here (edit this file on GitHub, even from a phone) or in chat; answered ones move to the decisions below.
(None open right now.)

## Answers (2026-11-16)
- About the maker (public): a former s worker with ADHD; the tool they needed while working; began as an app
  idea shelved in 2017 plus years of messy spreadsheets. Home page says this (no mention of which branches).
- Home page "Tours & houses" no longer mentions house cuts or the office holding cash.
- Own web address stays in the docs, not the home page privacy list.
- Social after Bluesky and Mastodon: Reddit. X only if someone sponsors the API cost (don't pay for it).
- AI is for statistics and search, not for writing. No drafting replies or captions: the creative part stays
  the worker's, and censoring models make drafting unreliable for this work anyway.

## Principles (2026-11-16)
- Privacy first, "seize the means": your data stays with you. Encourage self-hosting the other services too
  (Nextcloud or Synology for files and calendar, ntfy for notifications, a local AI model).
- Keep anything insider-only off public pages (site, demo). Coded names only inside the private app.
- Publicly, say "fan sites" or "OF", never the full platform name.
- Public messaging says "s work" / "s workers" (coded, deliberate). Not "independent work", not spelled out.
- Docker is the preferred install on Windows, Mac and Linux. No separate standalone Mac app.

## Docker install (decided 2026-11-16; one container + port 8008 done, image publishing waits on GitHub)
- One `docker-compose.yml` for users (simple), `restart: unless-stopped`.
- Default port **8008**.
- Publish a prebuilt image (e.g. on GitHub Container Registry) so install is a `docker compose up -d` or a
  `docker run` with no building. Update the setup builder (site/setup.js) and docs to match.
- Make Docker the main download on sworkr.com for every system.

## License
- Business Source License 1.1 (LICENSE): free for individual workers and groups of up to 5 workers;
  companies (agencies, brothels, clubs, platforms, hosts) need a commercial licence; each version becomes
  AGPL-3.0 four years after release. Have a lawyer check the wording before launch.
- GitHub: user will link the account; scan history for secrets before the first public push.

## Done recently
- Social (2026-11-16): connect Bluesky (app password), Mastodon (access token), Reddit (own script app, text
  posts); post a planned post now or let it post itself at its time; a content label per account (Bluesky
  self-labels, Mastodon sensitive, Reddit NSFW); likes/reposts/replies fetched, or imported from any CSV export
  by post link. Content > Social.
- Off-site backups to WebDAV (Nextcloud, Synology) were already built (offsite.py).
- Tour plan (2026-11-16): pack lists from templates, a budget by main category against actual spending,
  and meals & snacks whose groceries go onto the pack list and whose costs become the Food & drink plan.
- Club pay (2026-11-16): contractor or employee, house fees by arrival time, dances with the house's cut,
  VIP share, tip-outs, fines, a shift statement. Ideas for later: quotas/minimums, stage-set fees,
  pay-period summaries for employees (wage vs tips), different rules on different nights.
- Public wording: OF / fan sites only.
- One-container Docker install (Dockerfile + docker-compose.yml, port 8008); image workflow in .github/.
- Meds: injections with site rotation and dose steps (GLP-1, hormones).

## Next
- Social, later: pictures on Reddit; alt text for pictures; reminders when an auto-post fails (ntfy).
- Saved replies for inquiries.
- Discreet receipts for clients.
- Wipe everything: password, type a phrase, 10-second countdown you can cancel.
- Bad-date list export (import exists). No sharing between workers (legal risk).
- Website review page by page with the owner (home page done 2026-11-16; next: the docs pages).

## Bigger ideas
- Local AI: an optional assistant that talks to a model running on your own machine (LM Studio, llama.cpp,
  Ollama: all speak the OpenAI-style API on localhost). Cloud AI only as an explicit opt-in, clearly marked,
  off by default. Jobs: statistics and search (ask questions of your own numbers, find things across notes), not writing.
- Translations: Spanish, Russian, French first. Later.
