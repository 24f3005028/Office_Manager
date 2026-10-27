import type { DocumentRecord } from "./api/types";

const dateOnlyPattern = /^(\d{4})-(\d{2})-(\d{2})$/;

export interface DocumentDateGroup {
  key: string;
  label: string;
  documents: DocumentRecord[];
}

/**
 * Format an ISO timestamp or `YYYY-MM-DD` date as `DD.MM.YY`.
 *
 * Date-only values are formatted without constructing a `Date`, because
 * `new Date("2026-10-25")` is parsed as UTC midnight and can move to the
 * previous day in local time.
 */
export function formatDateLabel(value?: string | null): string | null {
  if (!value) return null;
  const dateOnly = dateOnlyPattern.exec(value);
  if (dateOnly) {
    return `${dateOnly[3]}.${dateOnly[2]}.${dateOnly[1].slice(-2)}`;
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  const parsed = new Date(timestamp);
  const day = String(parsed.getDate()).padStart(2, "0");
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const year = String(parsed.getFullYear()).slice(-2);
  return `${day}.${month}.${year}`;
}

/** The date the backend used for ordering, filtering and WhatsApp labels. */
export function documentDateValue(document: DocumentRecord): string | undefined {
  return document.effective_date ?? document.modified_at;
}

export function documentDateLabel(document: DocumentRecord): string | null {
  return formatDateLabel(documentDateValue(document));
}

export function isDateVerified(document: DocumentRecord): boolean {
  return document.date_source === "busy" || document.date_source === "pdf";
}

export function dateSourceLabel(document: DocumentRecord): string {
  if (document.date_source === "busy") return "BUSY";
  if (document.date_source === "pdf") return "PDF";
  return "File Date (Unverified)";
}

export function dateSourceTitle(document: DocumentRecord): string {
  if (document.date_source === "busy") {
    const voucher = document.matched_voucher_no
      ? `BUSY voucher ${document.matched_voucher_no}`
      : "The BUSY ledger";
    const warning =
      document.match_status === "series_mismatch_warning"
        ? " Series differs from the filename; please verify."
        : "";
    return `${voucher} supplied this date.${warning}`;
  }
  if (document.date_source === "pdf") {
    return "This is the voucher date printed on the PDF by BUSY.";
  }
  if (document.match_status === "ambiguous") {
    return "Several BUSY vouchers share this number, so the file date is used until it is verified.";
  }
  if (document.match_status === "unmatched") {
    return "No printed voucher date could be read from this PDF, so its file date is used. Check the PDF or sync the BUSY register.";
  }
  return "No verified voucher date was found, so this document's file date is used.";
}

/**
 * Group documents by their effective date without re-sorting. The backend
 * already returned them in authoritative send order.
 */
export function groupDocumentsByDate(documents: DocumentRecord[]): DocumentDateGroup[] {
  const groups: DocumentDateGroup[] = [];
  for (const document of documents) {
    const key = documentDateValue(document) ?? "unknown";
    const label = documentDateLabel(document) ?? "Unknown date";
    const last = groups[groups.length - 1];
    if (last && last.key === key) {
      last.documents.push(document);
    } else {
      groups.push({ key, label, documents: [document] });
    }
  }
  return groups;
}

export function countUnverifiedDocuments(documents: DocumentRecord[]): number {
  return documents.filter((document) => !isDateVerified(document)).length;
}

export function formatBytes(bytes?: number): string {
  if (bytes === undefined || !Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function documentTypeLabel(category: string): string {
  if (category === "bill" || category === "bills") return "Bill";
  if (category === "credit_note" || category === "credit_notes") return "Credit note";
  if (category === "debit_note" || category === "debit_notes") return "Debit note";
  return category;
}
