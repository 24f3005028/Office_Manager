# H.S. Traders Office 1.6.1

Android package `com.hstraders.office`, versionCode `12`.

Open PDF now opens the document in Google Drive's PDF viewer when available,
instead of opening Android print preview. If Drive is unavailable, another
registered PDF viewer is used. If no viewer is installed, the app explains how
to install one.

This applies to party statements, all-account outstanding reports, statement
activity and saved bill PDFs. File names, Download, Share and WhatsApp actions
retain their existing behaviour.

Documents open from the local downloaded file with temporary read access. The
office access token and authenticated download address are not passed to the
viewer. The print dependency has been removed.

## Verification

- TypeScript and all 35 mobile regression tests passed.
- Five native PDF-viewer tests and Android lint passed, covering Drive preference,
  fallback, missing viewers, invalid URI rejection and permission failures.
- The connected phone's installed Google Drive advertises a PDF viewer for
  `application/pdf`; no Drive activity class is hard-coded in the app.
- Signed Android release build and APK v2 signature verification passed. Version
  1.6.1, versionCode 12 and ARM64/ARMv7 support were checked. All 16 bundled app
  source files matched the committed source files.

APK size: 35,609,871 bytes.

SHA-256: `eee268541af3cbdee7d702255b5d97fec87f82a44068ae45e3806bf2f1aee94f`.
