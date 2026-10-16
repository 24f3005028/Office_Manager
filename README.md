# Office Hub

Office Hub is a local-first Windows dashboard and job engine for office automation. It is
designed for a single trusted workstation and keeps the browser UI separate from long-running
automation work.

The initial scaffold provides:

- A FastAPI dashboard bound to `127.0.0.1` by default.
- Durable SQLite jobs with `pending`, `running`, `succeeded`, `failed`, and `cancelled` states.
- A separate worker thread so BUSY, PDF, and spreadsheet work does not block HTTP requests.
- An APScheduler hook for a configurable midnight WhatsApp job.
- Safe dry-run task adapters for WhatsApp PDF discovery, BUSY export, and Google Sheets sync.
- A BUSY workflow that never opens the Access database: manual `.xlsx` import by default, with an
  optional profile-driven UI adapter.
- Strict workbook parsing and normalized Excel artifacts for Profit & Loss and Balance Sheet reports.
- A provider-neutral WhatsApp financial-help endpoint with replay protection and dry-run delivery.
- Typed settings from `.env`, with secrets and runtime data kept outside source control.
- Alembic migrations, pytest tests, Ruff checks, and Windows command scripts.

The integration adapters intentionally fail closed: no WhatsApp message, BUSY mutation, or Google
Sheets write happens until a concrete provider is configured and `ALLOW_EXTERNAL_ACTIONS=true` is
set explicitly.

## First run on Windows

Use **Command Prompt** for the setup commands below. Python 3.12 is selected explicitly because
the project is pinned to Python 3.12.

```cmd
cd /d "C:\DATA\Coding\New folder"
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
copy .env.example .env
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m office_hub
```

Open <http://127.0.0.1:8000>. For a development reload loop, use:

```cmd
.venv\Scripts\python.exe -m uvicorn office_hub.app:app --host 127.0.0.1 --port 8000 --reload
```

The application creates its runtime directory under `%LOCALAPPDATA%\OfficeHub` by default. That
directory contains the SQLite database and rotating logs, not the repository.

## Configure the workstation

1. Copy `.env.example` to `.env`.
2. Set `OFFICE_HUB_BILLING_FOLDER` to the invoice/PDF folder.
3. Set `OFFICE_HUB_BUSY_EXE_PATH` if BUSY UI automation will be enabled later.
4. Put Google service-account credentials in a protected local path and set
   `OFFICE_HUB_GOOGLE_CREDENTIALS_FILE` and `OFFICE_HUB_GOOGLE_SHEET_ID`.
5. Keep `OFFICE_HUB_ALLOW_EXTERNAL_ACTIONS=false` while testing. Dashboard jobs default to dry-run.
6. Set `OFFICE_HUB_SCHEDULED_WHATSAPP_ENABLED=true` only after the WhatsApp provider and recipient
   mapping have been implemented and tested. The scheduler uses `OFFICE_HUB_SCHEDULER_TIMEZONE`.
7. Keep `OFFICE_HUB_WHATSAPP_PROVIDER=dry_run` until the report workflow is proven with a real
   exported workbook.

The reference architecture originally used `config.json`. This scaffold uses Pydantic Settings and
`.env` instead: values are typed, environment-specific, and less likely to put credentials in a
committed JSON file. `config.json` is ignored if you create one locally.

## Windows startup

For a quick per-user startup entry, create a shortcut to `autostart.bat` in the Startup folder:

```cmd
shell:startup
```

For a more reliable scheduled task, run PowerShell as the intended user and execute:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_task.ps1
```

The task runs at logon, uses the repository's `.venv`, and starts the server on localhost. Review
the script before registering it on a shared machine. The app should run in the logged-in desktop
session when BUSY UI automation is required.

## Project layout

```text
office_hub/
├── pyproject.toml
├── .env.example
├── autostart.bat
├── scripts/
│   ├── bootstrap.cmd
│   ├── register_task.ps1
│   └── run_dashboard.cmd
├── migrations/
│   └── versions/0001_initial.py, 0002_inbound_messages.py
├── config/
│   └── busy_ui_profile.example.json
├── src/office_hub/
│   ├── app.py                 # FastAPI factory and lifespan
│   ├── config.py              # Typed local settings
│   ├── database.py            # SQLAlchemy engine/session factory
│   ├── models.py              # Durable jobs and job events
│   ├── repository.py          # Transactional persistence operations
│   ├── scheduler.py           # APScheduler integration
│   ├── worker.py              # Long-running job executor
│   ├── tasks/                 # WhatsApp, BUSY, Sheets adapters
│   │   ├── busy_reports.py    # Strict .xlsx parser and normalized artifacts
│   │   ├── busy_ui.py         # Optional profile-driven pywinauto adapter
│   │   └── busy_lock.py       # Single automation lock
│   ├── whatsapp/              # Parser, replay protection boundary, and providers
│   └── web/                   # Routes, templates, and static assets
└── tests/
```

## Checks

Run the checks from Command Prompt after installation:

```cmd
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m mypy src
```

`mypy` is intentionally strict and may identify follow-up typing work as integrations are filled
in. A check is only considered successful when its command completes with exit code 0.

## Integration boundaries

### WhatsApp PDF sender

`src/office_hub/tasks/whatsapp_sender.py` safely scans PDFs by filesystem modification date. It
returns a plan in dry-run mode. A real sender must be implemented behind a provider boundary (for
example, an approved WhatsApp Cloud API client) and must handle recipient mapping, rate limits,
retries, idempotency, and audit logs before live actions are enabled.

### BUSY exporter and report parser

`src/office_hub/tasks/busy_exporter.py` never connects to the `.mdb` file. Its safe default is:

1. Run a read-only Profit & Loss or Balance Sheet report in BUSY.
2. Export it as `.xlsx` using the headers `Section`, `Account`, `Debit`, `Credit`, and `Amount`.
3. Copy the export into `%LOCALAPPDATA%\OfficeHub\outputs\busy-inbox`.
4. Queue a BUSY job with `mode=manual_import` and the workbook path.
5. Office Hub parses the workbook and writes a unique normalized workbook into
   `%LOCALAPPDATA%\OfficeHub\outputs\busy-reports`.

The parser rejects `.mdb`, `.xls`, `.xlsm`, unknown headers, invalid amounts, and files outside the
configured inbox. It calculates summary values only from explicit sections. Unknown BUSY layouts
must be mapped deliberately; the application does not guess from arbitrary cells.

The dashboard can queue the request. A direct Command Prompt example after placing `pnl.xlsx` in the
inbox is:

```cmd
curl -X POST http://127.0.0.1:8000/api/jobs ^
  -H "Content-Type: application/json" ^
  -d "{\"task_name\":\"busy_exporter\",\"dry_run\":true,\"payload\":{\"report_type\":\"profit_loss\",\"start_date\":\"2026-10-01\",\"end_date\":\"2026-10-31\",\"mode\":\"manual_import\",\"input_file\":\"C:\\\\Users\\\\you\\\\AppData\\\\Local\\\\OfficeHub\\\\outputs\\\\busy-inbox\\\\pnl.xlsx\"}}"
```

The optional `mode=ui` adapter uses `pywinauto` only when all of these are true:

- `OFFICE_HUB_ALLOW_EXTERNAL_ACTIONS=true`
- `OFFICE_HUB_BUSY_AUTOMATION_ENABLED=true`
- a reviewed, machine-specific `busy_ui_profile.json` is configured
- the BUSY executable path is configured and exists

It acquires a lock, refuses to act while BUSY is the foreground window, runs only the configured
report/export sequence, and verifies a non-empty `.xlsx` output. The example profile is a template,
not a claim that those menu keys match your BUSY version. It is explicitly approved for one report
type; create and review a separate profile if Profit & Loss and Balance Sheet use different BUSY
menus. Test with a BUSY backup/company first.

Do not run the UI exporter while an operator is actively using BUSY. Desktop automation is not a
database transaction and cannot safely arbitrate human input.

### WhatsApp financial-help chat

`POST /api/whatsapp/inbound` is a local/provider-neutral boundary for a verified WhatsApp adapter.
It accepts a message ID, sender ID, and text such as:

```text
What is the profit and loss from 2026-10-01 to 2026-10-31?
```

or:

```text
Send balance sheet today
```

The first parser supports Profit & Loss, Balance Sheet, ISO dates, `today`, `yesterday`, and
current-year/current-month defaults. The sender must be in `OFFICE_HUB_WHATSAPP_ALLOWED_SENDERS`.
Message IDs are persisted for replay protection; message text is not persisted in the database.

The endpoint queues a BUSY report request and returns an acknowledgement. Once a workbook is parsed,
the worker prepares a concise summary and can send the normalized workbook through the selected
provider. With the default `dry_run` provider, no network request is made. The optional `cloud_api`
provider uses the official WhatsApp Cloud API only when external actions and complete credentials
are enabled.

The endpoint is not a public webhook by itself. A real provider integration must verify webhook
signatures and pass only verified messages to this local route.

### Google Sheets sync

`src/office_hub/tasks/gsheets_sync.py` is the boundary for `gspread` or the Google Sheets API. Use a
service account with the narrowest spreadsheet permissions, keep its JSON file outside the repo,
and make syncs idempotent so a restarted worker cannot append duplicate rows.

## Security and operational notes

- The server binds to localhost only. Do not expose it to a LAN without authentication and CSRF
  protection.
- External actions are opt-in and disabled by default.
- Logs contain job metadata and errors, not document contents or credentials.
- Use one worker on the local SQLite queue. A multi-user deployment needs a broker and a separate
  authentication model.
- Test desktop automation on a non-production BUSY company first. UI selectors and hotkeys are
  version-specific.
- Never point Office Hub at the live `.mdb` file for this workflow. The database is intentionally
  not part of the application configuration.
