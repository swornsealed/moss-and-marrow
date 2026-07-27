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

from rune_engine import RUNES, AETT_NAMES
from land_engine import ELEMENTS, SABBATS

try:
    from PIL import Image, ImageDraw
except ImportError:                                    # pragma: no cover
    pass


# ─── WHAT EACH GUIDE SAYS ─────────────────────────────────────────────────────
# Willow's voice: plain, unhurried, and straight about the method. A section
# is (heading, blocks); a block is either a paragraph of prose or a
# (term, meaning) pair, which renders as a small entry. The sections that
# matter most are the ones about the customer's own draw, because a guide
# that only explains the system leaves them no better off with the reading
# in front of them.

AETT_NOTES = [
    ("Freyr's eight", "livelihood and the made world: cattle, harvest, "
     "craft, the gift, the road. What people build and hold."),
    ("Heimdall's eight", "weather and ordeal: hail, need, ice, the yew, "
     "the lot-cup. What happens TO us, and what is endured."),
    ("Tyr's eight", "bonds and inheritance: the oath, the birch, the horse, "
     "the human, the homestead. What is owed between people."),
]

POSITION_NOTES = {
    1: [("The one stone", "drawn for the question as it was asked. No "
         "spread, no positions: one question, one answer.")],
    5: [("Beneath", "the root of the matter, sitting under everything else."),
        ("Behind", "what was laid down before this began, and binds it still."),
        ("Where you stand", "the present, in the act of becoming."),
        ("What is owed", "the debt, cost or task that must be answered. This "
         "is the hinge: it stands between where you are and what comes."),
        ("What becomes", "the shape already forming ahead. A shape, not a "
         "sentence: it is conditional on what is owed being met.")],
    9: [("Across, the three lines", "the Norns. Urd is what was laid down, "
         "Verdandi what is becoming, Skuld what takes shape ahead."),
        ("Down, the three columns", "you, the matter itself, and what meets "
         "it. Your own column read top to bottom is usually the most "
         "telling line in the whole cast."),
        ("Why both directions", "a line tells you when something happens. A "
         "column tells you whose it is. Read one way and you get a story; "
         "read both and you get the pattern behind it.")],
}


def _rune_meaning(name):
    for n, _g, _a, _e, _hm, upright, _merk in RUNES:
        if n == name:
            return upright
    return ""


def _rune_sections(draw_result, tier):
    runes = draw_result.get("runes") or []
    n = len(runes)
    birth = draw_result.get("birth_rune") or ""

    yours = []
    for r in runes:
        pos = (r.get("position") or "").replace("-", " ")
        face = r.get("orientation", "upright")
        head = f"{r.get('rune','')} ({face})" if face == "merkstave" else r.get("rune", "")
        if n > 1:
            head = f"{head}, at {pos}"
        body = r.get("meaning", "")
        if face == "merkstave":
            body = (f"{body}. Upright this rune reads: {_rune_meaning(r.get('rune',''))}. "
                    "It landed reversed, so that force is blocked or comes at a cost.")
        aett = r.get("aett", "")
        el = r.get("element", "")
        if aett or el:
            body += f" ({aett}, {el})"
        yours.append((head, body))

    birth_block = []
    if birth:
        birth_block = [
            (birth, _rune_meaning(birth)),
            ("Why it matters", "The runic calendar gives every half month of "
             "the year to a rune. Yours is the one ruling the half month you "
             "were born into: your standing stone. It is weighted heaviest in "
             "every cast made for you, so it comes up more often than chance "
             "would give it. If it appears among the stones above, you have "
             "walked into your own reading, and that position is about you "
             "more than about circumstance."),
        ]
    else:
        birth_block = ["No date of birth was given with this reading, so no "
                       "birth rune was set. If you send one with your next "
                       "reading, your standing stone will be weighted into "
                       "the cast and marked on the record."]

    return [
        ("What you are looking at", [
            "The Elder Futhark: twenty-four marks used across northern Europe "
            "for centuries before anyone used them to spell words. Each one is "
            "named for a thing rather than a sound. Fehu is cattle. Isa is "
            "ice. Perthro is the cup the lots are shaken from. That is why a "
            "rune can be read at all: you are not reading a letter, you are "
            "reading the thing it is named for, standing in your situation.",
            "They are cut, not written. Every stave is straight or slanted, "
            "because a cut made along the grain splits the wood, so no rune "
            "has a horizontal line in it. Your record shows them as they are "
            "made: gouged into the face of the lot and reddened, which is how "
            "carved runes were filled so they could be read."]),

        ("The three families", [
            "The twenty-four fall into three eights, and knowing which family "
            "a stone belongs to tells you what kind of trouble or help it is."] +
            AETT_NOTES + [
            "When several stones in one cast come from the same family, that "
            "is the loudest thing on the ground. A cast weighted to "
            "Heimdall's eight is about what is happening to you. One weighted "
            "to Tyr's is about what is happening between you and someone."]),

        ("Why these stones and no others", [
            "Your cast was not shuffled fresh for the look of it. It is drawn "
            "from four things: your name, your date of birth, your question, "
            "and the day it was asked. The same person asking the same thing "
            "on the same day would be given these stones, in this order, "
            "these ways up, every time. They were always going to be yours.",
            "Some stones are likelier than others before a single one is "
            "drawn. The rune ruling the half month of your birth carries the "
            "most weight. Then the element your question belongs to: a "
            "question about feeling leans toward water, one about work "
            "toward earth. Then the season the reading was made in.",
            "Weight is not certainty. It leans a cast; it does not decide "
            "one. A stone with no weight behind it can still fall, and when "
            "it does it is usually the one worth the most attention."]),

        ("Face up and face down", [
            "Fifteen of the twenty-four runes look different upside down. "
            "When one of those lands reversed it is called merkstave. On your "
            "record it is drawn upside down, on a cooler stone, with the cut "
            "in a duller red, so you can see at a glance which fell that way.",
            "A merkstave stone is not doom, and it has not been softened for "
            "you either. It is the same force blocked, delayed, turned "
            "inward, or arriving at a cost. Algiz upright is a guard raised; "
            "reversed it is a guard dropped, or turned against the person it "
            "was meant to protect. The nine remaining runes look identical "
            "either way up and are never read reversed."]),

        ("The positions in your cast", POSITION_NOTES.get(n, POSITION_NOTES[5])),

        ("Your stones", [
            "These are the stones that fell for you, in the order they were "
            "laid, with what each carries in the face it landed."] + yours),

        ("Your birth rune", birth_block),

        ("How the reading was made", [
            "Each stone is read against its own position first: not what the "
            "rune means in general, but what it means sitting there, in your "
            "question. A rune of endurance means one thing under the matter "
            "and another as what is owed.",
            "Then the cast is read as one thing: which family the stones came "
            "from, which element outweighs the others, how many fell "
            "reversed. Three or more reversed is a genuinely obstructed cast "
            "and the letter will say so plainly rather than let it accumulate "
            "as a surprise.",
            "The letter you received is that reading written out. Nothing in "
            "it was decided before the stones fell."]),

        ("How to use it", [
            "Read the letter first, from the top. It is the reading. The "
            "record is what the reading was made from: the stones exactly as "
            "they fell, kept so you can go back to them.",
            "You do not need to act on it the day it arrives. Sit with what "
            "is owed, since that is usually the part that asks something of "
            "you. When the same question comes round again, a new cast on a "
            "new day will not repeat this one, and the difference between "
            "them is worth having."]),
    ]


def _land_sections(draw_result, tier):
    signs = draw_result.get("signs") or []
    element = (draw_result.get("element") or "").lower()
    prev = draw_result.get("prev_sabbat") or ""
    season_line = draw_result.get("season_line") or ""

    wheel_stations = []
    for _m, _d, name, el, line in SABBATS:
        wheel_stations.append((name, f"{line} ({el})"))

    element_entries = [(el, meaning) for el, meaning in ELEMENTS.items()]

    yours = []
    for sg in signs:
        kind = sg.get("kind", "")
        label = {"plant": "The plant", "animal": "The animal",
                 "root": "The root sign"}.get(kind, kind.title())
        head = f"{sg.get('name','')} ({label.lower()})"
        body = sg.get("note", "")
        if kind == "root":
            body += (". A root sign stands for what lies under the question: "
                     "the thing you did not think to ask")
        body += f" ({sg.get('element','')})"
        yours.append((head, body))

    where = []
    if season_line:
        where.append(f"Your reading was made {season_line}.")
    if prev:
        line = next((l for _m, _d, n, _e, l in SABBATS if n == prev), "")
        if line:
            where.append(f"That places you in the stretch that opens at "
                         f"{prev}: {line}. The stretch you are standing in "
                         f"leans the whole reading toward its own element, "
                         f"more than anything else does.")
    where.append("This is the one thread in your reading that is not "
                 "personal. Everyone who reads on the day you did stands at "
                 "the same point in the year. What is yours is the open mark "
                 "on the wheel, where you came into it.")

    return [
        ("What you are looking at", [
            "Three threads run through every reading here: where the year "
            "stands, which element is loudest in your life at the moment, and "
            "the living thing that keeps crossing your path. The record shows "
            "all three, and the letter reads them together.",
            "None of it is cast indoors. Your question goes outside and is "
            "read where it lives, in whatever weather the day brings."]),

        ("The wheel of the year", [
            "The eight turns of the year, at their real calendar positions "
            "with Yule at the top and the year running clockwise. Four are "
            "the sun's own stations, the solstices and equinoxes, drawn "
            "ringed: the sun keeps them whether or not anyone marks the day. "
            "Four are the old fire festivals, about livestock and grain, "
            "drawn filled, because people light them."] + wheel_stations + [
            "The shaded half is the dark of the year, running from Samhain "
            "round through Yule to Beltane. The pale band is the daylight the "
            "year is carrying: widest at midsummer, thinnest at midwinter, "
            "never gone. The red hand is the day your reading was made."]),

        ("Where the year stands for you", where),

        ("The four elements", [
            "An element is not a mood. It is what a situation is made of, and "
            "what it will and will not accept."] + element_entries + [
            "One of them is louder than the others in your situation. Naming "
            "it is what tells you whether the thing in front of you needs "
            "patience, feeling, force, or plain speech."]),

        ("Why this element and no other", [
            "As with everything here, the draw is made from your name, your "
            "date of birth, your question, and the day, so the same person "
            "asking the same thing on the same day would always be given "
            "this. It is not shuffled fresh each time it is looked at.",
            "The year is the loudest voice: the season you are standing in "
            "leans the draw toward its own element. Then the question you "
            "asked. Then the season you were born into, and the number in "
            "your name. Weight leans it. It does not decide it, which is why "
            "an element can come up that nothing was pushing toward."]),

        ("Your signs", [
            "The living things that came up for you, and what each carries."]
            + yours + [
            "Each is drawn on the record in the colour of its own element, so "
            "you can see which of them answer the element that was drawn and "
            "which came from somewhere else. A sign that does not match is "
            "not a mistake: it is the reading saying something arrived from "
            "outside the situation's own nature."]),

        ("How the reading was made", [
            "The season is read first, because it is the ground everything "
            "else stands on. Then the element, against your question. Then "
            "each sign, read for what it is doing in your situation rather "
            "than what it means in general.",
            "The letter you received is that reading written out, in "
            "movements you can follow from the top. Nothing in it was decided "
            "before the draw was made."]),

        ("How to use it", [
            "Read the letter first. It is the reading. The record is what it "
            "was read from, and it is yours to keep.",
            "When the wheel comes round to this place next year, you will "
            "have something to set beside it: the same stretch of the year, a "
            "year further on."]),
    ]


def _wrap_hanging(d, text, font, first_w, rest_w):
    """Wrap where the first line is short because a bold term precedes it."""
    words, lines, cur, width = text.split(), [], "", first_w
    for w in words:
        trial = (cur + " " + w).strip()
        if _tw(d, trial, font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
            width = rest_w
    if cur:
        lines.append(cur)
    return lines


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
        sections = _rune_sections(draw_result or {}, tier)
        title, kicker = "Reading the Cast", "how to read your record"
    else:
        sections = _land_sections(draw_result or {}, tier)
        title, kicker = "Reading the Land", "how to read your record"

    canvas_w = 1200
    head_f, body_f = _font(14 * S, bold=True), _font(17 * S)
    text_w = (canvas_w - 250) * S

    # Measure first, so the sheet is exactly as tall as its content. The
    # render advances y in supersampled units (26 * S a line); these figures
    # are the same advances expressed at 1x, which is what the canvas takes.
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    term_f = _font(17 * S, bold=True)

    def _block_lines(block):
        """How many body lines a block takes, prose or entry alike."""
        if isinstance(block, tuple):
            term, meaning = block
            indent = text_w - 20 * S
            first = indent - _tw(probe, term + ": ", term_f)
            return len(_wrap_hanging(probe, meaning, body_f, first, indent))
        return len(_wrap(probe, block, body_f, text_w))

    height = 330                                        # inset and header block
    for name, blocks in sections:
        height += 40                                    # the section heading
        for block in blocks:
            height += 26 * _block_lines(block) + 12
        height += 16                                    # gap after the section
    height += 190 if is_runes else 105                  # the diagram
    height += 110                                       # footer and bottom inset
    canvas_h = int(height)

    img, d, box = _frame_and_cloth(canvas_w, canvas_h, S)
    _header(d, S, canvas_w, box, kicker, title, tier or "")

    cx = canvas_w * S / 2
    left = box[0] + 125 * S
    y = box[1] + 268 * S

    for idx, (name, blocks) in enumerate(sections):
        _tracked(d, name.upper(), cx, y, head_f, INK_FAINT, 4 * S)
        y += 38 * S
        for block in blocks:
            if isinstance(block, tuple):
                # an entry: the term set in bold, its meaning running on from
                # it. The first line is short by the width of the term, which
                # is set in a wider face than the body it shares the line with.
                term, meaning = block
                x = left + 20 * S
                label = term + ":"
                label_w = _tw(d, label, term_f)
                indent = text_w - 20 * S
                lines = _wrap_hanging(d, meaning, body_f, indent - label_w, indent)
                d.text((x, y), label, font=term_f, fill=INK)
                if lines:
                    d.text((x + label_w + 6 * S, y), lines[0], font=body_f, fill=INK)
                y += 26 * S
                for ln in lines[1:]:
                    d.text((x, y), ln, font=body_f, fill=INK)
                    y += 26 * S
            else:
                for ln in _wrap(d, block, body_f, text_w):
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
        b = generate_guide_image({"runes": r["runes"], "birth_rune": r["birth_rune"]}, tier,
                                 output_path=out / f"guide_{tier.replace(' ', '_')}.jpg")
        print(f"{tier}: {len(b):,} bytes")

    for tier in ("First Sign", "Reading of the Land", "The Whole Ground"):
        l = land_draw("Marion", "03/14/1988", "clarity", tier,
                      reading_date="2026-07-27")
        b = generate_guide_image({"signs": l["signs"], "element": l["element"],
                                  "season_line": l["season"]["season_line"],
                                  "prev_sabbat": l["season"]["prev_sabbat"]}, tier,
                                 output_path=out / f"guide_{tier.replace(' ', '_')}.jpg")
        print(f"{tier}: {len(b):,} bytes")
