# H.S. Traders Office 1.4.0

Android package `com.hstraders.office`, versionCode `7`. Install over the existing app.

## Navigation

The bottom bar is replaced by a rounded hamburger menu in the header. It opens Home,
Party statement, All accounts outstanding, Find a bill, Office tools, Shared tasks,
Activity and Account & connection. Existing Office/task drafts survive navigation.
Android Back closes the drawer first; tapping outside also closes it.

## All-account outstanding

- Manually request BUSY Favourites → Outstanding Bills → All Account, using format **new1**.
- Options match the supplied screenshot: no State/Salesman filters, Pending, start
  16 January 2025, requested end/status date, Name, Sort on Party Yes, older-than-days 0,
  remaining optional flags No, due-date basis D.
- The existing desktop lock and five-second office warning apply. No BUSY scheduler
  or direct database access was added. Workbook exports are temporary and deleted.
- The app groups bills by party, with account/grand totals, bill search, bill dates,
  due days, broker and discount fields. The report's as-of date is always displayed.
- Share report reveals Open PDF, Download, native Share and Send to my WhatsApp.
- The shared PDF is generated from the same verified data, matching the supplied
  print-style columns: S.No., Account, BROKER, Dated, Ref. No., Ref. Amt., Pending Amt.,
  DISCOUNT and Due Days. It includes company details, account subtotals, repeated
  headings and a grand total. Full names wrap instead of being truncated.
- The local company-header template is stored beside the office database as
  `mobile-outstanding-template.json`; it is not committed or embedded in the APK.
- All-account request history is private to the requesting user, as with party reports.
  PDFs and structured data have the existing 48-hour availability and failure cleanup.

## Validation

- The supplied Excel export was read without modifying it: 95 accounts, 280 bills,
  with every party subtotal and the grand total matching the structured app data.
- The generated PDF is 10 pages, visually checked on first/last pages with repeated
  headings and verified data/totals. The user's workbook and PDF are not published.
- 232 backend tests passed; Ruff and mypy passed (58 application source files).
- Mobile TypeScript and all 17 mobile regression tests passed.
- Phone-size synthetic preview verified drawer destinations, absence of the bottom
  bar, all-account totals, bill-number search, expanded bills and sharing controls.
- The new BUSY route/settings are checked against supplied screenshots and synthetic
  native-control tests. An end-to-end live BUSY run could not be completed because
  computer control continued reporting a stopped session after Escape. This limitation
  does not affect validation of the supplied Excel or generated print-style PDF.
- The separate mobile gateway was reloaded only after all report, sync and send queues
  were idle. Existing WhatsApp sender and Pouncha workflows are preserved.

APK SHA-256: `698a920aed43b41accdb8a87bc2a3e8df92b46c4361ad535ce8d032ca728e29c`.
APK size: 35,411,248 bytes; v2 signature and ARM64/ARMv7 verified.
