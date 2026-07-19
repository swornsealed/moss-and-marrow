# Moss & Marrow — template landing page

Single-file landing page for the nature-shop concept from `Earth_Readings_Market_Research.pdf`
(sibling shop to Sworn & Sealed). Green / white / peach palette, nature theme.
Brand name chosen 2026-07-19: **Moss & Marrow**. Reader persona: Willow.

## Structure
- `docs/index.html` — the whole site (CSS + HTML + JS, no build step, only external request is Google Fonts).
- `process_orders.py` — order pipeline, copied verbatim from Sworn & Sealed as the template
  (adaptation checklist in [SETUP.md](SETUP.md) — edit before first run).
- `land_engine.py` — deterministic season/element/sign engine (the tarot engine's nature
  counterpart, same `draw_reading` interface). Tested; run `python land_engine.py`.
- `moss-marrow-system-prompt.txt` — starter system prompt for the reading generation.
- `.github/workflows/process-orders.yml` — the 30-minute Actions schedule (copy also at repo root).
- Deploys exactly like swornandsealed.com: push this folder to its own GitHub repo (same
  account, new repo — see SETUP.md), enable GitHub Pages from the `docs/` folder, add a
  `docs/CNAME` when the domain is chosen.

## Before launch (template TODOs)
- Point the two Etsy links (final CTA + footer) at the live shop. Search `TEMPLATE:` comments in the HTML.
- Set `canonical` / `og:url` to the live domain.
- Prices shown are the launch-plan defaults: First Sign $28, Reading of the Land $68,
  The Whole Ground $135, The Turning Year $22 per turn.

## Preview
```
cd docs && python -m http.server 8613
```
then open http://localhost:8613/

`?shot` in the URL pins the hero height for full-page screenshot tooling; it changes nothing else.
