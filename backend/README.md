# Office Document Dashboard backend

This directory contains the modular FastAPI service for scanning local office PDFs and
queueing sequential WhatsApp sends through a local bridge.

## Setup

Python 3.13 is required. From `backend/`:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` when the document roots or bridge address differ. Root values use `|` as the
separator. The defaults are:

- Bills: `E:\BILL LDH 2026-27` and `E:\BILL PDF 2026-27`
- Credit notes: `E:\C N 26-27` and `E:\C N 2026-27 LDH`
- Debit notes: `E:\DEBIT NOTE 26-27` and `E:\DEBIT NOTE 26-27 LDH`

`DATABASE_PATH` is relative to the process working directory unless an absolute path is
provided. The application creates its SQLite parent directory automatically.

Date and BUSY ledger settings:

- `PDF_DATE_EXTRACTION` enables reading the voucher date printed on each PDF, default `true`.
  Extraction results are cached in `pdf_date_index`; the first full scan reads every PDF and
  subsequent scans only re-read new or changed files.
- `BUSY_INBOX_DIR` is the app-owned drop folder for Excel exports, default
  `data/busy_inbox`. The dashboard upload endpoint also saves there before parsing. Ledger
  import is optional because PDF dates are automatic.
- `BUSY_IGNORED_DIRECTORIES` is a `|`-separated list of folder names excluded from PDF
  scanning, default `BusyWin|EInvoiceTemp|EWayBillTemp|SYSTEM|XMPPMessages`.
- `BUSY_SERIES_ALIASES` maps filename/voucher series, default
  `{"HSTL": "HSL", "HSL": "HSL", "HST": "HST", "CN": "CN", "DN": "DN"}`.
- `BUSY_FINANCIAL_YEAR` limits matching to one financial year, default `26-27`.

Importing `app.main` or calling `create_app()` does not read runtime settings, open SQLite,
or create an HTTP client. Configuration, migrations, recovery, and the worker start inside
the ASGI lifespan. The existing `uvicorn app.main:app` entry point is retained. Run one backend
process/worker against a workspace database; the queue is a sequential local worker.

The API expects the bridge at `http://127.0.0.1:3001` by default. If the bridge has
`WHATSAPP_BRIDGE_API_KEY` configured, set the same value in the backend environment.

The web workspace can persist document roots through `/api/settings`. Each category accepts
multiple folders, and the scanner refreshes immediately after a successful update. On Windows,
`POST /api/settings/pick-folder` opens the native folder picker used by the frontend setup flow.

## Run

From `backend/` with the virtual environment active:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API is available under `/api`. Useful endpoints include:

- `GET /api/health`
- `GET /api/documents?category=bills&start_date=2026-04-01&end_date=2026-04-30`
- `GET /api/documents?document_types=bill,credit_note&start_date=2026-04-01&end_date=2026-04-30`
- `GET /api/documents/{file_id}/preview`
- `POST`, `GET /api/send-jobs`, `GET /api/send-jobs/{job_id}`
- `POST /api/send-jobs/{job_id}/cancel`
- `GET /api/whatsapp/status`, `/contacts`, and `/qr`
- `POST /api/whatsapp/start` and `/reconnect`
- `GET /api/settings`, `PUT /api/settings/document-roots`, and `POST /api/settings/pick-folder`
- `POST /api/busy-ledger/import` (multipart: optional `file`, `category`, `dry_run`)
- `GET /api/busy-ledger/status`

Create a send job with a JSON body such as:

```json
{
  "file_ids": ["opaque-file-id"],
  "recipient": "911234567890@c.us",
  "message": "Your documents"
}
```

The worker stores jobs and per-file statuses in SQLite and sends one file at a time. Files
are checked against the configured roots both when a job is created and immediately before
the bridge is called.

## Ordering and message sequence

The document list/preview order is authoritative. Documents are ordered by their resolved
accounting date, oldest first. Within one date the order is **all bills from folder 1 then
folder 2, then credit notes from folder 1 then folder 2, then debit notes from folder 1 then
folder 2**. Filenames use natural prefix/number ordering, and natural relative-path ordering
breaks any remaining ties. Creating a job uses this same order even if `file_ids` arrive in a
different order; the browser never re-sorts.

An optional intro is sent once per job; omitted, `null`, or `""` means no intro. Each contiguous
date run is preceded by exactly one `DD.MM.YY` label. PDFs have no repeated intro caption.
Cancellation is checked after the intro, after the label, and before starting the PDF. A PDF
already accepted by the bridge keeps its receipt if cancellation races with its send.

## PDF voucher dates

The scanner's document pipeline is **scan → resolve dates → filter → sort**. When
`PDF_DATE_EXTRACTION` is enabled, every PDF that was not matched by an imported BUSY ledger has
its first-page text layer read for the printed voucher date. Bills use `Dated` / `Invoice Date`;
credit notes use `Cr. Note Date`; debit notes use `Dr. Note Date`. The parsed date becomes
`effective_date` with `date_source: "pdf"` and `match_status: "pdf_extracted"`, and drives
filtering, preview order and the WhatsApp date label. No Excel export is required.

Results are cached in the `pdf_date_index` SQLite table by file id plus size and modification
time. A full first scan reads every PDF; subsequent scans only re-read new or changed files.
`PDF_DATE_EXTRACTION=false` disables the PDF reader and leaves the optional BUSY ledger as the
only upgraded date source. Only the PDF text layer is read; BUSY databases, XML files and
e-invoice temp files are never opened.

## BUSY ledger dates (optional)

`POST /api/busy-ledger/import` accepts an uploaded `.xlsx`, `.xlsm` or `.xls` export, or parses
every workbook already in `BUSY_INBOX_DIR` when no file is supplied. `dry_run=true` parses and
reports without writing the index. The parser scans the first 25 rows for common BUSY header
synonyms (date, voucher number, voucher type, party), supports native Excel dates, serial numbers
and common `DD-MM-YYYY` / `DD.MM.YY` / `DD-Mon-YYYY` strings, skips summary and continuation
rows, and deduplicates by `(category, raw voucher number, voucher date)`.

Workbooks are ephemeral: the source is permanently deleted after parsing, including on failure,
with three attempts and a short backoff for Windows file locks. Only normalized rows are stored
in `busy_voucher_index`; `busy_sync_batches` records each successful import. The backend never
opens BUSY `.bds`/`.mdb` databases, installation folders, XML files or e-invoice temp files.

Voucher numbers are compared as `(canonical series, financial year, serial)` after series-alias
normalization, never as raw strings. A single candidate supplies the BUSY date. With several
candidates the matcher first narrows by series, then uses party-name token similarity to pick one.
A matched ledger row takes priority over the PDF-printed date. Unmatched or ambiguous records
still receive their printed PDF date when it can be read; only unreadable PDFs keep their file
date with `date_source: "file_fallback"` and an amber **File Date (Unverified)** badge. A ledger
row may back only one distinct PDF; a second PDF claiming the same row makes both ambiguous
instead of silently reusing a date. `GET /api/busy-ledger/status` reports the last sync, indexed
totals and per-category date ranges.

## Bridge contract and readiness

`GET /api/whatsapp/status` preserves the bridge fields:

- `status`: `starting`, `authenticated`, `ready`, `qr`, `retrying`, `disconnected`,
  `auth_failure`, or `error`;
- `connected`, `qr_available`, `initializing`: booleans;
- `requires_action`: `null`, `link`, `relink`, or `repair`;
- `message`: string or `null`;
- `generation`, `qr_revision`: numbers.

`POST /api/whatsapp/start` and `/reconnect` return the bridge's immediate lifecycle status.
They do not wait for initialization or root synchronization. Poll status for progress.

Before claiming a queued file, the worker requires `status == "ready"`, `connected == true`,
and an acknowledged root list for that generation. Waiting does not consume retry attempts or
fail queued files. The worker and status polling retry root synchronization, including after
a generation change or observed bridge outage. `PUT /allowed-roots` sends `{"roots": []}` when
all folders are cleared. Settings are saved even if the bridge is temporarily unreachable.

Settings responses and WhatsApp status include:

- `roots_synced` and `bridge_roots_synced`: equivalent booleans;
- `bridge_sync_error`: string or `null`;
- `bridge_generation`: last observed valid generation or `null`;
- `queue_wait_reason`: `null`, `bridge_not_ready`, or `roots_not_synced`.

Both bridge send endpoints receive `operation_id` and the observed `generation`. Operation
keys are stable, opaque strings, unique per job intro, contiguous date-label run, and PDF.
Retries reuse the same key. A successful bridge response must contain:

```json
{"status": "sent", "message_id": "bridge-message-id", "operation_id": "original-operation-key"}
```

This is an **accepted/send-result receipt, not proof of delivery**. The bridge must journal
the key before external sending, return the stored receipt for a completed retry, and return
HTTP 409 with `outcome: "unknown"` for an incomplete journal after restart, without resending.
The backend validates and persists receipts; it does not promise exactly-once delivery.

Bridge errors use `{"error": "reason", "code": "CODE", "retryable": false,
"outcome": "not_started"}` or `outcome: "unknown"`. Only explicitly safe, retryable
`not_started` failures are retried, up to three failed attempts per file. Connection/pool
acquisition failures are safe to retry; read/write timeouts, lost responses, invalid receipts,
and unclassified HTTP errors are uncertain. Session-unavailable/generation-race rejections
with `not_started` wait for readiness again without spending the retry budget.

## Recovery and review

`GET /api/send-jobs` (existing list response, default limit 100, maximum 500) and
`GET /api/send-jobs/{job_id}` restore durable progress. Existing fields are retained. File
statuses additionally include `unknown`; job statuses additionally include `needs_review`.
Responses expose `operation_id`, `message_id`, label operation/receipt IDs, `attempt_count`,
`error_code`, and `outcome` on files, plus `intro_sent`, `intro_operation_id`, and
`intro_message_id` on jobs. `intro_sent` becomes true only after acknowledgment. `sent_at`
records acceptance by the bridge, not delivery to the recipient.

An uncertain intro, label, or PDF marks its active file `unknown` and its job `needs_review`.
Later files stay queued but are blocked. Other jobs can proceed. Cancelling a review job
cancels the remaining queued files while preserving the uncertain file and `needs_review`.
Restart recovery also converts interrupted `sending` rows to this state, including cancelled
in-flight jobs. No automatic replay or review-resolution endpoint is provided: inspect the
recipient conversation and the recorded operation before deciding whether to create a new job.

If saving an acknowledgment fails, the running worker retains it and retries SQLite
persistence without repeating the external operation. A crash before that receipt is saved
still requires review. Additive, repeatable migrations preserve populated legacy job/file
rows and backfill stable operation IDs; old receipts cannot be reconstructed. Previously
persisted jobs retain their stored ordering; the current date-first contract applies to new jobs.

## Checks

From `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check app tests
.\.venv\Scripts\mypy.exe app
```

The suite disables dotenv loading, clears application setting environment variables, confines
SQLite to per-test temporary fixtures, and rejects real HTTP transports. Fakes and HTTP mock
transports cover lifecycle/import safety, ordering, root synchronization, PDF failures,
cancellation, ambiguous outcomes, receipt persistence, and populated legacy migrations.
These checks do not start servers or verify live WhatsApp delivery.
