# Android outstanding bills app — proposed implementation

Status: implementation in progress. Backend account/token/job storage, exact invoice-header parsing, native report verification and a five-second Windows warning are scaffolded. The mobile API and Android app are not yet connected. BUSY native export still requires live calibration; do not treat this feature as production-ready. Android first, for the owner and selected employees. Fresh reports depend on the office PC staying powered on, online, unlocked, with H.S. TRADERS logged into BUSY. All generation is explicitly requested; no scheduler.

## Product flow

The home screen has two large actions: Outstanding bills and Find a bill.

Outstanding bills: Sign in → Search and select party → Get latest statement → View PDF → Download PDF or Send to my WhatsApp.

Default the status date to today in Asia/Kolkata. Put historical dates under More options. Show selected party, status date, generation time and outstanding total clearly. Show queued, generating, ready and actionable failure states. Previously generated reports must carry their actual generation time; never present a cached report as newly refreshed.

Use Expo / React Native / TypeScript, producing a signed Android APK for private installation. This matches the dashboard's language and leaves an iOS path available. Kotlin is unnecessary for this workflow because desktop BUSY automation remains on Windows.

## Report settings from supplied screenshots

Open Bills Receivable through Outstanding Analysis or the configured favourite, then One Account. STANDARD format, exact party account, Pending entries, account displayed by Name, minimum age 0 days, due-day basis D. Show On Account Amount & Ledger Balance = Yes; salesman filter and all other shown detail toggles = No.

Confirmed start date: 16 January 2025, before the current financial year. Do not limit outstanding reports to the current year. Ending date and Bills Status as on default to the requested date. Preserve partial payments and tiny residual balances, including the example's ₹1. Keep reference amount, pending amount, on-account amount and ledger balance distinct.

Use the existing native PDF layout: Print → As it is From Grid → S.No., Dated, Ref. No., Ref. Amt., Pending Amt., Due Days → portrait → Preview → Save document to PDF. Type, Due and Due Date columns are excluded. During calibration, test whether direct PDF export produces the identical layout; otherwise use the demonstrated preview/save route.

## Office integration

Before each mobile report operates BUSY, show a topmost office dialog for five seconds. The person at the computer can cancel the request if using BUSY, or continue immediately. No response means continue after five seconds. Escape, Enter and closing the warning cancel. A failure to display the warning blocks automation. This is an on-demand request delay, not a scheduler. Archived invoice retrieval never shows this warning because it does not operate BUSY.

Add an outstanding-report adapter to the existing backend. A single shared desktop queue/lock must cover both this adapter and Pouncha automation. Only one task may control BUSY at a time. Recognise company/account/report screens, recover through bounded Escape navigation, decline the Close Company prompt, and stop safely on unsaved work or unsupported dialogs. Do not write vouchers, adjustments or balances, and never access BUSY database files directly.

Save every output to a unique application-owned report directory. Verify the file is a valid non-empty PDF and that party, dates and report identity match the request before exposing it. Validate totals against BUSY on representative reports. Store report ownership, company, party, requested dates, settings, generation time and file hash. Keep statements outside folders scanned by the existing invoice sender.

Build the searchable party catalogue from an authorised BUSY account-list Excel export, using a stable account code where available. Confirm exact account names and company/year. Do not infer parties from WhatsApp contacts or invoice filenames. Initially, let the owner explicitly refresh this catalogue.

## Remote access and permissions

Start with a private Tailscale connection on the office PC and approved phones, with HTTPS via Tailscale Serve. It requires a one-time phone setup and an active VPN connection. Expose only a dedicated authenticated mobile API; keep the existing dashboard API, WhatsApp bridge, local settings and filesystem picker private to the office computer. Do not expose the entire current backend through a reverse proxy.

Use individual accounts, owner-approved enrollment, revocable sessions and server-enforced party permissions. Confirmed access: the owner and every approved employee can access all parties and their bill PDFs. Only the owner manages enrollment, revocation, configuration and source folders. All-party access does not permit anonymous access or arbitrary local file access. Store tokens in OS secure storage. Authorise every job, file download and delivery request, including history. Revoking access cannot revoke PDFs already saved to a phone.

Proposed endpoints: current user, party search, create report with idempotency key, job status, authenticated PDF download, send report to current user's registered WhatsApp number, and authorised history. Never accept arbitrary local file paths or recipient numbers from the mobile client.

## WhatsApp delivery

“Send to my WhatsApp” means the signed-in person's approved number, including employees. Reuse the existing bridge through a dedicated statement-delivery path, supporting the linked account's own chat where applicable. Do not add statements to normal invoice folders or reuse contact-picker assumptions that exclude the sending account. Confirm the number in the UI before sending. Keep delivery IDs and receipts; uncertain delivery must require review instead of automatic resend. Offer the phone's native Share action as an explicit alternative.

## Individual bill PDF lookup — added scope

Find a bill → Financial year (default 2026-27 initially) → Enter bill number → Find bill → Check party/full bill number → Open, Download or Send to my WhatsApp.

Use an admin-configured current/latest available financial year as the default; do not invent availability from the phone clock. List supported years with configured, indexed invoice archives, using the Indian April-to-March financial year. Expose all saved sales invoices, whether paid or unpaid; this lookup is independent of the outstanding report.

Accept a short number such as 74 or a full voucher number such as HST/L/26-27/74. Match the exact numeric bill identifier within the selected year; do not use substring matching (74 must not match 174). Preserve series and full voucher numbers. If both HST/26-27/74 and HST/L/26-27/74 exist, show both with party, date and full number so the user chooses. Reject a full voucher number whose embedded year conflicts with the selected year, with a clear correction prompt. Never silently choose a series or the first file.

Prefer the existing saved invoice PDFs already used by the WhatsApp bill sender. Add an invoice catalogue keyed by company, financial year, voucher series and full bill number, retaining authorised file IDs, party, date, source and modification/hash information. Filename parsing may propose a candidate, but confirm the invoice identity from PDF contents or an existing verified ledger mapping; unreadable or conflicting identities require review. Do not treat the current date-only PDF scanner as an existing bill-number search index. Deduplicate identical copies by content; conflicting versions must be clearly resolved before delivery.

Return existing PDFs directly without controlling BUSY, so archived bill lookup can work while BUSY automation is occupied. Office connectivity is still required to retrieve an uncached office file. If a PDF is absent, show Bill PDF not available; do not claim that any missing invoice can already be generated. A later explicit Generate from BUSY action can be added after separately calibrating sales-voucher lookup and printing, using the same desktop queue. No database access.

Add authenticated invoice search and file/download/send endpoints. Resolve every file server-side inside approved invoice roots, retaining existing path confinement and BUSY/system-directory exclusions. Never accept a caller-provided path. Use the same approved-user access and WhatsApp delivery safeguards as statements. Test overlapping numbers across years/series, leading zeros, full numbers, missing files, duplicate copies, conflicting versions and changed or unreadable PDFs.

## Received reference PDF

E:/File.pdf is a readable, single-page native Bills Receivable report for INDERJIT FABRICS, from 16 January 2025 through 5 November 2026, status as of 5 November 2026. It includes three invoices, including HST/L/26-27/74 and HST/26-27/1138, confirming multiple bill series. Reference and pending totals both equal INR 1,003,573.00; on-account amount is zero and ledger balance equals that pending total. The rendered portrait layout matches the requested six-column report. Keep this as a calibration reference; do not hardcode this party, these bills or amounts.

## Implementation sequence and acceptance

1. Sample PDF received and inspected: E:/File.pdf. Earliest report date and all-party employee access confirmed. Obtain the BUSY account-list Excel export and calibrate navigation/export locally. Confirm invoice archive coverage for each offered financial year.
2. Implement the desktop adapter and shared BUSY queue. Test paid, partly paid, old-year, ₹1 residual, zero outstanding, on-account credits and multi-page cases against native reports.
3. Implement mobile authentication, permission checks, report/download API and dedicated WhatsApp delivery. Test concurrent requests, retries, interruptions and cross-user access denial.
4. Build the simple Expo screens, outstanding statements, financial-year/bill-number lookup, PDF viewing/download, own-number delivery and honest offline states.
5. Configure approved private access and install signed APKs. Verify on a real Android phone over mobile data, including unavailable PC, locked desktop, BUSY in another screen, expired session and disconnected WhatsApp.

The user authorised implementation on 5 November 2026. Deliver and verify the report generator locally before remote access or APK distribution.

References: https://docs.expo.dev/build/internal-distribution/ ; https://docs.expo.dev/versions/latest/sdk/sharing/ ; https://tailscale.com/docs/features/tailscale-serve
