"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { api, ApiError } from "@/lib/api/client";
import { dateRangeFor, isValidDateRange, toDateInput, type DatePreset, type DateRange } from "@/lib/date";
import { sortDocuments } from "@/lib/documents";
import type {
  Contact,
  DocumentRecord,
  DocumentType,
  SendJob,
  WhatsappStatus,
  WorkspaceSettings,
} from "@/lib/api/types";
import { ConnectionStatus } from "./connection-status";
import { ContactPicker } from "./contact-picker";
import { DateFilter } from "./date-filter";
import { DocumentPreviewTable } from "./document-preview-table";
import { DocumentTypeFilter } from "./document-type-filter";
import { JobProgress } from "./job-progress";
import { SendConfirmation } from "./send-confirmation";

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function initialDateRange(): DateRange {
  const today = toDateInput(new Date());
  return { startDate: today, endDate: today };
}

export function DashboardPage() {
  const router = useRouter();
  const [datePreset, setDatePreset] = useState<DatePreset>("today");
  const [dateRange, setDateRange] = useState<DateRange>(initialDateRange);
  const [documentTypes, setDocumentTypes] = useState<DocumentType[]>(["bill", "credit_note", "debit_note"]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [hasPreviewed, setHasPreviewed] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [contactsError, setContactsError] = useState<string | null>(null);
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null);
  const [status, setStatus] = useState<WhatsappStatus | null>(null);
  const [workspaceSettings, setWorkspaceSettings] = useState<WorkspaceSettings | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [healthAvailable, setHealthAvailable] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [qrUrl, setQrUrl] = useState<string | null>(null);
  const [qrLoading, setQrLoading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [job, setJob] = useState<SendJob | null>(null);
  const [cancelling, setCancelling] = useState(false);

  const refreshConnection = useCallback(async () => {
    const results = await Promise.allSettled([api.getHealth(), api.getWhatsappStatus()]);
    const healthResult = results[0];
    const statusResult = results[1];
    const apiIsAvailable = healthResult.status === "fulfilled";
    setHealthAvailable(apiIsAvailable);
    if (statusResult.status === "fulfilled") {
      setStatus(statusResult.value);
      setConnectionError(null);
    } else {
      setStatus(null);
      setConnectionError(errorMessage(statusResult.reason, "WhatsApp status is unavailable."));
    }
    if (!apiIsAvailable && healthResult.status === "rejected") {
      setConnectionError("The dashboard API is unavailable.");
    }
  }, []);

  useEffect(() => {
    void refreshConnection();
    const interval = window.setInterval(() => void refreshConnection(), 10000);
    return () => window.clearInterval(interval);
  }, [refreshConnection]);

  useEffect(() => {
    let cancelled = false;
    void api.getSettings()
      .then((nextSettings) => {
        if (!cancelled) {
          setWorkspaceSettings(nextSettings);
          setSettingsError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) setSettingsError(errorMessage(error, "Workspace settings are unavailable."));
      })
      .finally(() => {
        if (!cancelled) setSettingsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const shouldLoadQr = Boolean(status?.qr_available || status?.status === "qr");
    if (!shouldLoadQr) {
      setQrUrl(null);
      return;
    }
    let cancelled = false;
    setQrLoading(true);
    void api.getQr()
      .then((url) => {
        if (!cancelled) setQrUrl(url || null);
      })
      .catch(() => {
        if (!cancelled) setQrUrl(null);
      })
      .finally(() => {
        if (!cancelled) setQrLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [status?.qr_available, status?.status]);

  useEffect(() => {
    return () => {
      if (qrUrl?.startsWith("blob:")) URL.revokeObjectURL(qrUrl);
    };
  }, [qrUrl]);

  const loadContacts = useCallback(async () => {
    setContactsLoading(true);
    setContactsError(null);
    try {
      setContacts(await api.getContacts());
    } catch (error) {
      setContactsError(errorMessage(error, "Contacts could not be loaded."));
      setContacts([]);
    } finally {
      setContactsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (status?.connected || status?.status === "ready") void loadContacts();
    else {
      setContacts([]);
      setSelectedContact(null);
    }
  }, [loadContacts, status?.connected, status?.status]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const updated = await api.getSendJob(job.job_id);
        if (cancelled) return;
        setJob(updated);
        setSendError(null);
        if (["queued", "running"].includes(updated.status)) {
          timer = window.setTimeout(() => void poll(), 1500);
        }
      } catch (error) {
        if (!cancelled) {
          setSendError(errorMessage(error, "Could not update send progress. Retrying…"));
          timer = window.setTimeout(() => void poll(), 3000);
        }
      }
    };
    timer = window.setTimeout(() => void poll(), 900);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [job]);

  useEffect(() => {
    let cancelled = false;
    void api.listSendJobs()
      .then((jobs) => {
        if (cancelled) return;
        const activeJob = jobs.find((candidate) => ["queued", "running"].includes(candidate.status));
        if (activeJob) setJob(activeJob);
      })
      .catch(() => {
        // Restoring an old job is helpful but must not block the sender.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setHasPreviewed(false);
    setDocuments([]);
    setPreviewError(null);
  }, [dateRange.endDate, dateRange.startDate, documentTypes]);

  const connected = Boolean(status?.connected || status?.status === "ready");
  const explicitBridgeAction = Boolean(
    status?.requires_action || status?.status === "qr" || status?.status === "auth_failure",
  );
  const setupRequired = Boolean(workspaceSettings && workspaceSettings.configured === false && connected);
  const redirectRequired = explicitBridgeAction || setupRequired;
  const workspaceReady = connected && Boolean(workspaceSettings?.configured) && status?.roots_synced !== false;
  const validFilters = isValidDateRange(dateRange) && documentTypes.length > 0;
  const activeJob = job && ["queued", "running"].includes(job.status);
  const canSend = workspaceReady && hasPreviewed && documents.length > 0 && Boolean(selectedContact) && !activeJob;

  useEffect(() => {
    if (redirectRequired) router.replace("/setup?returnTo=%2Fwhatsapp-bill-sender");
  }, [redirectRequired, router]);

  const previewSummary = useMemo(() => {
    if (!hasPreviewed) return "Choose filters, then preview the matching documents.";
    if (previewLoading) return "Scanning the selected folders…";
    return `${documents.length} ${documents.length === 1 ? "document" : "documents"} in send order`;
  }, [documents.length, hasPreviewed, previewLoading]);

  function chooseDatePreset(preset: DatePreset) {
    setDatePreset(preset);
    if (preset !== "custom") setDateRange(dateRangeFor(preset));
  }

  function updateDateRange(next: DateRange) {
    setDatePreset("custom");
    setDateRange(next);
  }

  async function previewDocuments() {
    if (!validFilters) return;
    setPreviewLoading(true);
    setPreviewError(null);
    setHasPreviewed(true);
    try {
      const result = await api.getDocuments({
        startDate: dateRange.startDate,
        endDate: dateRange.endDate,
        documentTypes,
      });
      setDocuments(sortDocuments(result));
    } catch (error) {
      setDocuments([]);
      setPreviewError(errorMessage(error, "Documents could not be loaded."));
    } finally {
      setPreviewLoading(false);
    }
  }

  async function confirmSend(rawMessage: string) {
    if (!selectedContact || !canSend) return;
    setSubmitting(true);
    setSendError(null);
    try {
      const message = rawMessage.trim();
      const created = await api.createSendJob({
        file_ids: documents.map((document) => document.file_id),
        recipient: selectedContact.id,
        message: message ? message : undefined,
      });
      setJob(created);
      setConfirming(false);
    } catch (error) {
      setSendError(errorMessage(error, "The send job could not be created."));
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelJob() {
    if (!job) return;
    setCancelling(true);
    setSendError(null);
    try {
      setJob(await api.cancelSendJob(job.job_id));
    } catch (error) {
      setSendError(errorMessage(error, "The send job could not be cancelled."));
    } finally {
      setCancelling(false);
    }
  }

  if (settingsLoading || redirectRequired) {
    return (
      <AppShell>
        <div className="page-loading">
          <span className="spinner dark" />
          {redirectRequired ? "Opening workspace setup…" : "Checking workspace readiness…"}
        </div>
        {settingsError && <p className="inline-error">{settingsError}</p>}
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="dashboard-intro">
        <div>
          <p className="eyebrow">Document dispatch</p>
          <h2>Prepare a clean send</h2>
          <p className="intro-copy">Find the right documents, review the order, and send them to one WhatsApp contact.</p>
        </div>
        <div className="date-stamp">
          <span>Today</span>
          <strong>{toDateInput(new Date())}</strong>
        </div>
      </div>

      <ConnectionStatus
        status={status}
        healthAvailable={healthAvailable}
        qrUrl={qrUrl}
        qrLoading={qrLoading}
        error={connectionError ?? settingsError}
        onRetry={() => void refreshConnection()}
      />

      <div className="workspace-grid">
        <aside className="control-column">
          <section className="panel filter-panel" aria-labelledby="filters-heading">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Step 01</p>
                <h2 id="filters-heading">Choose documents</h2>
              </div>
              <span className="step-number">1</span>
            </div>
            <DateFilter
              preset={datePreset}
              range={dateRange}
              onPresetChange={chooseDatePreset}
              onRangeChange={updateDateRange}
            />
            <DocumentTypeFilter value={documentTypes} onChange={setDocumentTypes} />
            {!validFilters && (
              <p className="field-error">Select at least one type and a valid date range.</p>
            )}
            <button
              className="button button-primary full-width"
              type="button"
              disabled={!validFilters || previewLoading}
              onClick={() => void previewDocuments()}
            >
              {previewLoading ? <><span className="spinner" /> Scanning…</> : <>Preview documents <span aria-hidden="true">↗</span></>}
            </button>
            {previewError && <p className="inline-error">{previewError}</p>}
          </section>

          <section className="panel contact-panel" aria-labelledby="recipient-heading">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Step 02</p>
                <h2 id="recipient-heading">Choose recipient</h2>
              </div>
              <span className="step-number">2</span>
            </div>
            <ContactPicker
              contacts={contacts}
              selected={selectedContact}
              loading={contactsLoading}
              error={contactsError}
              disabled={!connected}
              onSelect={setSelectedContact}
              onRetry={() => void loadContacts()}
            />
          </section>
        </aside>

        <section className="panel preview-panel" aria-labelledby="preview-heading">
          <div className="section-heading preview-heading">
            <div>
              <p className="eyebrow">Step 03</p>
              <h2 id="preview-heading">Preview &amp; send</h2>
              <p className="muted-text">{previewSummary}</p>
            </div>
            {hasPreviewed && documents.length > 0 && <span className="count-badge">{documents.length} files</span>}
          </div>

          {!hasPreviewed ? (
            <div className="preview-placeholder">
              <div className="preview-art" aria-hidden="true">
                <span className="art-back" /><span className="art-front" /><span className="art-line one" /><span className="art-line two" />
              </div>
              <h3>Your ordered preview will appear here</h3>
              <p>Use the filters on the left to scan your local document folders.</p>
            </div>
          ) : (
            <DocumentPreviewTable
              documents={documents}
            />
          )}

          <div className="preview-footer">
            <p className="muted-text">
              {!workspaceReady
                ? "Waiting for WhatsApp and document folders to finish syncing."
                : selectedContact
                  ? <>Ready for <strong>{selectedContact.name}</strong>.</>
                  : "Select a recipient to enable sending."}
            </p>
            <button
              className="button button-accent"
              type="button"
              disabled={!canSend}
              onClick={() => setConfirming(true)}
            >
              Review &amp; send <span aria-hidden="true">↗</span>
            </button>
          </div>
          {sendError && <p className="inline-error send-error">{sendError}</p>}
        </section>
      </div>

      {job && <JobProgress job={job} cancelling={cancelling} onCancel={() => void cancelJob()} />}

      {confirming && selectedContact && (
        <SendConfirmation
          contact={selectedContact}
          documents={documents}
          defaultMessage={`Documents for ${dateRange.startDate} to ${dateRange.endDate}`}
          submitting={submitting}
          onCancel={() => setConfirming(false)}
          onConfirm={(message) => void confirmSend(message)}
        />
      )}
    </AppShell>
  );
}
