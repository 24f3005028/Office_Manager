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
WhatsApp status/QR endpoints, document filtering, contacts, send jobs, polling, and job
cancellation.
