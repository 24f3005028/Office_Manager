# H.S. Traders Android app

Expo / React Native / TypeScript. The app connects only to an HTTPS mobile gateway.

## Included

- One-time invite enrollment, secure token storage, logout and owner revocation.
- Searchable parties; fresh outstanding statements with status date and pending total.
- Saved invoice lookup by financial year and exact short/full bill number, including multiple series.
- PDF opening through Android's print preview, saving to a chosen folder, native sharing and sending to the user's owner-approved WhatsApp number.
- Report history, office cancellation and honest unavailable/expired-file states.

## Office setup

1. Start `Start-Office.cmd`. It starts the mobile-only gateway on `127.0.0.1:8002` alongside the existing services. It does not generate reports at startup.
2. Open Settings → Manage mobile access in the dashboard. Import BUSY's List of Accounts Excel export when the party list changes. Only debtor and creditor names are stored.
3. Install/sign in to Tailscale on the office PC and approved phones. Confirm plan eligibility and limits with Tailscale; this repository does not start a paid subscription.
4. Run `scripts/Enable-MobileAccess.ps1` after approving the private remote endpoint. It proxies only port 8002 using private Tailscale Serve, never public Funnel. Do not proxy ports 8000, 3000 or 3001. Remove broad tailnet policies and allow only approved users/devices to the office HTTPS port.
5. Create a personal invite with name and international WhatsApp number. It expires in 15 minutes and works once. Enter the private office HTTPS address and invite in the Android app. Sessions expire after 30 days; the owner can revoke sooner.

The phone can download the APK from the private office address followed by `/install/android.apk` while connected to Tailscale. The release build prefills the office address from the signed-in Tailscale client. Initial APK installation does not require an app session; party lists, reports and invoice PDFs do.

The office PC must stay unlocked and BUSY logged into H.S. TRADERS for fresh reports. Each such request shows a five-second native warning; cancel/close/Escape/Enter prevents the request from touching BUSY. Ignoring it permits the request after five seconds. A shared cross-process lock excludes Pouncha automation. Archived invoice reads never operate BUSY. A user may have one active report request at a time.

Generated reports are available for 48 hours. Invoice search indexes existing authorised bill folders and configured `MOBILE_ARCHIVE_ROOTS`; unreadable/unidentified PDFs are omitted, conflicting versions are blocked. No BUSY database files are read. Statements live outside invoice-scanning folders.

## Build locally on Windows

Install dependencies with `bun install`. The release build uses official Google SDK tools and Microsoft's OpenJDK under the ignored `data/android-build` folder. Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Build-Android.ps1` from the repository root. The script checks TypeScript, regenerates the native Android project, applies private release signing and builds ARM phone APKs.

Output: `output/android/HS-Traders-Office.apk`. The private signing key and its credentials stay under `data/android-build/`; preserve them securely for future app updates. They must never be committed. `mobile/android` is generated and ignored. An optional `eas.json` is provided for a future cloud build, but the initial build is local.

The ignored `.g/` directory holds the Gradle cache at a short path for Windows native builds. For a JavaScript-only update with an already generated native project, `scripts/Build-Android.ps1 -SkipPrebuild` avoids regenerating native project files. Use a full build after changing native dependencies or Expo app configuration.

Validation commands: `bun run typecheck`, `bun run export`; backend tests in `backend/tests/test_mobile_api.py` and `test_mobile_foundations.py`.

## Current verification limits

Native BUSY report navigation/PDF save must pass `backend/scripts/verify_mobile_report.py` on the office desktop before fresh-report generation can be considered verified. Mock API tests do not substitute for this check. Real phone cellular-network access and a real WhatsApp delivery require the owner's account/device setup. No actual WhatsApp message is sent by tests.
