"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/layout/icons";
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

        if (!requiresSetup(nextStatus) && !isConnected(nextStatus) && !isStarting(nextStatus) && Date.now() - lastStartAt > 5000) {
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
      const keepPolling = !nextStatus || !isConnected(nextStatus) || settingsResult.status === "rejected";
      if (keepPolling) timer = window.setTimeout(() => void poll(), 1800);
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  const connected = isConnected(status);
  const initializing = loading || isStarting(status) || (!connected && !requiresSetup(status) && !error);
  const senderHref = requiresSetup(status) || (connected && settings?.configured === false)
    ? "/setup?returnTo=%2Fwhatsapp-bill-sender" : "/whatsapp-bill-sender";
  const whatsappLabel = connected ? "Connected" : initializing ? "Connecting…" : error && !status ? "Unavailable" : "Needs attention";
  const foldersReady = settings?.configured && status?.roots_synced !== false;
  const foldersLabel = !settings ? (loading ? "Checking…" : "Unavailable") :
    foldersReady ? "Ready" : settings.configured ? "Sync pending" : "Setup needed";

  return <AppShell>
    <header className="home-hero">
      <div className="home-hero-copy">
        <h1>Office workspace</h1>
        <p>Send customer bills and keep your Pouncha sheet up to date.</p>
      </div>
      <div className="hero-illustration" aria-hidden="true">
        <span className="hero-document hero-sheet"><Icon name="sheet" width="32" height="32" /></span>
        <span className="hero-document hero-bill"><Icon name="file" width="43" height="43" /></span>
        <span className="hero-document hero-send"><Icon name="send" width="21" height="21" /></span>
      </div>
    </header>
    <section className="home-section" aria-labelledby="workflows-heading">
      <h2 id="workflows-heading">Daily workflows</h2>
      <div className="task-grid">
        <article className="task-card">
          <span className="task-icon"><Icon name="send" width="25" height="25" /></span>
          <h3>Send bills on WhatsApp</h3>
          <p>Find PDF bills by date, review the files, and send them to a contact.</p>
          <Link className="button button-primary" href={senderHref}>Open bill sender</Link>
        </article>
        <article className="task-card">
          <span className="task-icon green"><Icon name="sheet" width="25" height="25" /></span>
          <h3>Update Pouncha sheet</h3>
          <p>Find missing sales bills in BUSY and add them to your Google Sheet.</p>
          <Link className="button button-secondary" href="/pouncha-sync">Open Pouncha</Link>
        </article>
      </div>
    </section>
    <section className="home-section" aria-labelledby="readiness-heading">
      <div className="home-section-heading"><h2 id="readiness-heading">Workspace status</h2><Link href="/settings">Open settings</Link></div>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <ul className="workspace-status panel" aria-live="polite">
        <li><span className="status-icon"><Icon name="chat" width="20" height="20" /></span><strong>WhatsApp</strong><span className={`status-pill ${connected ? "success" : initializing ? "neutral" : "warning"}`}><span className="status-dot" />{whatsappLabel}</span></li>
        <li><span className="status-icon"><Icon name="folder" width="20" height="20" /></span><strong>Bill folders</strong><span className={`status-pill ${foldersReady ? "success" : loading ? "neutral" : "warning"}`}><span className="status-dot" />{foldersLabel}</span></li>
      </ul>
    </section>
  </AppShell>;
}
