# Moss & Marrow — Automation Setup

The reading automation, cloned from the proven Sworn & Sealed machine.
One repo runs everything: the landing site (`docs/`, GitHub Pages) and the
order processor (`process_orders.py`, GitHub Actions every 30 minutes).

## How the machine works (unchanged from Sworn & Sealed)

```
Etsy sale ──► buyer gets intake-form link ──► branded form posts to Google Sheet
                                                        │
   GitHub Action (every 30 min) ────────────────────────┘
   1. reads new Sheet rows, verifies the order number against the Etsy API
   2. detects tier from the listing (LISTING_TIER_MAP) — never guesses
   3. land_engine.py draws season + element + signs (deterministic, seeded)
   4. Claude writes the reading (moss-marrow-system-prompt.txt is the law)
   5. sanitisers enforce the voice (em-dash strip, forbidden phrases, sign-off)
   6. tier deliverables are attached (record image / audio, if enabled)
   7. Gmail sends the reading; owner is Bcc'd for QC; Etsy order marked shipped
   8. state.json (queue + Etsy refresh token) is committed back to the repo
   Working hours are enforced: orders ingest around the clock, deliver 10–16.
```

## What it needs to produce output (the checklist)

| # | Thing | Where it goes | Notes |
|---|-------|--------------|-------|
| 1 | **Etsy shop + API app** for Moss & Marrow | secrets `ETSY_API_KEY`, `ETSY_SHOP_ID`, `ETSY_REFRESH_TOKEN` | Own shop = own tokens. Run `get_etsy_tokens.py` (copy from the S&S repo) once to mint the refresh token. Token self-rotates in `state.json` afterwards. |
| 2 | **Listing IDs → tiers** | repo variable `LISTING_TIER_MAP` | e.g. `123:First Sign,456:Reading of the Land,789:The Whole Ground,321:The Turning Year`. Set after the four listings are published. |
| 3 | **Intake form + Google Sheet** | sheet ID in `SHEET_CONFIG`, secret `GOOGLE_SERVICE_ACCOUNT_JSON` | Clone the S&S pattern: branded HTML form on this site (`docs/intake/`) posting to a Google Apps Script that appends rows. Share the sheet with the service account email. Column layout must match `_COL` in `process_orders.py`. |
| 4 | **Anthropic API key** | secret `ANTHROPIC_API_KEY` | Writes the readings. Same account as S&S is fine — cost tracking is per key, so a second key labelled "moss-marrow" keeps the books clean. |
| 5 | **System prompt** | `moss-marrow-system-prompt.txt` (in repo) | Starter included. Grow it the S&S way: each miss becomes a rule. |
| 6 | **Gmail sending address** | secrets `GMAIL_USER`, `GMAIL_APP_PASSWORD` | A separate address (e.g. willow.mossandmarrow@gmail.com) with an App Password. Do not send Willow's mail from Isadora's address — the doc's rule: siblings, never crossed. |
| 7 | **Timezone** | repo variable `TIMEZONE` | `America/Los_Angeles` to match the persona. |
| 8 | *(optional)* ElevenLabs voice | secrets `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Only if The Whole Ground gets an audio deliverable. Needs a NEW voice — Willow cannot sound like Isadora. |
| 9 | *(optional)* Google Calendar | secret `GOOGLE_CALENDAR_ID` | Only if a ceremony-scheduled tier is ever added. |

## Pipeline adaptation — DONE (2026-07-19)

`process_orders.py` has been fully adapted from the S&S template and verified
(compiles; dry-run tests pass for tier resolution, scheduling, the land-block
intake, sanitisers, the HTML email shell, and the Turning Year re-queue):

- **Engine**: draws from `land_engine.py` (season / element / signs).
- **Tiers**: First Sign (5–20 min), Reading of the Land (2–4 h),
  The Whole Ground (4–8 h, upsell-strip protected), The Turning Year
  (first drop same day, then one reading queued for each sabbat, 8 total,
  Etsy receipt marked shipped on the first drop).
- **Reading types / tabs**: `love`, `career`, `clarity`, `season`.
- **Deliverables**: text-only at launch (`TIERS_WITH_*` sets empty). The
  audio path, outdoor-observance closer, and record-image hook are wired
  and dormant — add a tier to the matching set to activate.
- **Persona**: every customer-facing string is Willow / Moss & Marrow
  (confirmations, shipped note, HTML email in the green/peach palette,
  canonical sign-off, alerts). All natal/astrology/Grand Ceremony code
  paths were removed, not just disabled.
- **Safety guard**: still refuses to run without `SHOP_BRAND=moss-and-marrow`.
- **Test orders**: `TEST-<TIER>-<TYPE>` with tiers FS/RL/WG/TY and types
  LOVE/CAREER/CLARITY/SEASON (owner email only, as before).
- **`state.json`**: not present by design — created fresh on first run.
  Never copy it from S&S.

Re-run the checks locally any time:
```
pip install -r requirements.txt
python land_engine.py                          # engine self-test
python process_orders.py                       # must exit 1 with the safety guard
SHOP_BRAND=moss-and-marrow ALLOW_TEST_ORDERS=1 python process_orders.py   # with env vars set
```

## GitHub: same account, new repo — no second account needed

One GitHub account can hold unlimited repositories, each with its own
Pages site, custom domain, Actions schedule, and secrets. Create
**`moss-and-marrow` as a new repo under the existing `swornsealed` account**.

Don't put it inside the `sworn-and-sealed` repo as a subfolder, because per
repo GitHub gives you only ONE Pages site (the S&S `docs/` already claims
it), ONE set of Actions secrets (the two shops' Etsy/Gmail tokens would
collide under the same names), and one `state.json` commit stream (the two
processors would interleave commits). A separate repo costs nothing and
keeps a mistake in one shop from ever touching the other.

Launch steps when ready:
```
cd moss-and-marrow
git init && git add -A && git commit -m "Moss & Marrow: site + automation"
gh repo create swornsealed/moss-and-marrow --private --source . --push
```
then in the new repo's settings: enable Pages (main branch, `/docs` folder),
add the secrets and variables from the checklist above, and the workflow in
`.github/workflows/process-orders.yml` starts running on its own schedule.
