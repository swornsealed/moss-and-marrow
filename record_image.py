"""
record_image.py — Moss & Marrow
Renders the keepsake image that ships with a reading: the Record of the Cast
(rune tiers) or the Record of the Land (land tiers).

The Sworn & Sealed counterpart (spread_image_generator.py) composites
photographs of Rider-Waite cards. Moss & Marrow has no card art and needs
none: runes are carved lines, so every glyph here is drawn as vector
strokes on a normalised grid. That means

  * no image assets to ship and no font dependency on the Actions runner
    (the Runic unicode block is not reliably installed there),
  * a merkstave stone can be drawn genuinely upside down, which is what
    the client would see on the ground,
  * the art scales to any size without going soft.

The whole canvas is rendered at 2x and downsampled, so the diagonals come
out smooth without any per-line anti-aliasing work.
"""

from io import BytesIO
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:                                    # pragma: no cover
    PILLOW_AVAILABLE = False


# ─── PALETTE (the brand, in ink) ──────────────────────────────────────────────

GROUND       = ( 12,  26,  17)     # deep forest, the dark earth the stones lie on
GROUND_EDGE  = (  8,  18,  11)     # vignette
STONE_FACE   = (232, 226, 210)     # pale river stone / cut rowan
STONE_FACE_M = (206, 198, 180)     # a face-down stone reads slightly darker
STONE_EDGE   = (150, 146, 128)
CARVED       = ( 38,  46,  32)     # the cut itself
CARVED_M     = ( 96,  56,  38)     # merkstave cuts read warmer, like old blood in the groove
LEAF         = (143, 184, 131)
LEAF_PALE    = (200, 230, 180)
PEACH        = (255, 185, 143)
CREAM        = (248, 246, 239)
CREAM_DIM    = (186, 196, 172)
CREAM_FAINT  = (128, 142, 118)
RULE         = ( 46,  74,  48)


# ─── THE 24 RUNES AS CUT STROKES ──────────────────────────────────────────────
# Unit coordinates: x 0 (left) to 1 (right), y 0 (top) to 1 (bottom).
# Each rune is a list of ((x1, y1), (x2, y2)) segments — the cuts you would
# make with a knife, in the order you would make them.

RUNE_STROKES = {
    "Fehu":     [((0.30, 0.00), (0.30, 1.00)),
                 ((0.30, 0.20), (0.76, 0.04)),
                 ((0.30, 0.52), (0.76, 0.36))],
    "Uruz":     [((0.24, 1.00), (0.24, 0.06)),
                 ((0.24, 0.06), (0.76, 0.26)),
                 ((0.76, 0.26), (0.76, 1.00))],
    "Thurisaz": [((0.30, 0.00), (0.30, 1.00)),
                 ((0.30, 0.22), (0.74, 0.50)),
                 ((0.74, 0.50), (0.30, 0.78))],
    "Ansuz":    [((0.30, 0.00), (0.30, 1.00)),
                 ((0.30, 0.10), (0.74, 0.32)),
                 ((0.30, 0.42), (0.74, 0.64))],
    "Raidho":   [((0.28, 0.00), (0.28, 1.00)),
                 ((0.28, 0.02), (0.72, 0.18)),
                 ((0.72, 0.18), (0.28, 0.44)),
                 ((0.36, 0.44), (0.74, 1.00))],
    "Kenaz":    [((0.72, 0.02), (0.28, 0.50)),
                 ((0.28, 0.50), (0.72, 0.98))],
    "Gebo":     [((0.18, 0.02), (0.82, 0.98)),
                 ((0.82, 0.02), (0.18, 0.98))],
    "Wunjo":    [((0.30, 0.00), (0.30, 1.00)),
                 ((0.30, 0.02), (0.74, 0.24)),
                 ((0.74, 0.24), (0.30, 0.46))],
    "Hagalaz":  [((0.24, 0.00), (0.24, 1.00)),
                 ((0.76, 0.00), (0.76, 1.00)),
                 ((0.24, 0.40), (0.76, 0.60))],
    "Nauthiz":  [((0.50, 0.00), (0.50, 1.00)),
                 ((0.18, 0.72), (0.82, 0.28))],
    "Isa":      [((0.50, 0.00), (0.50, 1.00))],
    "Jera":     [((0.24, 0.10), (0.60, 0.29)),
                 ((0.60, 0.29), (0.24, 0.48)),
                 ((0.76, 0.90), (0.40, 0.71)),
                 ((0.40, 0.71), (0.76, 0.52))],
    "Eihwaz":   [((0.50, 0.10), (0.50, 0.90)),
                 ((0.50, 0.10), (0.80, 0.00)),
                 ((0.50, 0.90), (0.20, 1.00))],
    "Perthro":  [((0.70, 0.02), (0.32, 0.26)),
                 ((0.32, 0.26), (0.32, 0.74)),
                 ((0.32, 0.74), (0.70, 0.98))],
    "Algiz":    [((0.50, 0.12), (0.50, 1.00)),
                 ((0.50, 0.46), (0.16, 0.04)),
                 ((0.50, 0.46), (0.84, 0.04))],
    "Sowilo":   [((0.72, 0.02), (0.32, 0.30)),
                 ((0.32, 0.30), (0.68, 0.66)),
                 ((0.68, 0.66), (0.28, 0.98))],
    "Tiwaz":    [((0.50, 0.14), (0.50, 1.00)),
                 ((0.50, 0.14), (0.20, 0.46)),
                 ((0.50, 0.14), (0.80, 0.46))],
    "Berkano":  [((0.30, 0.00), (0.30, 1.00)),
                 ((0.30, 0.03), (0.72, 0.26)),
                 ((0.72, 0.26), (0.30, 0.49)),
                 ((0.30, 0.51), (0.72, 0.74)),
                 ((0.72, 0.74), (0.30, 0.97))],
    "Ehwaz":    [((0.22, 0.00), (0.22, 1.00)),
                 ((0.78, 0.00), (0.78, 1.00)),
                 ((0.22, 0.04), (0.50, 0.54)),
                 ((0.50, 0.54), (0.78, 0.04))],
    "Mannaz":   [((0.20, 0.00), (0.20, 1.00)),
                 ((0.80, 0.00), (0.80, 1.00)),
                 ((0.20, 0.02), (0.80, 0.56)),
                 ((0.80, 0.02), (0.20, 0.56))],
    "Laguz":    [((0.34, 0.00), (0.34, 1.00)),
                 ((0.34, 0.03), (0.72, 0.32))],
    "Ingwaz":   [((0.50, 0.14), (0.82, 0.50)),
                 ((0.82, 0.50), (0.50, 0.86)),
                 ((0.50, 0.86), (0.18, 0.50)),
                 ((0.18, 0.50), (0.50, 0.14))],
    "Othala":   [((0.50, 0.02), (0.78, 0.33)),
                 ((0.78, 0.33), (0.50, 0.60)),
                 ((0.50, 0.60), (0.22, 0.33)),
                 ((0.22, 0.33), (0.50, 0.02)),
                 ((0.50, 0.60), (0.24, 1.00)),
                 ((0.50, 0.60), (0.76, 1.00))],
    "Dagaz":    [((0.20, 0.00), (0.20, 1.00)),
                 ((0.80, 0.00), (0.80, 1.00)),
                 ((0.20, 0.02), (0.80, 0.98)),
                 ((0.80, 0.02), (0.20, 0.98))],
}


# ─── LAYOUTS ──────────────────────────────────────────────────────────────────
# (canvas w, h, stone w, stone h, [(cx, cy), ...]) at 1x. Positions are the
# stone centres. Nine stones sit in three lines of three, as they were laid.

MARGIN = 150          # keeps stones clear of the vignette at the canvas edge


def _layout(n: int):
    if n == 1:
        return 1000, 1180, 300, 400, [(500, 600)]
    if n == 9:
        # Row pitch must clear the stone plus its label above (~34) and its
        # name and merkstave line below (~85), or the rows collide.
        w, h = 1320, 1700
        sw, sh = 200, 265
        xs = (340, 660, 980)
        ys = (540, 930, 1320)
        return w, h, sw, sh, [(x, y) for y in ys for x in xs]
    # five (and any other count) — one line, read left to right
    w, h = 1500, 1020
    sw, sh = 200, 280
    usable = w - 2 * MARGIN
    step = usable / (n - 1) if n > 1 else 0
    xs = [MARGIN + step * i for i in range(n)]
    return w, h, sw, sh, [(x, 560) for x in xs]


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def _font(size: int, bold: bool = False):
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf' if bold
        else '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
        'C:/Windows/Fonts/georgiab.ttf' if bold else 'C:/Windows/Fonts/georgia.ttf',
        'Georgia Bold.ttf' if bold else 'Georgia.ttf',
        '/System/Library/Fonts/Supplemental/Georgia Bold.ttf' if bold
        else '/System/Library/Fonts/Supplemental/Georgia.ttf',
        'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf',
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            pass
    return ImageFont.load_default()


def _tw(d, text, font):
    b = d.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def _centre(d, text, cx, y, font, fill):
    d.text((cx - _tw(d, text, font) / 2, y), text, font=font, fill=fill)


def _tracked(d, text, cx, y, font, fill, track):
    """Letterspaced small caps, the way the site sets its kickers."""
    widths = [_tw(d, ch, font) for ch in text]
    total = sum(widths) + track * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=font, fill=fill)
        x += w + track


def _draw_rune(d, name, cx, cy, w, h, colour, stroke, inverted=False):
    """Cut a rune into a stone. Inverted draws it merkstave: the same stone,
    fallen the other way up, which is exactly what the client would see."""
    strokes = RUNE_STROKES.get(name)
    if not strokes:
        return
    x0, y0 = cx - w / 2, cy - h / 2
    for (ax, ay), (bx, by) in strokes:
        if inverted:
            ax, ay, bx, by = 1 - ax, 1 - ay, 1 - bx, 1 - by
        d.line([(x0 + ax * w, y0 + ay * h), (x0 + bx * w, y0 + by * h)],
               fill=colour, width=stroke, joint="curve")


def _stone(d, cx, cy, w, h, merkstave):
    """A pale stone with a soft edge: river pebble, or a cut of rowan."""
    face = STONE_FACE_M if merkstave else STONE_FACE
    box = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
    r = int(min(w, h) * 0.30)
    # a whisper of shadow under the stone
    d.rounded_rectangle([box[0] + 6, box[1] + 10, box[2] + 6, box[3] + 10],
                        radius=r, fill=(6, 14, 9))
    d.rounded_rectangle(box, radius=r, fill=face, outline=STONE_EDGE, width=2)


def _vignette(img):
    """Darken the edges so the stones sit in the middle of the ground."""
    w, h = img.size
    d = ImageDraw.Draw(img, "RGBA")
    steps = 26
    for i in range(steps):
        a = int(72 * (i / steps) ** 2.2)
        d.rectangle([i * 3, i * 3, w - i * 3, h - i * 3], outline=(0, 0, 0, a), width=3)


# ─── THE RECORD ───────────────────────────────────────────────────────────────

def generate_record_image(
    tarot_result: dict,
    reading_type: str = "",
    client_name: str = "",
    tier: str = "",
    reading_date: str = "",
    output_path: Optional[str] = None,
) -> bytes:
    """
    Render the keepsake record for a reading.

    Parameters
    ----------
    tarot_result : the dict stored on the delivery. A rune cast carries
                   "runes"; a land reading carries "signs".
    reading_type : love | career | clarity | season — shown in the subtitle
    client_name  : shown under the title
    tier         : shown as the record's kicker
    reading_date : ISO date string, printed in the footer

    Returns raw JPEG bytes for email attachment.
    """
    if not PILLOW_AVAILABLE:
        raise ImportError("Pillow is required: pip install Pillow")

    runes = (tarot_result or {}).get("runes") or []
    if runes:
        return _render_cast(runes, tarot_result, reading_type, client_name,
                            tier, reading_date, output_path)
    return _render_land(tarot_result or {}, reading_type, client_name,
                        tier, reading_date, output_path)


def _frame(canvas_w, canvas_h, S):
    img = Image.new("RGB", (canvas_w * S, canvas_h * S), GROUND)
    return img, ImageDraw.Draw(img)


def _header(d, S, canvas_w, kicker, title, subtitle):
    _tracked(d, "MOSS & MARROW", canvas_w * S / 2, 54 * S,
             _font(19 * S, bold=True), PEACH, 7 * S)
    if kicker:
        _tracked(d, kicker.upper(), canvas_w * S / 2, 104 * S,
                 _font(15 * S), LEAF, 5 * S)
    _centre(d, title, canvas_w * S / 2, 146 * S, _font(52 * S), CREAM)
    if subtitle:
        _centre(d, subtitle, canvas_w * S / 2, 218 * S, _font(23 * S), CREAM_DIM)
    d.line([(canvas_w * S / 2 - 70 * S, 262 * S),
            (canvas_w * S / 2 + 70 * S, 262 * S)], fill=RULE, width=2 * S)


def _wrap(d, text, font, max_w):
    """Break a footer line to fit the canvas; the season line runs long."""
    words, lines, cur = text.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if _tw(d, trial, font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def _footer(d, S, canvas_w, canvas_h, lines):
    f = _font(17 * S)
    wrapped = []
    for ln in lines:
        wrapped.extend(_wrap(d, ln, f, (canvas_w - 120) * S))
    y = canvas_h * S - (28 + 26 * len(wrapped)) * S
    for ln in wrapped:
        _centre(d, ln, canvas_w * S / 2, y, f, CREAM_FAINT)
        y += 26 * S


def _save(img, S, canvas_w, canvas_h, output_path):
    _vignette(img)
    img = img.resize((canvas_w, canvas_h), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)
    if output_path:
        img.save(output_path, format="JPEG", quality=92)
    return buf.getvalue()


def _render_cast(runes, result, reading_type, client_name, tier, reading_date,
                 output_path):
    S = 2                                     # supersample factor
    n = len(runes)
    canvas_w, canvas_h, sw, sh, spots = _layout(n)
    img, d = _frame(canvas_w, canvas_h, S)

    subtitle = f"cast for {client_name}" if client_name else ""
    _header(d, S, canvas_w, tier or "The stones", "The Record of the Cast", subtitle)

    label_f    = _font(15 * S, bold=True)
    name_f     = _font(24 * S)
    orient_f   = _font(14 * S)
    stroke     = max(3, int(sw * 0.055)) * S

    for r, (cx, cy) in zip(runes, spots):
        cxS, cyS = cx * S, cy * S
        merk = r.get("orientation") == "merkstave"
        _stone(d, cxS, cyS, sw * S, sh * S, merk)
        _draw_rune(d, r.get("rune", ""), cxS, cyS,
                   sw * S * 0.46, sh * S * 0.52,
                   CARVED_M if merk else CARVED, stroke, inverted=merk)

        # position label above, rune name and face below
        pos = (r.get("position") or "").replace("-", " ")
        _tracked(d, pos.upper(), cxS, cyS - sh * S / 2 - 34 * S,
                 label_f, LEAF, 3 * S)
        _centre(d, r.get("rune", ""), cxS, cyS + sh * S / 2 + 22 * S,
                name_f, CREAM)
        if merk:
            _centre(d, "merkstave", cxS, cyS + sh * S / 2 + 56 * S,
                    orient_f, PEACH)

    foot = []
    if result.get("birth_rune"):
        foot.append(f"birth rune: {result['birth_rune']}")
    season = (result.get("season_line") or
              (result.get("season") or {}).get("season_line", ""))
    if season:
        foot.append(season)
    if reading_date:
        foot.append(f"cast {reading_date}")
    foot.append("Written by hand, at the edge of the woods.")
    _footer(d, S, canvas_w, canvas_h, foot)

    return _save(img, S, canvas_w, canvas_h, output_path)


def _render_land(result, reading_type, client_name, tier, reading_date,
                 output_path):
    """The land tiers' keepsake: season, element, and the signs that came."""
    S = 2
    signs = result.get("signs") or []
    # Size the canvas to its content so the record never carries dead space.
    canvas_w = 1200
    canvas_h = 330 + (130 if result.get("element") else 0) \
                   + 112 * len(signs) + 140
    img, d = _frame(canvas_w, canvas_h, S)

    subtitle = f"drawn for {client_name}" if client_name else ""
    _header(d, S, canvas_w, tier or "The land", "The Record of the Land", subtitle)

    cx = canvas_w * S / 2
    y = 330 * S

    element = (result.get("element") or "").upper()
    if element:
        _tracked(d, "THE ELEMENT", cx, y, _font(15 * S), LEAF, 5 * S)
        _centre(d, element, cx, y + 30 * S, _font(46 * S), PEACH)
        y += 130 * S

    if signs:
        _tracked(d, "THE SIGNS", cx, y, _font(15 * S), LEAF, 5 * S)
        y += 42 * S
        for s in signs:
            kind = (s.get("kind") or "").upper()
            _tracked(d, kind, cx, y, _font(13 * S), CREAM_FAINT, 3 * S)
            _centre(d, s.get("name", ""), cx, y + 22 * S, _font(34 * S), CREAM)
            _centre(d, f"({s.get('element','')})", cx, y + 68 * S,
                    _font(17 * S), LEAF_PALE)
            y += 112 * S

    foot = []
    season = (result.get("season_line") or
              (result.get("season") or {}).get("season_line", ""))
    if season:
        foot.append(season)
    if reading_date:
        foot.append(f"read {reading_date}")
    foot.append("Written by hand, at the edge of the woods.")
    _footer(d, S, canvas_w, canvas_h, foot)

    return _save(img, S, canvas_w, canvas_h, output_path)


# ─── CLI TEST ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rune_engine import draw_reading as rune_draw
    from land_engine import draw_reading as land_draw

    out = Path(__file__).parent / "_record_samples"
    out.mkdir(exist_ok=True)

    for tier in ("First Stone", "Rune Casting", "The Nine Worlds"):
        r = rune_draw("Marion", "03/14/1988", "clarity", tier,
                      reading_date="2026-07-26")
        b = generate_record_image(r, "clarity", "Marion", tier, "2026-07-26",
                                  output_path=out / f"{tier.replace(' ', '_')}.jpg")
        print(f"{tier}: {len(b):,} bytes")

    l = land_draw("Marion", "03/14/1988", "clarity", "Reading of the Land",
                  reading_date="2026-07-26")
    lr = {"season_line": l["season"]["season_line"], "element": l["element"],
          "signs": l["signs"], "name_number": l["name_number"]}
    b = generate_record_image(lr, "clarity", "Marion", "Reading of the Land",
                              "2026-07-26", output_path=out / "Reading_of_the_Land.jpg")
    print(f"Reading of the Land: {len(b):,} bytes")

    # every rune has strokes
    from rune_engine import RUNES
    missing = [r[0] for r in RUNES if r[0] not in RUNE_STROKES]
    assert not missing, f"no strokes for: {missing}"
    print(f"all {len(RUNE_STROKES)} runes have cut strokes")
