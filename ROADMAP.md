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
- Setup builder: option to add Caddy to the same docker-compose.yml (own web address without a separate download). mention how other selfhosted services, like ad guard home can further protect their privacy.
- Simplify social media integration where possible for ease of use such as including making it a part of the connection settings because duh?
- Workers know who gets paid work card fees. This needs no language explaining. It can be tied to a workplace and to tours, so that accurateinformation is reported to the user.
- Goals is now wallet (envelopes done 2026-11-18: an envelope can hold what a workplace keeps; still to do:
  rename to Wallet, personal wallet, choose which envelopes show on the dashboard). You can goal envelopes, office envelope, personal wallet. Wallet can show on dashboard with choice of which envelopes are shown.
- Local AI: an optional assistant that talks to a model running on your own machine (LM Studio, llama.cpp,
  Ollama: all speak the OpenAI-style API on localhost). Cloud AI only as an explicit opt-in, clearly marked,
  off by default. Jobs: statistics and search (ask questions of your own numbers, find things across notes), not writing.
- Driver contact profiles can have different rates for going different places, services, customizable and links to budget when a ride type with a drive is chosen. each driver may 
  use their own rates.
- start planning ways to gamify posting, earnings etc.
- persona planner. a place to keep social and work platform bios, wishlist links, social links. 
- penetration testing
- apple health support as an option, track health choices like water intake and food, sleep to see how these things effect income over time.

## Bigger ideas
- Translations: Spanish, Russian, French first. Later.
