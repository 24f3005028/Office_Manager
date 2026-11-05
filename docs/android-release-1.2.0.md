# H.S. Traders Office 1.2.0

Android package `com.hstraders.office`, versionCode `3`, signed with the existing release key. Install over the existing app to keep the saved connection.

## Added

- **Office → Update sheet:** view the last saved bill/date, continue or choose a custom range, preview missing bills, then explicitly confirm the Pouncha update. The office gets the five-second warning before BUSY is touched. Uncertain updates can be verified or released after manual sheet review.
- **Office → Send bills:** select dates and bills/credit notes/debit notes, choose individual PDFs or all, select a saved WhatsApp contact, review the opening message and confirm sending. Uses the existing office queue, oldest-first document ordering, date labels and cancellation of unsent files.
- All approved mobile users may use both tools. Request history is scoped to its creator. Repeated request keys do not queue duplicate work; unknown outcomes require review.
- Bill PDFs download as `BILL-NUMBER - PARTY NAME.pdf`. Outstanding PDFs download as `PARTY NAME.pdf`. The party name is compulsory; unreadable bill parties require an office check. Original archived PDFs are reused and preserved.

Includes the version 1.1 redesign, supplied launcher logo, separate country-code setup, corrected BUSY export format switching and temporary-file cleanup.

## Validation

- 206 backend tests passed; Ruff and strict mypy passed.
- Mobile TypeScript passed; Office screens checked at phone width with isolated sample data.
- Local ARM64/ARMv7 Android build passed. APK signature verified, versionCode 3. Temporary preview fixtures are absent from the APK.
- No real WhatsApp messages or Google Sheet updates were made by these tests.

The APK is built locally for ARM64/ARMv7 and served at the office's private `/install/android.apk` endpoint. GitHub publication uses tag `mobile-v1.2.0` after the source push succeeds.

APK size: 32,955,586 bytes. SHA-256: `0a75b88b9f6c70cbccda08b67da44d3336401aa731c3b4c7d42baf0933dd5145`.
