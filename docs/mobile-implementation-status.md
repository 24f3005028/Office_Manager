# Mobile delivery status — 5 November 2026

## Implemented

- Expo Android app, locally signed release APK at `output/android/HS-Traders-Office.apk`.
- One-time 15-minute invites, OS secure token storage, 30-day sessions, individual revocation and all-party access for approved users.
- Loopback-only office administration under Settings → Manage mobile access. The separate mobile gateway does not mount office settings, filesystem pickers or WhatsApp administration.
- Imported 898 trade-account names from the supplied BUSY account-list workbook. Tax IDs, addresses, balances and other columns are not stored by the mobile catalogue.
- Statement request/status/history/download, historical status date, fixed start 16 January 2025, pending total display and own-number WhatsApp delivery.
- Shared BUSY desktop lock, native five-second warning before mobile desktop work, office cancellation and interrupted-job recovery. No scheduler or automatic report generation.
- Exact saved-invoice search across 2024-25, 2025-26 and 2026-27, preserving full voucher series. Supports legacy `HST/187/24-25` and current `HST/26-27/74` formats. Identical copies are deduplicated; conflicting copies are blocked for office review.
- PDF opening, Android folder download, phone sharing and own-number WhatsApp sending. A lost send response is held for review; only confirmed not-started sends may be retried.
- Private Tailscale HTTPS Serve to port 8002. No Funnel or public dashboard/bridge exposure. The installer endpoint permits initial installation within the private network without an app session; billing routes still require authentication.

## Verification

- Complete backend suite: 185 passed, including the installer endpoint and 15 mobile tests.
- Strict mypy and Ruff passed; frontend TypeScript, ESLint and production build passed.
- Android TypeScript and Metro/Hermes bundle passed; native ARM64/ARMv7 release build succeeded. Final APK signing and package metadata checked with Android SDK tools. The office HTTPS address is prefilled; signing credentials and the keystore are absent from the APK.
- Mobile dependency audit clear after overriding the two moderate build-tool dependency advisories.
- Live private HTTPS health passed. Unauthenticated parties returned 401; office settings and mobile administration returned 404 through the private mobile endpoint.
- The private installer URL returned the correct Android package MIME type and HTTP range support. The installer is available before pairing, while billing data still requires an app session.
- Actual saved-bill lookup returned both `HST/26-27/74` and `HST/L/26-27/74`; legacy-year catalogue and bill lookup also checked locally.
- No actual WhatsApp message was sent by these checks. No BUSY accounting database was accessed.

## Still required

Fresh BUSY PDF export needs a successful live calibration run. The initial favourite-based navigation failed safely before setting any report fields. It was replaced with the existing verified Account Ledger navigation and its Ctrl+R Receivable shortcut. Automatic approval review blocked the retest after the desktop tool reported a physical Escape stop, so the replacement must not be described as verified. The office warning's timeout was exercised locally; cancellation and report ordering are covered by tests with fake exporters.

A real Android phone installation, cellular-network request and actual own-number WhatsApp delivery remain hands-on acceptance checks. Create an invite from the office page first. Keep the app-signing keystore and its credentials in the ignored `data/android-build` directory backed up privately for future updates.
