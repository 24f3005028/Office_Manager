# H.S. Traders Office 1.7.1

Android package `com.hstraders.office`, versionCode `14`.

- Fixed Copy account stopping at BUSY's PDF export dialog. Ledger exports also
  expose an optional Attach Link field with None selected; the adapter now accepts
  that layout, sets the destination and proceeds. Passwords, enabled links and
  unknown export fields are still rejected. The PDF account-name and date checks
  remain in place.
- Copy account and group balances start from the Create button without another
  confirmation on the phone. The office computer retains its five-second warning
  and cancellation option.
- Replaced circular in-app loading indicators with animated yarn-style progress
  bars, including active report preparation and office operations. Elapsed time
  appears for longer waits. Bars are indeterminate and respect reduced motion.
- Removed Send to my WhatsApp from every PDF action set. Use Share to choose
  WhatsApp or another app, or use Open PDF and Download as before.

Group closing balances were confirmed working by the owner on version 1.7.0.

## Verification

The full backend regression suite, mobile tests, TypeScript, Ruff and mypy pass.
PDF export tests cover both existing outstanding layouts and ledger layouts with
Attach Link=None, and reject passwords, links and unexpected extra fields.

The mobile gateway was restarted with no active reports or deliveries. Live Copy
account export from the phone still needs confirmation after this fix.
