# Pouncha sync implementation plan

Confirmed against the supplied script, two workbooks, screenshots and a read-only Google
Sheets API inspection on 5 November 2026. No BUSY navigation or live sheet writes were performed.

## Confirmed inputs

- Company: H.S. TRADERS; financial year 2026–27. BUSY 21 is expected to be running and logged in.
- Sheet ID: `1Ukd4bteeJryu8wW7hDdQVOaIwG0B6V2qLOKYu-GbcZ0`.
- Spreadsheet title: `POUNCHA 26/27`; target tab: `POUNCHA 26-27`, gid 0.
- Header row: 1. Data starts at row 2. Current last populated bill row: 1256.
- Last recorded bill: `HST/26-27/1182`, dated 31 October 2026.
- Existing service-account credentials successfully read the intended sheet using readonly
  scope. Do not log the credential contents. Read access does not independently prove write access.
- Column H holds manual remarks; 86 data rows have content beyond column G in the inspected
  snapshot. Preserve columns H onward, all existing rows, formatting and other tabs.

## Column mapping

| Google column | Existing header | Source |
|---|---|---|
| A | DATE | Sale voucher date, interpreted day first |
| B | BILL NO | Full Vch/Bill No, including series and financial year |
| C | PARTY NAME | Account on the Sale row |
| D | TRANSPORT | Labelled Transport continuation row |
| E | VEHICLE NO | Labelled Vehicle No. continuation row |
| F | STATION | Labelled Station continuation row |
| G | NARRATION | Challan/order reference such as HS-1182 or HSL-78 |

The sample converter calls G `Order No.`. In the live sheet it is `NARRATION`. Keep the live
header unchanged. A missing challan must produce an empty G value. Never use Transport,
Vehicle No., Station, E-Way Bill or another unrelated detail as a challan.

## Sample dry run

The raw AccountLedger_Sales.xlsx has its column headings on row 8. It contains 18 Sale
records dated 1–5 November 2026. None of those full voucher IDs is in the inspected sheet.
There are no duplicate voucher IDs in that sheet snapshot.

If synchronized against this unchanged snapshot, the 18 new records would occupy rows
1257–1274, writing A:G only. The export begins at HST/26-27/1183, includes HST/L/26-27/78,
and ends at HST/26-27/1199. HST/26-27/1191 has no challan; its G value remains blank.

The supplied Pouncha_Sales.xlsx has 56 records dated 22–31 October 2026. It is a format
reference, not a converted copy of the November raw sample. Do not claim a row-for-row match.
The existing converter assumes the next line is an order number and uses a fixed ten-row
detail window. Replace both assumptions with bounded voucher blocks and explicit recognition.

## User flow

Add a separate Pouncha page without changing WhatsApp sending or its bridge.

1. Read the sheet and display the latest valid bill/date.
2. Offer Continue from sheet and Custom range. Continue starts on the last recorded date,
   inclusive, to catch partially synchronized days; end defaults to today in Asia/Kolkata.
   A configurable lookback can catch older backdated bills. Custom dates are honored exactly.
3. Clicking Sync creates a persisted run and starts the export in a background thread/process.
4. Show Preparing, Exporting from BUSY, Parsing, Comparing, Appending and Verifying stages.
5. Show counts for exported, existing, appended, rejected and conflicting records, with concise
   reasons. No-op runs report that nothing new was found.
6. Include manual Excel upload as a fallback using the identical conversion/comparison path.

The normal Sync action performs the append after validation. A preview-only action supports
first-run checks and troubleshooting without altering the live sheet. No scheduler in version 1.

## BUSY export adapter

Attach only to the already-running BUSY window and verify company and financial year.
If BUSY is closed or logged out, stop with an instruction to open/log in. Do not launch
another instance or guess company-selection or authentication steps.

Reset navigation with individually observed Esc actions and a bounded attempt limit. When
the observed Close Company dialog appears, explicitly choose No, verify it dismissed, and
then open the ledger with Alt+L. Never send a blind burst of Esc keys or a default Enter
response. If an unsaved voucher, discard, overwrite or unknown dialog appears, stop without
answering it and explain what the user needs to resolve.

Use Account Ledger, STANDARD format, Sales account, selected start/end dates. Set these four
options to Y and verify them before generating the report:

- Show Vch. Long Narration
- Show Short Narration
- Show Opt. Fields/Transport Details
- Show data chronologically within date

Set all other enabled Yes/No report options to N, including Items Details and Bill References.
Do not attempt to edit disabled controls. Verify the selected account and date range in the
loaded report. Wait for actual loading completion, not only a fixed sleep.

Open Export, choose Microsoft Excel and a unique app-owned temporary filename. Keep
"For blank columns copy previous non-blank value" at Not Reqd.; filling down would break
voucher-boundary detection. Leave the password empty. BUSY may append .xlsx, so observe the
actual output path rather than guessing. Answer No to Open File Now. Never open Excel.

Wait until the output exists, its size is stable, and it can be opened as a valid workbook.
Record the run's own path. Clean up only the run's own temporary file; never delete the
user's supplied reference exports. Do not read or write any BUSY database or installation data.

Before enabling the adapter, inspect the actual Windows controls and test one export without
writing to Sheets. Prefer control identifiers and keyboard navigation; any coordinate fallback
must validate the current window/layout and stop when it does not match.

## Parser and comparison

Discover the Date/Type/Vch-Bill-No/Account header row instead of assuming a fixed row number.
Every Sale row starts a voucher block. Stop at the next main transaction or totals/footer.
Extract continuation fields by label, splitting once at the field separator and preserving
meaningful spaces and punctuation. Ignore numeric zero columns. Recognize challans by explicit
Order/Challan labels or known HS/HSL reference shapes; do not infer a challan from the bill ID.
Keep empty optional fields empty. Flag ambiguous or conflicting challan candidates.

Validate required date, full voucher number and party. Reject unsupported report layouts,
wrong company/account, out-of-range dates and conflicting duplicate exports before writing.
Use date-first ordering and natural series/serial ordering within dates; HST and HST/L remain
distinct. Voucher financial year is part of the identity. Normalize whitespace and casing only
for comparison, retaining original display values.

Read all existing bill IDs, not just the final bill number. Accept the sheet's existing
DD-MM-YYYY and DD/MM/YYYY date strings. Existing bills are skipped; changed details are
reported without updating the old row. Cancelled/deleted bills are never automatically removed.

## Sheets writes and recovery

Serialize sync runs and refresh the sheet immediately before append. Validate the A:G headers
and target tab. Append only A:G using literal input values, retaining identifier strings and
empty fields. Do not rewrite the sheet, insert a new header, sort existing rows or clear ranges.
Ensure row expansion and formatting changes, if needed, are confined to new rows and preserve
other columns. Confirm behavior on a disposable test sheet before the first live append.

Persist intended voucher IDs and run progress before the remote write. Inspect the returned
range, read back the appended values, and only then mark the run verified. If a response is
lost, re-read sheet IDs and values before considering another append. Ambiguous/conflicting
outcomes require review; never blindly resend the whole batch. The app lock does not lock
other human or third-party editors, so concurrent changes must be detected and reported.

## Implementation and acceptance order

1. Standalone parser with synthetic tests and the supplied November export as a reference.
   Verify 18 records, both voucher series, and blank challan for HST/26-27/1191. Add tests for
   missing/reordered details, >10 detail rows, header movement, footer exclusion and day-first dates.
2. Comparison, run persistence and read-only preview against the live sheet. Test duplicates,
   changed existing records, empty sheets with valid headers and invalid dates/layouts.
3. Sheets append/read-back using a disposable target. Test a lost response, a retry, a failed
   verification, concurrent modification and preservation of H remarks/formulas/formatting.
4. Calibrate BUSY control navigation and one temporary export. Verify Close Company=No,
   Open File Now=No, the four Y settings, dates/account and stop behavior for unsafe dialogs.
5. Connect the frontend date-range/Sync controls and upload fallback. Update the desktop
   launcher only as required to pick up this backend/frontend code; keep the WhatsApp bridge
   unchanged. Run existing WhatsApp regression checks before delivery.

All current inspection work is read-only with respect to the user's workbooks, live sheet,
reference converter script and BUSY application. Scratch reports live in ignored data/ files.
