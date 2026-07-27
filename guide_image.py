"""
guide_image.py — Moss & Marrow
The companion that ships beside the record: a short guide to reading it.

A customer who cannot tell what they are looking at has been sent
decoration. The reading is the interpretation; the record is the evidence
it was read from; this sheet says what the evidence is and how it was
arrived at, including the part most people quietly wonder about, which is
whether any of it was chosen for them or simply shuffled.

Two families, because the shop reads two ways: the stones (Elder Futhark)
and the land (season, element, sign). Each guide is tier-aware, so it
describes the cast the customer actually received rather than every cast
the shop can produce.

Built on record_image's frame, cloth and type, so the guide and the record
are visibly one pair.
"""

from io import BytesIO
from pathlib import Path
from typing import Optional

from record_image import (
    PILLOW_AVAILABLE, CLOTH, INK, INK_DIM, INK_FAINT, TERRACOTTA,
    ELEMENT_COLOUR, WOOD, WOOD_M, OCHRE, OCHRE_M, OCHRE_DEEP, OCHRE_M_DEEP,
    RUNE_STROKES, _font, _tw, _centre, _tracked, _wrap,
    _frame_and_cloth, _header, _save, _element_mark, _carve,
)

try:
    from PIL import Image, ImageDraw
except ImportError:                                    # pragma: no cover
    pass


# ─── WHAT EACH GUIDE SAYS ─────────────────────────────────────────────────────
# Willow's voice: plain, no hedging, and honest about the method. The
# positions section is filled in per tier at render time.

RUNE_POSITIONS = {
    1: ["One stone, drawn for the question as it was asked. No positions, "
        "no spread. The shortest honest answer the shop sells."],
    5: ["Beneath: the root of the matter, under everything else.",
        "Behind: what was laid down before this began, and still binds.",
        "Where you stand: the present, in the act of becoming.",
        "What is owed: the debt or the task that must be answered. This is "
        "the hinge of the reading.",
        "What becomes: the shape already forming ahead."],
    9: ["Nine stones in three lines of three, read both ways.",
        "Across, the three lines are the Norns: what was laid down (Urd), "
        "what is becoming (Verdandi), what takes shape ahead (Skuld).",
        "Down, the three columns are you, the matter itself, and what meets "
        "it. Your own column, read top to bottom, is usually the most "
        "telling line in the cast."],
}


def _rune_sections(n_stones: int):
    return [
        ("What you are looking at", [
            "The Elder Futhark: twenty-four marks used across northern Europe "
            "long before anyone used them to spell words. Each one is named "
            "for a thing rather than a sound. Fehu is cattle. Isa is ice. "
            "Perthro is the cup the lots are shaken from.",
            "They are cut, not written. Every stave is straight or slanted "
            "because a cut made along the grain splits the wood. That is why "
            "no rune has a horizontal line in it."]),
        ("Why these stones and no others", [
            "Your cast was not shuffled fresh for the look of it. It is drawn "
            "from your name, your date of birth, your question, and the day "
            "it was asked. The same person asking the same thing on the same "
            "day would be given these stones, in this order, these ways up, "
            "every time. They were always going to be yours.",
            "Some stones are likelier than others. The rune that rules the "
            "half month of your birth carries the most weight, then the "
            "element your question belongs to, then the season the reading "
            "was made in. Weight is not certainty: it leans the cast, it "
            "does not decide it."]),
        ("Face up and face down", [
            "Fifteen of the twenty-four runes look different upside down. "
            "When one of those lands reversed it is called merkstave, and on "
            "your record it is drawn upside down, on a cooler stone, with the "
            "cut in a duller red.",
            "A merkstave stone is not doom and it has not been softened for "
            "you. It is the same force blocked, delayed, turned inward, or "
            "arriving at a cost. The other nine runes look the same either "
            "way up and are never reversed."]),
        ("The positions", RUNE_POSITIONS.get(n_stones, RUNE_POSITIONS[5])),
        ("Your birth rune", [
            "The runic calendar gives every half month of the year to a rune. "
            "The one ruling the half month you were born into is your "
            "standing stone, and it weighs on every cast made for you. If it "
            "turns up among the stones themselves, you have walked into your "
            "own reading, and that position is about you more than about "
            "circumstance."]),
        ("How to use it", [
            "Read the letter first, from the top. It is the reading. The "
            "record is what the reading was made from: the stones exactly as "
            "they fell.",
            "Keep it. When the same question comes round again, a new cast on "
            "a new day will not repeat this one, and the difference between "
            "them is worth having."]),
    ]


def _land_sections(n_signs: int):
    signs_text = [
        "A plant and an animal: what grows where you are, and what moves "
        "through it.",
    ]
    if n_signs >= 3:
        signs_text.append(
            "And a root sign, a second plant, standing for what lies under "
            "the question. That is the thing you did not think to ask.")
    if n_signs == 1:
        signs_text = ["One sign, plant or animal, for one question."]
    signs_text.append(
        "Each is drawn in the colour of its own element, so you can see at a "
        "glance which of them answer the element that was drawn and which "
        "came from somewhere else.")
    return [
        ("What you are looking at", [
            "Three threads run through every reading here. Where the year "
            "stands, which element is loudest in your life at the moment, and "
            "the living thing that keeps crossing your path.",
            "None of it is cast indoors. Your question goes out and is read "
            "where it lives."]),
        ("The wheel", [
            "The eight turns of the year. Four are the sun's own stations, "
            "the solstices and the equinoxes, and they are drawn ringed: the "
            "sun keeps them whether or not anyone marks the day. Four are the "
            "old fire festivals, about livestock and grain, and they are "
            "drawn filled, because people light them.",
            "The shaded half is the dark of the year, from Samhain round "
            "through Yule to Beltane. The pale band is the daylight the year "
            "is carrying, widest at midsummer and thinnest at midwinter. The "
            "red hand is the day your reading was made. The open mark is "
            "where you came into the year."]),
        ("The elements", [
            "Earth is patience and ground: what holds, and what must be built "
            "slowly. Water is feeling and memory: what moves under the "
            "surface. Fire is will and appetite: what wants to burn through. "
            "Air is thought and speech: what circles and will not land.",
            "One of them is louder than the others in your situation. Naming "
            "it says what the situation needs, and what it will not accept."]),
        ("Why this element and no other", [
            "The year is the loudest voice: the season you are standing in "
            "leans the draw toward its own element. Then the question you "
            "asked. Then the season you were born into, and the number in "
            "your name.",
            "As with the stones, the draw is made from your name, your date "
            "of birth, your question and the day, so the same person asking "
            "the same thing on the same day would always be given this. "
            "Weight leans it. It does not decide it."]),
        ("The signs", signs_text),
        ("How to use it", [
            "Read the letter first, from the top. It is the reading. The "
            "record is what it was read from.",
            "Keep it. When the wheel comes round to this place next year, you "
            "will have something to set beside it."]),
    ]


# ─── SMALL DIAGRAMS ───────────────────────────────────────────────────────────

def _mini_lot(d, cx, cy, w, h, rune, merkstave, S):
    """A lot at guide scale, to show upright against merkstave."""
    face = WOOD_M if merkstave else WOOD
    d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                        radius=int(w * 0.10), fill=face,
                        outline=(168, 140, 105), width=max(1, S))
    strokes = RUNE_STROKES.get(rune, [])
    rw, rh = w * 0.46, h * 0.54
    sx, sy = cx - rw / 2, cy - rh / 2
    width = max(3, int(w * 0.062))
    cut = OCHRE_M if merkstave else OCHRE
    deep = OCHRE_M_DEEP if merkstave else OCHRE_DEEP
    for (ax, ay), (bx, by) in strokes:
        if merkstave:
            ax, ay, bx, by = 1 - ax, 1 - ay, 1 - bx, 1 - by
        _carve(d, (sx + ax * rw, sy + ay * rh),
                  (sx + bx * rw, sy + by * rh), width, cut, deep, S)


def _rune_diagram(d, cx, y, S):
    w, h = 96 * S, 132 * S
    gap = 190 * S
    lab = _font(15 * S)
    _mini_lot(d, cx - gap / 2, y + h / 2, w, h, "Thurisaz", False, S)
    _centre(d, "upright", cx - gap / 2, y + h + 14 * S, lab, INK_DIM)
    _mini_lot(d, cx + gap / 2, y + h / 2, w, h, "Thurisaz", True, S)
    _centre(d, "merkstave", cx + gap / 2, y + h + 14 * S, lab, TERRACOTTA)
    return h + 44 * S


def _land_diagram(d, cx, y, S):
    order = ["earth", "water", "fire", "air"]
    gap = 132 * S
    x0 = cx - gap * (len(order) - 1) / 2
    for i, el in enumerate(order):
        _element_mark(d, el, x0 + i * gap, y + 24 * S, 42 * S,
                      ELEMENT_COLOUR[el], S, weight=max(2, int(S * 2.2)))
        _centre(d, el, x0 + i * gap, y + 56 * S, _font(16 * S), ELEMENT_COLOUR[el])
    return 92 * S


# ─── THE GUIDE ────────────────────────────────────────────────────────────────

def generate_guide_image(
    draw_result: dict,
    tier: str = "",
    output_path: Optional[str] = None,
) -> bytes:
    """Render the companion guide for a reading. Returns JPEG bytes."""
    if not PILLOW_AVAILABLE:
        raise ImportError("Pillow is required: pip install Pillow")

    S = 2
    runes = (draw_result or {}).get("runes") or []
    is_runes = bool(runes)
    if is_runes:
        sections = _rune_sections(len(runes))
        title, kicker = "Reading the Cast", "how to read your record"
    else:
        sections = _land_sections(len((draw_result or {}).get("signs") or []))
        title, kicker = "Reading the Land", "how to read your record"

    canvas_w = 1200
    head_f, body_f = _font(14 * S, bold=True), _font(17 * S)
    text_w = (canvas_w - 250) * S

    # Measure first, so the sheet is exactly as tall as its content. The
    # render advances y in supersampled units (26 * S a line); these figures
    # are the same advances expressed at 1x, which is what the canvas takes.
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    height = 330                                        # inset and header block
    for name, paras in sections:
        height += 40                                    # the section heading
        for para in paras:
            height += 26 * len(_wrap(probe, para, body_f, text_w)) + 12
        height += 16                                    # gap after the section
    height += 190 if is_runes else 105                  # the diagram
    height += 110                                       # footer and bottom inset
    canvas_h = int(height)

    img, d, box = _frame_and_cloth(canvas_w, canvas_h, S)
    _header(d, S, canvas_w, box, kicker, title, tier or "")

    cx = canvas_w * S / 2
    left = box[0] + 125 * S
    y = box[1] + 268 * S

    for idx, (name, paras) in enumerate(sections):
        _tracked(d, name.upper(), cx, y, head_f, INK_FAINT, 4 * S)
        y += 38 * S
        for para in paras:
            for ln in _wrap(d, para, body_f, text_w):
                d.text((left, y), ln, font=body_f, fill=INK)
                y += 26 * S
            y += 12 * S
        # the diagram sits under the section it explains
        if is_runes and name == "Face up and face down":
            y += _rune_diagram(d, cx, y, S) + 10 * S
        elif (not is_runes) and name == "The elements":
            y += _land_diagram(d, cx, y, S) + 10 * S
        y += 16 * S

    _centre(d, "Written by hand, at the edge of the woods.",
            cx, box[3] - 52 * S, _font(16 * S), INK_FAINT)

    return _save(img, canvas_w, canvas_h, output_path)


# ─── CLI TEST ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from rune_engine import draw_reading as rune_draw
    from land_engine import draw_reading as land_draw

    out = Path(__file__).parent / "_record_samples"
    out.mkdir(exist_ok=True)

    for tier in ("First Stone", "Rune Casting", "The Nine Worlds"):
        r = rune_draw("Marion", "03/14/1988", "clarity", tier,
                      reading_date="2026-07-27")
        b = generate_guide_image({"runes": r["runes"]}, tier,
                                 output_path=out / f"guide_{tier.replace(' ', '_')}.jpg")
        print(f"{tier}: {len(b):,} bytes")

    for tier in ("First Sign", "Reading of the Land", "The Whole Ground"):
        l = land_draw("Marion", "03/14/1988", "clarity", tier,
                      reading_date="2026-07-27")
        b = generate_guide_image({"signs": l["signs"], "element": l["element"]}, tier,
                                 output_path=out / f"guide_{tier.replace(' ', '_')}.jpg")
        print(f"{tier}: {len(b):,} bytes")
