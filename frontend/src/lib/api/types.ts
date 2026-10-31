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

export type PounchaRunStatus = "queued" | "running" | "success" | "failed" | "skipped";

export interface PounchaSyncRun {
  run_id: string;
  trigger_type: string;
  start_date: string;
  end_date: string;
  exported_sale_count: number;
  already_in_sheet_count: number;
  appended_count: number;
  status: PounchaRunStatus;
  error_message: string | null;
  warnings: string[];
  started_at: string | null;
  completed_at: string | null;
}

export interface PounchaSchedulerStatus {
  enabled: boolean;
  running: boolean;
  timezone: string;
  next_run_at: string | null;
  waiting_for_busy: boolean;
  last_check_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
}

export interface PounchaSyncStatus {
  configured: boolean;
  upload_configured: boolean;
  sheets_configured: boolean;
  busy_configured: boolean;
  busy_calibrated: boolean;
  sync_enabled: boolean;
  scheduler: PounchaSchedulerStatus;
  last_run: PounchaSyncRun | null;
  active_run: PounchaSyncRun | null;
  recent_runs: PounchaSyncRun[];
}

export interface PounchaSyncQueued {
  run_id: string;
  status: "queued" | "running";
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
