# H.S. Traders Office 1.2.2

Android package `com.hstraders.office`, versionCode `5`. Install over the existing app.

## Fixed

- Empty, HTML and truncated gateway responses now show a clear office-unavailable/incomplete-response message instead of a raw JSON parsing error.
- A failed WhatsApp status check shows Unavailable rather than remaining on Checking indefinitely.
- Added **Check office connection** to the bill sender so status and contacts can be refreshed after the office services restart.
- Initial contact reads get at least 60 seconds for cold-start contact/LID loading; normal bridge request timeouts are unchanged.
- Unconfirmed sends and sheet updates are never automatically retried. Connection-loss messages direct the user to check the original request first.

The reported incident was caused by stopped office services: local ports 8000 and 8002 refused connections and private HTTPS returned 502. Starting the existing office launcher restored private gateway health to 200 and WhatsApp to ready. No startup scheduler was added.

## Checks

- Six mobile API regression tests passed, covering empty 502, HTML 502, truncated JSON, unconfirmed writes, connection loss and valid responses.
- Mobile TypeScript passed.
- Complete backend suite: 209 passed; Ruff and mypy passed.
- After backend reload, private gateway health returned 200, WhatsApp reported ready/connected, and the mobile contact read returned its first 100 contacts successfully.
- Local Android release build passed; package version 1.2.2/code 5 and APK v2 signature verified for ARM64 and ARMv7.
- APK size: 32,988,358 bytes. SHA-256: `9545b82fc8c32892725f41a72184303937f60e61040abf1b81932d57cea0f435`.
