# H.S. Traders Office 1.1.0

Android package: `com.hstraders.office`, versionCode `2`. Signed with the existing private release key so it can update the installed app without uninstalling it.

## Changes

- Redesigned mobile app with bottom navigation, clearer party search and a dedicated PDF result card.
- H.S. Traders logo in the app and Android launcher icon.
- Separate country calling code (default +91) and mobile number in phone setup and the office invite form. Pairing checks the approved number before consuming an invite.
- Outstanding PDF filenames use the party name for downloads, sharing and WhatsApp delivery.
- Outstanding requests use BUSY Favourites → Outstanding Bills → One Account → direct PDF export.
- Pouncha explicitly selects Microsoft Excel even after an outstanding PDF export; it removes temporary workbooks after parsing.
- Failed statement exports are deleted immediately. Completed reports are retained for 48 hours, then cleaned up at startup or normal report access. No scheduler is installed.

## Validation

- 201 backend tests passed; Ruff and strict mypy passed.
- Dashboard TypeScript, ESLint and production build passed.
- Android TypeScript and local ARM64/ARMv7 release build passed; APK v2 signature verified.
- Live BUSY export checks passed in both directions: PDF → Excel and Excel → PDF. The Excel check parsed 10 bills and verified workbook deletion without writing to Google Sheets.
- Mobile layouts reviewed at 390px and 360px widths using temporary sample data. Sample sessions and preview fixtures are absent from the APK.

## APK

- Asset: `HS-Traders-Office.apk`
- Size: 32,932,086 bytes
- SHA-256: `8bbd293ca9cfc2a3b2a0b43d375328dabf134edd441f38166461a23eff6ee55e`

The office's private `/install/android.apk` endpoint serves the updated APK immediately. The corresponding GitHub release is intended to use tag `mobile-v1.1.0`; confirm publication before distributing its URL.
