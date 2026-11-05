# H.S. Traders Office 1.2.1

Android package `com.hstraders.office`, versionCode `4`, using the existing release signing key. Install over the existing app to retain its saved connection.

## Changes

- Added **Copy code** to the office dashboard's generated invite.
- The server-designated approved invite manager can create new-user codes from **Invite new users** on Home or their account screen. The form separates country code and mobile number and includes native **Copy code** and **Hide code** actions.
- Mobile invite creation is enforced on the server and recorded against the creator. Ordinary users cannot create invites or grant themselves this permission. Invite-manager access itself must be enrolled from the office dashboard.
- Invites remain private, single-use and valid for 15 minutes. New phones still need their own Tailscale access; creating an app invite does not change VPN membership.
- The designated phone lives only in ignored office configuration, not the app or repository.

Includes the existing mobile Office tools, party-named PDFs, branded UI and report cleanup.

## Checks

- All 208 backend tests passed, including invite-manager, revocation, audit and non-delegation coverage.
- Dashboard TypeScript, lint and production build passed.
- Mobile TypeScript passed. Android version synchronization now also covers builds retaining the generated native project.
- Signed ARM64/ARMv7 APK build and signature verification passed; native clipboard module is registered and packaged. The invite-manager phone number is absent from the app bundle.

APK: 32,986,674 bytes. SHA-256: `74208d7406de7f125cb31f0db908a28ed81641a2de2cb8a67e7c58879a9d8267`.
