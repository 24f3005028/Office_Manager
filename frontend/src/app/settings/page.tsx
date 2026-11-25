"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/layout/icons";
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
      <header className="setup-header">
        <div>
          <h1>Settings</h1>
          <p className="intro-copy">Connect WhatsApp and choose where your bill files are saved.</p>
        </div>
      </header>
      {error && <div className="notice notice-error">{error}</div>}
      <section className="panel settings-access-card">
        <span className="status-icon"><Icon name="phone" width="20" height="20" /></span>
        <div><h2>Android app</h2><p className="muted-text">Manage approved people, connect phones and update the party list.</p></div>
        <Link href="/mobile-access" className="button button-secondary">Manage mobile access</Link>
      </section>
      <div className="settings-layout">
        <section className="panel settings-connection-card">
          <div className="section-heading compact-heading">
            <h2>WhatsApp account</h2>
            <span className={`status-pill ${connected ? "success" : "warning"}`}><span className="status-dot" />{connected ? "Connected" : "Setup needed"}</span>
          </div>
          <p className="muted-text">{connected ? "WhatsApp is connected to this computer." : "Link WhatsApp before opening the sender."}</p>
          <Link className="button button-primary" href="/setup">{connected ? "Review setup" : "Link WhatsApp"}</Link>
        </section>
        {settings && <section className="panel settings-folders-card"><FolderSettingsForm settings={settings} onSaved={setSettings} /></section>}
      </div>
    </AppShell>
  );
}
