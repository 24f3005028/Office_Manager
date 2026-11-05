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
  const ready = connected && Boolean(settings?.configured) && status?.roots_synced !== false;
  const senderHref = requiresSetup(status) || (connected && settings?.configured === false)
    ? "/setup?returnTo=%2Fwhatsapp-bill-sender" : "/whatsapp-bill-sender";
  return <AppShell>
    <div className="home-hero">
      <p className="eyebrow">Daily work</p>
      <h1>What would you like to do?</h1>
      <p className="intro-copy">Choose a task below. We will guide you through each step.</p>
    </div>
    {error && <div className="notice notice-error" role="alert">{error} You can still open a task and check its connection.</div>}
    <section className="task-grid" aria-label="Choose a task">
      <Link className="task-card" href={senderHref}>
        <div className="task-card-top"><span className="task-icon"><Icon name="send" width="30" height="30" /></span><span className={`status-pill ${ready ? "success" : initializing ? "neutral" : "warning"}`}><span className="status-dot" />{ready ? "WhatsApp ready" : initializing ? "Connecting WhatsApp" : "Check WhatsApp"}</span></div>
        <h2>Send bills on WhatsApp</h2>
        <p>Find the bills and send them to one contact.</p>
        <ol className="task-steps"><li>Choose the dates</li><li>Choose a contact</li><li>Check the bills and send</li></ol>
        <span className="button button-primary">Open bill sender <Icon name="arrow" /></span>
      </Link>
      <Link className="task-card" href="/pouncha-sync">
        <div className="task-card-top"><span className="task-icon green"><Icon name="sync" width="30" height="30" /></span><span className="status-pill neutral">Runs when you click</span></div>
        <h2>Update Pouncha sheet</h2>
        <p>Add new BUSY sales bills to your Google Sheet.</p>
        <ol className="task-steps"><li>Check the last saved bill</li><li>Choose the dates</li><li>Click Update sheet</li></ol>
        <span className="button button-primary">Open Pouncha <Icon name="arrow" /></span>
      </Link>
    </section>
    <section className="home-help panel"><span className="help-icon"><Icon name="help" /></span><div><h2>Setting up this computer?</h2><p>Connect WhatsApp and choose the folders where your bills are saved.</p></div><Link className="button button-secondary" href="/settings">Open settings <Icon name="arrow" /></Link></section>
    <div className="home-summary"><span><span className={`summary-dot ${connected ? "on" : "off"}`} />WhatsApp: {connected ? "Connected" : initializing ? "Connecting…" : "Needs attention"}</span><span><Icon name="folder" width="17" height="17" />Bill folders: {settings?.configured ? "Ready" : "Check settings"}</span></div>
  </AppShell>;
}
