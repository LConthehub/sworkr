# Sworkr roadmap

Ideas and decisions, so nothing is lost between work sessions. Newest decisions first.

## Open questions for the owner
Answer here (edit this file on GitHub, even from a phone) or in chat; answered ones move to the decisions below.
(None open right now.)

## Answers (2026-11-16)
- About the maker (public): a former s worker with ADHD; the tool they needed while working; began as an app
  idea shelved in 2017 plus years of unorganized spreadsheets. 
- Home page "Tours & houses" no longer mentions house cuts or the office holding cash.
- Own web address stays in the docs, not the home page privacy list.
- Social after Bluesky and Mastodon: Reddit. X only if someone sponsors the API cost.
- AI is for statistics and search, not for writing. No drafting replies or captions: the creative part stays
  the worker's, and censoring models make drafting unreliable for this work anyway.

## Principles (2026-11-16)
- Privacy first, "seize the means": your data stays with you. Encourage self-hosting the other services too
  (Nextcloud or Synology for files and calendar, ntfy for notifications, a local AI model).
- Keep anything insider-only off public pages (site, demo). Coded names only inside the private app.
- Publicly, say "fan sites" or "OF", never the full platform name.
- Receipts are an in-app feature only: don't mention them on the site, docs or demo text (owner, 2026-11-16).
- Public messaging says "s work" / "s workers" (coded, deliberate).
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
- Social extras: alt text for each picture (Bluesky, Mastodon, Reddit), pictures on Reddit as a gallery,
  an ntfy push when a scheduled post fails (discreet unless details are on). The Reddit gallery path is
  tested against a pretend Reddit only: check it with a real post.
- Erase everything now ends with a 10-second countdown and a big Stop button (after password + typing ERASE).
- Bad-date list: download your list as CSV (reads back in through the import); for your own use, not sharing.
- Discreet receipts (2026-11-16): your name and wording, numbered R-2026-001, saved as issued, print or PDF;
  "Receipt" on a paid booking; Settings > My work > Receipts.
- Dark mode (2026-11-16): Settings > Look (Light default, Dark, Follow my device), sworkr.com's dark colours.
- Saved replies fill in {name}, {day}, {time}, {wanted} from the inquiry.
- The app keeps its pink look with the frosted glass top bar (owner's choice, 2026-11-16).
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

## Done 2026-11-18
- Apple Health import: Settings > Health > Wellness log reads the Health app's export.zip for sleep (asleep time, one source per night) and water.
- Wellness log (Settings > Health): a daily check-in card (sleep, water, food, energy) and how earnings compare on better and worse days.
- Assistant (AI): Settings > Connections > Assistant; LM Studio / Ollama / llama.cpp on your own computer
  (cloud only with an explicit tick); dashboard card "Ask your numbers". Gets totals only, never names or
  notes, and won't write posts or messages. Tested against a pretend model only: try it with a real one.
- Driver rates: each contact you work with keeps their own rates (per trip, hour, mile, km, day); Ride on a booking logs it as a travel expense that day.
- Persona kit: each persona keeps bios by platform, social links and wishlist links, one tap to copy (Settings > My work > Personas > Kit).
- Work card fees: a license tied to a workplace puts its renewal fee on that workplace's tour (the one under way,
  else the next within 60 days). The "paid to the government" explanations are gone.
- Setup builder: "Your own web address" adds a Caddy container for HTTPS; install page mentions AdGuard Home,
  Nextcloud and ntfy for more privacy.
- Wallet: Money > Wallet (goals and envelopes), each can be shown on the dashboard's Wallet card or not.
- Social accounts are set up in Settings > Connections; Content > Social keeps the numbers.
- Notes card on the dashboard (one scratch pad, saves itself).
- After a booking: "How did it go?" (how it went, see again, talked about, notes), kept on the client's profile.
- Contacts > Client base: bars by age, how they found you, line of work, languages, bookings, spend, see again.
- Holidays: Settings > My work > Holidays, public holidays worked out locally (the `holidays` library).
- Client profiles: "Getting to know them" on each client (languages, translator, culture, talk about, avoid,
  passed away: set inactive so no Ghosts or birthday reminders).
- Routines: a dashboard card of your own checklists (morning, night, before/after a booking), four starters.
- Doctor day needs tweaking: waiting on the owner to say how.
- Doctor day: a workplace's doctor charge can say which weekday the doctor comes; tour tests land on it.
- Envelopes: a goal can be an envelope (no target), optionally holding what a workplace keeps for you.
- "Gone quiet" is now "Ghosts".
- Address fill-ins: iCloud fills itself in; Fastmail and mailbox.org buttons; "Use ntfy.sh".

## Next
- Docs review finished 2026-11-17 (last six pages in one pass; owner may veto). Troubleshooting page not re-read.
- Gamify posting and earnings: plan (2026-11-18), for the owner to pick from. Ideas, all private, all optional,
  and none that push working more than you want:
  - Streaks: days in a row you posted what you planned, kept routines, or logged money. A missed day pauses a
    streak instead of zeroing it (rest is part of the job).
  - Weekly goals you set yourself ("3 posts", "log every booking"), with a ring that fills; no goal is suggested
    from your numbers, so it never says "work more".
  - Personal bests: best week, best tour per working day, most inquiries from one post, longest posting streak.
  - Badges for setup and safety, not output: first backup, two-step sign-in on, a passkey, check-in used, a full
    week of routines, books closed for a month (every expense has a category).
  - Tour wrap-up: after a tour, a card with the highlights (kept vs costs, best day, new regulars).
  - A dashboard "level" for the Wallet: envelopes filling up (an emergency fund reaching 1, 3, 6 months).
  - Never public, never compared with other workers, and one switch turns all of it off.
- Penetration testing, part 1 done 2026-11-18: a test walks every API route (200+) and checks none answers
  without a login; Python dependencies audited clean (pip-audit). Frontend: 2 moderate react-router advisories
  that didn't apply here; cleared by upgrading to react-router 7.18.6 (npm audit: 0). Still to do: an outside
  tester before launch.

## Bigger ideas
- Translations: Spanish, Russian, French first. Later.
