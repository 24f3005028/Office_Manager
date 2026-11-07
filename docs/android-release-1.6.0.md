# H.S. Traders Office 1.6.0

Android package `com.hstraders.office`, versionCode `11`.
Install this APK over the existing app to retain sign-in and home-screen widgets.

## Interactive office tasks

- Tap a task's circular checkbox on the widget and confirm **Mark done** above the
  home screen. Repeating tasks keep their next occurrence open.
- Use **Add task**, **Open tasks** or **Refresh** directly from the widget.
- Existing widgets load office data after you open the updated app; no new data
  setup or fixed-party selection is required. Resize the task widget to see more rows.
- Completion checks the current server version. Duplicate taps cannot complete a
  second occurrence, and uncertain writes are not retried automatically.
- Offline errors retain the last verified list and show a status message. Direct
  widget actions require the private office connection, just like the app.

## Refined mobile workspace

- A live task summary, party statements and bill lookup lead the new home screen.
- Hamburger navigation groups reports, team tools and settings.
- Task checkboxes and deadlines stay prominent; notes, recipients and management
  options expand under **Details & options**.
- Optional guidance is expandable, with consistent cards, rounded controls and
  larger touch targets throughout shared components.
- The supplied logo sits inside a circular badge. A configured native company
  splash replaces the default Expo artwork and duplicate loading screen/spinner.

BUSY report requests still require explicit action and retain the office's
five-second cancellation warning. Widget reads and task completion do not operate
BUSY or send WhatsApp messages.

## Verification

TypeScript, 35 mobile regression tests, 12 native Android widget tests and Android
lint passed. Native tests cover completion confirmation, Add navigation, stale and
duplicate completion, repeating versions, offline uncertainty, scope and late-response
fences. See [design and security details](mobile-design.md).

The signed release build and APK v2 signature verification passed. All 15 bundled
app source files were compared with the committed sources and matched. ARM64 and
ARMv7 architectures, version 1.6.0 and versionCode 11 were verified.

Physical phone checks over wireless debugging on 7 November 2026:

- Updated the existing installation without clearing data; sign-in was retained.
- The redesigned home screen loaded, and the widget Add task shortcut opened the
  correct new-task form.
- The final APK was installed and cold-started. The app stayed running without fresh
  native or JavaScript crash errors.
- Completion, duplicate taps and repeat advancement were tested with synthetic tasks
  in native framework tests; no live office task was completed for verification.
- No BUSY export or WhatsApp message was triggered by these checks.

APK size: 35,611,591 bytes.

SHA-256: `3160e79905435ac67dedf12dd78f2f83b2607df91c89731962bca56ec7272553`.
