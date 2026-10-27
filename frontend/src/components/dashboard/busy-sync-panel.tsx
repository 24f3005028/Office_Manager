"use client";

import { useState } from "react";
import type { BusyLedgerStatus } from "@/lib/api/types";
import { DOCUMENT_CATEGORIES } from "@/lib/api/types";
import { formatDateLabel } from "@/lib/documents";

interface BusySyncPanelProps {
  status: BusyLedgerStatus | null;
  loading: boolean;
  importing: boolean;
  error: string | null;
  message: string | null;
  warnings: string[];
  onImport: (file: File) => void;
  onRefresh: () => void;
}

function formatTimestamp(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function indexedRange(status: BusyLedgerStatus): string | null {
  const starts = status.categories
    .map((category) => category.min_date)
    .filter((value): value is string => Boolean(value))
    .sort();
  const ends = status.categories
    .map((category) => category.max_date)
    .filter((value): value is string => Boolean(value))
    .sort();
  if (!starts.length || !ends.length) return null;
  const start = formatDateLabel(starts[0]);
  const end = formatDateLabel(ends[ends.length - 1]);
  if (!start || !end) return null;
  return start === end ? start : `${start} – ${end}`;
}

export function BusySyncPanel({
  status,
  loading,
  importing,
  error,
  message,
  warnings,
  onImport,
  onRefresh,
}: BusySyncPanelProps) {
  const [dragging, setDragging] = useState(false);
  const range = status ? indexedRange(status) : null;

  function acceptFile(file: File | undefined | null) {
    if (file && !importing) onImport(file);
  }

  return (
    <section className="panel busy-sync-panel" aria-labelledby="busy-sync-heading">
      <div className="busy-sync-copy">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Optional cross-check</p>
            <h2 id="busy-sync-heading">BUSY ledger</h2>
          </div>
          <span className="busy-excel-tag">Optional</span>
        </div>
        <p className="muted-text">
          Voucher dates are now read automatically from each PDF. Import the BUSY Sales, Credit
          Note or Debit Note register only if you want the ledger to override or cross-check
          those printed dates.
        </p>

        {status ? (
          <>
            <div className="busy-metrics">
              <div className="busy-metric">
                <span>Last sync</span>
                <strong>
                  {status.last_sync_at ? formatTimestamp(status.last_sync_at) : "Never"}
                </strong>
                <small>{status.last_sync_filename ?? "No workbook imported yet"}</small>
              </div>
              <div className="busy-metric">
                <span>Indexed vouchers</span>
                <strong>{status.total_vouchers.toLocaleString("en-IN")}</strong>
                <small>{range ? `Voucher dates ${range}` : "No voucher dates indexed"}</small>
              </div>
            </div>
            <div className="busy-category-chips" aria-label="Indexed vouchers by document type">
              {DOCUMENT_CATEGORIES.map((category) => {
                const indexed = status.categories.find(
                  (item) => item.category === category.value,
                );
                return (
                  <span
                    key={category.value}
                    className={`busy-category-chip${indexed?.total_vouchers ? " ready" : ""}`}
                  >
                    {category.shortLabel}
                    <strong>{(indexed?.total_vouchers ?? 0).toLocaleString("en-IN")}</strong>
                  </span>
                );
              })}
            </div>
          </>
        ) : (
          <p className="busy-empty">
            {loading
              ? "Checking the last BUSY sync…"
              : "No BUSY ledger has been imported. Printed PDF dates are still used automatically."}
          </p>
        )}

        {error && <p className="inline-error">{error}</p>}
        {message && <p className="busy-message">{message}</p>}
        {warnings.length > 0 && (
          <details className="busy-warnings">
            <summary>
              {warnings.length} parser warning{warnings.length === 1 ? "" : "s"}
            </summary>
            <ul>
              {warnings.slice(0, 8).map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
            {warnings.length > 8 && <p>+ {warnings.length - 8} more</p>}
          </details>
        )}
      </div>

      <div className="busy-sync-action">
        <label
          className={`busy-dropzone${dragging ? " dragging" : ""}${importing ? " importing" : ""}`}
          onDragEnter={(event) => {
            event.preventDefault();
            if (!importing) setDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            event.preventDefault();
            setDragging(false);
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            acceptFile(event.dataTransfer.files?.[0]);
          }}
        >
          <input
            className="sr-only"
            type="file"
            accept=".xlsx,.xlsm,.xls"
            disabled={importing}
            onChange={(event) => {
              acceptFile(event.currentTarget.files?.[0]);
              event.currentTarget.value = "";
            }}
          />
          <span className="busy-dropzone-icon" aria-hidden="true">
            {importing ? "…" : "⇪"}
          </span>
          <strong>{importing ? "Importing BUSY ledger…" : "Drop BUSY Excel here"}</strong>
          <span>or click to choose the register export</span>
          <em>.xlsx, .xlsm or .xls · permanently deleted after parsing</em>
        </label>
        <button
          className="busy-refresh"
          type="button"
          onClick={onRefresh}
          disabled={loading || importing}
        >
          {loading ? "Refreshing…" : "Refresh BUSY status"}
        </button>
      </div>
    </section>
  );
}
