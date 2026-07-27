"""
Moss & Marrow — Order Processor (DUPLICATE of the Sworn & Sealed pipeline)

This file is a copy. The Sworn & Sealed original lives untouched in its own
repo and keeps running there. This duplicate runs alongside it, for the
Moss & Marrow shop only, and is protected by the SHOP_BRAND safety guard
below: it exits immediately unless explicitly claimed for this shop.

Runs via GitHub Actions every 30 minutes.
Queues new intake orders and delivers readings during Willow's working hours.

Working hours:
  Monday – Friday  10:00 – 16:00
  Saturday – Sunday  10:00 – 13:00

Set TIMEZONE as a GitHub Actions variable (e.g. "America/Los_Angeles").
All other credentials are GitHub Actions secrets (see README / setup guide).
"""

import os
import json
import random
import smtplib
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from land_engine import draw_reading                        # season/element/sign engine
from rune_engine import draw_reading as rune_draw_reading   # Elder Futhark cast (same interface)
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

try:
    from record_image import generate_record_image
    SPREAD_IMAGE_AVAILABLE = True
except ImportError:
    SPREAD_IMAGE_AVAILABLE = False
    print("WARNING: record_image not available (Pillow missing) — readings will be text-only")

# ─── MOSS & MARROW SAFETY GUARD ────────────────────────────────────────────────
# FINAL SAFETY: this duplicate can never run against Sworn & Sealed.
# It refuses to start unless SHOP_BRAND=moss-and-marrow is set in the
# environment (this repo's workflow sets it; the Sworn & Sealed workflow does
# not and never will). So even if this file, its secrets, or its sheet were
# ever mixed up with the original shop, it exits before touching an order,
# a sheet row, an email, or an Etsy receipt.
if os.environ.get("SHOP_BRAND", "").strip() != "moss-and-marrow":
    raise SystemExit(
        "SAFETY GUARD: refusing to run.\n"
        "This is the Moss & Marrow DUPLICATE of the Sworn & Sealed processor.\n"
        "It only runs when SHOP_BRAND=moss-and-marrow is set (the Moss & Marrow\n"
        "workflow sets this automatically). Complete the adaptation checklist\n"
        "in SETUP.md before enabling it. Nothing has been read or written."
    )

# ─── WORKING HOURS ─────────────────────────────────────────────────────────────
# weekday(): 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
WORKING_HOURS = {
    0: (10, 16),   # Monday
    1: (10, 16),   # Tuesday
    2: (10, 16),   # Wednesday
    3: (10, 16),   # Thursday
    4: (10, 16),   # Friday
    5: (10, 13),   # Saturday
    6: (10, 13),   # Sunday
}

# ─── DELIVERY DELAYS (seconds) by tier ─────────────────────────────────────────
TIER_DELAYS = {
    "The Turning Year":    (5 * 60,   20 * 60),   # first drop same day; later drops re-queued per sabbat
    "The Whole Ground":    (4 * 3600, 8 * 3600),  # 4 – 8 hours
    "Reading of the Land": (2 * 3600, 4 * 3600),  # 2 – 4 hours
    "The Nine Worlds":     (4 * 3600, 8 * 3600),  # 4 – 8 hours (the deep cast)
    "Rune Casting":        (2 * 3600, 4 * 3600),  # 2 – 4 hours
    "First Stone":         (5 * 60,   20 * 60),   # 5 – 20 minutes
    "First Sign":          (5 * 60,   20 * 60),   # 5 – 20 minutes (plus cron slack ~ within the hour)
}

# Number of seasonal drops in a Turning Year subscription (the eight sabbats).
TURNING_YEAR_DROPS = 8

# The rune tiers, in ladder order. These cast the Elder Futhark (rune_engine)
# instead of drawing the land (land_engine); everything downstream is shared.
RUNE_TIERS = ("First Stone", "Rune Casting", "The Nine Worlds")

# Deliverable sets. Add tiers only when the corresponding deliverable is built.
TIERS_WITH_SPREAD_IMAGE = {"First Sign", "Reading of the Land", "The Whole Ground",
                           "The Turning Year", "First Stone", "Rune Casting",
                           "The Nine Worlds"}      # the keepsake record (record_image.py)
TIERS_WITH_AUDIO        = {"The Whole Ground"}     # Willow's spoken note (own ElevenLabs voice)
TIERS_WITH_RITUAL       = {"The Whole Ground"}     # the outdoor observance closer
TIERS_WITH_NATAL        = set()                    # never: Moss & Marrow casts no charts

# ─── GOOGLE SHEETS FORM CONFIGURATION ──────────────────────────────────────────
# One Sheet tab per reading type. The branded HTML intake form (GitHub Pages)
# posts to a Google Apps Script endpoint which writes rows here.
# The automation reads unprocessed rows and marks them processed after queuing.
#
# poi_is_client: True  → career/clarity (no other person; POI = client themselves)
#                False → love/reconciliation/thoughts (POI is a named third party)

SHEET_CONFIG = {
    "love":    {"tab": "love",    "poi_is_client": False},
    "career":  {"tab": "career",  "poi_is_client": True},
    "clarity": {"tab": "clarity", "poi_is_client": True},
    "season":  {"tab": "season",  "poi_is_client": True},   # The Turning Year intake
}

# Column indices in the Sheet (0-based, matches Apps Script Code.gs COLUMNS list).
# birth_time and birth_city are appended AFTER processed so existing sheet data and
# the processed-marker column (J) are never shifted. (Sworn & Sealed layout kept
# for form compatibility; Moss & Marrow ignores the two birth columns.)
_COL = {
    "timestamp":      0,
    "type":           1,
    "order_number":   2,
    "customer_email": 3,
    "customer_name":  4,
    "client_dob":     5,
    "poi_name":       6,
    "poi_dob":        7,
    "notes":          8,
    "processed":      9,
    "birth_time":     10,
    "birth_city":     11,
}

STATE_FILE = "state.json"

# ── QUALITY-CONTROL COPY ────────────────────────────────────────────────────────
# Every customer-facing email is blind-copied (Bcc) to the shop owner for quality
# control: confirmation emails, reminders, and the readings themselves. The copy is
# envelope-only (no Bcc header), so the customer never sees this address.
# Override or disable with the QC_BCC_EMAIL env var (set to "" to turn it off).
QC_BCC_EMAIL = os.environ.get("QC_BCC_EMAIL", "addictedyz450f@gmail.com").strip()

# Business-side alerts that need owner action ([ACTION NEEDED] holds, verification
# outages, audio failures) go here, kept separate from the QC blind copies above.
# Defaults to the shop's own Gmail account (GMAIL_USER, the Moss & Marrow address);
# override with the OWNER_ALERT_EMAIL env var to send them somewhere else.
OWNER_ALERT_EMAIL = (os.environ.get("OWNER_ALERT_EMAIL", "").strip()
                     or os.environ.get("GMAIL_USER", "").strip()
                     or QC_BCC_EMAIL)


def _recipients_with_qc(to_address):
    """Envelope recipient list for a send: the customer plus the QC blind copy."""
    rcpts = [to_address]
    if QC_BCC_EMAIL and QC_BCC_EMAIL.lower() != (to_address or "").lower():
        rcpts.append(QC_BCC_EMAIL)
    return rcpts


# A TEST- order bypasses Etsy verification, so the public intake form must not be
# able to claim a free reading with a guessed TEST code. Only honor test mode when
# the form email is one of the owner's own addresses, or ALLOW_TEST_ORDERS is set.
_ALLOW_TEST_ORDERS = os.environ.get("ALLOW_TEST_ORDERS", "").strip().lower() in ("1", "true", "yes")
_OWNER_EMAILS = {e.strip().lower() for e in (
    QC_BCC_EMAIL,
    os.environ.get("GMAIL_USER", ""),
    os.environ.get("CEREMONY_EMAIL", ""),
    os.environ.get("TEST_ORDER_EMAIL", ""),
) if e and e.strip()}


def _test_order_allowed(customer_email):
    return _ALLOW_TEST_ORDERS or (customer_email or "").strip().lower() in _OWNER_EMAILS


# ─── TIME UTILITIES ─────────────────────────────────────────────────────────────

def get_tz():
    return ZoneInfo(os.environ.get("TIMEZONE", "America/Los_Angeles").strip())


def now_local():
    return datetime.now(get_tz())


def is_working_hours(dt=None):
    if dt is None:
        dt = now_local()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_tz())
    hours = WORKING_HOURS.get(dt.weekday())
    if hours is None:
        return False
    return hours[0] <= dt.hour < hours[1]


def next_working_start():
    """Return the datetime when the next working window begins."""
    tz = get_tz()
    candidate = now_local().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    for _ in range(7 * 24):  # search up to 7 days ahead
        hours = WORKING_HOURS.get(candidate.weekday())
        if hours and candidate.hour == hours[0]:
            return candidate
        candidate += timedelta(hours=1)
    raise RuntimeError("Could not find next working window in 7 days")


def schedule_delivery(tier):
    """Return ISO timestamp for when this reading should be sent."""
    min_s, max_s = TIER_DELAYS[tier]
    delay = timedelta(seconds=random.randint(min_s, max_s))

    if is_working_hours():
        base = now_local()
    else:
        base = next_working_start()

    target = base + delay

    # If target falls outside working hours, push to next working start + half delay
    if not is_working_hours(target):
        half_delay = timedelta(seconds=random.randint(min_s // 2, max_s // 2))
        target = next_working_start() + half_delay

    return target.isoformat()


# ─── STATE ──────────────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
    else:
        state = {"last_checked_at": None, "pending_deliveries": []}
    # Permanent, never-pruned ledger of order numbers already redeemed, so a valid
    # order cannot be re-submitted for a second free reading after the 30-day
    # delivery queue prunes it.
    state.setdefault("redeemed_orders", [])
    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def draw_result_of(delivery):
    """The draw stored on a delivery.

    Moss & Marrow draws no cards, so the key is "draw_result". Deliveries
    queued before that rename carry the Sworn & Sealed name instead, and are
    still in flight in state.json, so both are accepted.
    """
    return delivery.get("draw_result") or delivery.get("tarot_result")


# ─── GOOGLE SHEETS INTAKE READER ────────────────────────────────────────────────

def get_sheet_rows(sheet_id, tab_name):
    """
    Return list of (row_index, fields_dict) for unprocessed rows in a Sheet tab.
    row_index is 1-based (Sheet row number, including the header row at row 1).
    Rows with anything in the 'processed' column are skipped.
    """
    svc    = _google_service("sheets", "v4")
    result = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!A:L",
    ).execute()
    rows = result.get("values", [])
    if len(rows) < 2:          # no data rows (row 1 is header)
        return []

    ncol = max(_COL.values()) + 1
    unprocessed = []
    for i, row in enumerate(rows[1:], start=2):        # Sheet row 2 = first data row
        row = (row + [""] * ncol)[:ncol]               # pad to full column count
        if row[_COL["processed"]].strip():             # already processed — skip
            continue
        fields = {k: row[v].strip() for k, v in _COL.items()}
        unprocessed.append((i, fields))
    return unprocessed


def mark_row_processed(sheet_id, tab_name, row_index):
    """Write 'yes' into the processed column so this row is not picked up again."""
    svc        = _google_service("sheets", "v4")
    col_letter = chr(ord("A") + _COL["processed"])   # column J
    svc.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"{tab_name}!{col_letter}{row_index}",
        valueInputOption="RAW",
        body={"values": [["yes"]]},
    ).execute()


def build_user_message(fields, reading_type, tier, draw, reading_date=""):
    """
    Construct the Claude intake block.
    For career/clarity (poi_is_client=True) POI = client themselves.
    Context fields (career_situation, clarity_area, situation, etc.) are
    folded into NOTES so Claude sees them as relevant context.
    """
    config        = SHEET_CONFIG.get(reading_type, SHEET_CONFIG["love"])
    customer_name = fields.get("customer_name", "Valued Client") or "Valued Client"
    client_dob    = fields.get("client_dob", "")

    if config["poi_is_client"]:
        poi_name = customer_name
        poi_dob  = client_dob
        # Combine all context fields into notes
        context_keys = [
            "career_situation", "career_question",
            "clarity_area", "clarity_situation",
            "notes",
        ]
    else:
        poi_name = fields.get("poi_name", "")
        poi_dob  = fields.get("poi_dob", "")
        context_keys = ["separation_context", "situation", "notes"]

    notes_parts = [fields[k] for k in context_keys if fields.get(k)]
    notes = " | ".join(notes_parts)

    # Every tier draws the land (land_engine.draw_reading), so all tiers get the
    # full formatted_block: LAND_DRAWN signs alongside the season position, the
    # loudest element, and the name number, so the reading weaves all three threads.
    land_block = draw["formatted_block"]

    block = (
        f"CLIENT: {customer_name}\n"
        f"POI: {poi_name}\n"
        f"POI_DOB: {poi_dob}\n"
        f"READING_TYPE: {reading_type}\n"
        f"TIER: {tier}\n"
        f"CLIENT_DOB: {client_dob}\n"
        f"{land_block}\n"
        f"NOTES: {notes}"
    )
    return block + "\n" + _lunar_context(reading_date)


# ─── ETSY ───────────────────────────────────────────────────────────────────────

def get_etsy_access_token(state):
    """
    Refreshes the Etsy OAuth2 access token using the stored refresh token.
    Saves the new refresh token back to state so it stays valid across runs.
    """
    api_key       = os.environ["ETSY_API_KEY"]
    refresh_token = state.get("etsy_refresh_token") or os.environ.get("ETSY_REFRESH_TOKEN", "")

    if not refresh_token:
        print("WARNING: No Etsy refresh token found — skipping Etsy verification.")
        return None, state

    r = requests.post(
        "https://api.etsy.com/v3/public/oauth/token",
        json={
            "grant_type":    "refresh_token",
            "client_id":     api_key,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    if r.status_code != 200:
        print(f"WARNING: Etsy token refresh failed ({r.status_code}) — skipping verification.")
        return None, state

    data = r.json()
    state["etsy_refresh_token"] = data["refresh_token"]
    return data["access_token"], state


def verify_etsy_order(order_number, access_token):
    """
    Look up the Etsy receipt for this order number.
    Returns:
      None          -- order genuinely not found / invalid (Etsy 400/404)
      "UNVERIFIED"  -- verification skipped (no access token available)
      "RETRY"       -- transient Etsy/network failure; the caller leaves the form
                       row unprocessed so the next run tries again, instead of
                       telling a real customer their order does not exist.
      dict          -- {"title", "listing_id", "variations"} of the first line item,
                       used to resolve the reading tier from the order itself.
    """
    if not access_token:
        return "UNVERIFIED"   # verification skipped; trust the order number

    shop_id = os.environ["ETSY_SHOP_ID"]
    url = f"https://openapi.etsy.com/v3/application/shops/{shop_id}/receipts/{order_number}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-api-key":     f"{os.environ['ETSY_API_KEY']}:{os.environ['ETSY_SHARED_SECRET']}",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as e:
        print(f"  Etsy lookup failed for {order_number} ({e}) — will retry next run")
        return "RETRY"
    if r.status_code in (400, 404):
        return None           # bad or unknown order number — genuinely not found
    if r.status_code != 200:
        print(f"  Etsy returned {r.status_code} for {order_number} — will retry next run")
        return "RETRY"
    data = r.json()
    if not data.get("receipt_id"):
        return None
    transactions = data.get("transactions", [])
    if not transactions:
        return None
    txn = transactions[0]
    return {
        "title":       txn.get("title", ""),
        "listing_id":  txn.get("listing_id"),
        "variations":  txn.get("variations", []),
        # Fields already present in the same receipt JSON — used to confirm the
        # order was actually paid, not refunded/cancelled, that the person filling
        # the form is the buyer who paid, and how many reading units were bought.
        "buyer_email": (data.get("buyer_email") or "").strip().lower(),
        "is_paid":     bool(data.get("is_paid")),
        "status":      (data.get("status") or "").strip().lower(),
        "refunded":    bool(data.get("refunds")),
        "n_units":     sum(int(t.get("quantity") or 1) for t in transactions),
    }


_SHIPPED_NOTE = (
    "Your reading has been delivered to your email. Thank you for trusting me "
    "with something this close to your heart. Willow, Moss and Marrow"
)


def mark_receipt_shipped(access_token, order_number, note_to_buyer=_SHIPPED_NOTE):
    """
    Mark the Etsy receipt shipped (createReceiptShipment, no tracking) the moment
    the reading is delivered by email, so the buyer sees the order completed and
    Etsy's review flow starts while they are holding the reading. Listings use a
    free-shipping profile, so "shipped" here simply closes the order loop.

    Never raises and never blocks a delivery: any failure logs a warning and the
    owner can mark the order shipped by hand in the Etsy dashboard. Requires the
    transactions_w OAuth scope — a 403 means the refresh token was minted with
    the old read-only scope and get_etsy_tokens.py must be re-run.
    """
    order_number = (order_number or "").strip().lstrip("#").strip()
    if not access_token or not order_number.isdigit():
        return False   # no token, or not a real Etsy receipt id (e.g. TEST- codes)
    shop_id = os.environ["ETSY_SHOP_ID"]
    url = f"https://openapi.etsy.com/v3/application/shops/{shop_id}/receipts/{order_number}/tracking"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-api-key":     f"{os.environ['ETSY_API_KEY']}:{os.environ['ETSY_SHARED_SECRET']}",
    }
    try:
        r = requests.post(url, headers=headers, timeout=15,
                          data={"note_to_buyer": note_to_buyer, "send_bcc": False})
    except requests.RequestException as e:
        print(f"  WARNING: could not mark order {order_number} shipped ({e}) — mark it manually")
        return False
    if r.status_code == 200:
        print(f"  Etsy order {order_number} marked shipped")
        return True
    if r.status_code == 403:
        print(f"  WARNING: Etsy refused to mark {order_number} shipped (403 — token lacks "
              f"transactions_w scope; re-run get_etsy_tokens.py and update ETSY_REFRESH_TOKEN)")
    else:
        print(f"  WARNING: Etsy returned {r.status_code} marking {order_number} shipped: {r.text[:150]}")
    return False


def _alert_etsy_verification_down(state):
    """
    Alert the owner (throttled to once per 6 hours) that Etsy verification is
    unavailable, so real orders being held are not silently piling up.
    """
    from datetime import timezone as _tz
    now  = datetime.now(_tz.utc)
    last = state.get("etsy_down_alerted_at")
    if last:
        try:
            if (now - datetime.fromisoformat(last)).total_seconds() < 6 * 3600:
                return
        except Exception:
            pass
    try:
        send_email(
            OWNER_ALERT_EMAIL,
            "[ACTION NEEDED] Etsy verification is unavailable",
            ETSY_DOWN_ALERT,
        )
        state["etsy_down_alerted_at"] = now.isoformat()
        print("  Etsy-down alert sent to owner")
    except Exception as e:
        print(f"  ERROR sending Etsy-down alert: {e}")


# ─── ASTROLOGICAL CEREMONY DATE ENGINE ─────────────────────────────────────────

def _moon_phase(dt: datetime) -> float:
    """Moon phase as fraction 0–1 (0/1 = new moon, 0.5 = full moon)."""
    from datetime import timezone as _tz
    known_new = datetime(2000, 1, 6, 18, 14).replace(tzinfo=_tz.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    days = (dt - known_new).total_seconds() / 86400
    return (days % 29.53058867) / 29.53058867


_ZODIAC_SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
                 "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]


def _moon_sign(dt: datetime) -> str:
    """Zodiac sign the Moon occupies at dt, via a low-precision (~0.3 degree)
    Meeus longitude. Ample accuracy to name the sign except within a whisker of a
    cusp, and far better than letting the model guess."""
    from datetime import timezone as _tz
    import math
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    j2000 = datetime(2000, 1, 1, 12, 0, tzinfo=_tz.utc)
    d = (dt - j2000).total_seconds() / 86400.0
    s = lambda x: math.sin(math.radians(x))
    L    = 218.316 + 13.176396 * d   # mean longitude
    M    = 134.963 + 13.064993 * d   # mean anomaly
    F    = 93.272  + 13.229350 * d   # argument of latitude
    D    = 297.850 + 12.190749 * d   # mean elongation
    Msun = 357.529 + 0.9856003 * d   # sun mean anomaly
    lon = (L + 6.289 * s(M) + 1.274 * s(2 * D - M) + 0.658 * s(2 * D)
             + 0.214 * s(2 * M) - 0.186 * s(Msun) - 0.114 * s(2 * F)) % 360.0
    return _ZODIAC_SIGNS[int(lon // 30)]


def _phase_name(fraction: float) -> str:
    """Human name for a 0–1 moon-phase fraction."""
    f = fraction % 1.0
    if f < 0.02 or f > 0.98: return "New Moon"
    if f < 0.23:  return "Waxing Crescent"
    if f < 0.27:  return "First Quarter"
    if f < 0.48:  return "Waxing Gibbous"
    if f < 0.52:  return "Full Moon"
    if f < 0.73:  return "Waning Gibbous"
    if f < 0.77:  return "Last Quarter"
    return "Waning Crescent"


def _next_phase_dt(reading_dt: datetime, target: str) -> datetime:
    """Datetime of the next New or Full Moon on/after reading_dt (hourly search
    over ~33 days, which always contains exactly one of each ahead)."""
    best_dt, best_metric = reading_dt, 9.9
    for h in range(0, 33 * 24):
        dt = reading_dt + timedelta(hours=h)
        f = _moon_phase(dt)
        metric = min(f, 1.0 - f) if target == "new" else abs(f - 0.5)
        if metric < best_metric:
            best_metric, best_dt = metric, dt
    return best_dt


def _lunar_context(reading_date: str) -> str:
    """Accurate lunar phase, moon sign, and next new/full moon dates for the
    reading date, so Willow references real astronomy instead of inventing it."""
    from datetime import timezone as _tz
    try:
        y, m, dd = (int(x) for x in reading_date.split("-"))
        base = datetime(y, m, dd, 12, 0, tzinfo=_tz.utc)
    except Exception:
        base = datetime.now(_tz.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    new_dt  = _next_phase_dt(base, "new")
    full_dt = _next_phase_dt(base, "full")
    fmt = lambda dt: dt.strftime("%d %B %Y").lstrip("0")
    return (
        "LUNAR_CONTEXT (accurate astronomy for the reading date, use ONLY this for "
        "any moon or lunar-date reference; never invent a phase, moon sign, or date):\n"
        f"  On the reading date the Moon is a {_phase_name(_moon_phase(base))} in {_moon_sign(base)}.\n"
        f"  Next New Moon: {fmt(new_dt)} (Moon in {_moon_sign(new_dt)}).\n"
        f"  Next Full Moon: {fmt(full_dt)} (Moon in {_moon_sign(full_dt)})."
    )


# (Sworn & Sealed's ceremony-date election — moon phases keyed to reading
#  types — has no Moss & Marrow counterpart and was removed.)


# ─── GOOGLE CALENDAR ─────────────────────────────────────────────────────────────

_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

def _google_service(api: str, version: str):
    """Build an authenticated Google API service client using the service account."""
    import json
    from google.oauth2 import service_account
    from googleapiclient.discovery import build as _build
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON not set")
    info  = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=_GOOGLE_SCOPES
    )
    return _build(api, version, credentials=creds)


# (Sworn & Sealed's Grand Ceremony calendar/Drive helpers were removed:
#  Moss & Marrow schedules nothing and waits on no photos.)


# ─── TIER / READING TYPE DETECTION ─────────────────────────────────────────────

# Optional, most-reliable override: map an Etsy listing_id straight to a tier.
# Set the LISTING_TIER_MAP env var as "listingid:Tier Name,listingid:Tier Name".
# Leave unset to resolve the tier from the order's variation or title instead.
def _load_listing_tier_map():
    mapping = {}
    for pair in os.environ.get("LISTING_TIER_MAP", "").split(","):
        if ":" in pair:
            lid, tier = pair.split(":", 1)
            if lid.strip() and tier.strip():
                mapping[lid.strip()] = tier.strip()
    return mapping

LISTING_TIER_MAP = _load_listing_tier_map()
VALID_TIERS = ("First Sign", "Reading of the Land",
               "First Stone", "Rune Casting", "The Nine Worlds",
               "The Whole Ground", "The Turning Year")


def _match_tier_keywords(text):
    """Return a tier only if the text names it explicitly; never guesses."""
    t = (text or "").lower()
    if "turning" in t and "year" in t:       return "The Turning Year"
    if "whole" in t and "ground" in t:       return "The Whole Ground"
    if "reading" in t and "land" in t:       return "Reading of the Land"
    if "first" in t and "sign" in t:         return "First Sign"
    if "nine" in t and "world" in t:         return "The Nine Worlds"
    if "first" in t and "stone" in t:        return "First Stone"
    if "rune" in t:                          return "Rune Casting"
    return None


def get_tier(order):
    """
    Resolve the reading tier from an Etsy order line item.

    `order` is the dict from verify_etsy_order (or a plain title string).
    Returns the tier name, or None if it cannot be determined. This never
    silently defaults to First Sign; the caller handles an unresolved tier
    (owner alert + hold) so a paid order is never under-delivered.

    Detection order: explicit listing_id map -> selected variation -> title.
    """
    if isinstance(order, str):
        return _match_tier_keywords(order)
    order = order or {}

    lid = str(order.get("listing_id") or "")
    if lid in LISTING_TIER_MAP and LISTING_TIER_MAP[lid] in VALID_TIERS:
        return LISTING_TIER_MAP[lid]

    for v in order.get("variations", []) or []:
        tier = _match_tier_keywords(v.get("formatted_value", ""))
        if tier:
            return tier

    return _match_tier_keywords(order.get("title", ""))


TIER_UNRESOLVED_ALERT = """\
Heads up: an order came in but the automation could not work out which tier it is,
so it has NOT been auto-delivered (to avoid sending the wrong reading).

Order number:  {order_num}
Customer:      {customer_email}
Reading type:  {reading_type}

Etsy line item data:
{detail}

Please handle this order manually, then make the tier explicit for this listing so
future orders resolve on their own: name the tier in the listing title or the
variation value, or add the listing_id to the LISTING_TIER_MAP secret.
"""


MULTI_ITEM_ALERT = """\
Heads up: an order was submitted that contains more than one reading, so it has NOT
been auto-delivered — the automation delivers one reading per order, and sending only
one would under-serve a paid order.

Order number:   {order_num}
Customer:       {customer_email}
Reading units:  {n_units}

Please deliver each reading on this order manually.
"""


UNKNOWN_LISTING_ALERT = """\
Heads up: an intake form was submitted against an Etsy order whose listing is NOT one
of the configured reading listings, so it has NOT been auto-delivered.

Order number:   {order_num}
Customer:       {customer_email}
Etsy listing:   {listing_id}

This can mean someone is trying to claim a reading against a different purchase.
Please check the order before delivering anything.
"""


ETSY_DOWN_ALERT = """\
Heads up: the automation could not verify orders against Etsy this cycle (the access
token could not be refreshed). Real orders are being HELD, not delivered, until Etsy
verification is working again.

If this persists, check that ETSY_API_KEY, ETSY_SHARED_SECRET, ETSY_SHOP_ID and
ETSY_REFRESH_TOKEN are set and that the refresh token is still valid (re-authorise if
needed). Held orders will deliver automatically once verification recovers.
"""


# (Sworn & Sealed's chart-tier alerts — solar fallback, birth-details request —
#  have no Moss & Marrow counterpart: no tier here casts a chart.)


AUDIO_FAILED_ALERT = """\
Heads up: a {tier} reading was delivered, but WITHOUT its spoken audio reflection.
The written reading and all other keepsakes went out normally; only the MP3 is
missing (ElevenLabs failed after retries, or no audio script was produced).

Customer:       {customer_name}
Customer email: {customer_email}
Order number:   {order_num}
Audio script:   {had_script}

Please record or regenerate the audio reflection and send it to the customer as a
follow-up, so they receive the full deliverable they paid for.
"""


# ── Reading-listing allowlist (F7) ──────────────────────────────────────────────
# Opt-in: set READING_LISTING_IDS to a comma-separated list of your reading listing
# ids. When set, an order for any other listing is held for review rather than
# auto-delivered. Empty (default) disables the check.
READING_LISTING_IDS = {
    x.strip() for x in os.environ.get("READING_LISTING_IDS", "").split(",") if x.strip()
}


def get_reading_type(title):
    t = title.lower()
    if "love" in t or "attraction" in t:
        return "love"
    if "career" in t or "work" in t or "job" in t:
        return "career"
    if "turning" in t or "season" in t or "wheel" in t or "sabbat" in t:
        return "season"
    return "clarity"


# ─── READING-TYPE CROSS-CHECK ──────────────────────────────────────────────────
# The customer selects the reading type on the single intake form (Etsy allows
# only one shop-wide message, so we cannot pre-set it per listing). We cross-check
# that choice against what they actually bought, derived from the Etsy order.

# Foolproof override: map an Etsy listing_id straight to a reading type.
# Set LISTING_TYPE_MAP as "listingid:love,listingid:career,...".
def _load_listing_type_map():
    mapping = {}
    for pair in os.environ.get("LISTING_TYPE_MAP", "").split(","):
        if ":" in pair:
            lid, t = pair.split(":", 1)
            t = t.strip().lower().replace("-", "_")
            if lid.strip() and t in SHEET_CONFIG:
                mapping[lid.strip()] = t
    return mapping

LISTING_TYPE_MAP = _load_listing_type_map()


def _type_keywords(text):
    """Confident reading type from text, or None (never guesses, unlike get_reading_type)."""
    t = (text or "").lower()
    if "love" in t or "attraction" in t:                            return "love"
    if "career" in t or "job" in t:                                 return "career"
    if "turning year" in t or "seasonal" in t or "sabbat" in t \
            or "wheel of the year" in t:                            return "season"
    if "clarity" in t:                                              return "clarity"
    return None


def get_order_reading_type(order):
    """
    Reading type resolved FROM the Etsy order (listing_id map -> variation -> title),
    for cross-checking the customer's form choice. Returns None when it cannot be
    determined confidently, so an ambiguous listing never triggers a false mismatch.
    """
    if isinstance(order, str):
        return _type_keywords(order)
    order = order or {}
    lid = str(order.get("listing_id") or "")
    if lid in LISTING_TYPE_MAP:
        return LISTING_TYPE_MAP[lid]
    for v in order.get("variations", []) or []:
        t = _type_keywords(v.get("formatted_value", ""))
        if t:
            return t
    return _type_keywords(order.get("title", ""))


EMAIL_MISMATCH_ALERT = """\
Heads up: an intake form was submitted for an order whose Etsy buyer email does not
match the email on the form, so it has NOT been auto-delivered.

Order number:   {order_num}
Form email:     {form_email}
Etsy buyer:     {buyer_email}
Reading type:   {reading_type}

This can be a gift or a typo, but it can also be someone claiming a reading against
an order they did not place. Please check the order and handle it manually.
"""


PAYMENT_ISSUE_ALERT = """\
Heads up: an intake form was submitted for an order that is not in a clean paid
state, so it has NOT been auto-delivered.

Order number:   {order_num}
Customer:       {customer_email}
Etsy status:    {status}
Paid:           {is_paid}
Refunded:       {refunded}

Please check the order in Etsy before delivering anything.
"""


TYPE_MISMATCH_ALERT = """\
Heads up: an order came in where the reading type on the intake form does not match
what was actually purchased, so it has NOT been auto-delivered.

Order number:   {order_num}
Customer:       {customer_email}
Form says:      {form_type}
Etsy order is:  {order_type}

The customer most likely selected the wrong reading on the form, so the details they
gave may not fit the reading they paid for. Please check the order and handle it
manually.
"""


# ─── CLAUDE API ─────────────────────────────────────────────────────────────────

# A reading delivery is retried up to this many times if generation fails
# (e.g. a transient Anthropic API timeout) before it is given up and the owner
# is alerted, instead of being permanently stuck in an "error" state.
_MAX_DELIVERY_ATTEMPTS = 4


def generate_reading(user_message, system_prompt):
    """
    Call Claude for the reading. Transient failures (429 rate limit, 5xx like the
    502 Bad Gateway seen in production) are retried in-run with backoff before
    giving up, so a single API blip doesn't error a paid order. A still-failing
    call raises; the caller marks the delivery for cross-run retry.
    """
    import time
    api_key = os.environ["ANTHROPIC_API_KEY"]
    last_exc = None
    for attempt in range(1, 4):
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      "claude-sonnet-4-6",
                    # Headroom well above the longest tier (GC 1,800 words + audio
                    # script ≈ 3,200 tokens): the API must never be the thing that
                    # truncates a reading mid-sentence.
                    "max_tokens": 8192,
                    "system":     system_prompt,
                    "messages":   [{"role": "user", "content": user_message}],
                },
                timeout=300,
            )
        except requests.RequestException as e:
            last_exc = e
            print(f"  WARNING: Claude request failed (attempt {attempt}/3): {e}")
            if attempt < 3:
                time.sleep(5 * attempt)
            continue
        if r.status_code == 200:
            return r.json()["content"][0]["text"]
        transient = r.status_code == 429 or r.status_code >= 500
        print(f"  WARNING: Claude returned {r.status_code} (attempt {attempt}/3)")
        if not transient or attempt == 3:
            r.raise_for_status()
        time.sleep(5 * attempt)
    raise last_exc


# ─── EMAIL ──────────────────────────────────────────────────────────────────────

_SIGNOFF_PATTERNS = (
    "this reading is offered",
    "this reading is provided",
    "provided as spiritual guidance",
    "offered as spiritual guidance",
    "— willow",
    "– willow",
    "written by hand, at the edge of the woods",
    "trust your own intuition",
    "your own knowing",
    "moss & marrow",
    "moss &amp; marrow",
)

_CANONICAL_PLAIN = (
    "\n\nThis reading is offered as spiritual guidance. "
    "Your own knowing is always the final word.\n\n"
    "Written by hand, at the edge of the woods.\n"
    "Willow, Moss & Marrow"
)


def _strip_em_dashes(text: str) -> str:
    """
    Replace em/en dashes with plain punctuation so customer-facing copy never
    carries the tell-tale "AI" em dash. Em dash becomes a comma; en dash a hyphen.
    Applied to every outbound subject and body, so it covers both the static
    templates and whatever Claude generates.
    """
    if not text:
        return text
    text = (text.replace(" — ", ", ").replace(" —", ", ")
                .replace("— ", ", ").replace("—", ", "))
    text = text.replace(" – ", " - ").replace("–", "-")
    text = text.replace(", ,", ",").replace(" ,", ",")
    return text


# (Sworn & Sealed's white-candle-note and rising-sign sanitisers were removed:
#  Moss & Marrow has no candle-colour ceremony emails and casts no charts.)


_FORBIDDEN_SOFTEN = (
    ("which tells me that ", "which holds that "),
    ("which tells me ",      "which holds "),
    (" tells me is that ",   " holds is that "),
    (" tells me is ",        " holds is "),
    (" tells me that ",      " holds that "),
    (" tells me ",           " holds "),
    (" tell me that ",       " hold that "),
    (" suggests that ",      " carries that "),
    (" indicates that ",     " points to how "),
    (" indicate that ",      " point to how "),
)


def _soften_forbidden_phrases(text: str) -> str:
    """
    System-prompt rule 8 bans flat, formulaic reader tics ("tells me",
    "suggests", "indicates") because they are the clearest sign of machine
    writing. The model mostly obeys but occasionally slips (a single reading was
    seen with "tells me" three times), so this rewrites the most common offenders
    into Willow's narrative register. Deliberately narrow: only whole-phrase
    swaps that stay grammatical are done here, everything else is left to the
    prompt so we never mangle the prose.
    """
    if not text:
        return text
    for bad, good in _FORBIDDEN_SOFTEN:
        text = text.replace(bad, good)
    return text


_GC_UPSELL_MARKERS = (
    "the whole ground",      # the flagship never names its own tier in-body
    "deeper reading",
    "go further",
    "going deeper",
    "go deeper",
    "fullest depth",
    "greater depth",
    "where that answer lives",
    "more room than",
    "more space than",
    "if you feel drawn",
    "read in their fullest",
)


def _strip_tier_upsell(text: str, tier: str) -> str:
    """
    The Whole Ground is the fullest reading offered, so it must never close with
    a depth invitation or point the client toward another tier. The model
    occasionally slips one in anyway, sometimes even naming the tier itself,
    which is mortifying on a top-tier reading the customer has already paid for.
    This is a deterministic safety net: on Whole Ground readings only, drop any
    trailing paragraph that reads as an upsell so it can never reach the
    customer. Only the last few paragraphs are examined, so the closing (and any
    sign-off) is preserved.
    """
    if not text or tier != "The Whole Ground":
        return text
    paras = text.rstrip().split("\n\n")
    tail_start = max(0, len(paras) - 3)
    kept = paras[:tail_start]
    for p in paras[tail_start:]:
        if p.strip() and any(m in p.strip().lower() for m in _GC_UPSELL_MARKERS):
            print(f"  Stripped flagship upsell paragraph: {p.strip()[:80]}…")
            continue
        kept.append(p)
    return "\n\n".join(kept).rstrip()


def _strip_role_labels(text: str) -> str:
    """
    Internal role words (client, customer, querent, seeker) must never appear in a
    customer-facing reading: it is written to the person in second person ("you"),
    so calling them "the client" breaks the spell and exposes the machinery. The
    prompt forbids it; this is the deterministic net. Leaked labels are rewritten
    to grammar-safe neutrals ("someone" / "their" / "people") rather than to "you",
    because a blind swap to "you" would break verb agreement ("the client misses"
    would become "you misses"). The case of the leading word is preserved.
    """
    if not text:
        return text
    import re

    def _mk(repl):
        def _sub(m):
            return repl[:1].upper() + repl[1:] if m.group(0)[:1].isupper() else repl
        return _sub

    # Only genuine internal jargon: "client", "customer", "querent". NOT "seeker"
    # (the Life Path 7 numerology archetype is "the Seeker") or "subject" (ordinary
    # word) — scrubbing those mangled real reading content.
    poss = r"(?:'|’)s"
    text = re.sub(rf"\b(?:the|a)\s+(?:client|customer|querent){poss}\b", _mk("their"),  text, flags=re.I)
    text = re.sub(r"\b(?:clients|customers|querents)\b",                 _mk("people"),  text, flags=re.I)
    text = re.sub(r"\b(?:the|a)\s+(?:client|customer|querent)\b",        _mk("someone"), text, flags=re.I)
    text = re.sub(rf"\b(?:client|customer|querent){poss}\b",             _mk("their"),   text, flags=re.I)
    text = re.sub(r"\b(?:client|customer|querent)\b",                    _mk("someone"), text, flags=re.I)
    return text


def _sanitise_plain(text: str) -> str:
    """
    Strip whatever sign-off Claude wrote and append the canonical one.
    Splits on paragraphs, drops any that contain sign-off language.
    """
    paras = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    clean = [
        p for p in paras
        if not any(s in p.lower() for s in _SIGNOFF_PATTERNS)
    ]
    return _strip_em_dashes("\n\n".join(clean) + _CANONICAL_PLAIN)


def _plain_movement_headers(text: str) -> str:
    """Render '§Movement' markers as bare uppercase lines for the plain-text email
    part. The HTML part styles the same markers into gold headers; plain text just
    needs them legible rather than showing a raw '§'."""
    import re
    return re.sub(r"(?m)^[ \t]*§[ \t]*(.+?)[ \t]*$", lambda m: m.group(1).upper(), text)


def _append_guided_ritual(reading: str, tier: str, draw_result: dict) -> str:
    """
    Close flagship readings with a short outdoor observance — the client-side
    step that involves the buyer. Inactive until a tier is added to
    TIERS_WITH_RITUAL; kept ready for The Whole Ground.

    The invitation NAMES the client's own drawn sign rather than "the sign in
    your reading", so the customer never has to guess which one is meant.
    Inserted just before the sign-off/disclaimer so it reads as part of the
    reading, not a footer.
    """
    if not reading or tier not in TIERS_WITH_RITUAL:
        return reading
    signs = (draw_result or {}).get("signs") or []
    named = (signs[0].get("name") if signs else "") or ""
    if not named:
        return reading
    ritual = (
        "§How to Sit With This\n\n"
        "A way to work with this reading. When you can, take it outside and read it "
        "through once, slowly, without stopping to decide anything. Then stand still "
        f"for a few minutes and pay attention to what is actually around you. {named} "
        "found its way into your reading; let the living world have the same chance. "
        "You do not need to act on what you notice. What is yours to carry forward "
        "will be clear by the time you go back in."
    )
    paras = reading.split("\n\n")
    for i, p in enumerate(paras):
        if any(s in p.lower() for s in _SIGNOFF_PATTERNS):
            paras.insert(i, ritual)
            return "\n\n".join(paras)
    paras.append(ritual)
    return "\n\n".join(paras)


def _auto_bold(text: str) -> str:
    """
    Auto-wrap the land vocabulary in <strong> tags so it stands out visually.
    Covers: the sabbats, the elements, the drawn plants and animals, and the
    numerology markers. Multi-word terms come first to avoid partial matches.
    """
    import re
    TERMS = [
        # The Elder Futhark
        r"Fehu", r"Uruz", r"Thurisaz", r"Ansuz", r"Raidho", r"Kenaz",
        r"Gebo", r"Wunjo", r"Hagalaz", r"Nauthiz", r"Isa", r"Jera",
        r"Eihwaz", r"Perthro", r"Algiz", r"Sowilo", r"Tiwaz", r"Berkano",
        r"Ehwaz", r"Mannaz", r"Laguz", r"Ingwaz", r"Othala", r"Dagaz",
        r"merkstave",
        # The eight turns of the wheel
        r"Samhain", r"Yule", r"Imbolc", r"Ostara",
        r"Beltane", r"Litha", r"Lammas", r"Mabon",
        r"Wheel of the Year",
        # Plants (multi-word first)
        r"Trailing blackberry", r"Devil's club", r"Skunk cabbage",
        r"Oregon grape", r"Sword fern", r"Red alder", r"Douglas fir",
        r"Salmonberry", r"Horsetail", r"Nettle", r"Lichen", r"Rowan",
        r"Cedar", r"Moss",
        # Animals (multi-word first)
        r"Black-tailed deer", r"Great blue heron", r"Douglas squirrel",
        r"Red-tailed hawk", r"Steller's jay", r"Barred owl", r"Banana slug",
        r"Black bear", r"Raven", r"Salmon", r"Coyote", r"Beaver",
        # Numerology phrases
        r"Master Builder", r"Master Number",
        r"\d{1,2} Name Number", r"Life Path \d{1,2}",
    ]
    for term in TERMS:
        pattern = rf"(?<![<\w])({term})(?![>\w])"
        text = re.sub(pattern, r'<strong style="color:#5d7a52;font-weight:700;">\1</strong>', text)
    return text


def _reading_to_html(plain_text: str) -> str:
    """
    Convert a plain-text reading into a Gmail-safe HTML email.

    Design goals:
    - Light warm-cream background so gold/brown text is readable in ALL clients
    - Dark branded header strip at top
    - Auto-bolded mystical key terms in deep amber
    - Visual divider between every paragraph for breathing room
    - Sign-off block styled distinctly from body
    """
    import html as _html

    lines = plain_text.strip().split("\n")

    # First non-empty line → reading title
    title_line = ""
    body_lines = []
    found_title = False
    for line in lines:
        if not found_title and line.strip():
            title_line = _html.escape(line.strip())
            found_title = True
        else:
            body_lines.append(line)

    # Collect blocks (split on blank lines). A line that begins with the section
    # marker '§' is a movement header — a chapter marker for the reading's
    # natural movements, emitted by the model on the long tiers and by the appended
    # ritual. Every other block is prose. Short tiers carry no markers, so this is a
    # no-op for them and they render as continuous prose exactly as before.
    blocks  = []   # list of ("h", text) | ("p", text)
    current = []
    def _flush_para():
        if current:
            blocks.append(("p", " ".join(current)))
            current.clear()
    for line in body_lines:
        s = line.strip()
        if s == "":
            _flush_para()
        elif s.startswith("§"):
            _flush_para()
            blocks.append(("h", s.lstrip("§").strip()))
        else:
            current.append(s)
    _flush_para()

    # Strip any sign-off Claude wrote (wording varies) and replace with our canonical version.
    # Anything that looks like a disclaimer, attribution, or sign-off is discarded.
    SIGNOFF_PATTERNS = (
        "This reading is offered",
        "This reading is provided",
        "provided as spiritual guidance",
        "offered as spiritual guidance",
        "— Willow",
        "– Willow",
        "Written by hand, at the edge of the woods",
        "Trust your own intuition",
        "Your own knowing",
        "MOSS &",
    )
    clean_blocks = []
    for kind, text in blocks:
        if kind == "p" and any(s.lower() in text.lower() for s in SIGNOFF_PATTERNS):
            continue   # drop it — we append our own below
        clean_blocks.append((kind, text))

    # Canonical sign-off — always appended by us, never from Claude
    CANONICAL_SIGNOFF = (
        "This reading is offered as spiritual guidance. "
        "Your own knowing is always the final word."
    )
    CANONICAL_ATTRIBUTION = "Willow, Moss &amp; Marrow"

    # Build body HTML. Prose paragraphs get the faint gold rule between them; a
    # movement header supplies its own separation, so no rule is drawn next to one.
    PARA_STYLE  = (
        "margin:0 0 0 0;padding:18px 0 18px 0;"
        "font-family:Georgia,'Times New Roman',serif;"
        "font-size:16px;line-height:1.85;color:#1e140a;"
    )
    RULE_STYLE  = "border:none;border-top:1px solid #b9cba6;margin:0;"

    def _header_row(txt):
        # Gold small-caps flanked by waxing/waning moons, with a short centred rule
        # beneath — orients the reader without exposing the spread's machinery.
        label = _html.escape(txt).upper()
        return (
            '<tr><td style="padding:34px 0 5px 0;text-align:center;'
            "font-family:'Palatino Linotype',Palatino,Georgia,serif;"
            "font-size:12px;font-weight:bold;letter-spacing:4px;text-transform:uppercase;"
            f'color:#5d7a52;">&#10087;&nbsp;&nbsp;{label}&nbsp;&nbsp;&#10087;</td></tr>'
            '<tr><td style="padding:0 0 6px 0;text-align:center;font-size:0;">'
            '<span style="display:inline-block;width:46px;border-top:1px solid #b9cba6;">&nbsp;</span>'
            "</td></tr>"
        )

    para_rows = []
    prev_kind = None
    for kind, text in clean_blocks:
        if kind == "h":
            para_rows.append(_header_row(text))
        else:
            if prev_kind == "p":
                para_rows.append(f'<tr><td><hr style="{RULE_STYLE}"></td></tr>')
            para_rows.append(f'<tr><td style="{PARA_STYLE}">{_linkify_html(_auto_bold(_html.escape(text)))}</td></tr>')
        prev_kind = kind

    # Always render the canonical sign-off (Claude's version was stripped above)
    signoff_html = (
        f'<tr><td style="padding:24px 0 0 0;">'
        f'<hr style="{RULE_STYLE}"></td></tr>'
        f'<tr><td style="padding:20px 0 4px 0;font-family:Georgia,serif;'
        f'font-size:13px;color:#5f7355;font-style:italic;line-height:1.7;">'
        f'{CANONICAL_SIGNOFF}<br>{CANONICAL_ATTRIBUTION}</td></tr>'
    )

    body_table = "\n".join(para_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Your Moss &amp; Marrow Reading</title>
</head>
<body style="margin:0;padding:0;background-color:#f5f0e8;">
<!--[if mso]><table width="600" align="center"><tr><td><![endif]-->
<table role="presentation" cellpadding="0" cellspacing="0" border="0"
       align="center" width="100%"
       style="max-width:620px;margin:0 auto;background-color:#f5f0e8;">

  <!-- Header — warm dark brown, moon phases, gold type -->
  <tr>
    <td bgcolor="#0c2415"
        style="background-color:#0c2415;padding:28px 32px 24px 32px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">

        <!-- Leaf row -->
        <tr>
          <td style="text-align:center;
                     font-family:Georgia,serif;
                     font-size:14px;
                     color:#8fb883;
                     letter-spacing:6px;
                     padding-bottom:14px;">
            &#10087;&nbsp;&#10022;&nbsp;&#10087;
          </td>
        </tr>

        <!-- Shop name -->
        <tr>
          <td style="text-align:center;
                     font-family:'Palatino Linotype',Palatino,Georgia,serif;
                     font-size:13px;letter-spacing:5px;text-transform:uppercase;
                     color:#ffb98f;">
            MOSS &amp; MARROW
          </td>
        </tr>

        <!-- Reader name -->
        <tr>
          <td style="text-align:center;padding-top:6px;
                     font-family:Georgia,serif;font-size:12px;
                     letter-spacing:2px;color:#a7c39a;font-style:italic;">
            with Willow &nbsp;&#xb7;&nbsp; Reader of the Land
          </td>
        </tr>

        <!-- Gold rule -->
        <tr>
          <td style="padding:16px 40px 0 40px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
              <tr><td style="border-top:1px solid #2e4a30;font-size:0;">&nbsp;</td></tr>
            </table>
          </td>
        </tr>

        <!-- Reading title -->
        <tr>
          <td style="text-align:center;padding-top:16px;
                     font-family:'Palatino Linotype',Palatino,Georgia,serif;
                     font-size:19px;font-weight:normal;font-style:italic;
                     letter-spacing:0.5px;color:#ffe3cb;line-height:1.5;">
            {title_line}
          </td>
        </tr>

        <!-- Personal tagline -->
        <tr>
          <td style="text-align:center;padding-top:12px;
                     font-family:Georgia,serif;font-size:12px;
                     color:#97a087;font-style:italic;line-height:1.6;
                     letter-spacing:0.3px;">
            This reading was walked, held, and written for you alone.
          </td>
        </tr>

      </table>
    </td>
  </tr>

  <!-- Colour bridge strip -->
  <tr>
    <td bgcolor="#2c2012"
        style="background-color:#2c2012;height:3px;font-size:0;">&nbsp;</td>
  </tr>

  <!-- Body -->
  <tr>
    <td style="padding:32px 32px 28px 32px;background-color:#f5f0e8;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
        {body_table}
        {signoff_html}
      </table>
    </td>
  </tr>

  <!-- Footer — deep forest green, Willow's voice -->
  <tr>
    <td bgcolor="#0c2415"
        style="background-color:#0c2415;padding:26px 32px 22px 32px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">

        <!-- Rule -->
        <tr>
          <td style="padding-bottom:18px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
              <tr><td style="border-top:1px solid #2e4a30;font-size:0;">&nbsp;</td></tr>
            </table>
          </td>
        </tr>

        <!-- Personal closing -->
        <tr>
          <td style="text-align:center;
                     font-family:'Palatino Linotype',Palatino,Georgia,serif;
                     font-size:13px;font-style:italic;
                     color:#ffb98f;line-height:1.9;">
            Thank you for trusting me with something this close to your heart.<br>
            The signs are only the beginning, the knowing was already inside you.
          </td>
        </tr>

        <!-- Signature -->
        <tr>
          <td style="text-align:center;padding-top:12px;
                     font-family:Georgia,serif;font-size:12px;
                     letter-spacing:2px;color:#a7c39a;font-style:italic;">
            from the edge of the woods &nbsp;&#xb7;&nbsp; Willow
          </td>
        </tr>

        <!-- Leaf row -->
        <tr>
          <td style="text-align:center;padding-top:14px;
                     font-family:Georgia,serif;font-size:12px;
                     color:#8fb883;letter-spacing:8px;">
            &#10087;&nbsp;&#10022;&nbsp;&#10087;
          </td>
        </tr>

        <!-- Disclaimer -->
        <tr>
          <td style="text-align:center;padding-top:14px;
                     font-family:Georgia,serif;font-size:10px;
                     letter-spacing:1px;color:#8a9c78;line-height:1.7;">
            MOSS &amp; MARROW &nbsp;&#xb7;&nbsp; SPIRITUAL GUIDANCE &amp; ENTERTAINMENT<br>
            This reading is offered for guidance and personal reflection only.
          </td>
        </tr>

      </table>
    </td>
  </tr>

</table>
<!--[if mso]></td></tr></table><![endif]-->
</body>
</html>"""


def parse_reading_and_script(claude_response: str) -> tuple:
    """
    Split Claude's output into (reading_text, audio_script).
    The audio script is delimited by [AUDIO SCRIPT BEGIN] / [AUDIO SCRIPT END].
    Returns (full_response, None) if no delimiter is found.
    """
    BEGIN = "[AUDIO SCRIPT BEGIN]"
    END   = "[AUDIO SCRIPT END]"
    if BEGIN in claude_response:
        parts        = claude_response.split(BEGIN, 1)
        reading_text = parts[0].strip()
        remainder    = parts[1]
        if END in remainder:
            audio_script = remainder.split(END, 1)[0].strip()
        else:
            audio_script = remainder.strip()
        return reading_text, audio_script
    return claude_response.strip(), None


def _clean_audio_fillers(script: str) -> str:
    """
    The spoken reflection should convey contemplation through breath, a soft
    [exhales] or [sighs] flanked by pauses, not through verbal "um"/"uh"/"hmm"
    fillers, which read as nervous or machine-glitchy. The prompt now asks for
    breath instead of fillers, but this is a deterministic safety net that removes
    any residual standalone filler tokens the model still emits. Word-boundary
    matched so it never touches real words (human, number, assume, her). Audio
    only, the written reading is untouched.
    """
    if not script:
        return script
    import re
    # Standalone verbal fillers only: um/umm, uh/uhh, hm/hmm, erm. Also consume the
    # punctuation the filler carries (a trailing "..." or a single , . ! ?) so no
    # stray marks are left behind. Intentional ellipses attached to real words are
    # preserved because the match is anchored on the filler word itself.
    cleaned = re.sub(
        r'\b(?:um+|uh+|hm+|erm+)\b(?:\s*\.\.\.|\s*[.,!?])?\s*',
        '', script, flags=re.IGNORECASE,
    )
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)           # collapse doubled spaces
    cleaned = re.sub(r'[ \t]+([,.!?])', r'\1', cleaned)    # unstrand punctuation
    return cleaned.strip()


def generate_audio(script_text: str) -> bytes | None:
    """
    Convert script_text to MP3 via ElevenLabs.
    Returns raw MP3 bytes, or None if ElevenLabs is not configured or fails.
    """
    api_key  = os.environ.get("ELEVENLABS_API_KEY",  "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if not api_key or not voice_id:
        print("  ElevenLabs not configured — skipping audio generation")
        return None
    try:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key":   api_key,
            "Content-Type": "application/json",
            "Accept":       "audio/mpeg",
        }
        # Eleven v3 does NOT support SSML <break time="Xs"/> tags (v2-only); v3 uses
        # bracketed pause tags instead. Convert any break tags the model emitted so
        # pacing actually renders instead of being ignored (or worse, garbled) as
        # unsupported markup — a deterministic net even though the prompt now asks
        # for v3 tags natively.
        import re as _re
        def _break_to_pause(m):
            try:
                secs = float(m.group(1))
            except ValueError:
                secs = 1.0
            if secs <= 0.6:
                return "[short pause]"
            if secs < 1.3:
                return "[pause]"
            return "[long pause]"
        voiced_text = _re.sub(r'<break\s+time="([\d.]+)s?"\s*/?\s*>', _break_to_pause, script_text)
        voiced_text = _re.sub(r"[ \t]{2,}", " ", voiced_text)
        # ElevenLabs commonly slurs or clips the first word or two as the voice
        # "warms up" at generation onset. Prepend a disposable breath + a beat so
        # that artifact lands on a non-verbal sound, and the first real words (the
        # customer's name) arrive after the voice has settled. Applied only to the
        # audio sent to ElevenLabs — the stored/QC audio_script stays clean.
        if not voiced_text.lstrip().startswith(("[exhales]", "[sighs]")):
            voiced_text = "[exhales] [short pause] " + voiced_text
        payload = {
            "text":     voiced_text,
            "model_id": "eleven_v3",
            "voice_settings": {
                # v3 documents three stability modes: 0.0 Creative / 0.5 Natural /
                # 1.0 Robust. Natural keeps the voice faithful while still
                # responding to the emotion tags; Creative hallucinates more.
                "stability":        0.5,
                "similarity_boost": 0.70,
                "style":            0.30,
                "use_speaker_boost": False,  # OFF — reduces metallic glitching on longer audio
            },
        }
        # Retry transient ElevenLabs failures (rate limits, 5xx, network) a few
        # times before giving up, so a momentary blip doesn't cost the customer the
        # MP3 they paid for. A permanent failure still returns None (handled by the
        # caller, which alerts the owner).
        import time
        for attempt in range(1, 4):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=90)
            except requests.RequestException as e:
                print(f"  WARNING: ElevenLabs request failed (attempt {attempt}/3): {e}")
                if attempt < 3:
                    time.sleep(3 * attempt)
                    continue
                return None
            if resp.status_code == 200:
                print(f"  Audio generated: {len(resp.content):,} bytes")
                return resp.content
            print(f"  WARNING: ElevenLabs {resp.status_code} (attempt {attempt}/3): {resp.text[:200]}")
            # 4xx other than 429 won't fix itself — do not retry.
            if resp.status_code < 500 and resp.status_code != 429:
                return None
            if attempt < 3:
                time.sleep(3 * attempt)
        return None
    except Exception as e:
        print(f"  WARNING: Audio generation failed: {e}")
        return None


def send_email(to_address, subject, body,
               image_bytes: bytes = None, image_filename: str = "spread.jpg",
               audio_bytes: bytes = None, audio_filename: str = "ceremony_reflection.mp3",
               extra_images: list = None):
    """
    Send an HTML email with plain-text fallback, optionally with a JPEG image attachment.
    image_bytes — raw JPEG bytes from generate_record_image(); omit for text-only.
    extra_images — optional list of (bytes, filename) for additional image attachments
    for any additional keepsake images.
    """
    gmail_user = os.environ["GMAIL_USER"]
    gmail_pass = os.environ["GMAIL_APP_PASSWORD"]

    # Outer wrapper: mixed (allows attachments); inner alternative holds text/html pair
    outer = MIMEMultipart("mixed")
    outer["Subject"] = _strip_em_dashes(subject)
    outer["From"]    = f"Willow at Moss & Marrow <{gmail_user}>"
    outer["To"]      = to_address

    # Normalise the plain-text sign-off.
    plain_body = _sanitise_plain(body)

    # Build alternative part (plain + html). The HTML styles the '§' movement
    # markers into gold headers; the plain-text part shows them as uppercase lines.
    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(_plain_movement_headers(plain_body), "plain"))
    alternative.attach(MIMEText(_reading_to_html(plain_body), "html"))
    outer.attach(alternative)

    if image_bytes:
        img_part = MIMEImage(image_bytes, _subtype="jpeg")
        img_part.add_header(
            "Content-Disposition", "attachment", filename=image_filename
        )
        outer.attach(img_part)

    for extra_bytes, extra_name in (extra_images or []):
        if not extra_bytes:
            continue
        part = MIMEImage(extra_bytes)
        part.add_header("Content-Disposition", "attachment", filename=extra_name)
        outer.attach(part)

    if audio_bytes:
        from email.mime.base import MIMEBase
        from email import encoders
        audio_part = MIMEBase("audio", "mpeg")
        audio_part.set_payload(audio_bytes)
        encoders.encode_base64(audio_part)
        audio_part.add_header(
            "Content-Disposition", "attachment", filename=audio_filename
        )
        outer.attach(audio_part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, _recipients_with_qc(to_address), outer.as_string())


ORDER_ERROR_EMAIL = """\
Hi {name},

Thank you for placing your order with Moss & Marrow.

I was not able to locate your order number ({order_num}) in our system. \
This sometimes happens when an order is very recent. If you placed it in the \
last few minutes, please wait a little while and try again.

If this keeps happening, please reply to this email with your Etsy order \
confirmation and I will get your reading booked in manually.

Willow
Moss & Marrow
"""

# Sent to customer immediately on queue — one version per tier, describing that
# tier's real deliverables. (Moss & Marrow keys nothing to zodiac signs; the
# Sworn & Sealed candle-colour table has no counterpart here.)

# ── CANDLE COMPANIONS (DORMANT) ─────────────────────────────────────────────
# Print-on-demand candle listings sold alongside the readings. Both URLs stay
# empty until the Etsy candle listings are live; while they are empty, no
# customer email mentions a candle purchase anywhere. To activate, set the
# repo variables TABLE_CANDLE_URL and CEREMONY_CANDLE_URL to the live listing
# URLs — no other change is needed.
TABLE_CANDLE_URL    = os.environ.get("TABLE_CANDLE_URL", "").strip()
CEREMONY_CANDLE_URL = os.environ.get("CEREMONY_CANDLE_URL", "").strip()
_CEREMONY_CANDLE_MIN_DAYS = 10   # only offered when it can ship before the ceremony


def _candle_ps() -> str:
    """Closing line for reading deliveries; empty while the store is dormant."""
    if not TABLE_CANDLE_URL:
        return ""
    return ("\n\nIf you would like the candle I carry out to the readings, "
            "it is here: " + TABLE_CANDLE_URL)


def _linkify_html(escaped: str) -> str:
    """Wrap bare http(s) URLs in already-escaped HTML text with styled anchors
    so listing links in the email body are clickable."""
    import re
    return re.sub(r"(https?://[^\s<]+)",
                  r'<a href="\1" style="color:#5d7a52;">\1</a>', escaped)


CONFIRM_FIRST_SIGN = """\
Hi {name},

Your order has been received and your reading is confirmed.

I will take your question out with me during my next working session. Your \
First Sign arrives as a written reading, delivered by email, usually within \
the hour of your form reaching me during working hours. One question, one \
sign, answered plainly.

Working hours: Monday to Friday 10am to 4pm, Saturday and Sunday 10am to 1pm \
(Pacific Time). If you order outside these hours, your reading begins at the \
start of the next working window.

If there is anything you would like to add before I begin, reply to this email.

Willow
Moss & Marrow
"""

CONFIRM_READING_OF_LAND = """\
Hi {name},

Your order has been received and your reading is confirmed.

I will take your question outside during my next working session and read it \
where it lives. Your Reading of the Land arrives as a full written reading \
across the three threads, where the year stands for you, which element is \
loudest, and the sign that keeps finding you, woven into one answer for your \
situation.

Delivery: within 2 to 4 hours, during my working hours.

Working hours: Monday to Friday 10am to 4pm, Saturday and Sunday 10am to 1pm \
(Pacific Time).

If there is anything you would like to add before I begin, reply to this email.

Willow
Moss & Marrow
"""

# (Sworn & Sealed's Grand Ceremony templates — elected dates, candle colours,
#  photo dispatch — have no Moss & Marrow counterpart and were removed.)

CONFIRM_WHOLE_GROUND = """\
Hi {name},

Your Whole Ground reading is confirmed. This is the deepest reading I write, \
where you stand, what the season is bringing, and the question you have not \
thought to ask, read above ground and below it.

Your reading will arrive by email within 4 to 8 hours, during my working \
hours. I will carry your question out and work it through season, element, \
and sign on the living ground. It comes to you as a full written reading \
you keep, together with a short spoken note, recorded the moment I come in \
from your reading, before I sit down to write.

If you would like to hold a small moment of your own while I work, you are \
welcome to. There is no set time for this, do it whenever feels right before \
your reading arrives:

1. Step outside, wherever outside is for you, a garden, a balcony, a street \
with a tree on it.

2. Stand still for three slow breaths and notice what is actually there, the \
air, the light, whatever is growing or moving.

3. Let your question sit in the open while you do. You are not looking for an \
answer. You are letting the question breathe.

None of this is required, the reading stands on its own, but many people find \
that a few minutes outside deepens what they receive.

Working hours: Monday to Friday 10am to 4pm, Saturday and Sunday 10am to 1pm \
(Pacific Time).

If there is anything you would like to add before I begin, reply to this email.

Willow
Moss & Marrow
"""

CONFIRM_FIRST_STONE = """\
Hi {name},

Your First Stone is confirmed.

One question, one stone. I will take your question outside during my next
working session, put my hand in the pouch without looking, and draw the
single rune that answers it. Then I tell you plainly what it says, face up
or face down.

Your reading arrives by email, usually within the hour of your form
reaching me during working hours.

Working hours: Monday to Friday 10am to 4pm, Saturday and Sunday 10am to
1pm (Pacific Time). If you order outside these hours, your reading begins
at the start of the next working window.

Willow
Moss & Marrow
"""

CONFIRM_NINE_WORLDS = """\
Hi {name},

Your Nine Worlds casting is confirmed.

This is the deepest cast I lay. Nine stones, in three lines of three, on
open ground: the line of what was laid down, the line of what is becoming,
and the line of what takes shape ahead. Read across, those are the three
Norns. Read down, they are you, the matter itself, and what meets it. Nine
is the Futhark's own number, and a cast this size shows the pattern behind
a situation, not only its answer.

Your reading arrives by email within 4 to 8 hours, during my working
hours: every stone read in its place, the lines and the columns both, and
plain ground to stand on at the end.

Working hours: Monday to Friday 10am to 4pm, Saturday and Sunday 10am to
1pm (Pacific Time).

If there is anything you would like to add before I begin, reply to this
email.

Willow
Moss & Marrow
"""

CONFIRM_RUNE_CASTING = """\
Hi {name},

Your Rune Casting is confirmed.

The runes are an old alphabet of the north, each mark a thing the land
already knows: harvest, ice, gift, daybreak. Mine are cut from a fallen
rowan branch, and they come outside with me the way everything here does.
I will carry your question out during my next working session and cast
five stones for it on open ground: what lies beneath, what came before,
where you stand, what is owed, and what becomes.

Your reading arrives by email within 2 to 4 hours, during my working
hours: the five stones as they fell, face up or face down, each one read
plainly against your question.

Working hours: Monday to Friday 10am to 4pm, Saturday and Sunday 10am to
1pm (Pacific Time).

If there is anything you would like to add before I begin, reply to this
email.

Willow
Moss & Marrow
"""

CONFIRM_TURNING_YEAR = """\
Hi {name},

Your place in The Turning Year is confirmed.

This is a year read as it happens: a personal written reading at each of the \
eight turns of the wheel, Imbolc, Ostara, Beltane, Litha, Lammas, Mabon, \
Samhain and Yule, each one written for where you stand as the season moves.

Your first reading arrives today, during my working hours, so you can see \
where the year holds you right now. After that, each reading arrives by email \
at the turn itself, eight in all. Keep them together; by the end you will have \
the whole year in writing, a record of where you were at every turn.

Working hours: Monday to Friday 10am to 4pm, Saturday and Sunday 10am to 1pm \
(Pacific Time).

If there is anything you would like me to hold in mind across the year, reply \
to this email.

Willow
Moss & Marrow
"""


# ─── MAIN PROCESSING ────────────────────────────────────────────────────────────

def ingest_new_submissions(state, access_token):
    """
    Poll all Google Sheet tabs for new intake form submissions and queue them.
    Each tab corresponds to one reading type; tier is determined from the Etsy order.
    Rows are marked 'processed' in the Sheet immediately after queuing.
    """
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    if not sheet_id:
        print("  WARNING: GOOGLE_SHEET_ID not set — skipping order ingestion")
        return 0

    existing_ids    = {d["submission_id"] for d in state["pending_deliveries"]}
    existing_orders = {d["order_number"]  for d in state["pending_deliveries"]
                       if d.get("order_number")}
    redeemed        = set(state.get("redeemed_orders", []))   # permanent ledger
    new_count       = 0

    for reading_type, config in SHEET_CONFIG.items():
        try:
            rows = get_sheet_rows(sheet_id, config["tab"])
        except Exception as e:
            print(f"  WARNING: could not read '{config['tab']}' tab — {e}")
            continue

        for row_index, fields in rows:
            sub_id         = f"{config['tab']}-row{row_index}"
            customer_email = fields.get("customer_email", "")
            # Buyers paste from the Etsy email, which shows "Order #1234567890",
            # so strip whitespace and any leading '#' before the API lookup.
            order_number   = fields.get("order_number", "").strip().lstrip("#").strip()
            customer_name  = fields.get("customer_name", "Valued Client") or "Valued Client"

            if sub_id in existing_ids:
                continue

            if not customer_email or not order_number:
                print(f"  Skip {config['tab']} row {row_index} — missing email or order number")
                mark_row_processed(sheet_id, config["tab"], row_index)
                continue

            # ── Test order detection ───────────────────────────────────────────
            # Format: TEST-<TIER>-<TYPE>  e.g. TEST-DD-CAREER. Only honored from an
            # owner address (or when ALLOW_TEST_ORDERS is set), so the public form
            # cannot claim a free reading with a guessed TEST code.
            looks_test = order_number.upper().startswith("TEST")
            is_test    = looks_test and _test_order_allowed(customer_email)
            if looks_test and not is_test:
                print(f"  TEST-style order {order_number} from non-owner {customer_email} — not honored as a test")

            # Duplicate / replay guard — one reading per real Etsy order number, ever.
            # existing_orders catches same-run and in-queue repeats; the permanent
            # redeemed ledger catches re-submission after the 30-day queue prunes.
            if not is_test:
                if order_number in existing_orders or order_number in redeemed:
                    print(f"  Skip row {row_index} — order {order_number} already redeemed")
                    mark_row_processed(sheet_id, config["tab"], row_index)
                    continue

            if is_test:
                # Format: TEST-<TIER>-<TYPE>  e.g. TEST-RL-CAREER
                parts     = order_number.upper().split("-")
                tier_code = parts[1] if len(parts) > 1 else "FS"
                type_code = parts[2] if len(parts) > 2 else reading_type.upper()
                tier = {
                    "FS": "First Sign", "RL": "Reading of the Land",
                    "WG": "The Whole Ground", "TY": "The Turning Year",
                    "RC": "Rune Casting", "FST": "First Stone",
                    "NW": "The Nine Worlds",
                }.get(tier_code, "First Sign")
                effective_type = {
                    "LOVE": "love", "CAREER": "career",
                    "CLARITY": "clarity", "SEASON": "season",
                }.get(type_code, reading_type)
                print(f"  TEST ORDER — tier={tier} type={effective_type}")
            else:
                order_info = verify_etsy_order(order_number, access_token)
                if order_info == "RETRY":
                    # Transient Etsy/API failure: leave the row unprocessed so the
                    # next run retries — never tell a real customer their valid
                    # order was not found because Etsy hiccuped.
                    print(f"  Etsy temporarily unavailable for {order_number} — leaving row for next run")
                    continue
                if order_info is None:
                    print(f"  Order {order_number} not found in Etsy — sending error email")
                    try:
                        send_email(
                            customer_email,
                            "Your Moss & Marrow Order, A Quick Note",
                            ORDER_ERROR_EMAIL.format(name=customer_name, order_num=order_number),
                        )
                    except Exception as e:
                        print(f"  ERROR sending error email: {e}")
                    mark_row_processed(sheet_id, config["tab"], row_index)
                    continue

                if order_info == "UNVERIFIED":
                    # Etsy verification could not run this cycle (usually a transient
                    # token/refresh failure). NEVER deliver an unverified order — leave
                    # the row so the next run verifies it once Etsy is reachable again.
                    # The owner is alerted once per outage from main().
                    print(f"  Etsy verification unavailable — leaving {order_number} for next run")
                    continue

                if order_info != "UNVERIFIED":
                    # Payment gate: never deliver a cancelled or refunded order, and
                    # hold-alert the owner rather than guess.
                    if order_info.get("status") == "canceled" or order_info.get("refunded"):
                        print(f"  Order {order_number} is cancelled/refunded — holding for review")
                        try:
                            send_email(
                                OWNER_ALERT_EMAIL,
                                f"[ACTION NEEDED] Cancelled/refunded order — {order_number}",
                                PAYMENT_ISSUE_ALERT.format(
                                    order_num=order_number, customer_email=customer_email,
                                    status=order_info.get("status") or "unknown",
                                    is_paid=order_info.get("is_paid"),
                                    refunded=order_info.get("refunded"),
                                ),
                            )
                        except Exception as e:
                            print(f"  ERROR sending payment-issue alert: {e}")
                        mark_row_processed(sheet_id, config["tab"], row_index)
                        continue
                    # Not paid yet (e.g. "payment processing"): leave the row so the
                    # next run re-checks, rather than delivering an unpaid reading.
                    if not order_info.get("is_paid"):
                        print(f"  Order {order_number} not paid yet — leaving row for next run")
                        continue
                    # Buyer binding: the person filling the form must be the buyer who
                    # paid. Only checked when Etsy returned a buyer email.
                    buyer_email = order_info.get("buyer_email", "")
                    if buyer_email and buyer_email != customer_email.strip().lower():
                        print(f"  Buyer/form email mismatch for {order_number} — holding for review")
                        try:
                            send_email(
                                OWNER_ALERT_EMAIL,
                                f"[ACTION NEEDED] Buyer email mismatch — order {order_number}",
                                EMAIL_MISMATCH_ALERT.format(
                                    order_num=order_number, form_email=customer_email,
                                    buyer_email=buyer_email,
                                    reading_type=reading_type.replace("_", " "),
                                ),
                            )
                        except Exception as e:
                            print(f"  ERROR sending email-mismatch alert: {e}")
                        mark_row_processed(sheet_id, config["tab"], row_index)
                        continue

                    # Redemption must be for one of our reading listings (F7). Opt-in
                    # via READING_LISTING_IDS; empty disables the check.
                    if READING_LISTING_IDS and str(order_info.get("listing_id") or "") not in READING_LISTING_IDS:
                        print(f"  Order {order_number} listing {order_info.get('listing_id')} not a reading listing — holding")
                        try:
                            send_email(
                                OWNER_ALERT_EMAIL,
                                f"[ACTION NEEDED] Non-reading listing — order {order_number}",
                                UNKNOWN_LISTING_ALERT.format(
                                    order_num=order_number, customer_email=customer_email,
                                    listing_id=order_info.get("listing_id"),
                                ),
                            )
                        except Exception as e:
                            print(f"  ERROR sending listing alert: {e}")
                        mark_row_processed(sheet_id, config["tab"], row_index)
                        continue

                    # Multi-item / multi-quantity order (F5): one order can hold several
                    # readings. Delivering one would under-serve a paid order, so hold
                    # the whole order for manual handling.
                    if order_info.get("n_units", 1) > 1:
                        print(f"  Order {order_number} has {order_info['n_units']} reading units — holding for manual handling")
                        try:
                            send_email(
                                OWNER_ALERT_EMAIL,
                                f"[ACTION NEEDED] Multi-item order — {order_number}",
                                MULTI_ITEM_ALERT.format(
                                    order_num=order_number, customer_email=customer_email,
                                    n_units=order_info["n_units"],
                                ),
                            )
                        except Exception as e:
                            print(f"  ERROR sending multi-item alert: {e}")
                        mark_row_processed(sheet_id, config["tab"], row_index)
                        continue

                # Cross-check the reading type the customer selected on the form
                # against what they actually bought. A confident mismatch means the
                # wrong reading was chosen (and likely the wrong fields filled), so
                # hold it and alert the owner rather than deliver the wrong reading.
                if order_info != "UNVERIFIED":
                    order_type = get_order_reading_type(order_info)
                    if order_type and order_type != reading_type:
                        print(f"  Reading-type mismatch — form says '{reading_type}', "
                              f"order {order_number} is '{order_type}' — holding for review")
                        try:
                            send_email(
                                OWNER_ALERT_EMAIL,
                                f"[ACTION NEEDED] Reading-type mismatch — order {order_number}",
                                TYPE_MISMATCH_ALERT.format(
                                    order_num=order_number,
                                    customer_email=customer_email,
                                    form_type=reading_type.replace("_", " "),
                                    order_type=order_type.replace("_", " "),
                                ),
                            )
                        except Exception as e:
                            print(f"  ERROR sending mismatch alert: {e}")
                        mark_row_processed(sheet_id, config["tab"], row_index)
                        continue

                # Resolve the tier from the order itself. Never guess.
                tier = None if order_info == "UNVERIFIED" else get_tier(order_info)

                if not tier:
                    # Tier unresolved: do NOT ship the cheapest reading (that would
                    # under-deliver a paid order). Alert the owner and hold it.
                    print(f"  WARNING: could not resolve tier for order {order_number} — holding for manual review")
                    detail = order_info if isinstance(order_info, str) \
                             else json.dumps(order_info, indent=2, default=str)
                    try:
                        send_email(
                            OWNER_ALERT_EMAIL,
                            f"[ACTION NEEDED] Unresolved tier for order {order_number}",
                            TIER_UNRESOLVED_ALERT.format(
                                order_num=order_number,
                                customer_email=customer_email,
                                reading_type=reading_type,
                                detail=detail,
                            ),
                        )
                    except Exception as e:
                        print(f"  ERROR sending tier-alert email: {e}")
                    mark_row_processed(sheet_id, config["tab"], row_index)
                    continue

                effective_type = reading_type

            # Mark processed immediately — prevents double-processing on next run.
            # NOTE: the order is NOT recorded as redeemed here. Redemption is
            # recorded only at the moment the delivery is actually queued, so an
            # order held by a later gate (e.g. the chart-tier solar-fallback hold)
            # can be resubmitted with corrected details and process normally.
            mark_row_processed(sheet_id, config["tab"], row_index)
            existing_ids.add(sub_id)

            # Resolve effective POI (may be the client themselves for career/clarity)
            eff_config = SHEET_CONFIG.get(effective_type, config)
            client_dob = fields.get("client_dob", "")
            if eff_config["poi_is_client"]:
                poi_name = customer_name
                poi_dob  = client_dob
            else:
                poi_name = fields.get("poi_name", "")
                poi_dob  = fields.get("poi_dob", "")

            # Draw for the tier: the Rune Casting tier casts the Elder Futhark;
            # every other tier draws the land (season, element, and signs).
            tz           = os.environ.get("TIMEZONE", "America/Los_Angeles").strip()
            reading_date = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
            _engine = rune_draw_reading if tier in RUNE_TIERS else draw_reading
            draw = _engine(
                poi_name=poi_name or customer_name,
                poi_dob=poi_dob,
                reading_type=effective_type,
                tier=tier,
                reading_date=reading_date,
                timezone=tz,
            )

            reading_type_final = effective_type
            user_message = build_user_message(fields, reading_type_final, tier, draw, reading_date=reading_date)

            # (Moss & Marrow casts no natal charts and elects no ceremony dates:
            #  the Sworn & Sealed natal / Grand Ceremony ingest steps have no
            #  counterpart here.)
            from datetime import timezone as _tz
            if is_test:
                scheduled_for = datetime.now(_tz.utc).isoformat()
            else:
                scheduled_for = schedule_delivery(tier)

            state["pending_deliveries"].append({
                "submission_id":  sub_id,
                "scheduled_for":  scheduled_for,
                "status":         "pending",
                "customer_email": customer_email,
                "customer_name":  customer_name,
                "order_number":   order_number,
                "tier":           tier,
                "reading_type":   reading_type_final,
                "user_message":   user_message,
                "draw_block":     draw["formatted_block"],
                "test":           is_test,
                # The Turning Year: which of the eight drops this entry is, plus
                # the intake fields so later turns can be redrawn for their date.
                "turn_number":    1 if tier == "The Turning Year" else None,
                "intake_fields":  dict(fields) if tier == "The Turning Year" else None,
                "draw_result": (
                    {
                        "runes":           draw["runes"],
                        "birth_rune":      draw["birth_rune"],
                        "merkstave_count": draw["merkstave_count"],
                        "season_line":     draw["season"]["season_line"],
                        "name_number":     draw["name_number"],
                    }
                    if tier in RUNE_TIERS else
                    {
                        "season_line": draw["season"]["season_line"],
                        "prev_sabbat": draw["season"]["prev_sabbat"],
                        "birth_md":    draw.get("birth_md"),
                        "element":     draw["element"],
                        "signs":       draw["signs"],
                        "name_number": draw["name_number"],
                    }
                ),
            })
            existing_ids.add(sub_id)
            existing_orders.add(order_number)
            # Permanently record a real order as redeemed the moment it is queued,
            # so it can never be claimed again after the delivery queue prunes
            # (test codes excluded so they stay reusable).
            if not is_test and order_number and order_number not in redeemed:
                redeemed.add(order_number)
                state["redeemed_orders"].append(order_number)

            # ── Send confirmation email
            try:
                if tier == "The Turning Year":
                    send_email(
                        customer_email,
                        "The Turning Year, Confirmed",
                        CONFIRM_TURNING_YEAR.format(name=customer_name),
                    )
                elif tier == "The Whole Ground":
                    send_email(
                        customer_email,
                        "Your Moss & Marrow Reading, Confirmed",
                        CONFIRM_WHOLE_GROUND.format(name=customer_name),
                    )
                elif tier == "Reading of the Land":
                    send_email(
                        customer_email,
                        "Your Moss & Marrow Reading, Confirmed",
                        CONFIRM_READING_OF_LAND.format(name=customer_name),
                    )
                elif tier == "Rune Casting":
                    send_email(
                        customer_email,
                        "Your Rune Casting, Confirmed",
                        CONFIRM_RUNE_CASTING.format(name=customer_name),
                    )
                elif tier == "First Stone":
                    send_email(
                        customer_email,
                        "Your First Stone, Confirmed",
                        CONFIRM_FIRST_STONE.format(name=customer_name),
                    )
                elif tier == "The Nine Worlds":
                    send_email(
                        customer_email,
                        "Your Nine Worlds Casting, Confirmed",
                        CONFIRM_NINE_WORLDS.format(name=customer_name),
                    )
                else:
                    send_email(
                        customer_email,
                        "Your Moss & Marrow Reading, Confirmed",
                        CONFIRM_FIRST_SIGN.format(name=customer_name),
                    )
                print(f"  Confirmation email sent to {customer_email}")
            except Exception as e:
                print(f"  WARNING: ceremony-begun email failed: {e}")

            print(f"  Queued: {customer_name} — {tier} — deliver after {scheduled_for}")
            new_count += 1
            # Persist after each queued order: the Sheet row is already marked
            # processed, so losing the in-memory queue entry to a later crash
            # would silently drop the order.
            save_state(state)

    return new_count


def _queue_next_turning_year_drop(state, delivery):
    """
    After a Turning Year drop is sent, queue the next one for the coming
    sabbat, until all TURNING_YEAR_DROPS turns have been delivered.

    The land for the next turn is drawn NOW for the sabbat date (draws are
    seeded by name + date, so drawing early is identical to drawing on the
    day) and the intake message is rebuilt so the season block is right for
    the turn being delivered, not for the day the subscription started.
    """
    turn = int(delivery.get("turn_number") or 1)
    if turn >= TURNING_YEAR_DROPS:
        print(f"  Turning Year complete for {delivery['customer_name']} ({turn} turns)")
        return

    fields   = delivery.get("intake_fields") or {}
    tz_name  = os.environ.get("TIMEZONE", "America/Los_Angeles").strip()
    local_tz = ZoneInfo(tz_name)
    today    = datetime.now(local_tz).date()

    from land_engine import season_position
    pos = season_position(today)
    next_sabbat = today + timedelta(days=max(pos["days_until"], 1))
    reading_date = next_sabbat.strftime("%Y-%m-%d")

    poi_name = fields.get("customer_name") or delivery["customer_name"]
    draw = draw_reading(
        poi_name=poi_name,
        poi_dob=fields.get("client_dob", ""),
        reading_type="season",
        tier="The Turning Year",
        reading_date=reading_date,
        timezone=tz_name,
    )
    user_message = build_user_message(
        fields, "season", "The Turning Year", draw, reading_date=reading_date
    )
    user_message += f"\nTURNING_YEAR_TURN: {turn + 1} of {TURNING_YEAR_DROPS}"

    from datetime import timezone as _tz
    drop_dt = datetime(next_sabbat.year, next_sabbat.month, next_sabbat.day,
                       10, 0, 0, tzinfo=local_tz)
    state["pending_deliveries"].append({
        "submission_id":  f"{delivery['submission_id']}-turn{turn + 1}",
        "scheduled_for":  drop_dt.astimezone(_tz.utc).isoformat(),
        "status":         "pending",
        "customer_email": delivery["customer_email"],
        "customer_name":  delivery["customer_name"],
        "order_number":   delivery.get("order_number", ""),
        "tier":           "The Turning Year",
        "reading_type":   "season",
        "user_message":   user_message,
        "draw_block":     draw["formatted_block"],
        "test":           False,
        "turn_number":    turn + 1,
        "intake_fields":  fields,
        "draw_result": {
            "season_line": draw["season"]["season_line"],
            "prev_sabbat": draw["season"]["prev_sabbat"],
            "birth_md":    draw.get("birth_md"),
            "element":     draw["element"],
            "signs":       draw["signs"],
            "name_number": draw["name_number"],
        },
    })
    print(f"  Turning Year: queued turn {turn + 1}/{TURNING_YEAR_DROPS} "
          f"for {delivery['customer_name']} on {reading_date}")


def deliver_pending(state, system_prompt, access_token=None):
    """Send readings that are due and within working hours."""
    tz     = get_tz()
    now    = now_local()
    sent   = 0
    cutoff = now - timedelta(days=30)

    # Check working hours once — but test orders bypass this
    outside_hours = not is_working_hours()
    if outside_hours:
        nxt = next_working_start()
        print(f"  Outside working hours — next window opens {nxt.strftime('%A %d %b at %H:%M %Z')}")

    # (Sworn & Sealed's Grand Ceremony morning-reminder pass has no Moss &
    #  Marrow counterpart and was removed.)

    for delivery in state["pending_deliveries"]:
        # Retry deliveries that errored on a previous run (e.g. a transient API
        # timeout) instead of leaving them permanently stuck, up to a cap.
        if delivery.get("status") not in ("pending", "error"):
            continue
        if delivery.get("attempts", 0) >= _MAX_DELIVERY_ATTEMPTS:
            if delivery.get("status") == "error" and not delivery.get("gaveup_alerted"):
                delivery["gaveup_alerted"] = True
                print(f"  Giving up on {delivery.get('customer_name')} after "
                      f"{_MAX_DELIVERY_ATTEMPTS} attempts — alerting owner")
                try:
                    send_email(
                        OWNER_ALERT_EMAIL,
                        f"[ACTION NEEDED] Reading generation failed — order {delivery.get('order_number')}",
                        f"After {_MAX_DELIVERY_ATTEMPTS} attempts the reading for "
                        f"{delivery.get('customer_name')} ({delivery.get('order_number')}) "
                        f"could not be generated.\n\nLast error: {delivery.get('error')}\n\n"
                        f"Please handle this order manually.",
                    )
                except Exception as e:
                    print(f"  ERROR sending give-up alert: {e}")
            continue

        is_test = delivery.get("test", False)

        # Skip non-test orders outside working hours
        if outside_hours and not is_test:
            continue

        scheduled = datetime.fromisoformat(delivery["scheduled_for"])
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=tz)

        if now < scheduled:
            print(f"  Waiting: {delivery['customer_name']} — due {scheduled.strftime('%H:%M %Z')}")
            continue

        # Re-verify a real order just before generation: a refund or cancellation
        # landing between intake and delivery (minutes for most tiers, up to three
        # weeks for a Grand Ceremony) must stop the send. Transient Etsy failures
        # simply defer to the next run; a receipt that has gone bad is alerted and
        # not delivered.
        if not is_test and delivery.get("order_number") and access_token:
            recheck = verify_etsy_order(delivery["order_number"], access_token)
            if recheck == "RETRY":
                print(f"  Etsy re-check unavailable for {delivery['order_number']} — delivering next run")
                continue
            if recheck is None or (isinstance(recheck, dict)
                                   and (recheck.get("status") == "canceled" or recheck.get("refunded"))):
                why = ("receipt no longer found on re-check" if recheck is None
                       else f"refunded/cancelled before delivery (status={recheck.get('status') or 'unknown'})")
                delivery["status"] = "cancelled"
                delivery["error"]  = why
                print(f"  Order {delivery['order_number']} {why} — not sending")
                try:
                    send_email(
                        OWNER_ALERT_EMAIL,
                        f"[ACTION NEEDED] Order changed before delivery — {delivery['order_number']}",
                        PAYMENT_ISSUE_ALERT.format(
                            order_num=delivery["order_number"],
                            customer_email=delivery["customer_email"],
                            status=(recheck or {}).get("status") if isinstance(recheck, dict) else "not found",
                            is_paid=(recheck or {}).get("is_paid") if isinstance(recheck, dict) else "unknown",
                            refunded=(recheck or {}).get("refunded") if isinstance(recheck, dict) else "unknown",
                        ),
                    )
                except Exception as e:
                    print(f"  ERROR sending pre-delivery payment alert: {e}")
                save_state(state)
                continue

        # Time to generate reading and send to customer
        try:
            delivery["attempts"] = delivery.get("attempts", 0) + 1
            print(f"  Generating: {delivery['customer_name']} ({delivery['tier']}), attempt {delivery['attempts']}…")
            raw_response = generate_reading(delivery["user_message"], system_prompt)

            # Split reading text from audio script (audio tiers only)
            reading, audio_script = parse_reading_and_script(raw_response)

            # Voice + tier guards applied deterministically so a model slip never
            # reaches the customer: soften forbidden reader tics and, on the
            # flagship, strip any upsell paragraph.
            reading = _soften_forbidden_phrases(reading)
            reading = _strip_tier_upsell(reading, delivery["tier"])
            # Internal role words ("the client", "the querent") must never reach the
            # customer, who is addressed as "you". Strip any that leaked.
            reading      = _strip_role_labels(reading)

            # Close flagship readings with the outdoor observance, naming the
            # client's own drawn sign (inactive until TIERS_WITH_RITUAL is set).
            reading = _append_guided_ritual(reading, delivery["tier"], draw_result_of(delivery))

            # Contemplation in the audio is carried by breath, not by verbal "um"
            # fillers, so strip any residual ones the model still slips in.
            audio_script = _clean_audio_fillers(_strip_role_labels(audio_script))

            # Close the spoken reflection with a warm sign-off from Willow ONLY if
            # the script just stops cold. A script that already ends on a natural
            # voice-note close ("Talk soon.", "Take care.") must be left alone —
            # stacking the canned sign-off after a real goodbye produced a doubled,
            # mechanical-sounding ending.
            # Search the last stretch rather than strict endswith: real closes
            # often carry the client's name after them ("Talk soon, Cleo."),
            # which endswith() missed — re-stacking the sign-off anyway.
            _tail = (audio_script or "").strip().lower()[-70:]
            _natural_close = any(c in _tail for c in (
                "willow", "talk soon", "speak soon", "take care", "bye for now",
                "see you soon", "until then", "be well", "goodnight", "good night",
            ))
            if audio_script and not _natural_close:
                audio_script = audio_script.rstrip() + "\n\nFrom the edge of the woods. Willow."

            # Generate audio — only for tiers in TIERS_WITH_AUDIO (none at launch)
            audio_bytes    = None
            audio_filename = "willow_reflection.mp3"
            if delivery["tier"] in TIERS_WITH_AUDIO and audio_script:
                print(f"  Audio script: {len(audio_script.split())} words — generating MP3…")
                audio_bytes = generate_audio(audio_script)
            elif delivery["tier"] in TIERS_WITH_AUDIO and not audio_script:
                print(f"  WARNING: No audio script found in Claude response for {delivery['tier']}")

            # A paid audio tier that ends up with no MP3 (ElevenLabs failed after
            # retries, or the model produced no script) would otherwise ship silently
            # without a promised deliverable. Deliver the reading anyway so the
            # customer is not blocked, but alert the owner to make and send the audio.
            if delivery["tier"] in TIERS_WITH_AUDIO and not audio_bytes:
                print(f"  WARNING: {delivery['tier']} audio missing — delivering reading, alerting owner")
                try:
                    send_email(
                        OWNER_ALERT_EMAIL,
                        f"[ACTION NEEDED] Audio missing — {delivery['customer_name']} ({delivery['tier']})",
                        AUDIO_FAILED_ALERT.format(
                            tier=delivery["tier"],
                            customer_name=delivery["customer_name"],
                            customer_email=delivery["customer_email"],
                            order_num=delivery.get("order_number", ""),
                            had_script="yes" if audio_script else "no (model produced none)",
                        ),
                    )
                except Exception as e:
                    print(f"  ERROR sending audio-failure alert: {e}")

            # Generate the keepsake record: the cast (rune tiers) or the land.
            img_bytes = None
            img_filename = "your_record.jpg"
            tier_gets_image = delivery["tier"] in TIERS_WITH_SPREAD_IMAGE
            if SPREAD_IMAGE_AVAILABLE and tier_gets_image and draw_result_of(delivery):
                try:
                    img_bytes = generate_record_image(
                        draw_result=draw_result_of(delivery),
                        reading_type=delivery["reading_type"],
                        client_name=delivery["customer_name"],
                        tier=delivery["tier"],
                        reading_date=(delivery.get("scheduled_for") or "")[:10],
                    )
                    safe_name = delivery["customer_name"].lower().replace(" ", "_")
                    kind = "cast" if delivery["tier"] in RUNE_TIERS else "land"
                    img_filename = f"record_of_the_{kind}_{safe_name}.jpg"
                    print(f"  Record image: {len(img_bytes):,} bytes")
                except Exception as img_err:
                    print(f"  WARNING: record image failed: {img_err}")
            elif not tier_gets_image:
                print(f"  {delivery['tier']} tier — text-only delivery (no record image)")

            # (Sworn & Sealed's natal keepsakes and Grand Ceremony photo dispatch
            #  have no Moss & Marrow counterpart and were removed. Every tier
            #  sends directly to the customer.)
            if delivery["tier"] == "The Turning Year":
                _turn   = int(delivery.get("turn_number") or 1)
                subject = f"The Turning Year, Reading {_turn} of {TURNING_YEAR_DROPS}"
            else:
                subject = f"Your Moss & Marrow Reading: {delivery['tier']}"
            send_email(
                delivery["customer_email"],
                subject,
                reading + _candle_ps(),
                image_bytes=img_bytes,
                image_filename=img_filename,
                audio_bytes=audio_bytes,
                audio_filename=audio_filename,
            )
            delivery["status"]  = "sent"
            delivery["sent_at"] = now.isoformat()
            # Persist the finished audio script (what Willow actually "said",
            # after cleaning + sign-off) for QC: the MP3 is not human-readable,
            # so this is the only way to review the spoken words. Small text;
            # only stored when the tier produced audio.
            if audio_script:
                delivery["audio_script"] = audio_script
            sent += 1
            extras = []
            if img_bytes:   extras.append("record image")
            if audio_bytes: extras.append("audio")
            print(f"  Sent to {delivery['customer_email']} ({', '.join(extras) or 'text only'})")
            # Close the Etsy loop: mark the receipt shipped so the buyer sees
            # the order completed the moment the reading lands. Real orders
            # only — TEST- codes have no Etsy receipt. A Turning Year order is
            # one receipt covering eight drops, so it ships on the first turn.
            if not delivery.get("test") and int(delivery.get("turn_number") or 1) == 1:
                mark_receipt_shipped(access_token, delivery.get("order_number", ""))

            # The Turning Year: queue the next seasonal drop for the coming
            # sabbat, until all eight turns have been delivered.
            if delivery["tier"] == "The Turning Year" and not delivery.get("test"):
                _queue_next_turning_year_drop(state, delivery)

        except Exception as e:
            print(f"  ERROR for {delivery['customer_name']}: {e}")
            delivery["status"] = "error"
            delivery["error"]  = str(e)

        # Persist after every delivery attempt so a crash later in the run can
        # never resend a reading that already went out (or lose an error mark).
        save_state(state)

    # Prune sent/error entries older than 30 days
    state["pending_deliveries"] = [
        d for d in state["pending_deliveries"]
        if d["status"] == "pending"
        or (
            d["status"] == "sent"
            and d.get("sent_at")
            and datetime.fromisoformat(d["sent_at"]).replace(tzinfo=tz) > cutoff
        )
        or (d["status"] == "error")   # keep errors for inspection
    ]

    return sent


# ─── ENTRY POINT ────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"Moss & Marrow Order Processor")
    print(f"Local time: {now_local().strftime('%A %d %b %Y %H:%M %Z')}")
    print(f"Working hours: {'YES' if is_working_hours() else 'NO'}")
    print(f"{'='*60}\n")

    # Load system prompt from file in repo
    system_prompt_path = "moss-marrow-system-prompt.txt"
    if os.path.exists(system_prompt_path):
        with open(system_prompt_path, encoding="utf-8") as f:
            system_prompt = f.read()
        print(f"System prompt loaded ({len(system_prompt):,} chars)")
    else:
        system_prompt = os.environ.get("SYSTEM_PROMPT", "")
        print("WARNING: moss-marrow-system-prompt.txt not found — using SYSTEM_PROMPT env var")

    state = load_state()

    # Refresh Etsy token (stores new refresh token in state)
    access_token, state = get_etsy_access_token(state)
    # Etsy rotates the refresh token on every use, so persist it immediately:
    # if a later step crashes, the always-run commit step still saves the new
    # token instead of stranding all future runs on a dead one.
    save_state(state)

    # Etsy verification unavailable this cycle: real orders will be held (never
    # delivered unverified). Alert the owner, throttled, so held orders don't pile
    # up silently. Re-arm the alert once verification recovers.
    if access_token is None:
        print("  WARNING: Etsy verification unavailable — real orders will be held this run")
        _alert_etsy_verification_down(state)
    else:
        state.pop("etsy_down_alerted_at", None)

    # 1. Always ingest new submissions (even outside working hours — queues them)
    print("\n── Checking Google Sheet for new orders ──")
    new = ingest_new_submissions(state, access_token)
    print(f"  New orders queued: {new}")
    pending = sum(1 for d in state["pending_deliveries"] if d["status"] == "pending")
    print(f"  Total in queue:    {pending}")

    # 2. Deliver during working hours only
    print("\n── Processing delivery queue ──")
    sent = deliver_pending(state, system_prompt, access_token)
    print(f"  Readings sent this run: {sent}")

    save_state(state)
    print("\nDone.\n")


if __name__ == "__main__":
    main()
