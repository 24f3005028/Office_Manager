"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { FolderSettingsForm } from "@/components/settings/folder-settings-form";
import { api, ApiError } from "@/lib/api/client";
import type { WhatsappStatus, WorkspaceSettings } from "@/lib/api/types";

function messageFor(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export default function SettingsRoute() {
  const [status, setStatus] = useState<WhatsappStatus | null>(null);
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([api.getWhatsappStatus(), api.getSettings()])
      .then(([nextStatus, nextSettings]) => {
        setStatus(nextStatus);
        setSettings(nextSettings);
      })
      .catch((reason) => setError(messageFor(reason, "Settings could not be loaded.")));
  }, []);

  const connected = Boolean(status?.connected || status?.status === "ready");

  return (
    <AppShell>
      <div className="setup-header">
        <div>
          <p className="eyebrow">Workspace settings</p>
          <h2>Keep the setup under control.</h2>
          <p className="intro-copy">Manage the local WhatsApp link and the folders the backend scans for bills, credit notes, and debit notes.</p>
        </div>
        <Link className="button button-secondary" href="/">Back home</Link>
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      <div className="settings-layout">
        <section className="panel settings-connection-card">
          <div className="section-heading compact-heading">
            <div><p className="eyebrow">WhatsApp connection</p><h2>Linked sending account</h2></div>
            <span className={`status-pill ${connected ? "success" : "warning"}`}><span className="status-dot" />{connected ? "Connected" : "Setup needed"}</span>
          </div>
          <p className="muted-text">{connected ? "The local bridge is ready and contacts can be imported by the sender." : "Link WhatsApp before opening the sender."}</p>
          <Link className="button button-primary" href="/setup">{connected ? "Review setup" : "Link WhatsApp"} <span aria-hidden="true">↗</span></Link>
        </section>
        {settings && <section className="panel settings-folders-card"><FolderSettingsForm settings={settings} onSaved={setSettings} /></section>}
      </div>
    </AppShell>
  );
}
