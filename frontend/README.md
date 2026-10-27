# Office Document Dashboard frontend

This directory contains the modular Next.js dashboard for previewing office documents and
queueing WhatsApp sends through the local API.

## Setup

From `frontend/`:

```powershell
bun install
Copy-Item .env.example .env.local
bun run dev
```

The dashboard defaults to `http://127.0.0.1:8000`. Set `NEXT_PUBLIC_API_BASE_URL` in
`.env.local` when the FastAPI service uses another address.

## Checks

```powershell
bun run typecheck
bun run lint
bun run build
```

The page expects the API contract documented by the office dashboard backend: health and
WhatsApp status/QR endpoints, document filtering, contacts, send jobs, polling, job
cancellation, and the optional BUSY ledger import/status endpoints.

Voucher dates are read automatically from each PDF's printed date, so the dashboard works
without importing an Excel ledger. Preview rows display a green **PDF** badge for a printed
voucher date, a green **BUSY** badge when an optional ledger match overrides it, or an amber
**File Date (Unverified)** badge when no printed date could be read. The **BUSY ledger** panel
is optional and only cross-checks or replaces those dates.
