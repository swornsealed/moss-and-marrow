/**
 * Moss & Marrow — Intake Form Endpoint
 * Google Apps Script Web App
 *
 * Deploy from the mossandmarrowreadings@gmail.com account, attached to the
 * "Moss & Marrow — Intake" spreadsheet (Extensions → Apps Script):
 *   Execute as: Me
 *   Who has access: Anyone
 *
 * This script receives POST requests from the branded intake form
 * (mossandmarrowreadings.com/intake/), writes each submission as a new row
 * in the correct tab of the Google Sheet, then returns a JSON response.
 *
 * Sheet tab names must exactly match the keys in TAB_NAMES below.
 * Each tab must have this header row in row 1:
 *   timestamp | type | order_number | customer_email | customer_name |
 *   client_dob | poi_name | poi_dob | notes | processed | birth_time | birth_city
 */

// ── TAB NAMES ──────────────────────────────────────────────────────────────────
// Maps the form's `type` value to the Sheet tab name.
const TAB_NAMES = {
  love:    "love",
  career:  "career",
  clarity: "clarity",
  season:  "season",     // The Turning Year
};

// ── COLUMN ORDER ───────────────────────────────────────────────────────────────
// Must match the header row in every tab. birth_time / birth_city are kept for
// layout compatibility with the order processor; Moss & Marrow leaves them blank.
const COLUMNS = [
  "timestamp",
  "type",
  "order_number",
  "customer_email",
  "customer_name",
  "client_dob",
  "poi_name",
  "poi_dob",
  "notes",
  "processed",    // left blank on write; automation marks "yes" when processed
  "birth_time",   // unused by Moss & Marrow, kept for column-layout compatibility
  "birth_city",   // unused by Moss & Marrow, kept for column-layout compatibility
];

// ── POST HANDLER ───────────────────────────────────────────────────────────────

function doPost(e) {
  try {
    const data     = JSON.parse(e.postData.contents);
    const type     = (data.type || "love").toLowerCase().replace(/-/g, "_");
    const tabName  = TAB_NAMES[type] || "love";
    const ss       = SpreadsheetApp.getActiveSpreadsheet();
    const sheet    = ss.getSheetByName(tabName);

    if (!sheet) {
      return _json({ status: "error", message: "Tab not found: " + tabName });
    }

    // Ensure header row exists
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(COLUMNS);
    }

    // Build row in column order
    const row = [
      new Date().toISOString(),          // timestamp
      type,                              // type
      (data.order_number   || "").trim(),
      (data.customer_email || "").trim(),
      (data.customer_name  || "").trim(),
      (data.client_dob     || "").trim(),
      (data.poi_name       || "").trim(),
      (data.poi_dob        || "").trim(),
      (data.notes          || "").trim(),
      "",                                // processed — blank until automation picks it up
      (data.birth_time     || "").trim(),
      (data.birth_city     || "").trim(),
    ];

    sheet.appendRow(row);

    return _json({ status: "ok" });

  } catch (err) {
    return _json({ status: "error", message: err.toString() });
  }
}

// ── GET HANDLER (health check) ─────────────────────────────────────────────────

function doGet(e) {
  return ContentService
    .createTextOutput("Moss & Marrow intake endpoint is live.")
    .setMimeType(ContentService.MimeType.TEXT);
}

// ── SETUP HELPER ──────────────────────────────────────────────────────────────
// Run once from the Apps Script editor (Run → setupSheetHeaders) to create any
// missing tabs with correct headers. Safe to run when tabs already exist.

function setupSheetHeaders() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  Object.values(TAB_NAMES).forEach(function(tabName) {
    let sheet = ss.getSheetByName(tabName);
    if (!sheet) {
      sheet = ss.insertSheet(tabName);
    }
    // Only write headers if the sheet is empty
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(COLUMNS);
      // Style header row: deep forest green with pale leaf text
      const headerRange = sheet.getRange(1, 1, 1, COLUMNS.length);
      headerRange.setFontWeight("bold");
      headerRange.setBackground("#14301f");
      headerRange.setFontColor("#c8e2b9");
    }
  });

  SpreadsheetApp.getUi().alert("Sheet tabs created with headers.");
}

// ── HELPERS ────────────────────────────────────────────────────────────────────

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
