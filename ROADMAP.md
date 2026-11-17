# Sworkr roadmap

Ideas and decisions, so nothing is lost between work sessions. Newest decisions first.

## Open questions for the owner
Answer here (edit this file on GitHub, even from a phone) or in chat; answered ones move to the decisions above.
1. Home page: is "Made by a worker, from ten years of spreadsheets." how you want to describe yourself publicly?
2. Home page, "Tours & houses": it mentions house cuts and the office holding your cash. Too insider for the public page?
3. Home page, privacy list: "On your phone, privately. Nothing is opened to the internet." Mention the own-web-address
   option there too, or leave it to the docs?
4. Social: which networks matter most to you after Bluesky and Mastodon (Reddit, X at a price, others)?
5. Local AI: which jobs first? Suggested: drafting replies to inquiries, summarising a client's notes, sorting expenses,
   writing post captions.

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
- Tour plan (2026-11-16): pack lists from templates, a budget by main category against actual spending,
  and meals & snacks whose groceries go onto the pack list and whose costs become the Food & drink plan.
- Club pay (2026-11-16): contractor or employee, house fees by arrival time, dances with the house's cut,
  VIP share, tip-outs, fines, a shift statement. Ideas for later: quotas/minimums, stage-set fees,
  pay-period summaries for employees (wage vs tips), different rules on different nights.
- Public wording: OF / fan sites only.
- One-container Docker install (Dockerfile + docker-compose.yml, port 8008); image workflow in .github/.
- Meds: injections with site rotation and dose steps (GLP-1, hormones).

## Next
- Social: post to Bluesky and Mastodon; Reddit posting with the person's own app key; import stats from
  platforms' CSV exports.
- Saved replies for inquiries.
- Discreet receipts for clients.
- Wipe everything: password, type a phrase, 10-second countdown you can cancel.
- Automatic off-site backups (Nextcloud, Synology, WebDAV).
- Bad-date list export (import exists). No sharing between workers (legal risk).
- Website review page by page with the owner (home page: questions pending).

## Bigger ideas
- Local AI: an optional assistant that talks to a model running on your own machine (LM Studio, llama.cpp,
  Ollama: all speak the OpenAI-style API on localhost). Cloud AI only as an explicit opt-in, clearly marked,
  off by default. Ideas: draft replies to inquiries, summarise a client's notes, sort expenses, write post captions.
- Translations: Spanish, Russian, French first. Later.
