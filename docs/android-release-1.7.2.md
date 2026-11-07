# H.S. Traders Office 1.7.2

Android package `com.hstraders.office`, versionCode `15`.

Replaced the old Android alert boxes throughout the app with branded bottom
sheets: white surfaces, rounded corners, navy full-width buttons and clear
red styling for destructive actions. This includes task completion, cancellation,
discarding edits, report and sending confirmations, connection checks and saved
PDF acknowledgements.

The home-screen task widget also uses a rounded light confirmation sheet. Its
completion action still checks the selected task version and explains how a
repeating task behaves.

Back or tapping outside cancels safely. Double taps cannot repeat an action.
Sheets support long content, accessibility headings, safe-area spacing and
reduced-motion preferences. Existing report exports, PDF sharing and task rules
retain their behaviour.

The owner confirmed that both Copy account and group balances work in 1.7.1.

## Verification

- TypeScript and all 43 mobile tests pass, including safe dismissal and action
  selection checks.
- All 14 native widget tests pass, including single completion, safe cancellation
  and repeating-task explanations in the new sheet.
- Android release build and APK v2 signature verification pass. All 21 bundled app
  source files match the source tree.
- Installed on the paired phone as an update, version 1.7.2 / code 15. The app stays
  running without startup exceptions.

APK size: 35,641,051 bytes.

SHA-256: `8c80982bbc73bfbe6e377aa377882fbfb337cbe2b39d95946430b35b610ad6f1`.
