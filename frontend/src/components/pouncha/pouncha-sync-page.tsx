"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { api, ApiError } from "@/lib/api/client";
import type { PounchaSyncRun, PounchaSyncStatus } from "@/lib/api/types";
import { toDateInput } from "@/lib/date";

function messageFor(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function defaultDates(): { startDate: string; endDate: string } {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 3);
  return { startDate: toDateInput(start), endDate: toDateInput(end) };
}

function formatDateTime(value: string | null, timeZone = "Asia/Kolkata"): string {
  if (!value) return "—";
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  }).format(new Date(timestamp));
}

function formatDate(value: string): string {
  const timestamp = Date.parse(`${value}T00:00:00`);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(timestamp));
}

function triggerLabel(value: string): string {
  switch (value) {
    case "scheduled_midnight":
      return "Midnight";
    case "startup_catchup":
      return "Catch-up";
    case "manual_busy":
      return "Manual BUSY";
    case "manual_excel":
      return "Excel upload";
    default:
      return value;
  }
}

function statusLabel(status: PounchaSyncRun["status"]): string {
  switch (status) {
    case "success":
      return "Success";
    case "failed":
      return "Failed";
    case "skipped":
      return "Skipped";
    case "running":
      return "Running";
    case "queued":
      return "Queued";
    default:
      return status;
  }
}

function statusTone(status: PounchaSyncRun["status"]): string {
  if (status === "success") return "success";
  if (status === "failed") return "danger";
  if (status === "skipped") return "warning";
  return "neutral";
}

function isActive(run: PounchaSyncRun | null | undefined): boolean {
  return Boolean(run && (run.status === "queued" || run.status === "running"));
}

export function PounchaSyncPage() {
  const [status, setStatus] = useState<PounchaSyncStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [dates, setDates] = useState(defaultDates);
  const [queuedRunId, setQueuedRunId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await api.getPounchaStatus();
      setStatus(next);
      setError(null);
      if (queuedRunId) {
        const finished = next.recent_runs.find(
          (run) => run.run_id === queuedRunId && !isActive(run),
        );
        if (finished) {
          setMessage(
            finished.status === "success"
              ? `Sync complete: ${finished.appended_count} new bill${
                  finished.appended_count === 1 ? "" : "s"
                } added to POUNCHA 26-27.`
              : `Sync ${statusLabel(finished.status).toLowerCase()}: ${
                  finished.error_message ?? "No detail was recorded."
                }`,
          );
          setQueuedRunId(null);
        }
      }
    } catch (loadError) {
      setError(messageFor(loadError, "Pouncha sync status could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [queuedRunId]);

  useEffect(() => {
    let cancelled = false;
    void load();
    const timer = window.setInterval(() => {
      if (!cancelled) void load();
    }, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [load]);

  async function syncNow() {
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const queued = await api.runPounchaSync({
        start_date: dates.startDate,
        end_date: dates.endDate,
      });
      setQueuedRunId(queued.run_id);
      setMessage("Sync queued. BUSY 21 is being driven in the background.");
      await load();
    } catch (syncError) {
      setError(messageFor(syncError, "The Pouncha sync could not be queued."));
    } finally {
      setSubmitting(false);
    }
  }

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    setMessage(null);
    try {
      const run = await api.uploadPounchaExcel(file, {
        startDate: dates.startDate,
        endDate: dates.endDate,
      });
      setMessage(
        run.status === "success"
          ? `Upload complete: ${run.appended_count} new bill${
              run.appended_count === 1 ? "" : "s"
            } added to POUNCHA 26-27.`
          : `Upload ${statusLabel(run.status).toLowerCase()}: ${
              run.error_message ?? "No detail was recorded."
            }`,
      );
      await load();
    } catch (uploadError) {
      setError(
        messageFor(uploadError, "The sales ledger workbook could not be uploaded."),
      );
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  const configured = Boolean(status?.configured);
  const uploadConfigured = Boolean(status?.upload_configured);
  const active = isActive(status?.active_run);
  const waitingForBusy = Boolean(status?.scheduler.waiting_for_busy);
  const lastSuccess = status?.recent_runs.find((run) => run.status === "success");
  const recentRuns = status?.recent_runs.slice(0, 5) ?? [];

  const badge = !status?.sync_enabled
    ? { tone: "warning", label: "Sync disabled" }
    : !status.sheets_configured
      ? { tone: "warning", label: "Setup required" }
      : !status.busy_configured
        ? { tone: "warning", label: "BUSY automation unavailable" }
        : !status.busy_calibrated
          ? { tone: "warning", label: "Calibration required" }
          : waitingForBusy
            ? { tone: "warning", label: "Waiting for BUSY 21" }
            : active
              ? { tone: "neutral", label: "Sync running" }
              : { tone: "success", label: "Ready" };

  return (
    <AppShell>
      <div className="pouncha-header">
        <div>
          <p className="eyebrow">Daily sales sync</p>
          <h2>Pouncha 26-27</h2>
          <p className="intro-copy">
            Pull every BUSY Sale bill from the Account Ledger into the
            <strong> POUNCHA 26-27 </strong>
            Google Sheet. Existing bill numbers and Column H remarks are never
            touched.
          </p>
        </div>
        <span className={`status-pill ${badge.tone}`}>
          <span className="status-dot" />
          {badge.label}
        </span>
      </div>

      {error && <div className="notice notice-error">{error}</div>}
      {message && <div className="notice notice-success">{message}</div>}

      {loading && !status ? (
        <section className="panel pouncha-loading">
          <span className="spinner dark" />
          <span>Checking the scheduler and recent runs…</span>
        </section>
      ) : (
        <>
          <section className="pouncha-metrics" aria-label="Sync status">
            <div className="panel pouncha-metric">
              <span>Next auto-sync</span>
              <strong>
                {status?.scheduler.enabled
                  ? formatDateTime(status.scheduler.next_run_at)
                  : "Disabled"}
              </strong>
              <small>Daily at 12:00 AM IST · 3-day lookback</small>
            </div>
            <div className="panel pouncha-metric">
              <span>Last successful sync</span>
              <strong>
                {lastSuccess
                  ? `${lastSuccess.appended_count} new bill${
                      lastSuccess.appended_count === 1 ? "" : "s"
                    }`
                  : "No sync yet"}
              </strong>
              <small>
                {lastSuccess
                  ? formatDateTime(lastSuccess.completed_at)
                  : "The first run will append the current window."}
              </small>
            </div>
            <div className="panel pouncha-metric">
              <span>Google Sheet</span>
              <strong>{status?.sheets_configured ? "Connected" : "Not configured"}</strong>
              <small>POUNCHA 26-27 · Columns A–G only</small>
            </div>
            <div className="panel pouncha-metric">
              <span>Scheduler</span>
              <strong>
                {status?.scheduler.running
                  ? "Running"
                  : status?.scheduler.enabled
                    ? "Starting"
                    : "Off"}
              </strong>
              <small>
                {waitingForBusy
                  ? "BUSY 21 is closed; retrying every 15 minutes."
                  : status?.scheduler.last_error
                    ? status.scheduler.last_error
                    : "Startup catch-up is enabled."}
              </small>
            </div>
          </section>

          {!configured && (
            <section className="panel pouncha-setup">
              <div>
                <p className="eyebrow">One-time setup</p>
                <h3>Connect the Google Sheet and BUSY recipe</h3>
              </div>
              <ol>
                <li>
                  Save the Google service-account JSON at
                  <code>backend/config/google_service_account.json</code>.
                </li>
                <li>
                  Share the <strong>POUNCHA 26-27</strong> Google Sheet with the
                  service-account <code>client_email</code> as Editor.
                </li>
                <li>
                  Set <code>POUNCHA_SPREADSHEET_ID</code> in{" "}
                  <code>backend/.env</code> and restart the backend.
                </li>
                <li>
                  Calibrate the Account Ledger recipe with BUSY 21 open before
                  using <strong>Sync Now from BUSY</strong>.
                </li>
              </ol>
            </section>
          )}

          <section className="pouncha-actions">
            <div className="panel pouncha-action-card">
              <div>
                <p className="eyebrow">Primary</p>
                <h3>Sync now from BUSY</h3>
                <p className="muted-text">
                  Drives BUSY 21 through the Account Ledger Sales recipe. The
                  backend exports a temporary workbook, appends only new bill
                  numbers, and deletes the export.
                </p>
              </div>
              <div className="pouncha-date-row">
                <label>
                  <span>Start date</span>
                  <input
                    type="date"
                    value={dates.startDate}
                    max={dates.endDate}
                    onChange={(event) =>
                      setDates((current) => ({
                        ...current,
                        startDate: event.target.value,
                      }))
                    }
                  />
                </label>
                <label>
                  <span>End date</span>
                  <input
                    type="date"
                    value={dates.endDate}
                    min={dates.startDate}
                    onChange={(event) =>
                      setDates((current) => ({
                        ...current,
                        endDate: event.target.value,
                      }))
                    }
                  />
                </label>
              </div>
              <button
                type="button"
                className="button button-primary"
                onClick={() => void syncNow()}
                disabled={!configured || active || submitting}
              >
                {submitting || active ? "Sync in progress…" : "Sync Now from BUSY"}
              </button>
              {!configured && (
                <p className="pouncha-hint">
                  {!status?.sheets_configured
                    ? "Configure Google Sheets above to enable the manual sync."
                    : !status.busy_calibrated
                      ? "Calibrate the Account Ledger Sales recipe before syncing from BUSY."
                      : "Pouncha sync is not enabled."}
                </p>
              )}
            </div>

            <div className="panel pouncha-action-card">
              <div>
                <p className="eyebrow">Fallback</p>
                <h3>Upload sales ledger Excel</h3>
                <p className="muted-text">
                  Already have <code>AccountLedger_Sales.xlsx</code>? Upload it
                  to run the same parser, deduplication, and local archive
                  without touching the BUSY window.
                </p>
              </div>
              <label className={`pouncha-dropzone ${uploading ? "uploading" : ""}`}>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,.xlsm"
                  disabled={!uploadConfigured || uploading}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void upload(file);
                  }}
                />
                <span className="pouncha-dropzone-icon" aria-hidden="true">
                  ↑
                </span>
                <strong>
                  {uploading ? "Uploading and appending…" : "Choose an .xlsx file"}
                </strong>
                <span>BUSY Account Ledger Sales export</span>
              </label>
              <p className="pouncha-hint">
                The upload is deleted after parsing. The local archive is written
                when <code>POUNCHA_LOCAL_EXCEL_PATH</code> is set.
              </p>
            </div>
          </section>

          <section className="panel pouncha-runs">
            <div className="pouncha-runs-heading">
              <div>
                <p className="eyebrow">Audit trail</p>
                <h3>Last 5 sync runs</h3>
              </div>
              <button
                type="button"
                className="text-button"
                onClick={() => void load()}
              >
                Refresh
              </button>
            </div>
            {recentRuns.length === 0 ? (
              <p className="muted-text">
                No Pouncha sync has run yet. The midnight scheduler will create
                the first audit row after BUSY 21 is available.
              </p>
            ) : (
              <div className="table-wrap">
                <table className="document-table pouncha-table">
                  <thead>
                    <tr>
                      <th>Date range</th>
                      <th>Trigger</th>
                      <th>Bills found</th>
                      <th>New bills added</th>
                      <th>Status</th>
                      <th>Completed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentRuns.map((run) => (
                      <tr key={run.run_id}>
                        <td>
                          {formatDate(run.start_date)} – {formatDate(run.end_date)}
                        </td>
                        <td>{triggerLabel(run.trigger_type)}</td>
                        <td>{run.exported_sale_count}</td>
                        <td>
                          <strong>{run.appended_count}</strong>
                          {run.already_in_sheet_count > 0 && (
                            <small className="pouncha-already">
                              {run.already_in_sheet_count} already present
                            </small>
                          )}
                        </td>
                        <td>
                          <span className={`status-pill ${statusTone(run.status)}`}>
                            {statusLabel(run.status)}
                          </span>
                          {run.error_message && (
                            <small className="pouncha-run-error">
                              {run.error_message}
                            </small>
                          )}
                        </td>
                        <td>{formatDateTime(run.completed_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </AppShell>
  );
}
