# Manual Pouncha sync

The implementation is deliberately manual. There is no scheduler module, background polling
for new bills, catch-up interval, automatic startup export or automatic resume. Backend startup
only initializes the local run journal and marks interrupted runs failed or needing review.

## Using the page

Open `/pouncha-sync` from the dashboard navigation or home card. The page reads the current
Google Sheet status. Choose Continue from sheet or Custom dates and BUSY or uploaded Excel.
Click **Preview only** to inspect missing bills without changing Sheets, or **Sync to Google
Sheet** to export, compare, append and verify. No synchronization starts just by visiting a page.

Continue includes the latest recorded date to avoid missing the remainder of a partially
synchronized day. For older backdated bills, select a custom range. The end date defaults to
today in Asia/Kolkata and cannot be in the future. BUSY exports are limited to the configured
financial year. An empty sheet requires a custom start date and the existing A:G header row.

The supplied credentials are loaded locally from `backend/config/google_service_account.json`
(or GOOGLE_SERVICE_ACCOUNT_FILE), never through a browser prompt. The account needs access to
the specified sheet; an append needs Editor access. Google Sheets reads/writes have bounded
timeouts. Optional settings are in `backend/.env.example`; no scheduler setting exists.

## Data handling

A:G are DATE, BILL NO, PARTY NAME, TRANSPORT, VEHICLE NO, STATION and NARRATION. Full voucher
identity retains HST versus HST/L and financial year. G holds a recognized HS/HSL challan/order
reference and stays empty when absent. Labelled transport/vehicle/station lines cannot become
a challan. The parser finds headers and transaction boundaries without a ten-row detail limit.

New records are sorted by date, series and serial. Existing bills are skipped; different
existing details are reported. Duplicate existing bill IDs, malformed headers, interrupted
bill tables and remarks-only rows stop writes. Only seven literal values are appended per
record, so formulas are not interpreted from text. H onward and all existing rows are preserved.

The app journals intended rows before a write and reads back the result. Lost/invalid responses
and failed verification become `needs_review`. Further syncs are blocked until verified or
explicitly released after manual review. Verification/release never resend data. The app lock
does not prevent simultaneous human/third-party edits, which can cause a review result.

## Desktop adapter

The adapter attaches to an existing BUSY 21 company; it does not launch BUSY or enter login
details. It uses accessible controls and validates the expected ledger and export layouts.
There are no screen coordinates. Escape navigation is bounded; Close Company is answered No.
Unsaved-work, overwrite and unknown blocking dialogs stop the export. STANDARD / Sales,
selected dates and all nine Y/N fields are read back before generating the report. Only long
narration, short narration, transport details and chronological order are Y. Export uses
Microsoft Excel, blank password and Not Reqd. for fill-down; Open File Now is answered No.

Only a unique temporary report is opened/deleted. User reference exports and BUSY database
files are never modified or opened. No input is sent to WhatsApp or its bridge by this feature.

## Validation and remaining live check

The parser was checked against the supplied original export: 18 bills, HST/L retained,
HST/26-27/1191 with blank challan. Automated tests cover manual-only behavior, remarks
preservation, duplicate prevention, wrong exports, uncertain writes, read-back, and restart
recovery. The API/Sheets writer are tested with fake adapters; no live sheet append was tested.

The initial desktop adapter incorrectly treated a disabled company owner as an unknown
dialog. BUSY's VB6 report forms disable their owners while keeping the current owned form
enabled. The adapter now resolves the unique enabled visible form, including UIA-owned
windows omitted by Desktop.windows(), and scopes fields/buttons to that active form. Offscreen
VB6 helper textboxes are excluded. Navigation tries up to 15 individual Escape presses through
other BUSY screens. Close Company is answered No, including when the final Escape opens it.
If the homepage is not reached, Alt+L is attempted once directly. The expected ledger fields
must appear before any dates/options are entered. Known unsaved-work and destructive
confirmations still stop input immediately; they are never dismissed by this fallback.

A live local-only test successfully backed out through Print/report screens, chose No at
Close Company, opened the Sales ledger, set the dates/options, and exported Microsoft Excel.
The native export caption is Export Data; both this caption and Export Report Data are accepted.
The 31 October–4 November 2026 export parsed 26 bills, all within the requested dates. The
temporary workbook was removed after parsing. No live Google Sheet append was performed.

## API

- GET `/api/pouncha-sync/status`: read sheet metadata and recent manual runs.
- POST `/api/pouncha-sync/run`: queue an explicitly requested BUSY export.
- POST `/api/pouncha-sync/upload`: queue conversion of an uploaded original .xlsx ledger.
- GET `/api/pouncha-sync/runs/{id}`: read progress/results.
- POST `/api/pouncha-sync/runs/{id}/verify`: read-only reconciliation of an uncertain write.
- POST `/api/pouncha-sync/runs/{id}/release`: explicitly acknowledge review without resending.

Run requests contain `end_date`, optional `start_date` (omitted for Continue), and
`preview_only`. Upload requests use the same fields as multipart form data. Only POST run/upload
requests enqueue synchronization. Browser origins outside the configured frontend allow-list
are rejected. Run payloads are stored in `pouncha_manual_runs`, separate from the old scheduler
history and WhatsApp send queue.
