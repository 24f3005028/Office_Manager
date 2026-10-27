# Local WhatsApp bridge

This directory contains the localhost-only Node bridge used by the office document dashboard.
It owns the `whatsapp-web.js` browser session, exposes a small HTTP API, and sends PDFs through
a bounded, single-lane queue. Tests inject a fake client and never launch WhatsApp.

## Setup

Node.js 20 or newer is recommended. From `whatsapp-bridge/`:

```powershell
bun install
Copy-Item .env.example .env
```

Set `WHATSAPP_ALLOWED_ROOTS` to the directories that may contain PDFs. Use `|` between roots;
an empty value is valid and disables path-based sends. The bridge validates roots atomically,
resolves the requested file and roots at execution time, requires a regular file with a `%PDF-`
signature, and enforces a 25 MiB path/upload limit. `WHATSAPP_RUNTIME_DIR` stores the persistent
`LocalAuth` browser session and the hashed operation journal under `operations-v1/`; it should not
be committed. Recovery never deletes this authentication data.

The bridge launches the system-installed Google Chrome (puppeteer `channel: "chrome"`), so the
bundled Chromium download is not required. If Chrome lives in a non-default location, set
`WHATSAPP_EXECUTABLE_PATH` to its `chrome.exe`.

## Run

```powershell
bun run start
```

The server binds to `127.0.0.1:3001` by default:

- `GET /status` — connection state and whether a QR is available
- `POST /start` — schedule an idempotent start and return the current status promptly
- `POST /reconnect` — schedule an idempotent reconnect and return the current status promptly
- `GET /qr` — QR SVG while pairing is required
- `GET /contacts` — sorted saved contacts; verified LID mappings are converted to phone chat IDs
- `POST /send-text` — submit one text operation
- `POST /send-document` — submit one path or multipart PDF operation

The path-based send body is:

```json
{
  "contact_id": "1234567890@c.us",
  "operation_id": "job-intro-2026-10-24",
  "generation": 3,
  "file_path": "C:\\OfficeDocuments\\bill-001.pdf",
  "caption": "Your document"
}
```

`operation_id` is required and must be stable for the backend job. A successful operation returns:

```json
{"status":"sent","message_id":"...","operation_id":"job-intro-2026-10-24"}
```

The receipt means that `whatsapp-web.js` accepted the send result after using
`waitUntilMsgSent: true`; it does not claim recipient delivery. A duplicate in-flight operation
joins the original promise. A completed duplicate returns its saved receipt. A pending journal
record found after a process restart returns HTTP 409 with `code: "outcome_unknown"` and is never
replayed. SDK submission failures or missing message IDs use the same non-retryable unknown result.

The status response preserves `status`, `connected`, and `qr_available`, and adds:
`initializing`, `requires_action` (`null`, `link`, `relink`, or `repair`), `message`, `generation`,
and `qr_revision`. States are `starting`, `authenticated`, `ready`, `qr`, `retrying`,
`disconnected`, `auth_failure`, and `error`. Authentication failures/QR states require linking;
terminal startup failure requires repair. Starting and reconnecting do not delete saved auth.

The FastAPI worker uses the JSON path flow, so the bridge validates the configured roots without
copying the whole PDF through the API process. For compatibility, `/send-document` also accepts a
multipart form with `to`, `caption`, and a PDF `file` field.

If `WHATSAPP_BRIDGE_API_KEY` is set, use `x-api-key` or a Bearer token on bridge requests.
Browser `Origin` values are rejected before mutations unless listed in `WHATSAPP_CORS_ORIGINS`.
This is a local service boundary: loopback binding, the optional API key, and the origin list are
defense-in-depth and do not replace host-level access control. Lifecycle events are logged without
QR values, API keys, paths, request bodies, captions, or private SDK errors.

`whatsapp-web.js` is loaded from the installed dependency only; the bridge does not automatically
launch WhatsApp during installation. The postinstall compatibility check patches the verified
media-send and message-ID source shapes and fails closed if the installed source changes. Current
WhatsApp Web builds expose a sent message's serialized ID as `id.$1` instead of `id._serialized`;
the message-ID patch teaches the pinned library to find the sent message with either shape, and
the bridge accepts either shape in its receipt. Run the checks without writing with
`bun run check:patch`.

## Checks

```powershell
bun run typecheck
bun run test
bun run build
```
