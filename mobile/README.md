# H.S. Traders Android app

Expo / React Native / TypeScript. The app connects only to an HTTPS mobile gateway.

## Included

- One-time invite enrollment, secure token storage, logout and owner revocation.
- Searchable parties; fresh outstanding statements with status date and pending total.
- Saved invoice lookup by financial year and exact short/full bill number, including multiple series.
- PDF opening through Android's print preview, saving to a chosen folder, native sharing and sending to the user's owner-approved WhatsApp number.
- Report history, office cancellation and honest unavailable/expired-file states.
- Version 1.1: navy/blue mobile redesign, bottom navigation and the H.S. Traders logo as the Android launcher icon.
- Separate country code (default +91) and mobile number during pairing, checked against the invite's approved number. The office invite form uses the same split.
- Outstanding PDFs use the party name for opening, downloads, sharing and WhatsApp attachments.
- Version 1.2 adds **Office**: all approved users can preview/update Pouncha and send selected saved PDFs to office WhatsApp contacts. The existing office queue performs sends with the dashboard's ordering, date labels, cancellation and uncertain-outcome handling. Mobile Pouncha exports always show the five-second office warning.
- Bill downloads use `BILL-NUMBER - PARTY NAME.pdf`; statement downloads use `PARTY NAME.pdf`. A bill whose party cannot be read must be checked by the office before mobile downloading or own-number sharing.
- Version 1.2.1 adds Copy code on the office dashboard and native clipboard copying for mobile invites. The server-designated invite manager has **Invite new users** on Home and a form under their account. New users receive ordinary access; invite-manager enrollment stays on the office dashboard.

## Office setup

1. Start `Start-Office.cmd`. It starts the mobile-only gateway on `127.0.0.1:8002` alongside the existing services. It does not generate reports at startup.
2. Open Settings → Manage mobile access in the dashboard. Import BUSY's List of Accounts Excel export when the party list changes. Only debtor and creditor names are stored.
3. Install/sign in to Tailscale on the office PC and approved phones. Confirm plan eligibility and limits with Tailscale; this repository does not start a paid subscription.
4. Run `scripts/Enable-MobileAccess.ps1` after approving the private remote endpoint. It proxies only port 8002 using private Tailscale Serve, never public Funnel. Do not proxy ports 8000, 3000 or 3001. Remove broad tailnet policies and allow only approved users/devices to the office HTTPS port.
5. Create a personal invite with name and international WhatsApp number. It expires in 15 minutes and works once. Enter the private office HTTPS address and invite in the Android app. Sessions expire after 30 days; the owner can revoke sooner.

The phone can download the APK from the private office address followed by `/install/android.apk` while connected to Tailscale. The release build prefills the office address from the signed-in Tailscale client. Initial APK installation does not require an app session; party lists, reports and invoice PDFs do.

Set `MOBILE_INVITE_ADMIN_PHONE` only in the ignored office `backend/.env` to the designated approved user's international digits-only number. Empty disables remote invitation creation. Authorization is checked against the authenticated account on every request, and the creator is audited. Raw invite codes are returned once and stored only as hashes. App invites do not grant Tailscale membership.

The office PC must stay unlocked and BUSY logged into H.S. TRADERS for fresh reports. Each such request shows a five-second native warning; cancel/close/Escape/Enter prevents the request from touching BUSY. Ignoring it permits the request after five seconds. A shared cross-process lock excludes Pouncha automation. Archived invoice reads never operate BUSY. A user may have one active report request at a time.

Generated reports are available for 48 hours, then deleted at startup or on normal report requests/history access. Failed output is deleted immediately. No cleanup scheduler is installed. Pouncha Excel exports are temporary and removed after parsing, including failed runs. Original uploads and saved invoice archives are preserved. Invoice search indexes existing authorised bill folders and configured `MOBILE_ARCHIVE_ROOTS`; unreadable/unidentified PDFs are omitted, conflicting versions are blocked. No BUSY database files are read. Statements live outside invoice-scanning folders.

## Build locally on Windows

Version 1.4.0 uses the header hamburger menu instead of bottom tabs. All accounts
outstanding shows grouped pending bills and totals; Share report offers PDF download,
native sharing and own-number WhatsApp delivery. Fresh reports use All Account/new1
and the office warning. The print-style PDF is built from the same validated export
as the app view. The company-header template is local to the office database folder.

Version 1.3.0 adds Shared tasks, selected-person reminders and a simpler navigation flow.
Each phone must enable reminders and grant notification permission under Shared tasks.
Use Test notification on the physical phone. Background refresh is read-only and takes
15 minutes or longer; Android power restrictions and force-stop can delay it. It never
starts BUSY or sends bills automatically. See `docs/mobile-workflow-and-roadmap.md` at
the repository root for task recurrence, access controls and reminder limitations.

Install dependencies with `bun install`. The release build uses official Google SDK tools and Microsoft's OpenJDK under the ignored `data/android-build` folder. Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Android.ps1` from the repository root. The script checks TypeScript, regenerates the native Android project, applies private release signing and builds ARM phone APKs.

Output: `output/android/HS-Traders-Office.apk`. The private signing key and its credentials stay under `data/android-build/`; preserve them securely for future app updates. They must never be committed. `mobile/android` is generated and ignored. An optional `eas.json` is provided for a future cloud build, but the initial build is local.

The ignored `.g/` directory holds the Gradle cache at a short path for Windows native builds. For a JavaScript-only update with an already generated native project, `scripts/Build-Android.ps1 -SkipPrebuild` avoids regenerating native project files. Use a full build after changing native dependencies or Expo app configuration.

Validation commands: `bun run typecheck`, `bun run export`; backend tests in `backend/tests/test_mobile_api.py` and `test_mobile_foundations.py`.

Release builds also need a cold-start check on an Android device: JavaScript tests
and web previews cannot detect AndroidX Startup failures. The tracked
`android-keep-rules.pro` preserves reflective Room database and WorkManager input
merger constructors under R8 full mode. `Build-Android.ps1` attaches these rules
after either prebuild or `-SkipPrebuild`, and fails if the generated ProGuard
configuration no longer matches. Keep release optimization enabled.

## Current verification limits

If the phone reports that the office is unavailable, run `Start-Office.cmd` on the office computer and use **Office → Send bills → Check office connection** (or reopen the Office tab in older versions). The private URL can return 502 while the local services are stopped. Starting Tailscale alone does not start the dashboard services. Version 1.2.2 handles empty/truncated responses without exposing JSON parsing errors and never automatically repeats unconfirmed sends or updates. Run `bun run test` for the client response-handling regression tests.

Native BUSY report navigation/PDF save must pass `backend/scripts/verify_mobile_report.py` on the office desktop before fresh-report generation can be considered verified. Mock API tests do not substitute for this check. Real phone cellular-network access and a real WhatsApp delivery require the owner's account/device setup. No actual WhatsApp message is sent by tests.
