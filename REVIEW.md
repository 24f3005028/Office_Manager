# Repository review — 5 November 2026

This records the initial cleanup. Subsequent work rebuilt Pouncha as a manual-only feature
(see `docs/pouncha-manual-sync.md`), redesigned the dashboard and added a shared BUSY desktop
lock. The Android/mobile feature is work in progress and is not exposed by the running API.
Latest verification: 170 backend regression tests plus 5 mobile-foundation tests passed;
Ruff, strict mypy, frontend TypeScript/ESLint and 64 bridge tests passed. The redesigned
frontend production build and desktop/phone layouts were checked before mobile work began.

## Completed changes

- Removed BUSY desktop automation, export runners, UI profiles, calibration/inspection scripts,
  automation-specific tests and configuration, and the dependent Pouncha Google Sheets feature.
  Removed its startup scheduler, routes, UI pages, API types, CSS and Python dependencies.
- Kept manual ledger import and date matching because the existing WhatsApp sender uses them.
  PDF date extraction, sorting, opening messages, date labels, send receipts, cancellation,
  restart recovery and duplicate-send protections remain intact.
- Fixed a preview race: an old scan response can no longer populate documents after filters
  change. Sending stays disabled during a fresh preview. Restored jobs needing review remain
  visible after reloading the sender. Setup return paths are restricted to known local pages.
- Upgraded Next.js from 14.2.15 to 15.5.28 and React to 19.2.6. Updated matching type/lint
  dependencies, switched linting to the ESLint CLI, and patched vulnerable transitive packages.
  The WhatsApp SDK stays at its working version, 1.34.7, with its existing send-ID patches.
- Updated Python development tooling after an installed-environment audit found vulnerable
  pip, pytest and an unused installed pypdf helper. The current Python environment audit is clear.
- Removed the local database and browser cache/preferences from Git tracking while preserving
  the on-disk files. Added cache exclusions. This does not remove prior commits from Git history.
- Saved the four pre-existing modified BUSY files as a Git patch before removal, at
  `data/review-backup/busy-before-removal.patch` (ignored local data).

## One-click startup

Desktop shortcut: `Office WhatsApp Sender.lnk`, in the Windows desktop folder.
Target: `Start-Office.cmd` in this repository, which runs `scripts/Start-Office.ps1`.

The launcher checks installed dependencies, matching API URLs/keys and browser compatibility
patches; builds changed sources before a cold start; starts hidden background processes; checks
each service; and opens the bill sender. Subsequent clicks reuse healthy processes belonging
to this workspace. Occupied ports from another workspace are rejected. A mutex prevents two
simultaneous launcher instances. Logs are timestamped under `data/launcher/`.

First startup was tested from empty application ports. Repeat startup reused the same services.
Backend and frontend bind to 127.0.0.1, on ports 8000 and 3000. The bridge reads its configured
loopback port (3001 here). Existing WhatsApp authentication and folder settings were preserved.

## Verification

| Check | Result |
|---|---|
| Backend regression suite | 143 passed |
| Backend Ruff | Passed |
| Backend strict mypy | Passed, 36 source files |
| Bridge fake-client/HTTP/queue/receipt tests | 64 passed |
| Bridge TypeScript, build and compatibility patches | Passed |
| Frontend TypeScript, ESLint and production build | Passed |
| Frontend `bun audit` | No advisories |
| Installed Python `pip-audit` | No known vulnerabilities |
| Launcher preflight and repeated startup | Passed |
| Live backend health | Database OK, send worker running |
| Live WhatsApp readiness | Connected, ready, document roots synchronized |
| Live contact import | 1,781 contacts returned; no contact details logged |
| Desktop shortcut | Target and working directory verified |

The tests use fake WhatsApp clients and mock HTTP transports. Live checks covered startup,
session restoration, readiness and contacts. No real message or bill was sent during review.
These checks do not guarantee the absence of every possible defect or future WhatsApp Web change.

## Remaining limitations

The bridge audit reports two high-severity advisories for the same transitive package,
`extract-zip@2.0.1`. Upstream lists no patched release:

- [Symlink target validation advisory](https://github.com/advisories/GHSA-jmr9-qjv8-65gv)
- [Symlink entry overwrite advisory](https://github.com/advisories/GHSA-7pqw-9j4j-h8q3)

This dependency belongs to Puppeteer's browser archive installer. This application uses
installed Chrome, and automatic browser downloads are disabled in `.puppeteerrc.cjs` to avoid
that extraction path. This mitigation does not change the audit result or patch the dependency;
manually invoking its archive extraction would still be affected.

The backend test suite emits one upstream Starlette warning about its httpx TestClient adapter.
All tests pass. Existing historical Pouncha database tables and credentials were preserved;
no active application code reads or schedules the removed feature.

Security version selection followed the
[Next.js October 2026 update](https://nextjs.org/blog/nextjs-security-update-october-14-2026).
