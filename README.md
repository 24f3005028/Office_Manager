# Office Document Dashboard

Local Windows dashboard for finding bills, credit notes, and debit notes by their file modified
date and sending the selected PDFs one at a time to a WhatsApp contact through a linked WhatsApp
Web session.

## Modules

```text
backend/          FastAPI, SQLite job queue, document scanner
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

Open <http://localhost:3000>. The home grid takes you to the WhatsApp bill sender. If the local
workspace is not ready, the sender routes you through WhatsApp linking, live contact import, and
multi-folder setup for bills, credit notes, and debit notes before allowing a send.

## Date and ordering rules

- A document is included when its Windows local last-modified date is inside the inclusive range.
- PDFs are sent by document type in this order: bills, credit notes, debit notes.
- Within a type, the filename prefix and numeric document number are sorted naturally, so `HST-2`
  comes before `HST-10`. Configured root order breaks duplicate-number ties.
- A date label is sent before each contiguous date run in that type-first order.

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
cd backend; python -m pytest; ruff check app tests; mypy app
cd frontend; bun run typecheck; bun run lint; bun run build
cd whatsapp-bridge; bun run typecheck; bun run test; bun run build
```

The WhatsApp bridge is an unofficial WhatsApp Web automation integration for a personal/local
workflow. It is localhost-only by default and must not be exposed publicly.
