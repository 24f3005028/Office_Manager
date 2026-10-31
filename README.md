# Office Document Dashboard

Local Windows dashboard for finding bills, credit notes, and debit notes by their printed
accounting date and sending the selected PDFs one at a time to a WhatsApp contact through a
linked WhatsApp Web session. The same backend also runs the daily Pouncha sales sync from
BUSY 21 into Google Sheets.

## Modules

```text
backend/          FastAPI, SQLite job queue, document scanner, BUSY automation
frontend/         Next.js dashboard UI
whatsapp-bridge/  Node.js whatsapp-web.js session and send adapter
```

Each module has its own README and checks. The boundaries are intentional so future dashboard
features can add new domain modules without putting their state and routes into the main page.

## First run

Open three PowerShell windows.

### 1. WhatsApp bridge

```powershell
cd whatsapp-bridge
bun install
Copy-Item .env.example .env
bun run start
```

Scan the QR shown by the bridge's WhatsApp Web browser window. The session is persisted in
`whatsapp-bridge/runtime/`.

### 2. FastAPI backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

The default folders in `backend/.env.example` point at the six supplied `E:\` document roots.
The bridge `.env` must allow those same roots because it validates path-based sends.

### 3. Next.js frontend

```powershell
cd frontend
bun install
Copy-Item .env.example .env.local
bun run dev
```

Open <http://localhost:3000>. The home grid takes you to the WhatsApp bill sender and the
Pouncha daily sync. If the local workspace is not ready, the sender routes you through WhatsApp
linking, live contact import, and multi-folder setup for bills, credit notes, and debit notes
before allowing a send.

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

## BUSY desktop automation

The backend can drive an already-running BUSY 21 Rel 14.2 desktop to export the Account Ledger
recipes used by the Pouncha sync: **Sales** (bills), **Sales Return** (credit notes), and
**Purchase Return** (debit notes). It is opt-in and refuses to run until the UI profile is
calibrated against the installed BUSY build.

- Run the backend in the logged-in interactive Windows session; do not install it as a service.
- Open BUSY 21 and log into `H.S. Traders` (the expected company is configurable).
- Discovery uses a direct Win32 window enumeration plus the process image path, not a WMI query or
  pywinauto path scan. The defaults are `BUSY_EXECUTABLE_PATH=C:\BusyWin\Busy21.exe` and
  `BUSY_WINDOW_TITLE_RE=^Busy\s+21\s+Rel\b`; the double space in the real title and a moved
  executable are both tolerated. The runner attaches by window handle and falls back from the
  `win32` backend to `uia` if needed.
- The shipped `backend/config/busy_ui_profile.json` is intentionally uncalibrated. The pipeline
  refuses to run until `calibrated` is `true` and every required focus key or control selector
  is filled in.
- The recipes use the `BAGS` format, the `Sales` / `Sales Return` / `Purchase Return` account,
  `DD-MM-YYYY` dates, and set **Transport Details** and **Bill References** to `Y`.
- The export dialog is set to `Microsoft Excel`. The File Name is entered without `.xlsx`
  because BUSY appends the extension; the pipeline polls both the extensionless name and the
  `.xlsx` file. An "open file after export" prompt is answered with `N` / `{ESC}`, and Excel is
  never opened.
- Safety: the pipeline takes an exclusive lock, waits for the desktop to be idle, attaches to
  the existing BUSY window, verifies the company title, exports to
  `data/busy_automation/`, parses the workbook, and deletes the temporary file. It never closes
  BUSY, never starts a second instance, and never kills `EXCEL.EXE`.

### Account Ledger calibration checklist

1. Open BUSY 21 and log into `H.S. Traders`.
2. Run the inspector without sending any keys:

   ```powershell
   cd backend
   .\.venv\Scripts\python.exe scripts\inspect_busy_ui.py --watch
   .\.venv\Scripts\python.exe scripts\inspect_busy_ui.py --controls
   ```

   If auto-discovery ever misses a window, attach explicitly with `--pid <pid>`,
   `--handle 0x<hwnd>`, or `--backend uia`; these switches only change how the read-only
   inspector attaches.

3. Navigate manually to **Account Ledger**, choose the **BAGS** format and the **Sales**
   account, and note the focus keys, modal titles, and control selectors.
4. Repeat for **Sales Return** and **Purchase Return**.
5. Fill `navigation_keys`, `modal_keys`, the format/account/date selectors, and the export
   `format_control` (Data Format = `Microsoft Excel`), `path_control`, and
   `open_after_control` in `backend/config/busy_ui_profile.json`.
6. Set `calibrated: true` for each recipe you verified.
7. Validate one export without touching Google Sheets:

   ```powershell
   .\.venv\Scripts\python.exe scripts/test_pouncha_export.py
   ```

   Inspect the workbook copy under `data/pouncha_calibration/` and confirm the A:G rows before
   enabling the scheduler.

## Pouncha daily sales sync

`/pouncha-sync` exports the BUSY Account Ledger Sales window and appends new sale bills to the
**POUNCHA 26-27** Google Sheet. The tab has no header row: Row 1 is the first sale bill. The
sync reads existing voucher numbers from Column B and appends new rows to Columns A:G only.
Column H remarks such as `P` or `BILTY AA GYI` are never read or overwritten.

Columns written per bill:

```text
A Date | B Vch/Bill No | C Account | D Transport | E Vehicle No | F Station | G Order No
```

### Google Sheets setup

1. Create a Google Cloud project, enable the **Google Sheets API**, and create a service
   account.
2. Download the service-account JSON key to `backend/config/google_service_account.json`.
   The file is git-ignored.
3. Share the **POUNCHA 26-27** spreadsheet with the service account's `client_email` as
   **Editor**.
4. Copy the spreadsheet ID from its URL and set `POUNCHA_SPREADSHEET_ID` in
   `backend/.env`.
5. Leave `POUNCHA_SHEET_TAB_NAME=POUNCHA 26-27` unless the tab was renamed.

The sync never creates the tab or a header row. If the tab is missing, the run fails with an
actionable error instead of guessing.

### Pouncha environment settings

| Setting | Default | Purpose |
|---|---|---|
| `POUNCHA_SPREADSHEET_ID` | empty | Google Sheet ID. Required for any Sheets write. |
| `POUNCHA_SHEET_TAB_NAME` | `POUNCHA 26-27` | Existing headerless tab name. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `config/google_service_account.json` | Service-account key, relative to `backend/`. |
| `POUNCHA_LOCAL_EXCEL_PATH` | empty | Optional local archive. Empty disables it. |
| `POUNCHA_SYNC_ENABLED` | `true` | Master switch for the scheduler, manual BUSY sync, and upload. |
| `POUNCHA_SYNC_LOOKBACK_DAYS` | `3` | Default window is `today - 3` through `today` IST. |
| `POUNCHA_CATCHUP_INTERVAL_MINUTES` | `15` | How often the scheduler checks for a missed run. |
| `POUNCHA_TIMEZONE` | `Asia/Kolkata` | Midnight schedule and audit timestamps. |
| `POUNCHA_LOCK_PATH` | `data/pouncha_sync.lock` | Serializes scheduler, manual, and upload runs. |
| `POUNCHA_UPLOAD_DIR` | `data/pouncha_uploads` | Temporary upload storage; files are deleted after parsing. |

The page shows **Calibration required** until
`account_ledger_sales.calibrated` is `true` in `backend/config/busy_ui_profile.json`. The
Excel upload fallback is available as soon as Sheets is configured because it does not drive
the BUSY desktop.

### Schedule and catch-up

- The scheduler runs every day at **00:00 IST** and exports the window from
  `today - POUNCHA_SYNC_LOOKBACK_DAYS` through `today` (3 days by default).
- On backend startup, and every `POUNCHA_CATCHUP_INTERVAL_MINUTES` (15 by default), it checks
  whether a successful run has completed since midnight. If not, it runs the catch-up.
- If BUSY 21 is closed, catch-up skips quietly and the page shows **Waiting for BUSY 21**;
  no failed audit row is created. It retries on the next interval.
- The scheduler does not start a run until Google Sheets is configured and the Account Ledger
  Sales recipe is calibrated. The page shows the missing step instead.
- Each run is stored in the `pouncha_sync_runs` table with its trigger, date window, counts,
  status, warnings, and timestamps. A run left `queued` or `running` by a backend restart is
  marked failed with `Interrupted by a backend restart`.
- The scheduler and manual paths share `POUNCHA_LOCK_PATH`, so two syncs cannot append to the
  same sheet at once.

### Manual sync and Excel upload

- **Sync Now from BUSY** calls `POST /api/pouncha-sync/run`. The endpoint returns **202** with a
  `run_id`; the page polls `/api/pouncha-sync/status` and `/api/pouncha-sync/runs/{run_id}`.
  A queued background run creates an audit row immediately and updates it when the export
  finishes.
- **Upload sales ledger Excel** accepts an `.xlsx`/`.xlsm` Account Ledger export, runs the same
  parser, deduplication, local archive, and Sheets append, and returns the completed run
  synchronously. The uploaded file is deleted after parsing, including on failure. The upload
  works even when BUSY is closed, but still requires Google Sheets and `POUNCHA_SYNC_ENABLED`.
- Existing voucher numbers are deduplicated using the same canonical key as the BUSY ledger
  parser. New rows are sorted by date, `HST` before `HST/L`, then serial.
- When `POUNCHA_LOCAL_EXCEL_PATH` is set, a copy of every parsed sale row is also written to
  that local workbook. Set it to an empty value to disable the archive. Archive failures are
  reported as run warnings and do not roll back a successful Sheets append.
- The sync never writes to Sheets when there are no new rows and never modifies existing rows.
  It appends Columns A:G only; Column H remarks are preserved.

### Pouncha API endpoints

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/api/pouncha-sync/status` | Scheduler state, configuration flags, last run, active run, and last 10 audit rows. |
| `POST` | `/api/pouncha-sync/run` | Queue a BUSY export. Returns `202 {run_id, status}`; rejects a second active run with `409`. |
| `GET` | `/api/pouncha-sync/runs/{run_id}` | Poll one audit row. |
| `POST` | `/api/pouncha-sync/upload-excel` | Multipart `.xlsx`/`.xlsm` upload; parses and appends synchronously. |

Configuration errors return `503`; invalid dates or workbooks return `400`; Sheets API failures
return `502`.

## Startup and WhatsApp readiness

The homepage stays visible while the saved WhatsApp session is starting, retrying, or syncing
contacts and document roots. It redirects to setup only when the bridge explicitly reports that
linking, relinking, or repair is required. A temporary bridge/API interruption is shown as a
retryable connection state instead of being treated as a missing WhatsApp link.

The bridge and backend use stable operation IDs and receipts for each opening message, date label,
and PDF. If a response is lost after a send may have started, the job is paused as `needs_review`
instead of blindly resending a document and risking a duplicate.

## Checks

```powershell
cd backend; python -m pytest; ruff check app tests scripts; mypy app scripts
cd frontend; bun run typecheck; bun run lint; bun run build
cd whatsapp-bridge; bun run typecheck; bun run test; bun run build
```

The WhatsApp bridge is an unofficial WhatsApp Web automation integration for a personal/local
workflow. It is localhost-only by default and must not be exposed publicly.
