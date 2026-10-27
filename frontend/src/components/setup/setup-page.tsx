"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { FolderSettingsForm } from "@/components/settings/folder-settings-form";
import { api, ApiError } from "@/lib/api/client";
import type { Contact, WhatsappStatus, WorkspaceSettings } from "@/lib/api/types";

function messageFor(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function connected(status: WhatsappStatus | null): boolean {
  return Boolean(status?.connected || status?.status === "ready");
}

function statusLabel(status: WhatsappStatus | null): string {
  if (connected(status)) return "Connected";
  if (status?.status === "qr" || status?.qr_available) return "Scan required";
  if (status?.status === "starting" || status?.status === "authenticated" || status?.status === "retrying" || status?.initializing) return "Starting";
  if (status?.requires_action === "repair") return "Repair required";
  if (status?.status === "error") return "Connection issue";
  return "Not linked";
}

export function SetupPage() {
  const router = useRouter();
  const [returnTo, setReturnTo] = useState("/whatsapp-bill-sender");
  const [status, setStatus] = useState<WhatsappStatus | null>(null);
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contactsLoaded, setContactsLoaded] = useState(false);
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [qrLoading, setQrLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const whatsappState = status?.status;
  const whatsappConnected = connected(status);
  const qrAvailable = Boolean(status?.qr_available);

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, nextSettings] = await Promise.all([api.getWhatsappStatus(), api.getSettings()]);
      setStatus(nextStatus);
      setSettings(nextSettings);
      setError(null);
    } catch (reason) {
      setError(messageFor(reason, "Workspace setup could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.getWhatsappStatus());
      setError(null);
    } catch (reason) {
      setError(messageFor(reason, "WhatsApp status could not be refreshed."));
    }
  }, []);

  useEffect(() => {
    const queryReturnTo = new URLSearchParams(window.location.search).get("returnTo");
    if (queryReturnTo?.startsWith("/")) setReturnTo(queryReturnTo);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (whatsappState === undefined || whatsappConnected) return;
    let cancelled = false;
    setStarting(true);
    void api.startWhatsapp()
      .then((nextStatus) => {
        if (!cancelled) setStatus(nextStatus);
      })
      .catch((reason) => {
        if (!cancelled) setError(messageFor(reason, "WhatsApp could not be started. Check that the local bridge is running."));
      })
      .finally(() => {
        if (!cancelled) setStarting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [whatsappConnected, whatsappState]);

  useEffect(() => {
    if (!qrAvailable && whatsappState !== "qr") {
      setQrUrl(null);
      return;
    }
    let cancelled = false;
    setQrLoading(true);
    void api.getQr()
      .then((url) => {
        if (!cancelled) setQrUrl(url || null);
      })
      .catch((reason) => {
        if (!cancelled) setError(messageFor(reason, "The WhatsApp QR code is not available yet."));
      })
      .finally(() => {
        if (!cancelled) setQrLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [qrAvailable, whatsappState]);

  useEffect(() => {
    const interval = window.setInterval(() => void refreshStatus(), 2000);
    return () => window.clearInterval(interval);
  }, [refreshStatus]);

  useEffect(() => {
    if (!whatsappConnected) {
      setContacts([]);
      setContactsLoaded(false);
      return;
    }
    let cancelled = false;
    void api.getContacts()
      .then((nextContacts) => {
        if (cancelled) return;
        setContacts(nextContacts);
        setContactsLoaded(true);
      })
      .catch((reason) => {
        if (!cancelled) {
          setContactsLoaded(false);
          setError(messageFor(reason, "Contacts could not be imported. Retry after WhatsApp finishes loading."));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [whatsappConnected]);

  useEffect(() => {
    return () => {
      if (qrUrl?.startsWith("blob:")) URL.revokeObjectURL(qrUrl);
    };
  }, [qrUrl]);

  const currentStep = useMemo(() => {
    if (!whatsappConnected) return 1;
    if (!contactsLoaded) return 2;
    return 3;
  }, [contactsLoaded, whatsappConnected]);
  const complete = Boolean(whatsappConnected && contactsLoaded && settings?.configured);

  async function reconnect() {
    setReconnecting(true);
    setError(null);
    try {
      setStatus(await api.reconnectWhatsapp());
      setContactsLoaded(false);
    } catch (reason) {
      setError(messageFor(reason, "WhatsApp could not be restarted."));
    } finally {
      setReconnecting(false);
    }
  }

  if (loading) {
    return <AppShell><div className="page-loading"><span className="spinner dark" /> Preparing workspace setup…</div></AppShell>;
  }

  return (
    <AppShell>
      <div className="setup-header">
        <div>
          <p className="eyebrow">Workspace setup</p>
          <h2>Make sending effortless.</h2>
          <p className="intro-copy">Link WhatsApp once, import the contacts you already use, and point the dashboard at your document folders.</p>
        </div>
        <Link className="button button-secondary" href="/">Back home</Link>
      </div>

      <div className="setup-progress" aria-label="Setup progress">
        {["Link WhatsApp", "Import contacts", "Choose folders"].map((label, index) => {
          const step = index + 1;
          const done = step === 1 ? connected(status) : step === 2 ? contactsLoaded : Boolean(settings?.configured);
          return (
            <div className={currentStep === step ? "setup-progress-step active" : done ? "setup-progress-step done" : "setup-progress-step"} key={label}>
              <span>{done ? "✓" : String(step).padStart(2, "0")}</span>
              <strong>{label}</strong>
            </div>
          );
        })}
      </div>

      {error && <div className="notice notice-error">{error}</div>}

      <div className="setup-layout">
        <section className="panel setup-main-card">
          <div className="setup-main-heading">
            <div>
              <p className="eyebrow">Step {String(currentStep).padStart(2, "0")}</p>
              <h2>{currentStep === 1 ? "Link your WhatsApp workspace" : currentStep === 2 ? "Import your contacts" : "Choose document folders"}</h2>
            </div>
            <span className={`status-pill ${complete ? "success" : "warning"}`}><span className="status-dot" />{complete ? "Ready" : statusLabel(status)}</span>
          </div>

          {!connected(status) && (
            <div className="whatsapp-link-panel">
              <div className="whatsapp-link-copy">
                <span className="module-icon whatsapp-icon" aria-hidden="true">◔</span>
                <div>
                  <h3>{starting ? "Starting the local bridge…" : "Scan once to link WhatsApp"}</h3>
                  <p>{status?.status === "auth_failure" ? "The previous session could not be authenticated. Start a fresh link and scan the new code." : "Keep WhatsApp open on your phone while you link this local workspace."}</p>
                </div>
              </div>
              {(qrUrl || qrLoading) ? (
                <div className="setup-qr-block">
                  {qrUrl ? (
                    // The local bridge returns a short-lived SVG/data URL; remote image optimization is not useful here.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img className="setup-qr" src={qrUrl} alt="WhatsApp pairing QR code" />
                  ) : <div className="setup-qr qr-loading"><span className="spinner dark" /></div>}
                  <div>
                    <strong>Open WhatsApp → Linked devices → Link a device</strong>
                    <p className="muted-text">Scan this code from the phone that should send the documents.</p>
                  </div>
                </div>
              ) : (
                <div className="setup-waiting-state">
                  <span className="spinner dark" />
                  <span>{status?.status === "starting" || starting ? "Waiting for WhatsApp to provide a QR code…" : "Waiting for the local bridge…"}</span>
                </div>
              )}
              <div className="setup-actions">
                <button className="button button-primary" type="button" onClick={() => void refresh()} disabled={starting}>Refresh connection</button>
                <button className="button button-secondary" type="button" onClick={() => void reconnect()} disabled={reconnecting}>{reconnecting ? "Restarting…" : "Restart linking"}</button>
              </div>
            </div>
          )}

          {connected(status) && !contactsLoaded && (
            <div className="setup-success-panel">
              <div className="success-mark">✓</div>
              <div>
                <h3>WhatsApp is linked</h3>
                <p>Contact import is running so the sender can use the live WhatsApp address book.</p>
              </div>
              <button className="button button-secondary" type="button" onClick={() => { setContactsLoaded(false); void api.getContacts().then((items) => { setContacts(items); setContactsLoaded(true); }).catch((reason) => setError(messageFor(reason, "Contacts could not be imported."))); }}>Retry import</button>
            </div>
          )}

          {connected(status) && contactsLoaded && (
            <div className="contacts-imported-panel">
              <div className="success-mark">✓</div>
              <div>
                <h3>Contacts imported</h3>
                <p>{contacts.length ? `${contacts.length} contacts are available in the sender.` : "WhatsApp is linked; no individual contacts were returned yet."}</p>
              </div>
              <span className="status-pill success">Live address book</span>
            </div>
          )}

          {connected(status) && contactsLoaded && settings && (
            <FolderSettingsForm settings={settings} onSaved={setSettings} />
          )}

          {complete && (
            <div className="setup-complete-banner">
              <div>
                <p className="eyebrow">All set</p>
                <h3>Your workspace is ready for professional dispatch.</h3>
              </div>
              <button className="button button-accent" type="button" onClick={() => router.push(returnTo)}>Open WhatsApp sender <span aria-hidden="true">↗</span></button>
            </div>
          )}
        </section>

        <aside className="setup-side-column">
          <section className="panel setup-checklist-card">
            <p className="eyebrow">Readiness</p>
            <h2>One clear path to send</h2>
            <ul className="readiness-list">
              <li className={connected(status) ? "complete" : ""}><span>{connected(status) ? "✓" : "1"}</span><div><strong>WhatsApp linked</strong><small>{connected(status) ? "Ready to send" : "Scan the QR code"}</small></div></li>
              <li className={contactsLoaded ? "complete" : ""}><span>{contactsLoaded ? "✓" : "2"}</span><div><strong>Contacts imported</strong><small>{contactsLoaded ? `${contacts.length} contacts available` : "Live address book"}</small></div></li>
              <li className={settings?.configured ? "complete" : ""}><span>{settings?.configured ? "✓" : "3"}</span><div><strong>Folders configured</strong><small>{settings?.configured ? "Bills, CNs, and DNs ready" : "Add all three document types"}</small></div></li>
            </ul>
          </section>
          <section className="panel setup-note-card">
            <p className="eyebrow">Local by design</p>
            <h3>Documents stay on this workstation.</h3>
            <p>Folder paths and the WhatsApp session are kept in the local workspace. Sends continue one document at a time for predictable delivery.</p>
          </section>
        </aside>
      </div>
    </AppShell>
  );
}
