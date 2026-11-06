# H.S. Traders Office 1.3.0

Android package `com.hstraders.office`, versionCode `6`. Install over the existing app.

## New

- Shared office tasks: anyone approved can add work, set a due date/time, choose reminder recipients, and mark tasks done.
- Once, daily, weekly and monthly repeats, including month-end dates; creator/manager edit and cancellation controls.
- Android phone reminders with an explicit permission/enable step and Test notification. Private background refresh reads tasks only, never BUSY or WhatsApp sends.
- Simpler Home/Office task menus, three-step bill sending, combined Activity navigation and visible/Android Back navigation.
- Office/task drafts and bill searches survive tab changes; consistent circular icon backgrounds and rounded navigation pills.
- Native Android date and time pickers for task deadlines and document/report filters.

## How to use reminders

Every recipient should install this APK, then open **Shared tasks → Enable phone reminders**
and allow notifications. Use **Test notification** on each phone. Select the desired people
when adding a task; unselected people can view the task without receiving its reminders.

Android background refresh takes 15 minutes or longer and can be delayed by battery
restrictions, force-stop, or unavailable Tailscale/office services. Already-synced reminders
can work offline. This is best-effort local notification delivery, not instant remote push
or exact alarm delivery. Open the app to refresh changes promptly.

Existing BUSY report/sheet operations remain manual, with the five-second office warning.
No automatic BUSY scheduler or direct BUSY database access was added.

## Validation

- The existing 209 backend tests and all 11 new task tests passed (220 total), including task sharing/authentication, selected recipients, idempotency, concurrent completion, manager editing, auditing and recurrence.
- Ruff and mypy passed (56 application source files).
- Mobile TypeScript and all 17 reminder/API regression checks passed, including cancellation on session expiry/revocation and preservation of the pending test notification during refresh.
- Phone-size web preview checked with synthetic data: sender steps, retained selections and task drafts, recipient selection and task creation. No real messages, sheet changes or BUSY operations were triggered.
- Physical-phone notification delivery still needs the built-in Test notification check after installation.
- Private gateway health returned 200; the new task and recipient routes returned 401 without authentication. The office application database was backed up before enabling the task schema.
- Local Android build succeeded; version 1.3.0/code 6, ARM64/ARMv7 and APK v2 signature verified. APK size: 35,396,452 bytes.
- SHA-256: `c9192353c0b4451621aaee19f708b392bb664fa6b8d15acbb6297e1392f70ab0`.
