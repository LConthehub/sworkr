# Sworkr launch plan

Written 2026-11-21. The site (sworkr.com), downloads, docs and ~480 automated tests already exist, so launch
means: make sure a stranger's install works, switch money on, then tell people.

## Feature freeze
- Pick a freeze date (proposed: 2026-11-30). After it, new ideas go to a "Later" list in ROADMAP.md, not
  into the code. Only bug fixes and confusing spots get fixed until launch.

## Launch checklist (in order)

### 1. A stranger's install works (most important)
- [ ] Confirm the image exists at `ghcr.io/lconthehub/sworkr` (GitHub profile > Packages).
      `docker-compose.yml` already uses `image: ghcr.io/lconthehub/sworkr:latest`, so if the image was never
      published, every Docker install fails. If missing: repo > Actions > Image > Run workflow.
- [ ] On a computer that has never run sworkr (MacBook or CachyOS box), download sworkr-start.zip from
      sworkr.com and follow only the public docs. Note every spot where you get stuck, and fix those.

### 2. Security pass
- [ ] Repo Settings > Code security: turn on secret scanning to check the full history.
      (A check of the current files on 2026-11-21 found no keys, only a fake test token.)

### 3. Pretend-only pieces: test for real or mark "beta"
- [ ] One real Reddit post (gallery path tested only against a pretend Reddit).
- [ ] One real local model in LM Studio for the Assistant.
- [ ] One real SimpleFIN Bridge bank link.

### 4. Beta testers (two weeks, proposed Dec 1-14)
- [ ] 3-5 trusted workers use it for real. Fix only bugs and confusing spots.

### 5. Money switched on
- [ ] Turn on GitHub Sponsors for LConthehub; link site/donate.html from the site footer and README.
      BTCPay at pay.sworkr.com can come later.
- [ ] Add a "Paid setup help" page: the privacy promise (below) and a booking link with a deposit.

### 6. Legal
- [ ] Lawyer review of the Business Source License wording and the site disclaimer.

### 7. Announce (proposed early January)
- [ ] Posts on Bluesky, Mastodon and the planned Reddit communities; word of mouth through testers.

## Money ideas (decided directions, not built yet)

### Paid setup help (start first: earns from day one)
- Tiers: remote setup session (45-60 min video call); done-for-you box (mini PC or NAS shipped ready);
  ongoing care (monthly: updates, backup checks, help).
- Rough prices to test, then adjust: $50-100 per session; hardware plus a setup fee for a box;
  $10-20/month for care.
- Invoice as "software setup and IT support".
- Full session checklist: the "Sworkr Paid Setup Checklist" doc
  (https://claude.ai/artifact/FCAobuqQmrFZiQ1aX2eirB).
- Check whether the city or state needs a business license; keep records for taxes.

Privacy promise, shared before every booking:
1. Setup happens before any real data goes in. I never see your clients, bookings or money.
2. You create every password, passphrase and passkey yourself. I never know them.
3. No remote access stays behind after the session.
4. I keep only your first name and how to reach you.

### Client donations
- Risky: a client donating "for" a worker creates a payment record linking both to a s work tool.
  If offered at all: anonymous only (crypto via BTCPay, or a general "support the project" link, no worker
  names).

### Commercial licenses and workplace editions (after the worker launch)
- First: sell commercial licenses for the existing app to small agencies or studios (already required by
  the license). Ask them what a workplace edition needs.
- Later, a workplace edition: shift and room scheduling, house fees and payout statements, compliance
  (e.g. Nevada health tests), roster and onboarding.
- Rule: the worker's data stays the worker's. The house sees only what each worker chooses to share
  (availability, test-clear status), never clients, other income or notes.
- Pricing: yearly per location or per worker on the roster; set after talking to real houses.
- Sell only to businesses operating legally where they are; lawyer checks the terms. Expect invoices or
  bank transfer, since payment processors are strict with adult businesses.
- Life Is Lived could share sworkr's engine (resources + plans fitting together) later.

## Using Claude sparingly
- Claude for architecture, tricky bugs and security; local models (LM Studio) for routine work.
- Bring a written list of everything to one session.
- Keep this file and ROADMAP.md current so any session picks up fast.
