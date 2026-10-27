"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { api, ApiError } from "@/lib/api/client";
import type { WhatsappStatus, WorkspaceSettings } from "@/lib/api/types";

function messageFor(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function isConnected(status: WhatsappStatus | null): boolean {
  return Boolean(status?.connected || status?.status === "ready");
}

function isStarting(status: WhatsappStatus | null): boolean {
  return Boolean(
    status?.initializing ||
      (status && ["starting", "retrying", "authenticated"].includes(status.status ?? "")),
  );
}

function requiresSetup(status: WhatsappStatus | null): boolean {
  return Boolean(status?.requires_action || status?.status === "qr" || status?.status === "auth_failure");
}

export function HomePage() {
  const router = useRouter();
  const [status, setStatus] = useState<WhatsappStatus | null>(null);
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let lastStartAt = 0;

    const poll = async () => {
      const results = await Promise.allSettled([api.getWhatsappStatus(), api.getSettings()]);
      if (cancelled) return;

      const statusResult = results[0];
      const settingsResult = results[1];
      if (statusResult.status === "fulfilled") {
        const nextStatus = statusResult.value;
        setStatus(nextStatus);
        setError(null);

        if (requiresSetup(nextStatus)) {
          router.replace("/setup?returnTo=%2Fwhatsapp-bill-sender");
          return;
        }

        if (!isConnected(nextStatus) && !isStarting(nextStatus) && Date.now() - lastStartAt > 5000) {
          lastStartAt = Date.now();
          void api.startWhatsapp().catch(() => {
            // The next status poll supplies the actionable state. A temporary
            // bridge/API failure must not send the user to relinking.
          });
        }
      } else {
        setError(messageFor(statusResult.reason, "WhatsApp status is temporarily unavailable."));
      }

      if (settingsResult.status === "fulfilled") {
        setSettings(settingsResult.value);
      } else {
        setError(messageFor(settingsResult.reason, "Workspace settings could not be loaded."));
      }

      setLoading(false);
      const nextStatus = statusResult.status === "fulfilled" ? statusResult.value : null;
      const keepPolling = !nextStatus || !isConnected(nextStatus) || !settingsResult.status || settingsResult.status === "rejected";
      if (keepPolling) timer = window.setTimeout(() => void poll(), 1800);
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [router]);

  const connected = isConnected(status);
  const initializing = loading || isStarting(status) || (!connected && !requiresSetup(status) && !error);
  const ready = connected && Boolean(settings?.configured) && status?.roots_synced !== false;
  const senderHref = ready ? "/whatsapp-bill-sender" : "/setup?returnTo=%2Fwhatsapp-bill-sender";
  const senderDetail = initializing
    ? "Restoring the saved WhatsApp session and checking your workspace."
    : ready
      ? "Choose documents, review the order, and send them one at a time."
      : connected
        ? "Finish document folder setup before sending."
        : "WhatsApp needs attention before documents can be sent.";

  return (
    <AppShell>
      <div className="home-hero">
        <div>
          <p className="eyebrow">Office operations</p>
          <h2>Good morning. Let&apos;s get work moving.</h2>
          <p className="intro-copy">Prepare office documents, confirm the recipient, and send with a clear delivery trail.</p>
        </div>
        <div className={`workspace-health ${ready ? "ready" : initializing ? "loading" : "needs-attention"}`}>
          <span className="status-dot" />
          {ready ? "Workspace ready" : initializing ? "Starting workspace" : "Action required"}
        </div>
      </div>

      {error && <div className="notice notice-error">{error}</div>}

      {initializing && (
        <section className="startup-card panel" aria-live="polite">
          <div className="startup-spinner"><span className="spinner dark" /></div>
          <div>
            <p className="eyebrow">Workspace startup</p>
            <h2>{status?.message ?? "Connecting to WhatsApp…"}</h2>
            <p className="muted-text">Your saved session is being restored. This page will update automatically; no relinking is needed while it is loading.</p>
          </div>
          <span className="startup-pulse" aria-hidden="true" />
        </section>
      )}

      <section className="module-grid" aria-label="Workspace modules">
        <Link className={`module-card module-card-primary ${initializing ? "module-card-loading" : ""}`} href={senderHref} aria-disabled={initializing} onClick={(event) => { if (initializing) event.preventDefault(); }}>
          <div className="module-card-top">
            <span className="module-icon" aria-hidden="true">↗</span>
            <span className={`status-pill ${ready ? "success" : initializing ? "neutral" : "warning"}`}>
              <span className="status-dot" />
              {ready ? "Ready" : initializing ? "Loading" : "Setup"}
            </span>
          </div>
          <div>
            <p className="eyebrow">Module 01</p>
            <h3>WhatsApp bill sender</h3>
            <p>{senderDetail}</p>
          </div>
          <span className="module-action">{ready ? "Open sender" : initializing ? "Waiting for WhatsApp" : "Open setup"} <span aria-hidden="true">→</span></span>
        </Link>

        <Link className="module-card module-card-secondary" href="/settings">
          <span className="module-icon" aria-hidden="true">⚙</span>
          <div>
            <p className="eyebrow">Workspace settings</p>
            <h3>Manage folders and connection</h3>
            <p>Review the WhatsApp link, import status, and local document sources.</p>
          </div>
          <span className="module-action">Open settings <span aria-hidden="true">→</span></span>
        </Link>
      </section>

      <div className="home-summary">
        <span><span className={`summary-dot ${connected ? "on" : "off"}`} /> WhatsApp {connected ? "ready" : initializing ? "starting" : "needs attention"}</span>
        <span><span className={`summary-dot ${settings?.configured ? "on" : "off"}`} /> Document folders {settings?.configured ? "configured" : "incomplete"}</span>
      </div>
    </AppShell>
  );
}
