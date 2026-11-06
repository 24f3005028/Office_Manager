# Mobile delivery status — 5 November 2026

## Implemented

- Version 1.4.0 (Android versionCode 7): hamburger drawer replaces bottom navigation. All-account outstanding requests use BUSY All Account/new1, with verified Excel parsing, searchable party/bill display and print-style PDF sharing. The supplied 95-account/280-bill report and generated 10-page PDF reconcile. The live native route still needs an app test because computer control was stopped; its settings are covered by supplied screenshots and regression tests. See `android-release-1.4.0.md`.

- Version 1.3.0 (Android versionCode 6): simpler task menus, three-step bill sending, Activity sections, retained Office/task drafts, Android Back handling, circular icon containers and native date/time pickers. Shared tasks support due dates, selected reminder recipients, daily/weekly/monthly repeats and audited completion. Phone reminders use opt-in Android local notifications plus private read-only background task refresh (15 minutes or longer; Android may delay it). BUSY and WhatsApp actions remain explicit/manual. See `mobile-workflow-and-roadmap.md` for limits and the agreed next party-page proposal.

- Version 1.2.2 (Android versionCode 5) replaces raw JSON parse failures from empty/HTML/truncated gateway responses with actionable offline messages, marks failed WhatsApp status checks unavailable, and adds an explicit connection refresh. Six client regression tests verify response handling and that uncertain writes are not automatically repeated.

- Version 1.2.1 (Android versionCode 4) adds dashboard/native Copy code buttons and remote invitation creation for the single server-configured invite manager. The designated approved account is configured in ignored local settings; its phone is not embedded in the app or committed. The capability is server-authorized, revocable, and invitation creators are audited.

- Version 1.2.0 (Android versionCode 3) adds the mobile Office tab: Pouncha preview/update, date/category document selection, saved WhatsApp recipients, opening messages, explicit send confirmation, job progress/cancellation and per-user request history. Every approved mobile user can use both tools.
- Mobile tools use fixed loopback calls to the existing office services. No dashboard settings, WhatsApp account controls, bridge API keys or generic proxy paths are exposed through the mobile gateway. Repeated request keys never queue duplicate sends/updates; lost confirmations are held for review.
- Bill download names include the bill number and required party name. Statement names use the party name. These names are also used for own-number WhatsApp attachments; original archive files are unchanged.

- Expo Android app, locally signed release APK at `output/android/HS-Traders-Office.apk`.
- Version 1.1.0 (Android versionCode 2): redesigned mobile screens, bottom navigation, supplied H.S. Traders launcher icon, separate country-code/mobile-number setup and party-named statement PDFs.
- Failed report exports are removed immediately. Completed PDFs are removed after 48 hours at startup and on ordinary report requests/history access, without a scheduler. Pouncha temporary Excel cleanup is regression-tested on success, export/parse failure and uncertain append outcomes.
- One-time 15-minute invites, OS secure token storage, 30-day sessions, individual revocation and all-party access for approved users.
- Loopback-only office administration under Settings → Manage mobile access. The separate mobile gateway does not mount office settings, filesystem pickers or WhatsApp administration.
- Imported 898 trade-account names from the supplied BUSY account-list workbook. Tax IDs, addresses, balances and other columns are not stored by the mobile catalogue.
- Statement request/status/history/download, historical status date, fixed start 16 January 2025, pending total display and own-number WhatsApp delivery.
- Shared BUSY desktop lock, native five-second warning before mobile desktop work, office cancellation and interrupted-job recovery. No scheduler or automatic report generation.
- Exact saved-invoice search across 2024-25, 2025-26 and 2026-27, preserving full voucher series. Supports legacy `HST/187/24-25` and current `HST/26-27/74` formats. Identical copies are deduplicated; conflicting copies are blocked for office review.
- PDF opening, Android folder download, phone sharing and own-number WhatsApp sending. A lost send response is held for review; only confirmed not-started sends may be retried.
- Private Tailscale HTTPS Serve to port 8002. No Funnel or public dashboard/bridge exposure. The installer endpoint permits initial installation within the private network without an app session; billing routes still require authentication.

## Verification

- Complete backend suite: 208 passed, including report navigation, Excel/PDF format switching, pairing phone checks, party-named attachments, cleanup, mobile Office authentication/ownership/idempotency, mobile Pouncha warning cancellation, designated invite-manager authorization and auditing.
- Strict mypy and Ruff passed; frontend TypeScript, ESLint and production build passed.
- Android TypeScript and Metro/Hermes bundle passed; native ARM64/ARMv7 release build succeeded. Final APK signing and package metadata checked with Android SDK tools. The office HTTPS address is prefilled; signing credentials and the keystore are absent from the APK.
- Mobile dependency audit clear after overriding the two moderate build-tool dependency advisories.
- Live private HTTPS health passed. Unauthenticated parties returned 401; office settings and mobile administration returned 404 through the private mobile endpoint.
- The private installer URL returned the correct Android package MIME type and HTTP range support. The installer is available before pairing, while billing data still requires an app session.
- Actual saved-bill lookup returned both `HST/26-27/74` and `HST/L/26-27/74`; legacy-year catalogue and bill lookup also checked locally.
- No actual WhatsApp message was sent by these checks. No BUSY accounting database was accessed.

## Still required

Native outstanding export passed a live check on 5 November 2026: homepage recovery → Alt+F → O → Enter → One Account → report options → Alt+E → PDF. RAJAN TEXTILES returned a verified one-page statement for 16 January 2025–5 November 2026. Switching back from Excel to PDF also passed. Pouncha then selected Microsoft Excel from the custom format dropdown, parsed ten bills for 4–5 November 2026 and removed its workbook; no Google Sheet writes were made by this test. The direct export's columns and Total footer are supported alongside earlier print-layout reports. No Account Ledger, Ctrl+R or Print Preview steps are used for statements. The office warning remains mandatory; cancellation and report ordering are covered by tests. Ruff and strict mypy passed.

The user has installed and connected the Android app after disabling conflicting Android Private DNS. A fresh request from the updated gateway and actual own-number WhatsApp delivery remain hands-on acceptance checks. The existing Send to my WhatsApp action sends the verified exported PDF to the signed-in user's approved phone through the bridge. Keep the app-signing keystore and its credentials in the ignored `data/android-build` directory backed up privately for future updates.
