"""
rune_engine.py — Moss & Marrow
Deterministic Elder Futhark casting engine.

The rune sibling of Sworn & Sealed's tarot_engine.py and this shop's
land_engine.py, with the same call shape: process_orders.py calls
draw_reading(...) and receives a dict whose `formatted_block` is pasted
into the Claude intake message.

Casts are seeded with SHA-256 from the reading inputs. Same person, same
question, same day — always the same stones, the same faces up. The cast
was always going to fall this way for this person at this moment.

Traditional influences woven into the weighting (mirroring the tarot
engine's birth card / sun sign / planetary day):
  1. Birth rune      — the rune ruling the half-month of birth in the
                       runic calendar (2.2x). The Futhark's own birth card.
  2. Question type   — each reading type has an elemental affinity; runes
                       of that element burn brighter (1.4x).
  3. Season element  — the element the current season leans toward, from
                       land_engine.season_position (1.3x). The cast stays
                       tied to the living year, as everything here is.
  4. Name number     — Pythagorean numerology of the name, reduced onto
                       one of the three ættir (1.2x on its eight runes).

Three casts ladder by tier (TIER_SPREAD): one stone (First Stone), five
(Rune Casting), nine in three lines of three (The Nine Worlds).

Merkstave: invertible runes fall face-down-reversed 30% of the time,
deterministically. Nine runes are the same stone either way up (Gebo,
Hagalaz, Nauthiz, Isa, Jera, Eihwaz, Sowilo, Ingwaz, Dagaz) and are
always read upright — the engine never marks them merkstave.
"""

import hashlib
import random
from datetime import datetime, date
from zoneinfo import ZoneInfo

from land_engine import season_position, TYPE_ELEMENT, name_number


# ─── THE 24 RUNES OF THE ELDER FUTHARK ────────────────────────────────────────
# (name, glyph, aett 0-2, element, half-month start (month, day), upright, merkstave)
# Ætt 0 = Freyr's eight, 1 = Heimdall's eight, 2 = Tyr's eight.
# Half-months follow the runic calendar: Fehu opens on 29 June; each rune
# rules roughly fifteen days. (Dagaz and Othala trade places in some older
# listings; the calendar below closes the year with Dagaz into Fehu.)
# Merkstave = None marks the nine non-invertible stones.

RUNES = [
    # ── Freyr's ætt ──
    ("Fehu",     "ᚠ", 0, "earth", (6, 29),
     "mobile wealth, earned abundance, resources in motion; what is tended multiplies",
     "dissipation, income slipping, wealth held too tightly to grow"),
    ("Uruz",     "ᚢ", 0, "earth", (7, 14),
     "raw vitality, untamed strength, health returning, the will to endure",
     "strength misdirected, a worn-down will, force used where patience was owed"),
    ("Thurisaz", "ᚦ", 0, "fire", (7, 29),
     "the protective thorn, necessary conflict, a catalytic force that clears the way",
     "spite, recklessness, walking into a fight that was never yours"),
    ("Ansuz",    "ᚨ", 0, "air", (8, 13),
     "a message arriving, true speech, counsel from an elder or an unexpected mouth",
     "words twisted, advice that serves the giver, a message missed or withheld"),
    ("Raidho",   "ᚱ", 0, "air", (8, 29),
     "a journey underway, right movement, the road that orders itself once taken",
     "a stalled journey, movement for its own sake, the wrong road held out of pride"),
    ("Kenaz",    "ᚲ", 0, "fire", (9, 13),
     "the controlled flame, skill and craft, insight that lights the work at hand",
     "a light withheld, false clarity, skill gone cold from disuse"),
    ("Gebo",     "ᚷ", 0, "air", (9, 28),
     "a gift and its obligation, exchange in balance, partnership sealed by giving",
     None),
    ("Wunjo",    "ᚹ", 0, "air", (10, 13),
     "joy earned, harmony in the household, the clearing that follows honest effort",
     "joy postponed, sorrow carried quietly, celebration before the work is done"),
    # ── Heimdall's ætt ──
    ("Hagalaz",  "ᚺ", 1, "water", (10, 28),
     "the hailstorm, disruption from outside; what levels the field also waters it",
     None),
    ("Nauthiz",  "ᚾ", 1, "fire", (11, 13),
     "need and constraint, the fire lit in scarcity; what lack is here to teach",
     None),
    ("Isa",      "ᛁ", 1, "water", (11, 28),
     "ice and standstill, the frozen river that must be waited out; clarity in stillness",
     None),
    ("Jera",     "ᛃ", 1, "earth", (12, 13),
     "the year's rightful harvest; what was honestly planted ripens in its own season",
     None),
    ("Eihwaz",   "ᛇ", 1, "earth", (12, 28),
     "the yew, endurance through endings, the spine of the matter, a reliable defence",
     None),
    ("Perthro",  "ᛈ", 1, "water", (1, 13),
     "the lot-cup, the unrevealed, what is still being decided beneath the surface",
     "secrets working against you, a gamble already lost, refusing to be seen"),
    ("Algiz",    "ᛉ", 1, "air", (1, 28),
     "protection, the raised guard, sanctuary honestly kept, help from what watches",
     "the guard dropped or turned inward, a warning ignored, false shelter"),
    ("Sowilo",   "ᛊ", 1, "fire", (2, 12),
     "the sun that cannot be argued with; vitality, success approaching, the goal visible",
     None),
    # ── Tyr's ætt ──
    ("Tiwaz",    "ᛏ", 2, "air", (2, 27),
     "justice and the kept oath, courage in right order, victory through a cost honestly paid",
     "an unjust fight, a cause without honour, letting the cost fall on others"),
    ("Berkano",  "ᛒ", 2, "earth", (3, 14),
     "the birch, birth and becoming, new growth after clearing, tending the small into being",
     "growth stalled, care withheld, a beginning that needs different soil"),
    ("Ehwaz",    "ᛖ", 2, "earth", (3, 30),
     "the horse, partnership that moves, trust between two travelling together",
     "mistrust in harness, a pairing pulling two directions, restlessness without aim"),
    ("Mannaz",   "ᛗ", 2, "air", (4, 14),
     "the human weave, community, aid given and received as equals, knowing your place in the pattern",
     "isolation, self-regard blocking help, expecting what you will not give"),
    ("Laguz",    "ᛚ", 2, "water", (4, 29),
     "the water, intuition trusted, what moves beneath reason; the current that knows the sea",
     "flood or drought of feeling, intuition overruled, fear of the deep"),
    ("Ingwaz",   "ᛜ", 2, "earth", (5, 14),
     "the seed at rest, potential gathered and stored, a completed stage awaiting its spring",
     None),
    ("Othala",   "ᛟ", 2, "earth", (5, 29),
     "inheritance and the homestead, ground held by long tending, what is yours by right of care",
     "clinging to what should pass, the weight of kin, fences built where gates belong"),
    ("Dagaz",    "ᛞ", 2, "fire", (6, 14),
     "daybreak, the turn that cannot be stopped, transformation completed between two breaths",
     None),
]

AETT_NAMES = ("Freyr's ætt", "Heimdall's ætt", "Tyr's ætt")

# ─── THE CASTS ────────────────────────────────────────────────────────────────
# Three depths, the way the tarot engine ladders three-card to ten-card
# spreads. Each entry is (key, meaning); the draw takes as many stones as
# the tier's list is long.

# One stone. Odin's draw: a single question, a single answer.
CAST_ONE = [
    ("answer", "the one stone, drawn for the question as asked"),
]

# Five stones. The middle three are the Norns' positions (Urd, Verdandi,
# Skuld); the first and last root and resolve them.
CAST_FIVE = [
    ("beneath", "what lies beneath, the root of the matter"),
    ("behind",  "what came before, laid down and still binding (Urd)"),
    ("stands",  "where you stand, the present becoming (Verdandi)"),
    ("owed",    "what is owed, the debt or challenge that must be answered"),
    ("becomes", "what becomes, the shape already forming ahead (Skuld)"),
]

# Nine stones, three lines of three, laid in reading order (row by row).
# Read across as the Norns' three lines, and down as three columns:
#   column 0 = you, column 1 = the matter itself, column 2 = what meets it.
CAST_NINE = [
    # Urd's line — what was laid down
    ("root-you",     "Urd, your line: the root you carry into this, laid down before it began"),
    ("root-matter",  "Urd, the matter's line: where this situation actually started"),
    ("root-other",   "Urd, the meeting line: the debt or history carried in from outside you"),
    # Verdandi's line — what is becoming
    ("now-you",      "Verdandi, your line: you as you stand in it right now"),
    ("now-matter",   "Verdandi, the matter's line: the heart of the thing as it is today"),
    ("now-other",    "Verdandi, the meeting line: what stands with you or against you now"),
    # Skuld's line — what is taking shape
    ("ahead-you",    "Skuld, your line: what this will ask of you"),
    ("ahead-matter", "Skuld, the matter's line: the way that opens if the asking is met"),
    ("ahead-other",  "Skuld, the meeting line: what becomes of what meets you"),
]

# Tier → cast. Unknown tiers fall to the five-stone cast.
TIER_SPREAD = {
    "First Stone":     CAST_ONE,
    "Rune Casting":    CAST_FIVE,
    "The Nine Worlds": CAST_NINE,
}

# Line and column labels for the nine-stone cast, so the reading can be
# told what it is looking at without re-deriving the geometry.
NINE_LINES   = ("Urd (what was laid down)", "Verdandi (what is becoming)", "Skuld (what takes shape)")
NINE_COLUMNS = ("you", "the matter itself", "what meets it")

MERKSTAVE_RATE = 0.30


# ─── BIRTH RUNE ───────────────────────────────────────────────────────────────

def birth_rune_index(dob: str):
    """Index of the rune ruling the half-month of birth, or None without a DOB."""
    if not dob:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            d = datetime.strptime(dob.strip(), fmt).date()
            break
        except ValueError:
            continue
    else:
        return None
    # Walk the calendar: each rune rules from its start date to the day before
    # the next rune's start. Fehu (Jun 29) opens the runic year.
    marks = []
    for i, r in enumerate(RUNES):
        m, day = r[4]
        marks.append((date(d.year, m, day), i))
    marks.sort()
    idx = marks[-1][1]                       # date before Jan 13 → last mark of prior year
    for start, i in marks:
        if d >= start:
            idx = i
    return idx


# ─── SEED AND WEIGHTS ─────────────────────────────────────────────────────────

def make_seed(poi_name: str, poi_dob: str, reading_date: str, reading_type: str) -> int:
    """Deterministic 256-bit seed from reading inputs (same recipe as the
    tarot engine: changing any field changes the entire cast)."""
    raw = f"{poi_name.strip().lower()}|{(poi_dob or '').strip()}|{reading_date}|{reading_type.lower()}"
    return int(hashlib.sha256(raw.encode()).hexdigest(), 16)


def _build_weights(poi_name: str, poi_dob: str, reading_type: str, on: date) -> list:
    weights = [1.0] * len(RUNES)

    # 1. Birth rune — 2.2x
    br = birth_rune_index(poi_dob or "")
    if br is not None:
        weights[br] *= 2.2

    # 2. Question-type element — 1.4x
    q_elem = TYPE_ELEMENT.get(reading_type.lower(), "earth")
    for i, r in enumerate(RUNES):
        if r[3] == q_elem:
            weights[i] *= 1.4

    # 3. Current season element — 1.3x (the cast belongs to the living year)
    s_elem = season_position(on)["season_element"]
    for i, r in enumerate(RUNES):
        if r[3] == s_elem:
            weights[i] *= 1.3

    # 4. Name number → ætt — 1.2x on its eight runes
    nn = name_number(poi_name)
    if nn:
        aett = (min(nn, 9) - 1) % 3
        for i, r in enumerate(RUNES):
            if r[2] == aett:
                weights[i] *= 1.2

    return weights


def _weighted_draw(weights, rng, n):
    """Weighted draw without replacement (same pattern as the tarot engine)."""
    remaining = list(range(len(weights)))
    w = list(weights)
    drawn = []
    for _ in range(n):
        total = sum(w[i] for i in remaining)
        r = rng.uniform(0, total)
        cumul = 0.0
        for idx in remaining:
            cumul += w[idx]
            if cumul >= r:
                drawn.append(idx)
                remaining.remove(idx)
                break
    return drawn


# ─── PUBLIC API ───────────────────────────────────────────────────────────────

def draw_reading(
    poi_name: str,
    poi_dob: str,
    reading_type: str,
    tier: str,
    reading_date: str = None,
    timezone: str = "America/Los_Angeles",
) -> dict:
    """
    Cast the runes for a reading. Same signature as tarot_engine.draw_reading
    and land_engine.draw_reading, so process_orders.py can dispatch on tier.

    Returns dict with keys:
        runes            — list of {position, position_meaning, rune, glyph,
                           aett, element, orientation, meaning}
        birth_rune       — str or ""
        name_number      — int
        merkstave_count  — int
        aett_spread      — str summary
        element_spread   — str summary
        season           — dict from season_position()
        formatted_block  — str ready to paste into the Claude intake
    """
    if reading_date is None:
        reading_date = datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")
    on = datetime.strptime(reading_date, "%Y-%m-%d").date()

    positions = TIER_SPREAD.get(tier, CAST_FIVE)

    rng     = random.Random(make_seed(poi_name, poi_dob or "", reading_date, reading_type))
    weights = _build_weights(poi_name, poi_dob or "", reading_type, on)
    drawn   = _weighted_draw(weights, rng, len(positions))

    runes = []
    aett_counts = [0, 0, 0]
    elem_counts = {}
    merk = 0
    for (pos, pos_meaning), idx in zip(positions, drawn):
        name, glyph, aett, elem, _hm, upright, merkstave = RUNES[idx]
        reversed_face = merkstave is not None and rng.random() < MERKSTAVE_RATE
        if reversed_face:
            merk += 1
        aett_counts[aett] += 1
        elem_counts[elem] = elem_counts.get(elem, 0) + 1
        entry_index = len(runes)
        runes.append({
            "position":         pos,
            "position_meaning": pos_meaning,
            "line":             NINE_LINES[entry_index // 3] if len(positions) == 9 else "",
            "column":           NINE_COLUMNS[entry_index % 3] if len(positions) == 9 else "",
            "rune":             name,
            "glyph":            glyph,
            "aett":             AETT_NAMES[aett],
            "element":          elem,
            "orientation":      "merkstave" if reversed_face else "upright",
            "meaning":          merkstave if reversed_face else upright,
        })

    br_idx  = birth_rune_index(poi_dob or "")
    br_name = RUNES[br_idx][0] if br_idx is not None else ""
    nn      = name_number(poi_name)
    season  = season_position(on)

    aett_spread = " / ".join(
        f"{AETT_NAMES[i]} {aett_counts[i]}" for i in range(3) if aett_counts[i]
    )
    element_spread = ", ".join(f"{e} {c}" for e, c in sorted(elem_counts.items()))

    # Formatted block for the Claude intake
    lines = [f"RUNES_CAST ({len(runes)} stones, tier: {tier}):"]
    for r in runes:
        lines.append(
            f"  [{r['position']}] {r['rune']} {r['glyph']} ({r['orientation']}) — "
            f"{r['meaning']}  <{r['aett']}, {r['element']}; position: {r['position_meaning']}>"
        )
    if len(runes) == 9:
        lines.append(
            "CAST_SHAPE: three lines of three, laid row by row. Lines across = "
            + "; ".join(NINE_LINES)
            + ". Columns down = " + ", ".join(NINE_COLUMNS)
            + ". Read both directions."
        )
    if br_name:
        lines.append(
            f"BIRTH_RUNE: {br_name}  (rules the half-month of {poi_name}'s birth — "
            f"authoritative; their standing stone, read it as the person themselves wherever it falls)"
        )
    lines += [
        f"MERKSTAVE_COUNT: {merk} of {len(runes)}",
        f"AETT_SPREAD: {aett_spread}",
        f"ELEMENT_SPREAD: {element_spread}",
        f"SEASON: cast {season['season_line']}",
        f"NAME_NUMBER: {nn}",
        f"READING_DATE: {reading_date}",
    ]

    return {
        "runes":           runes,
        "birth_rune":      br_name,
        "name_number":     nn,
        "merkstave_count": merk,
        "aett_spread":     aett_spread,
        "element_spread":  element_spread,
        "season":          season,
        "formatted_block": "\n".join(lines),
    }


# ─── CLI TEST ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    for tier in ("First Stone", "Rune Casting", "The Nine Worlds"):
        out = draw_reading("Marion", "03/14/1988", "clarity", tier,
                           reading_date="2026-07-20")
        print(f"\n=== {tier} ===")
        print(out["formatted_block"])
    out = draw_reading("Marion", "03/14/1988", "clarity", "Rune Casting",
                       reading_date="2026-07-20")
    again = draw_reading("Marion", "03/14/1988", "clarity", "Rune Casting",
                         reading_date="2026-07-20")
    assert out == again, "cast is not deterministic"
    print("\ndeterministic OK")
    nodob = draw_reading("Sofia", "", "love", "Rune Casting", reading_date="2026-07-20")
    assert "BIRTH_RUNE" not in nodob["formatted_block"]
    print("no-DOB OK:", ", ".join(r["rune"] for r in nodob["runes"]))
