# H.S. Traders Office 1.5.0

Android package `com.hstraders.office`, versionCode `9`. Install over the existing app.

## Android home-screen widgets

- **Office tasks** shows upcoming open tasks, their due dates, the open/overdue
  counts and the last refresh time. Choose My tasks or All tasks. Enlarge the widget
  to show up to three tasks; tap to open the matching task filter in the app.
- **Party outstanding** shows the chosen party's latest saved pending amount and
  statement date. Tap to view/download/share the available statement. When no
  statement is available, it opens that party's create-statement screen.
- Both widgets have rounded panels/buttons and resize with the launcher. They are
  home-screen widgets, not lock-screen widgets. The current app icon is preserved.
- Add the task widget from Shared tasks. Choose a party through Party statement,
  then tap **Use party for home widget**. Android asks before adding a new widget;
  an existing widget updates without a duplicate prompt. All party widgets on a
  phone share the chosen party.
- Manage the selected party, task filter, saved-data refresh or disabling widgets
  under **Account & connection → Home-screen widgets**. Launchers without the pin
  prompt can add them through long-press home screen → Widgets → H.S. Traders Office.
- A saved party statement also offers **New statement for this party**, keeping
  that party selected while choosing a fresh statement date.

## Saved-data updates and access

Widget refreshes only read the authenticated user's profile, tasks and saved-report
history. They never generate a BUSY report, update Pouncha, send WhatsApp messages
or complete tasks automatically. Fresh reports still require a request in the app
and retain the office's five-second BUSY warning.

Updates run while using the app and, when widgets are enabled, on Android's best
effort background schedule (15 minutes or longer). Tailscale and the office gateway
must be reachable. Offline reads preserve timestamped saved data. The statement's
own as-of date is always shown; an old statement is not presented as a fresh balance.

The snapshot is bounded by session expiry or 24 hours without refresh. Individual
statements also retain their 48-hour availability limit. Android can delay repainting
until the next widget update. Logout, expired access and observed revocation clear
the widgets. The snapshot contains no credentials, phone numbers or PDFs and stays
in the app's private no-backup directory. Task notifications remain independent.

## Validation

- 30 mobile regression tests passed, including read-only background requests, task
  filtering, party/report selection, expiry, offline reads, session-switch races,
  refresh coalescing and avoiding duplicate widget prompts.
- Six Android framework tests use native graphics to inflate real RemoteViews,
  check resizing, tap-to-open, minimum-size layout with a long party name, report
  expiry and clearing/restoring both existing widgets.
- Synthetic native-rendered task and party previews were visually checked. No
  business data or phone session was used in these previews.
- TypeScript, Android lint and the signed release build passed. The previous
  WorkManager startup constructor rules remain enabled.
- No USB phone was detected during this update. Real launcher pinning, device-specific
  sizing and a cold start of this APK still need confirmation on an actual phone.
- No backend changes or live BUSY/WhatsApp operations were required for this update.

APK SHA-256: `471c0e905f1d76c5e984ec04b9e2502a09f50ff69fbf7d06037d2235a6aa036a`.
APK size: 35,492,519 bytes; v2 signature, version and ARM64/ARMv7 verified.
Both widget receivers and the app deep-link scheme were checked in the final APK;
the widget and WorkManager reflective constructors are retained in the R8 output.
