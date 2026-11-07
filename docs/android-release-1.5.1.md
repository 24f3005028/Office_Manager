# H.S. Traders Office 1.5.1

Android package `com.hstraders.office`, versionCode `10`. Update over the existing app.

## Widgets without data setup

- **Party statement search** is a rounded, one-row **Search party…** bar. It opens
  party search with the keyboard ready. No fixed party or widget configuration is needed.
- Select any party to open its latest available saved statement with a primary
  **Share PDF** button. Android's sharing menu lets you select WhatsApp or another app.
  The statement's as-of date remains visible. An expired or unavailable report opens
  the create-statement flow instead; an already running request is reused.
- **Office tasks** automatically reads all open office tasks after the normal app
  sign-in, including when no widget preferences have been saved. The enable switch
  is removed. My tasks remains an optional filter, not a setup requirement.
- Task changes trigger a fresh widget read after any older in-flight read finishes.
  Foreground use and Android's best effort background schedule also refresh data.
- Add widgets using the launcher's Widgets menu or the app's Add widget buttons.
  Android still requires its normal confirmation before adding a widget. Existing
  widgets update in place without duplicate prompts. An older large party widget
  can be resized to one row with the launcher's resize handles.
- Old fixed-party and enable/disable preferences are migrated automatically. The
  search bar displays no cached party name or balance and needs no background data.

## Manual office operations and access

Background reads only use `/me` and `/tasks`; they never operate BUSY, update Pouncha,
send messages or complete tasks. A fresh statement still requires the user's request
and retains the office's five-second warning. Sharing opens the phone's share menu;
it does not automatically choose or message a recipient.

The existing office session, Tailscale connection and available office gateway are
required to read office data. Offline task reads preserve timestamped cached data.
Background updates may take 15 minutes or longer. Logout, expired access and observed
revocation clear task snapshots; snapshots contain no credentials, phone numbers or
PDFs and remain in private storage excluded from Android backups.

## Verification

- TypeScript and mobile regression tests cover automatic loading without settings,
  scope selection, migration, session expiry/revocation, offline reads, read-only
  requests, task-change races and quick-share report availability.
- Android framework tests use native graphics to check real task rendering/resizing,
  the search bar's one-row layout, tap-to-open, absence of legacy balances and expiry.
- Native-rendered search-bar preview was visually checked. Android lint and signed
  APK verification are part of the local build checks.
- The prior WorkManager startup keep rules remain enabled. No BUSY data or backend
  logic is changed by this release.

Final checks: 34 mobile tests and six native widget tests passed; TypeScript,
Android lint, release build and v2 signing verification passed.

Physical phone verification completed on 7 November 2026 over wireless debugging:

- Updated the existing app to versionCode 10 without clearing data; sign-in remained intact.
- Cold start reached React Native, stayed running and produced no fresh native crash.
- The existing Office tasks widget refreshed automatically. Its empty state matched
  the authenticated task list with All open selected, without widget configuration.
- The party shortcut opened the search field with focus and the keyboard visible.
- The owner added the search bar and confirmed it works. Android's launcher reported
  both task and party-search widget instances bound to the installed app.
- No BUSY export or WhatsApp message was triggered by these checks. Live PDF sharing
  and fresh statement generation were not exercised in this device verification.

APK SHA-256: `0a20e6495b17db48405b9c874a611381872b62f5ede09c5697bdbedb67861607`.
APK size: 35,491,172 bytes; ARM64/ARMv7 and versionCode 10 verified.
