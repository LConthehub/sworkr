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

## Waiting on the owner (2026-11-19)
- Donations: site/donate.html is built (tiers $5, $25, $100, any amount) but not linked yet. To go live:
  turn on GitHub Sponsors for LConthehub, and set up a BTCPay Server at pay.sworkr.com (Docker; needs a
  Caddy entry). Then link it from the home page footer and the README.
- Affiliate links: sign up with Porkbun, Namecheap and Njalla's affiliate programs and swap the codes into
  the registrar links on the web-address docs page (they're marked rel="sponsored" and disclosed).
- Performer testing (TTS, PASS): from the owner's notes or friends; the websites couldn't be read.
  (Nye and Lyon are covered by the Nevada house set: the owner confirmed what's there is fine.)

## Done 2026-11-19
- Content > Protect: paperwork for everyone on camera or behind it (ID check and release dates, where the copies
  are, a blank release to copy), and stolen content with a takedown notice to copy and a chase after 10 days.
- Decoy password (Settings > Security & privacy): a second password opens a separate, harmless account under the
  same username; the real account's sign-in history notes when it was used.
- Money > Payouts: a payout day for each place, and pending money on the day it should land.
- Money > Taxes: platform tax forms checked against what was recorded.
- Customs: orders that go in the post (packed, posted, carrier, tracking).
- Clip stores are a starter platform for content creators as well as fetish work.
- "Wellness log" is now "Daily check-in"; Supplies is a dashboard card of its own.
- Quick fixes: auto log-out 5 min choice and 15 min default; no sign-in history on the demo; supplies starters.
- Settings regrouped (Money and Safety groups; tests under Health; backups first).
- Health tests: clear / not clear results; booking a party during a house stay warns until the test there is
  clear and the work card is current; what each test takes and checks for; a Nevada house set (NAC 441A.800).
  County rules (Nye, Lyon) and performer testing (TTS, PASS) could not be confirmed online: ask the owner/friends.
- Easier install: sworkr-start.zip with double-click Start / Update / Stop (Windows tested in an isolated copy).
- Home screen name & icon (Settings > Look), Android long-press shortcuts.
- Docs: first time with Docker, No-IP, your own domain, Own your data (self-hosting, VPN), Android; README rewritten.
- Fuller expense categories, coloured from the app's palette.
- Conventions with a booth and promo list; Calendar > Meals with a shopping list; optional calories and macros.
- Simulation test: four pretend workers, 90 days, every screen checked. It found and fixed: steady pay counting
  months before someone started, routine streaks broken by days off, getting-ready time added to house parties.

## Done 2026-11-18
- Only what fits: each part of sworkr shows for the kinds of work it's for (Settings > My work > Show everything
  to see all). Two more kinds of work: massage or bodywork, online seller.
- Today strip on the dashboard: quick logs (shift, stream, calls, scene, sale), the safety timer, supplies low.
- Safety: alerts by ntfy push to the trusted contact as well as email; a timer for anything, with an all-clear.
- Money > Overview: what an hour really pays, and steady pay from a buffer envelope.
- Supplies (Settings > Health), incident log and privacy check-up (Settings > Security & privacy).
- Review pass: routines, the daily check-in and Progress now use your own day, not the server's UTC day
  (ticks used to reset at 4pm Pacific); editing a routine keeps ticks on unchanged steps; "paused" streaks
  shown correctly; dark-mode colours for the goal rings; rates form fits a phone; demo sample data and docs
  cover the new features.
- Progress (all the gamifying ideas): streaks (posting, routines, money; one missed day pauses), weekly goals
  you set (rings), personal bests, badges for setup and safety, tour wrap-up card, wallet level; one switch in
  Settings > Look turns it all off.
- Bank (Money > Bank): SimpleFIN Bridge setup token, transactions brought in once each, add as expense or income or ignore. Tested against a pretend bridge only.
- Settings: "Reminders" is now "Notifications".
- First run: after "How do you work?", "Connect what you use" offers email, calendar, content library,
  phone notifications, phone access and health tracking (all optional).
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
- Penetration testing, part 1 done 2026-11-18: a test walks every API route (200+) and checks none answers
  without a login; Python dependencies audited clean (pip-audit). Frontend: 2 moderate react-router advisories
  that didn't apply here; cleared by upgrading to react-router 7.18.6 (npm audit: 0). Still to do: an outside
  tester before launch.

### Owner's list, 2026-11-19
- Easier install for first-time Docker users; streamline install and update on the site and GitHub; better README.
- Auto log-out: add 5 minutes as a choice, 15 minutes the default.
- Docs: No-IP as a DDNS option; say clearly a domain or subdomain you own works; maybe affiliate links to domain
  providers (discuss). Self-hosting spirit throughout the docs; VPN reminders where they fit.
- Donations page on sworkr.com, small and large options (discuss).
- A better word than "wellness" (discuss).
- Supplies: no test kits in the starters; "Hand sanitizer"; add "Toy cleaner".
- Demo: don't show sign-ins (invasive).
- Web app instructions, with a way to set a custom home-screen icon; do it from the Tailscale or own-address URL.
- Android: what's missing compared with iPhone.
- Meal planning and shopping lists (beyond tours). Optional calorie and macro tracking, off unless turned on.
- More fleshed-out budget categories; default colours that fit the app.
- Settings order that makes sense in practice.
- Fake test personas using it for a few simulated months, to find what breaks or is awkward.
- Convention booth planning: promo materials and their costs, outfits; convention trips budgeted like tours.
- Doctor day: usually the same weekday at a brothel (e.g. Wednesday), results the next day. A party can only be
  booked after the test clears and the work card is current.
- Health test questions (cervical swab, blood draw...). What Nevada counties require (owner worked in Nye and
  Lyon; they differed). Talent Testing Service for how performer testing works.

## Bigger ideas
- Translations: Spanish, Russian, French first. Later.
