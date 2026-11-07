# H.S. Traders Office 1.7.0

Android package `com.hstraders.office`, versionCode `13`.

## New reports

- **Copy account:** select an account, optionally filter by group, and generate its
  Account Ledger PDF. Dates default to the current financial year through today
  and support a custom range. BUSY uses STANDARD, Single Account (Auto), Name,
  opening balance included, chronological order enabled and the eight other
  detail flags disabled, matching the supplied settings.
- **Group closing balances:** choose a named account group and a current-year
  report date. View and search each account's debit or credit closing balance,
  see reconciled totals, and open an individual Copy account from a row.
- Open, download, share or send the report to your registered WhatsApp number.
  PDF names include the account or group name. Open PDF retains Google Drive
  preference and falls back to another installed PDF viewer.

Find both under **Copy account & balances** in the hamburger menu or home shortcut.
All approved mobile users can request reports. The office's existing five-second
warning allows a person working in BUSY to cancel before automation starts.
Requests share the existing BUSY desktop lock and run only after confirmation;
no report scheduler is added.

The office catalogue contains 1,201 accounts and 31 named groups, including
non-trade accounts. Only account names and group membership are imported. The
existing statement-party catalogue remains compatible.

Group balances are read from a temporary BUSY Excel export and reconciled against
its totals. The app and generated PDF use the same verified rows. Excel files are
deleted even on parsing failure. Reports remain available for 48 hours under the
existing cleanup policy; failed output is removed. All processing uses report
exports and the dashboard's own database, with no BUSY database access.

## Verification

- All 250 backend tests and 40 mobile tests passed; TypeScript, Ruff and mypy passed.
- The actual BUSY group Excel reference parsed 15 accounts and reconciled exactly.
  The actual two-page Account Ledger PDF passed exact account-name and ordered
  date verification. Tests also reject mismatched subjects, dates and totals.
- Synthetic multipage group PDFs were rendered and inspected for headers, wrapped
  names, totals and page breaks.
- Both updated services started successfully; report routes require authentication.
- Signed APK v2 verification passed. Version 1.7.0, versionCode 13 and ARM64/ARMv7
  support were checked. All 18 bundled app source files match the source tree.
- Installed over the existing app on the paired phone and confirmed cold startup.

The new BUSY navigation was checked against supplied settings and reference
exports with automated regression tests. A fresh end-to-end export from the phone
still needs the owner's confirmation.

APK size: 35,634,491 bytes.

SHA-256: `36b3310c68ab02903f65d2036225d20900f2e35ec769f36a099cdbb860571517`.
