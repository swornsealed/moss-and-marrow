"""
record_image.py — Moss & Marrow
Renders the keepsake that ships with a reading: the Record of the Cast
(rune tiers) or the Record of the Land (land tiers).

The design follows what the sources actually describe. Tacitus (Germania,
ch. 10, c. 98 AD) gives the canonical account of Germanic lot-casting: a
branch is cut from a nut-bearing tree, sliced into strips, each marked with
a sign, and the lots are thrown onto a white cloth before being lifted and
read. So the object here is not a pebble on dark ground. It is a pale
wooden lot on linen.

Three further details from the record, all of them visual:

  * Runes are knife-cuts. Every stave is straight or diagonal because a
    horizontal cut runs along the grain and splits the wood. The strokes
    below are the cuts you would actually make, in order.
  * Cuts were reddened. The sagas use rjoda, "to redden": carved runes were
    filled with ochre so they could be read. The cuts here are rust-red.
  * Lots are thrown, not placed. Each falls at its own angle, seeded from
    the rune and its position so the same cast always lands the same way.

Rune glyphs are drawn as vector strokes rather than set in a font: the
Runic unicode block is not reliably installed on the Actions runner, a
merkstave lot can be turned genuinely upside down, and the art scales
without going soft. The canvas renders at 2x and downsamples.
"""

import hashlib
import math
from io import BytesIO
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:                                    # pragma: no cover
    PILLOW_AVAILABLE = False


# ─── PALETTE ──────────────────────────────────────────────────────────────────
# Forest frame (the brand), linen cloth (Tacitus), rowan wood, ochre cuts.

FRAME_TOP    = ( 26,  56,  38)     # moss in the light
FRAME_BOT    = ( 14,  32,  21)     # moss in shadow
CLOTH        = (238, 232, 216)     # the white cloth, warmed to linen
CLOTH_SHADE  = (223, 215, 196)     # its weave and fold
CLOTH_EDGE   = (206, 197, 175)
WOOD         = (223, 203, 172)     # rowan, cut and planed
WOOD_DARK    = (198, 174, 140)     # grain
WOOD_EDGE    = (168, 140, 105)     # the sawn edge
WOOD_M       = (206, 190, 168)     # a lot fallen merkstave sits cooler
WOOD_M_DARK  = (182, 164, 140)
OCHRE        = (162,  58,  38)     # the reddened cut
OCHRE_DEEP   = (108,  34,  24)     # pigment pooled at the bottom of the V
OCHRE_M      = (128,  58,  46)     # duller in a merkstave cut
OCHRE_M_DEEP = ( 86,  38,  32)
CUT_SHADE    = (176, 148, 112)     # the wall of the groove facing the light
CUT_LIP      = (236, 219, 191)     # the wall catching it
INK          = ( 44,  40,  32)     # type on the cloth
INK_DIM      = ( 98,  92,  78)
INK_FAINT    = (132, 125, 108)
PEACH        = (255, 185, 143)     # the brand accent, on the frame only
CREAM        = (248, 246, 239)
RULE         = (192, 182, 160)


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


# ─── WHAT THE RUNES ARE NAMED FOR ─────────────────────────────────────────────
# Every rune name is a concrete thing. Naming it under the lot is the lore
# the keepsake is missing: Fehu is cattle, Perthro is the lot-cup itself.

RUNE_LORE = {
    "Fehu":     "cattle",        "Uruz":     "the aurochs",
    "Thurisaz": "the thorn",     "Ansuz":    "the mouth",
    "Raidho":   "the ride",      "Kenaz":    "the torch",
    "Gebo":     "the gift",      "Wunjo":    "joy",
    "Hagalaz":  "hail",          "Nauthiz":  "need",
    "Isa":      "ice",           "Jera":     "the year",
    "Eihwaz":   "the yew",       "Perthro":  "the lot-cup",
    "Algiz":    "the elk",       "Sowilo":   "the sun",
    "Tiwaz":    "the star",      "Berkano":  "the birch",
    "Ehwaz":    "the horse",     "Mannaz":   "the human",
    "Laguz":    "water",         "Ingwaz":   "the seed",
    "Othala":   "the homestead", "Dagaz":    "daybreak",
}


# ─── LAYOUTS ──────────────────────────────────────────────────────────────────
# Canvas, lot size, and lot centres at 1x. Lots are thrown, so the spacing
# leaves room for each to sit at its own angle.

def _layout(n: int):
    if n == 1:
        return 980, 1180, 230, 330, [(490, 610)]
    if n == 9:
        return 1360, 1760, 180, 250, [
            (x, y) for y in (570, 970, 1370) for x in (350, 680, 1010)]
    w, h = 1580, 1060
    margin = 210
    step = (w - 2 * margin) / (n - 1) if n > 1 else 0
    return w, h, 200, 285, [(margin + step * i, 585) for i in range(n)]


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
    widths = [_tw(d, ch, font) for ch in text]
    total = sum(widths) + track * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=font, fill=fill)
        x += w + track


def _wrap(d, text, font, max_w):
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


def _angle_for(rune: str, position: str) -> float:
    """A thrown lot lands where it lands, but the same cast must always
    render the same way, so the angle is hashed from the lot itself."""
    h = hashlib.sha256(f"{rune}|{position}".encode()).digest()
    return (h[0] / 255.0) * 16.0 - 8.0          # -8 to +8 degrees


# ─── THE CUT ──────────────────────────────────────────────────────────────────

def _cut_poly(p1, p2, width, taper=0.17):
    """A knife cut is not a stroke of even width. The blade enters at a point,
    opens to full width through the middle, and lifts to a point again, so the
    cut is a long lens rather than a rectangle."""
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return None
    ux, uy = dx / length, dy / length
    px, py = -uy, ux                     # perpendicular to the cut
    hw = width / 2.0
    t = length * taper
    b = (x1 + ux * t, y1 + uy * t)       # shoulder near the entry
    c = (x2 - ux * t, y2 - uy * t)       # shoulder near the lift
    return [(x1, y1),
            (b[0] + px * hw, b[1] + py * hw),
            (c[0] + px * hw, c[1] + py * hw),
            (x2, y2),
            (c[0] - px * hw, c[1] - py * hw),
            (b[0] - px * hw, b[1] - py * hw)]


def _carve(d, p1, p2, width, cut, deep, S):
    """Gouge one cut and redden it.

    A V-groove lit from the upper left is shaded on its upper-left wall and
    lit on its lower-right one, which is the reverse of a raised line: that
    inversion is what makes the mark read as cut INTO the wood rather than
    drawn on top of it. The pigment sits deepest along the centre.
    """
    o = max(1.0, width * 0.11)
    shade = _cut_poly((p1[0] - o, p1[1] - o), (p2[0] - o, p2[1] - o), width * 1.16)
    lip   = _cut_poly((p1[0] + o, p1[1] + o), (p2[0] + o, p2[1] + o), width * 1.11)
    body  = _cut_poly(p1, p2, width)
    core  = _cut_poly(p1, p2, width * 0.40, taper=0.30)
    if not body:
        return
    if shade:
        d.polygon(shade, fill=CUT_SHADE)
    if lip:
        d.polygon(lip, fill=CUT_LIP)
    d.polygon(body, fill=cut)
    if core:
        d.polygon(core, fill=deep)


# ─── THE LOT ──────────────────────────────────────────────────────────────────

def _lot_tile(rune, merkstave, w, h, S):
    """One wooden lot with its rune cut and reddened, on a transparent tile
    big enough to rotate inside."""
    pad = int(max(w, h) * 0.35)
    tw_, th_ = w + pad * 2, h + pad * 2
    tile = Image.new("RGBA", (tw_, th_), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)

    face  = WOOD_M if merkstave else WOOD
    grain = WOOD_M_DARK if merkstave else WOOD_DARK
    cut   = OCHRE_M if merkstave else OCHRE

    x0, y0, x1, y1 = pad, pad, pad + w, pad + h
    r = int(w * 0.10)
    d.rounded_rectangle([x0, y0, x1, y1], radius=r,
                        fill=face, outline=WOOD_EDGE, width=max(2, S))

    # long grain down the strip, the way a sliced branch runs
    gh = hashlib.sha256(rune.encode()).digest()
    for i in range(5):
        gx = x0 + int(w * (0.16 + 0.17 * i)) + (gh[i] % 7) - 3
        top = y0 + int(h * 0.06) + (gh[i + 5] % 9)
        bot = y1 - int(h * 0.06) - (gh[i + 10] % 9)
        d.line([(gx, top), (gx, bot)], fill=grain, width=max(1, S // 2))

    # the sawn ends read darker
    d.line([(x0 + r, y0 + 2), (x1 - r, y0 + 2)], fill=WOOD_EDGE, width=max(1, S // 2))
    d.line([(x0 + r, y1 - 2), (x1 - r, y1 - 2)], fill=WOOD_EDGE, width=max(1, S // 2))

    # the cuts themselves, gouged and reddened
    strokes = RUNE_STROKES.get(rune)
    if strokes:
        rw, rh = w * 0.46, h * 0.54
        cx, cy = pad + w / 2, pad + h / 2
        sx, sy = cx - rw / 2, cy - rh / 2
        width = max(4, int(w * 0.062))
        deep = OCHRE_M_DEEP if merkstave else OCHRE_DEEP
        for (ax, ay), (bx, by) in strokes:
            if merkstave:
                ax, ay, bx, by = 1 - ax, 1 - ay, 1 - bx, 1 - by
            _carve(d, (sx + ax * rw, sy + ay * rh),
                      (sx + bx * rw, sy + by * rh), width, cut, deep, S)
    return tile


def _place_lot(canvas, shadow, rune, merkstave, cx, cy, w, h, angle, S):
    tile = _lot_tile(rune, merkstave, w, h, S)
    rot = tile.rotate(angle, resample=Image.BICUBIC, expand=False)
    px, py = int(cx - rot.width / 2), int(cy - rot.height / 2)

    sil = Image.new("RGBA", rot.size, (0, 0, 0, 0))
    sil.paste((0, 0, 0, 70), (0, 0), rot.split()[3])
    shadow.alpha_composite(sil, (px + int(5 * S), py + int(9 * S)))
    canvas.alpha_composite(rot, (px, py))


# ─── THE CLOTH ────────────────────────────────────────────────────────────────

def _frame_and_cloth(canvas_w, canvas_h, S, inset=52):
    """Forest ground, then the cloth the lots were thrown onto."""
    w, h = canvas_w * S, canvas_h * S
    img = Image.new("RGB", (w, h), FRAME_BOT)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = (y / h) ** 0.8
        d.line([(0, y), (w, y)], fill=tuple(
            int(a + (b - a) * t) for a, b in zip(FRAME_TOP, FRAME_BOT)))

    i = inset * S
    box = [i, i, w - i, h - i]

    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [box[0] + 4 * S, box[1] + 8 * S, box[2] + 4 * S, box[3] + 8 * S],
        radius=6 * S, fill=(0, 0, 0, 90))
    img = Image.alpha_composite(img.convert("RGBA"),
                                sh.filter(ImageFilter.GaussianBlur(7 * S)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=6 * S, fill=CLOTH, outline=CLOTH_EDGE, width=S)
    img = img.convert("RGBA")

    # Cloth, with no lines in it at all. Ruled lines in either direction read
    # as graph paper, and drawn threads read as banding, so the texture is
    # made of noise only: a fine grain for the fibre, and a broad mottle
    # underneath for the unevenness of cloth that has been laid down.
    cw, ch = int(box[2] - box[0]), int(box[3] - box[1])
    if cw > 0 and ch > 0:
        mottle = (Image.effect_noise((cw, ch), 44)
                  .filter(ImageFilter.GaussianBlur(26 * S)))
        broad = Image.new("RGBA", (cw, ch), CLOTH_SHADE + (255,))
        broad.putalpha(mottle.point(lambda v: min(54, int(abs(v - 128) * 2.6))))
        img.alpha_composite(broad, (int(box[0]), int(box[1])))

        fibre = (Image.effect_noise((cw, ch), 18)
                 .filter(ImageFilter.GaussianBlur(0.5)))
        grain = Image.new("RGBA", (cw, ch), CLOTH_SHADE + (255,))
        grain.putalpha(fibre.point(lambda v: int(abs(v - 128) * 0.26)))
        img.alpha_composite(grain, (int(box[0]), int(box[1])))

    return img, ImageDraw.Draw(img), box


def _header(d, S, canvas_w, box, kicker, title, subtitle):
    cx = canvas_w * S / 2
    _tracked(d, "MOSS & MARROW", cx, box[1] + 34 * S,
             _font(17 * S, bold=True), INK_DIM, 6 * S)
    if kicker:
        _tracked(d, kicker.upper(), cx, box[1] + 74 * S,
                 _font(14 * S), INK_FAINT, 5 * S)
    _centre(d, title, cx, box[1] + 112 * S, _font(50 * S), INK)
    if subtitle:
        _centre(d, subtitle, cx, box[1] + 180 * S, _font(22 * S), INK_DIM)
    d.line([(cx - 62 * S, box[1] + 224 * S), (cx + 62 * S, box[1] + 224 * S)],
           fill=RULE, width=2 * S)


def _footer(d, S, canvas_w, box, lines):
    f = _font(16 * S)
    wrapped = []
    for ln in lines:
        wrapped.extend(_wrap(d, ln, f, (box[2] - box[0]) - 80 * S))
    y = box[3] - (26 + 24 * len(wrapped)) * S
    for ln in wrapped:
        _centre(d, ln, canvas_w * S / 2, y, f, INK_FAINT)
        y += 24 * S


def _save(img, canvas_w, canvas_h, output_path):
    img = img.convert("RGB").resize((canvas_w, canvas_h), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92, optimize=True)
    if output_path:
        img.save(output_path, format="JPEG", quality=92)
    return buf.getvalue()


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

def generate_record_image(
    draw_result: dict,
    reading_type: str = "",
    client_name: str = "",
    tier: str = "",
    reading_date: str = "",
    output_path: Optional[str] = None,
) -> bytes:
    """Render the keepsake record from a draw. A rune cast carries "runes";
    a land reading carries "signs". Moss & Marrow draws no cards.
    Returns raw JPEG bytes for email attachment."""
    if not PILLOW_AVAILABLE:
        raise ImportError("Pillow is required: pip install Pillow")

    runes = (draw_result or {}).get("runes") or []
    if runes:
        return _render_cast(runes, draw_result or {}, client_name, tier,
                            reading_date, output_path)
    return _render_land(draw_result or {}, client_name, tier,
                        reading_date, output_path)


def _render_cast(runes, result, client_name, tier, reading_date, output_path):
    S = 2
    canvas_w, canvas_h, lw, lh, spots = _layout(len(runes))
    img, d, box = _frame_and_cloth(canvas_w, canvas_h, S)

    _header(d, S, canvas_w, box, tier or "the stones",
            "The Record of the Cast",
            f"cast for {client_name}" if client_name else "")

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    lots = Image.new("RGBA", img.size, (0, 0, 0, 0))
    for r, (cx, cy) in zip(runes, spots):
        _place_lot(lots, shadow, r.get("rune", ""),
                   r.get("orientation") == "merkstave",
                   cx * S, cy * S, lw * S, lh * S,
                   _angle_for(r.get("rune", ""), r.get("position", "")), S)

    img = Image.alpha_composite(img.convert("RGBA"),
                                shadow.filter(ImageFilter.GaussianBlur(6 * S)))
    img = Image.alpha_composite(img, lots)
    d = ImageDraw.Draw(img)

    # With nine lots the name and its lore share one line, or the rows run
    # into each other. With one or five there is room to stack them.
    tight = len(runes) > 5
    label_f = _font(14 * S, bold=True)
    name_f  = _font(21 * S if tight else 23 * S)
    lore_f  = _font(16 * S)
    merk_f  = _font(13 * S)
    for r, (cx, cy) in zip(runes, spots):
        cxS, cyS = cx * S, cy * S
        name = r.get("rune", "")
        lore = RUNE_LORE.get(name, "")
        pos = (r.get("position") or "").replace("-", " ").upper()
        _tracked(d, pos, cxS, cyS - (lh / 2 + 40) * S, label_f, INK_DIM, 3 * S)
        if tight:
            _centre(d, f"{name}  ·  {lore}" if lore else name,
                    cxS, cyS + (lh / 2 + 22) * S, name_f, INK)
            merk_y = lh / 2 + 50
        else:
            _centre(d, name, cxS, cyS + (lh / 2 + 22) * S, name_f, INK)
            if lore:
                _centre(d, lore, cxS, cyS + (lh / 2 + 56) * S, lore_f, INK_FAINT)
            merk_y = lh / 2 + 82
        if r.get("orientation") == "merkstave":
            _centre(d, "merkstave", cxS, cyS + merk_y * S, merk_f, OCHRE)

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
    _footer(d, S, canvas_w, box, foot)

    return _save(img, canvas_w, canvas_h, output_path)


def _render_land(result, client_name, tier, reading_date, output_path):
    S = 2
    signs = result.get("signs") or []
    canvas_w = 1200
    canvas_h = 320 + (128 if result.get("element") else 0) + 118 * len(signs) + 150
    img, d, box = _frame_and_cloth(canvas_w, canvas_h, S)

    _header(d, S, canvas_w, box, tier or "the land",
            "The Record of the Land",
            f"drawn for {client_name}" if client_name else "")

    cx = canvas_w * S / 2
    y = box[1] + 268 * S

    if result.get("element"):
        _tracked(d, "THE ELEMENT", cx, y, _font(14 * S), INK_FAINT, 5 * S)
        _centre(d, result["element"].upper(), cx, y + 28 * S, _font(44 * S), OCHRE)
        y += 128 * S

    if signs:
        _tracked(d, "THE SIGNS", cx, y, _font(14 * S), INK_FAINT, 5 * S)
        y += 40 * S
        for s in signs:
            _tracked(d, (s.get("kind") or "").upper(), cx, y,
                     _font(12 * S), INK_FAINT, 3 * S)
            _centre(d, s.get("name", ""), cx, y + 20 * S, _font(32 * S), INK)
            _centre(d, s.get("element", ""), cx, y + 64 * S, _font(16 * S), INK_DIM)
            y += 118 * S

    foot = []
    season = (result.get("season_line") or
              (result.get("season") or {}).get("season_line", ""))
    if season:
        foot.append(season)
    if reading_date:
        foot.append(f"read {reading_date}")
    foot.append("Written by hand, at the edge of the woods.")
    _footer(d, S, canvas_w, box, foot)

    return _save(img, canvas_w, canvas_h, output_path)


# ─── CLI TEST ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rune_engine import draw_reading as rune_draw, RUNES
    from land_engine import draw_reading as land_draw

    out = Path(__file__).parent / "_record_samples"
    out.mkdir(exist_ok=True)

    for tier in ("First Stone", "Rune Casting", "The Nine Worlds"):
        r = rune_draw("Marion", "03/14/1988", "clarity", tier,
                      reading_date="2026-07-27")
        stored = {"runes": r["runes"], "birth_rune": r["birth_rune"],
                  "season_line": r["season"]["season_line"]}
        b = generate_record_image(stored, "clarity", "Marion", tier, "2026-07-27",
                                  output_path=out / f"{tier.replace(' ', '_')}.jpg")
        print(f"{tier}: {len(b):,} bytes")

    l = land_draw("Marion", "03/14/1988", "clarity", "Reading of the Land",
                  reading_date="2026-07-27")
    lr = {"season_line": l["season"]["season_line"], "element": l["element"],
          "signs": l["signs"]}
    b = generate_record_image(lr, "clarity", "Marion", "Reading of the Land",
                              "2026-07-27", output_path=out / "Reading_of_the_Land.jpg")
    print(f"Reading of the Land: {len(b):,} bytes")

    missing = [r[0] for r in RUNES if r[0] not in RUNE_STROKES]
    assert not missing, f"no strokes for: {missing}"
    no_lore = [r[0] for r in RUNES if r[0] not in RUNE_LORE]
    assert not no_lore, f"no lore for: {no_lore}"
    print(f"all {len(RUNE_STROKES)} runes have cuts and lore")
