# Office Document Dashboard

Local Windows dashboard for finding bills, credit notes and debit notes by their printed
accounting date and sending PDFs sequentially to a saved WhatsApp contact.

## One-click startup

Double-click **Office WhatsApp Sender** on the desktop, or run **Start-Office.cmd** here.
It starts the WhatsApp bridge, FastAPI backend and production frontend in the background,
checks their HTTP endpoints, and opens http://127.0.0.1:3000/whatsapp-bill-sender.
The saved WhatsApp session restores automatically; use setup only if linking is required.

- Clicking again reuses healthy services; it does not open another WhatsApp session.
- Source changes trigger a build on the next cold start. A running service must be restarted
  before changed server code or configuration takes effect. Never rebuild while using the UI.
- Logs are under data/launcher/ with a separate timestamped stdout/stderr pair per service.
- Startup failures stay visible in the launcher console and show the relevant log location.
- The backend and frontend use ports 8000 and 3000 on loopback. The bridge port is read from
  its .env (3001 by default). API URLs and API keys must agree; preflight checks this.
- Services stay running after the launcher closes. Close them before shutting down or restarting
  their processes; wait for sends to finish first. This is a local interactive app, not a service
  installed to start automatically with Windows.

Optional PowerShell commands from the repository root:

```powershell
# Validate dependencies/configuration without starting anything
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Start-Office.ps1 -CheckOnly
# Start without opening a browser
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Start-Office.ps1 -NoBrowser
# Recreate the desktop shortcut after moving the repository
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Install-DesktopShortcut.ps1
```

## First-time installation

Requires Python 3.13+, Node.js 20.19+ and Bun for dependency installation, plus installed
Google Chrome (or WHATSAPP_EXECUTABLE_PATH pointing to another compatible Chrome).
The launcher uses backend/.venv/Scripts/python.exe and Node directly after installation.

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Copy examples only when the destination does not exist. Preserve existing settings.
if (!(Test-Path .env)) { Copy-Item .env.example .env }
cd ../whatsapp-bridge
bun install
if (!(Test-Path .env)) { Copy-Item .env.example .env }
cd ../frontend
bun install
if (!(Test-Path .env.local)) { Copy-Item .env.example .env.local }
cd ..
.\Start-Office.cmd
```

## Modules and cleanup

- backend/: FastAPI, SQLite queue, PDF scanning/date extraction, optional manual ledger import.
- frontend/: Next.js dashboard, setup, settings and WhatsApp bill sender.
- whatsapp-bridge/: pinned whatsapp-web.js integration, durable receipts and send adapter.
- scripts/: one-click startup, configuration checks and desktop shortcut installation.

The previous BUSY automation and Pouncha scheduler were removed. A new manual-only Pouncha
sync is available at /pouncha-sync. It runs only after an explicit Sync or Preview click.
There is no scheduler, startup export, catch-up task or automatic retry of sheet writes.
Manual Excel ledger import remains available to preserve the sender's accounting-date matches.
Existing databases, credentials, PDFs, folder settings and WhatsApp authentication are preserved.
Historical Pouncha tables are retained but are not used. New manual runs use pouncha_manual_runs.
The pre-existing uncommitted BUSY edits were saved in data/review-backup/busy-before-removal.patch.
Local databases and browser runtime files are excluded from Git tracking; existing Git history
still contains any versions committed previously.

## Manual Pouncha sync

Open **Pouncha sync** from the dashboard navigation. Choose Continue from sheet (includes the
last recorded day) or Custom dates, then click **Sync to Google Sheet**. Preview only performs
comparison without sheet writes. The Excel upload source is available when desktop export
is unavailable. The sheet must have its existing A:G headers and valid bill rows.

The BUSY adapter expects one running, logged-in H.S. TRADERS company in the configured
financial year. It sends individual Escape actions, explicitly chooses No at Close Company,
sets STANDARD / Sales and the four agreed Yes options, and exports Excel. Unexpected layouts
or unsafe dialogs stop the run; it never opens BUSY database files. Live desktop calibration
remains necessary if the installed controls do not match the expected layout.

The local service-account file is backend/config/google_service_account.json. It must have
Editor access to the target sheet. Optional environment values are in backend/.env.example.
No Google API call or BUSY export starts on backend initialization. The status page reads the
sheet when opened or refreshed, and progress polling only reads the existing run journal.

New bills append in A:G only; existing rows and H onward remain untouched. Missing challans
are blank. Changed existing bills are reported without overwriting them. An uncertain write
blocks further sync until Verify sheet again confirms it, or you explicitly release the run
after checking the sheet. Restarted runs are failed or marked for review; never auto-resumed.

## Date and ordering rules

- Voucher dates are read automatically from the text layer of each PDF using labelled voucher
  dates (`Invoice Date`, `Bill Date`, `Dated`, `Cr. Note Date`, `Dr. Note Date`) with a top-header
  fallback. Acknowledgement, order, dispatch, e-way and reference dates are ignored. No Excel
  export is required. The date is cached by file size, modification time and extractor version,
  so the first scan reads every PDF and later scans only re-read new, changed or old-version files.
- Importing the BUSY Sales / Credit Note / Debit Note register from the optional **BUSY ledger**
  panel overrides the printed date when a ledger match exists. The uploaded workbook is deleted
  after parsing; only the minimal voucher/date/party index is kept in SQLite.
- A document is included when its effective accounting date is inside the inclusive range.
  Printed PDF dates show a green **PDF** badge, ledger-matched dates show a green **BUSY** badge,
  and only unreadable/unsupported PDFs fall back to the Windows last-modified date with an amber
  **File Date (Unverified)** badge.
- Documents are ordered by accounting date, oldest first. Within each date the order is bills,
  credit notes, then debit notes; configured folder 1 comes before folder 2, and filenames use
  natural prefix/number ordering.
- Exactly one `DD.MM.YY` message precedes each contiguous date run. The preview, send job and
  WhatsApp messages all use this backend order; the browser never re-sorts documents.
- BUSY installation folders (`BusyWin`, `EInvoiceTemp`, `EWayBillTemp`, `SYSTEM`,
  `XMPPMessages`) are excluded from scanning. The backend never reads BUSY database, `.bds`,
  `.mdb`, XML or e-invoice files. PDF date reading uses only the PDF text layer.

## Startup and WhatsApp readiness

The homepage stays visible while the saved WhatsApp session is starting, retrying, or syncing
contacts and document roots. It redirects to setup only when the bridge explicitly reports that
linking, relinking, or repair is required. A temporary bridge/API interruption is shown as a
retryable connection state instead of being treated as a missing WhatsApp link.

The bridge and backend use stable operation IDs and receipts for each opening message, date label,
and PDF. If a response is lost after a send may have started, the job is paused as `needs_review`
instead of blindly resending a document and risking a duplicate.

## Android app

The private mobile app includes party statements, saved bill PDFs, office tools and
shared tasks. Its home-screen task widget supports completion, adding a task and
manual refresh; the party widget opens search directly. See
[mobile design and widget behaviour](docs/mobile-design.md) and
[Android release 1.6.0](docs/android-release-1.6.0.md).

## Checks

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
cd ../frontend
bun run typecheck
bun run lint
bun run build
bun audit
cd ../whatsapp-bridge
bun run typecheck
bun run test
bun run build
bun run check:patch
bun audit
```

See REVIEW.md for completed checks and remaining dependency limitations.
The bridge is a local, unofficial WhatsApp Web integration and should stay on loopback.
