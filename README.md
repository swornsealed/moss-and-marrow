# Moss & Marrow — landing site + order automation

Nature-shop sibling of Sworn & Sealed, from `Earth_Readings_Market_Research.pdf`.
Green / white / peach palette. Brand: **Moss & Marrow**. Reader persona: **Willow**.
Domain: **mossandmarrowreadings.com** (chosen 2026-07-19; `docs/CNAME` set).
Shop email: mossandmarrowreadings@gmail.com.

## Structure
- `docs/index.html` — the whole site (CSS + HTML + JS, no build step, only external request is Google Fonts).
- `docs/CNAME`, `docs/robots.txt`, `docs/sitemap.xml` — served by GitHub Pages.
- `process_orders.py` — order pipeline, fully adapted from Sworn & Sealed (see [SETUP.md](SETUP.md)).
- `land_engine.py` — deterministic season/element/sign engine (the tarot engine's nature
  counterpart, same `draw_reading` interface). Tested; run `python land_engine.py`.
- `record_image.py` — the keepsake record that ships with every reading: the
  Record of the Cast (runes drawn as vector cuts, merkstave stones rendered
  upside down) or the Record of the Land. No image assets, no font dependency.
  Run `python record_image.py` to write samples to `_record_samples/`.
- `moss-marrow-system-prompt.txt` — system prompt for the reading generation.
- `.github/workflows/process-orders.yml` — the 30-minute Actions schedule (copy also at repo root;
  disabled on GitHub until secrets are configured).

## Before launch (remaining TODOs)
- Point the two Etsy links (final CTA + footer) at the live shop. Search `TEMPLATE:` comments in the HTML.
- Set the Porkbun DNS records for mossandmarrowreadings.com (see SETUP.md) and enforce HTTPS.
- Add the Actions secrets, then enable the workflow (SETUP.md checklist).
- Prices shown are the launch-plan defaults. Two families of reading:
  - **The land** (`land_engine.py`): First Sign $28, Reading of the Land $68,
    The Whole Ground $135, The Turning Year $22 per turn.
  - **The stones** (`rune_engine.py`): First Stone $25 (1 rune), Rune Casting $45
    (5 runes), The Nine Worlds $95 (9 runes, three lines of three).
  Rune tiers use the same seeded-draw design as the S&S tarot engine, laddered by
  `TIER_SPREAD`. TEST codes: `FST`, `RC`, `NW`. Seven Etsy listings at launch.

## Preview
```
cd docs && python -m http.server 8613
```
then open http://localhost:8613/

`?shot` in the URL pins the hero height for full-page screenshot tooling; it changes nothing else.
