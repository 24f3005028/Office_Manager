export type DocumentType = "bill" | "credit_note" | "debit_note";
export type DocumentCategory = "bills" | "credit_notes" | "debit_notes";
export type DocumentDateSource = "busy" | "pdf" | "file_fallback";
export type DocumentMatchStatus =
  | "matched"
  | "unmatched"
  | "ambiguous"
  | "series_mismatch_warning"
  | "pdf_extracted";

export const DOCUMENT_CATEGORIES: Array<{
  value: DocumentCategory;
  label: string;
  shortLabel: string;
}> = [
  { value: "bills", label: "Bills", shortLabel: "Bills" },
  { value: "credit_notes", label: "Credit notes", shortLabel: "CNs" },
  { value: "debit_notes", label: "Debit notes", shortLabel: "DNs" },
];

export const DOCUMENT_TYPES: Array<{
  value: DocumentType;
  label: string;
  shortLabel: string;
}> = [
  { value: "bill", label: "Bills", shortLabel: "Bill" },
  { value: "credit_note", label: "Credit notes", shortLabel: "Credit note" },
  { value: "debit_note", label: "Debit notes", shortLabel: "Debit note" },
];

export interface HealthResponse {
  status?: string;
  service?: string;
  [key: string]: unknown;
}

export type WhatsappConnectionState =
  | "starting"
  | "qr"
  | "authenticated"
  | "ready"
  | "retrying"
  | "disconnected"
  | "auth_failure"
  | "error"
  | string;

export type WhatsappRequiredAction = "link" | "relink" | "repair";

export interface WhatsappStatus {
  status?: WhatsappConnectionState;
  connected?: boolean;
  qr_available?: boolean;
  initializing?: boolean;
  requires_action?: WhatsappRequiredAction | null;
  message?: string | null;
  generation?: number;
  qr_revision?: number;
  roots_synced?: boolean;
  bridge_roots_synced?: boolean;
  bridge_sync_error?: string | null;
  queue_wait_reason?: string | null;
  [key: string]: unknown;
}

export interface WorkspaceCategoryStatus {
  configured: boolean;
  valid_roots: number;
  total_roots: number;
}

export interface WorkspaceSettings {
  document_roots: Record<DocumentCategory, string[]>;
  category_status: Record<DocumentCategory, WorkspaceCategoryStatus>;
  configured: boolean;
}

export interface Contact {
  id: string;
  name: string;
  number?: string;
  phone_display?: string;
  is_business?: boolean;
}

export interface DocumentRecord {
  file_id: string;
  category: DocumentType | string;
  file_name: string;
  relative_path?: string;
  size_bytes?: number;
  modified_at?: string;
  root_index?: number;
  effective_date?: string;
  date_source?: DocumentDateSource;
  match_status?: DocumentMatchStatus;
  matched_voucher_no?: string | null;
}

export interface BusyLedgerSampleKey {
  category: DocumentCategory;
  raw_voucher_no: string;
  canonical_series: string;
  fy: string;
  serial: number;
  voucher_date: string;
  party_name: string;
}

export interface BusyLedgerFileResult {
  filename: string;
  category: DocumentCategory | null;
  detected_headers: Record<string, string>;
  rows_found: number;
  rows_imported: number;
  sample_keys: BusyLedgerSampleKey[];
  warnings: string[];
  min_date: string | null;
  max_date: string | null;
  deleted: boolean;
}

export interface BusyLedgerImportResponse {
  dry_run: boolean;
  files: BusyLedgerFileResult[];
  rows_found: number;
  rows_imported: number;
  warnings: string[];
}

export interface BusyLedgerCategoryStatus {
  category: DocumentCategory;
  total_vouchers: number;
  min_date: string | null;
  max_date: string | null;
}

export interface BusyLedgerStatus {
  last_sync_at: string | null;
  last_sync_filename: string | null;
  total_vouchers: number;
  categories: BusyLedgerCategoryStatus[];
}

export interface SendJobFile {
  file_id: string;
  category?: DocumentType | string;
  file_name?: string;
  date_label?: string | null;
  status?: "queued" | "sending" | "sent" | "failed" | "cancelled" | "unknown" | string;
  error?: string | null;
  sent_at?: string | null;
  operation_id?: string;
  message_id?: string | null;
  label_operation_id?: string | null;
  label_message_id?: string | null;
  attempt_count?: number;
  error_code?: string | null;
  outcome?: "not_started" | "unknown" | null;
}

export type SendJobStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "needs_review" | string;

export interface SendJob {
  job_id: string;
  status: SendJobStatus;
  contact_id?: string;
  contact_name?: string;
  recipient?: string;
  error?: string | null;
  cancel_requested?: boolean;
  files: SendJobFile[];
  created_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  intro_sent?: boolean;
  intro_message_id?: string | null;
  intro_operation_id?: string;
}

export interface CreateSendJobRequest {
  file_ids: string[];
  recipient: string;
  message?: string;
}

export interface PounchaRun {
  run_id: string;
  status: "queued" | "running" | "success" | "failed" | "needs_review" | "reviewed";
  stage: string;
  source: string;
  preview_only: boolean;
  start_date: string | null;
  end_date: string;
  created_at: string;
  exported_count: number;
  existing_count: number;
  new_count: number;
  appended_count: number;
  conflicts: string[];
  warnings: string[];
  preview: string[][];
  error: string | null;
  updated_range: string | null;
}

export interface PounchaStatus {
  manual_only: true;
  scheduler_enabled: false;
  configured: boolean;
  sheet_url: string;
  tab: string;
  last_bill: string | null;
  last_date: string | null;
  bill_count: number | null;
  sheet_error: string | null;
  recent_runs: PounchaRun[];
}
