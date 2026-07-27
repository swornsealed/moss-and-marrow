"""
land_engine.py — Moss & Marrow
Deterministic season / element / sign drawing engine.

The nature-shop counterpart of Sworn & Sealed's tarot_engine.py, with the
same call shape: process_orders.py calls draw_reading(...) and receives a
dict whose `formatted_block` is pasted into the Claude intake message.

Draws are seeded with SHA-256 from the reading inputs. Same person, same
question, same day — always the same season, element, and signs. The land
was always going to say this to this person at this moment.

Weighting influences (analogous to the tarot engine's birth card / sun sign):
  1. Season element    — the element the current season leans toward (1.6x)
  2. Birth season      — element of the season the person was born in (1.5x,
                         only when a DOB is provided; DOB is optional here)
  3. Question type     — each reading type has an elemental affinity (1.4x)
  4. Name number       — Pythagorean numerology of the name maps to an
                         element and boosts its signs (1.3x)
"""

import hashlib
import random
from datetime import datetime, date
from zoneinfo import ZoneInfo


# ─── THE WHEEL OF THE YEAR ────────────────────────────────────────────────────
# Fixed calendar approximations; good enough for reading context.
# (month, day, name, season_element, line used to describe the turn)

SABBATS = [
    ( 2,  1, "Imbolc",   "water", "the first loosening of winter"),
    ( 3, 20, "Ostara",   "air",   "the balance point, light gaining"),
    ( 5,  1, "Beltane",  "fire",  "the year at full flower"),
    ( 6, 21, "Litha",    "fire",  "the longest light, the turn begins"),
    ( 8,  1, "Lammas",   "earth", "first harvest, the proving of what was planted"),
    ( 9, 22, "Mabon",    "earth", "the balance point, dark gaining"),
    (11,  1, "Samhain",  "water", "the veil month, the year lets go"),
    (12, 21, "Yule",     "earth", "the still point, the held breath of the year"),
]

ELEMENTS = {
    "earth": "patience, ground, the slow true thing; what holds and what must be built",
    "water": "feeling, memory, grief and renewal; what moves under the surface",
    "fire":  "will, appetite, anger and courage; what wants to burn through",
    "air":   "thought, speech, doubt and clarity; what circles and will not land",
}

# Reading types → elemental affinity (mirror of SIGN_MAJOR-style weighting)
TYPE_ELEMENT = {
    "love":           "water",
    "career":         "earth",
    "clarity":        "air",
    "reconciliation": "water",
    "thoughts":       "air",
    "season":         "earth",   # Turning Year drops
}


# ─── THE SIGNS ────────────────────────────────────────────────────────────────
# The living things Willow reads. Pacific Northwest, per the brand brief.
# Each entry: (name, element, one-line meaning note for the intake block)

PLANTS = [
    ("Cedar",        "earth", "shelter and lineage; the thing that outlasts weather"),
    ("Rowan",        "fire",  "protection at the threshold; the small tree that stands guard"),
    ("Moss",         "water", "patience that wins; soft persistence on hard ground"),
    ("Sword fern",   "earth", "endurance through the dark season; keeps green underneath"),
    ("Nettle",       "fire",  "a sting that feeds; the useful thing behind the warning"),
    ("Salmonberry",  "water", "early sweetness; the first thing to offer itself"),
    ("Devil's club", "fire",  "a boundary that means it; medicine you must approach slowly"),
    ("Red alder",    "water", "the mender; grows first in broken ground and fixes it"),
    ("Douglas fir",  "earth", "the long ambition; slow height, deep hold"),
    ("Lichen",       "air",   "partnership; two things living as one, weather-readers"),
    ("Trailing blackberry", "earth", "the low harvest; what is gathered by those who stoop"),
    ("Skunk cabbage","fire",  "the unlovely herald; spring announced by what no one praises"),
    ("Oregon grape", "earth", "bitter root, bright fruit; the sour thing that heals"),
    ("Horsetail",    "water", "the old survivor; what was here before and knows how to stay"),
]

ANIMALS = [
    ("Raven",             "air",   "the messenger who will not flatter; watches, then speaks"),
    ("Salmon",            "water", "return against the current; the cost of going home"),
    ("Black-tailed deer", "earth", "quiet passage; the one who moves without disturbing"),
    ("Barred owl",        "air",   "the question asked at night; what hunts by listening"),
    ("Coyote",            "fire",  "the honest trickster; appetite that teaches by taking"),
    ("Great blue heron",  "water", "stillness as a skill; the patience that feeds"),
    ("Douglas squirrel",  "earth", "provision; the small economy of putting things by"),
    ("Banana slug",       "earth", "the unhurried; nothing is late that arrives whole"),
    ("Steller's jay",     "fire",  "the loud claim; boldness that costs and pays"),
    ("Red-tailed hawk",   "air",   "the wide view; what is obvious from height and hidden from the ground"),
    ("Beaver",            "water", "the changed river; work that redirects what seemed fixed"),
    ("Black bear",        "earth", "the deep rest; strength that knows its seasons"),
]

TIER_SIGNS = {
    "First Sign":          1,   # one sign, plant or animal
    "Reading of the Land": 2,   # one plant, one animal
    "The Whole Ground":    3,   # two + a root sign (what lies under the question)
    "The Turning Year":    1,   # one sign per seasonal drop
}


# ─── NUMEROLOGY (same Pythagorean reduction as the tarot engine) ──────────────

_PYTH = {c: (i % 9) + 1 for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}
_NUM_ELEMENT = {1: "fire", 2: "water", 3: "air", 4: "earth", 5: "air",
                6: "water", 7: "air", 8: "earth", 9: "fire",
                11: "air", 22: "earth", 33: "water"}


def _reduce(n: int, master=(11, 22, 33)) -> int:
    while n > 9 and n not in master:
        n = sum(int(d) for d in str(n))
    return n


def name_number(name: str) -> int:
    total = sum(_PYTH.get(ch, 0) for ch in name.lower())
    return _reduce(total) if total else 0


def parse_dob(dob: str):
    """(month, day) from a date of birth in any of the accepted formats."""
    if not dob:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            d = datetime.strptime(dob.strip(), fmt).date()
            return (d.month, d.day)
        except ValueError:
            continue
    return None


def birth_season_element(dob: str) -> str | None:
    """Element of the sabbat season the person was born into. DOB optional."""
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
    return season_position(d)["season_element"]


# ─── SEASON POSITION ──────────────────────────────────────────────────────────

def season_position(on: date) -> dict:
    """Where the year stands: last sabbat passed, next ahead, and the lean."""
    marks = []
    for y in (on.year - 1, on.year, on.year + 1):
        for m, d, name, elem, line in SABBATS:
            marks.append((date(y, m, d), name, elem, line))
    marks.sort()
    prev = max((mk for mk in marks if mk[0] <= on), key=lambda mk: mk[0])
    nxt  = min((mk for mk in marks if mk[0] >  on), key=lambda mk: mk[0])
    since, until = (on - prev[0]).days, (nxt[0] - on).days
    lean = prev if since <= until else nxt
    return {
        "prev_sabbat": prev[1], "prev_line": prev[3], "days_since": since,
        "next_sabbat": nxt[1],  "next_line": nxt[3],  "days_until": until,
        "season_element": lean[2],
        "season_line": (f"{since} days past {prev[1]} ({prev[3]}), "
                        f"{until} days short of {nxt[1]} ({nxt[3]})"),
    }


# ─── THE DRAW ─────────────────────────────────────────────────────────────────

def make_seed(poi_name: str, poi_dob: str, reading_date: str, reading_type: str) -> int:
    raw = f"{poi_name.lower().strip()}|{(poi_dob or '').strip()}|{reading_date}|{reading_type.lower()}"
    return int(hashlib.sha256(raw.encode()).hexdigest(), 16)


def _weighted_pick(pool, weights_for, rng, n):
    picked, pool = [], list(pool)
    for _ in range(min(n, len(pool))):
        weights = [weights_for(item) for item in pool]
        total = sum(weights)
        r, acc = rng.random() * total, 0.0
        for i, w in enumerate(weights):
            acc += w
            if r <= acc:
                picked.append(pool.pop(i))
                break
    return picked


def draw_reading(
    poi_name: str,
    poi_dob: str,
    reading_type: str,
    tier: str,
    reading_date: str = None,
    timezone: str = "America/Los_Angeles",
) -> dict:
    """
    Draw the land for a reading. Same signature as tarot_engine.draw_reading
    so process_orders.py needs only the import line changed.

    Returns dict with keys:
        season           — dict from season_position()
        element          — str, the loudest element for this reading
        element_note     — str
        signs            — list of {kind, name, element, note}
        name_number      — int
        formatted_block  — str ready to paste into the Claude intake
    """
    if reading_date is None:
        reading_date = datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")
    on = datetime.strptime(reading_date, "%Y-%m-%d").date()

    season = season_position(on)
    rng = random.Random(make_seed(poi_name, poi_dob or "", reading_date, reading_type))

    # Element weights
    favours = {
        season["season_element"]:                        1.6,
        TYPE_ELEMENT.get(reading_type.lower(), "earth"): 1.4,
    }
    born = birth_season_element(poi_dob or "")
    if born:
        favours[born] = favours.get(born, 1.0) * 1.5
    nn = name_number(poi_name)
    nn_elem = _NUM_ELEMENT.get(nn)
    if nn_elem:
        favours[nn_elem] = favours.get(nn_elem, 1.0) * 1.3

    elements = list(ELEMENTS)
    weights  = [favours.get(e, 1.0) for e in elements]
    r, acc = rng.random() * sum(weights), 0.0
    element = elements[-1]
    for e, w in zip(elements, weights):
        acc += w
        if r <= acc:
            element = e
            break

    # Sign weights: signs of the drawn element burn brighter
    def sign_weight(entry):
        return 1.8 if entry[1] == element else 1.0

    n = TIER_SIGNS.get(tier, 1)
    signs = []
    if n == 1:
        pool = PLANTS + ANIMALS
        (nm, el, note), = _weighted_pick(pool, sign_weight, rng, 1)
        kind = "plant" if (nm, el, note) in PLANTS else "animal"
        signs.append({"kind": kind, "name": nm, "element": el, "note": note})
    else:
        (p_nm, p_el, p_note), = _weighted_pick(PLANTS, sign_weight, rng, 1)
        (a_nm, a_el, a_note), = _weighted_pick(ANIMALS, sign_weight, rng, 1)
        signs.append({"kind": "plant",  "name": p_nm, "element": p_el, "note": p_note})
        signs.append({"kind": "animal", "name": a_nm, "element": a_el, "note": a_note})
        if n >= 3:   # the root sign: what lies under the question
            rest = [p for p in PLANTS if p[0] != p_nm]
            (r_nm, r_el, r_note), = _weighted_pick(rest, sign_weight, rng, 1)
            signs.append({"kind": "root", "name": r_nm, "element": r_el, "note": r_note})

    # Formatted block for the Claude intake
    lines = ["LAND_DRAWN:"]
    for s in signs:
        lines.append(f"  [{s['kind']}] {s['name']} ({s['element']}) — {s['note']}")
    lines += [
        f"SEASON: {season['season_line']}",
        f"SEASON_ELEMENT: {season['season_element']}",
        f"LOUDEST_ELEMENT: {element}  ({ELEMENTS[element]})",
        f"NAME_NUMBER: {nn}",
        f"READING_DATE: {reading_date}",
    ]

    return {
        "season":          season,
        "birth_md":        parse_dob(poi_dob or ""),   # where they came into the year
        "element":         element,
        "element_note":    ELEMENTS[element],
        "signs":           signs,
        "name_number":     nn,
        "formatted_block": "\n".join(lines),
    }


# ─── CLI TEST ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    for tier in TIER_SIGNS:
        out = draw_reading("Marion", "03/14/1988", "clarity", tier,
                           reading_date="2026-07-19")
        print(f"\n=== {tier} ===")
        print(out["formatted_block"])
