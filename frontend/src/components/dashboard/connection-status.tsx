import type { WhatsappStatus } from "@/lib/api/types";

interface ConnectionStatusProps {
  status: WhatsappStatus | null;
  healthAvailable: boolean;
  qrUrl: string | null;
  qrLoading: boolean;
  error: string | null;
  onRetry: () => void;
}

function connectionCopy(status: WhatsappStatus | null): {
  label: string;
  detail: string;
  tone: "success" | "warning" | "danger" | "neutral";
} {
  if (status?.connected || status?.status === "ready") {
    return { label: "Connected", detail: "WhatsApp is ready to send", tone: "success" };
  }
  if (status?.status === "qr" || status?.qr_available) {
    return { label: "Scan required", detail: "Link this workspace with WhatsApp", tone: "warning" };
  }
  if (status?.status === "starting" || status?.status === "authenticated") {
    return { label: "Starting", detail: "Waiting for WhatsApp to finish loading", tone: "neutral" };
  }
  if (status?.status === "retrying" || status?.initializing) {
    return { label: "Connecting", detail: "Restoring the saved WhatsApp session", tone: "neutral" };
  }
  if (status?.requires_action === "repair") {
    return { label: "Action required", detail: "The local WhatsApp session needs attention", tone: "danger" };
  }
  if (status?.status === "auth_failure") {
    return { label: "Authentication failed", detail: "Restart Office and scan again", tone: "danger" };
  }
  if (status?.status === "error") {
    return { label: "Connection issue", detail: status.message ?? "The WhatsApp bridge needs a retry", tone: "warning" };
  }
  return { label: "Reconnecting", detail: "Waiting for WhatsApp to connect", tone: "neutral" };
}

export function ConnectionStatus({
  status,
  healthAvailable,
  qrUrl,
  qrLoading,
  error,
  onRetry,
}: ConnectionStatusProps) {
  const apiDown = !healthAvailable && Boolean(error);
  const copy = apiDown
    ? { label: "Unavailable", detail: "Office dashboard is not connected", tone: "danger" }
    : connectionCopy(status);
  const note = apiDown
    ? "Open the Office desktop shortcut, then try again."
    : copy.tone !== "success" && status?.message !== copy.detail ? status?.message : null;

  return (
    <section className="connection-card panel" aria-labelledby="connection-heading">
      <div className="connection-overview">
        <div className="connection-heading">
          <h2 id="connection-heading">WhatsApp connection</h2>
          <span className={`status-pill ${copy.tone}`} role="status">
            <span className="status-dot" aria-hidden="true" />
            {copy.label}
          </span>
        </div>
        <p className="connection-detail">{copy.detail}</p>
      </div>
      <button className="button button-quiet" type="button" onClick={onRetry}>
        <span aria-hidden="true">↻</span> Refresh status
      </button>

      {note && <p className="connection-note muted-text">{note}</p>}
      {!apiDown && (qrUrl || qrLoading) && (
        <div className="qr-panel">
          {qrUrl ? (
            // The bridge serves a local SVG/data URL; it is deliberately not optimized remotely.
            // eslint-disable-next-line @next/next/no-img-element
            <img className="qr-image" src={qrUrl} alt="WhatsApp pairing QR code" />
          ) : (
            <div className="qr-placeholder" role="status" aria-label="Loading QR code">
              <span className="spinner dark" />
            </div>
          )}
          <div>
            <strong>Scan to connect</strong>
            <p className="muted-text">Open WhatsApp → Linked devices → Link a device.</p>
          </div>
        </div>
      )}

      {error && <p className="inline-error">{error}</p>}
    </section>
  );
}
