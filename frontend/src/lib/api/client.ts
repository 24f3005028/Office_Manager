import type {
  Contact,
  CreateSendJobRequest,
  DocumentCategory,
  DocumentRecord,
  DocumentType,
  HealthResponse,
  SendJob,
  WhatsappStatus,
  WorkspaceSettings,
} from "./types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...options?.headers,
      },
    });
  } catch {
    throw new ApiError("The dashboard API could not be reached.", 0);
  }

  if (!response.ok) {
    let detail = "The API returned an error.";
    try {
      const body = (await response.json()) as { detail?: string; error?: string };
      detail = body.detail ?? body.error ?? detail;
    } catch {
      // Keep a safe generic message when the server did not return JSON.
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

function normalizeContacts(payload: Contact[] | { contacts?: Contact[] }): Contact[] {
  const contacts = Array.isArray(payload) ? payload : payload.contacts ?? [];
  return contacts
    .filter((contact) => Boolean(contact.id))
    .map((contact) => ({ ...contact, name: contact.name || contact.number || contact.id }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

function normalizeDocuments(payload: DocumentRecord[]): DocumentRecord[] {
  return payload.map((document) => ({
    ...document,
    category: normalizeDocumentType(document.category),
  }));
}

export function normalizeDocumentType(category: string): DocumentType | string {
  const normalized = category.toLowerCase();
  if (normalized === "bills" || normalized === "bill") return "bill";
  if (normalized === "credit_notes" || normalized === "credit_note") return "credit_note";
  if (normalized === "debit_notes" || normalized === "debit_note") return "debit_note";
  return category;
}

export const api = {
  getHealth: () => request<HealthResponse>("/api/health"),
  getWhatsappStatus: () => request<WhatsappStatus>("/api/whatsapp/status"),
  startWhatsapp: () => request<WhatsappStatus>("/api/whatsapp/start", { method: "POST" }),
  reconnectWhatsapp: () => request<WhatsappStatus>("/api/whatsapp/reconnect", { method: "POST" }),
  getContacts: async () => normalizeContacts(await request<Contact[] | { contacts?: Contact[] }>("/api/whatsapp/contacts")),
  listSendJobs: () => request<SendJob[]>("/api/send-jobs?limit=20"),
  getDocuments: async (params: {
    startDate: string;
    endDate: string;
    documentTypes: DocumentType[];
  }) => {
    const query = new URLSearchParams({
      start_date: params.startDate,
      end_date: params.endDate,
      document_types: params.documentTypes.join(","),
    });
    return normalizeDocuments(await request<DocumentRecord[]>(`/api/documents?${query.toString()}`));
  },
  getQr: async () => {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/whatsapp/qr`, { cache: "no-store" });
    } catch {
      throw new ApiError("The QR endpoint could not be reached.", 0);
    }
    if (!response.ok) throw new ApiError("A WhatsApp QR code is not available yet.", response.status);
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const body = (await response.json()) as { data_url?: string; qr?: string };
      return body.data_url ?? body.qr ?? "";
    }
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  },
  getSettings: () => request<WorkspaceSettings>("/api/settings"),
  updateDocumentRoots: (documentRoots: Record<DocumentCategory, string[]>) =>
    request<WorkspaceSettings>("/api/settings/document-roots", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_roots: documentRoots }),
    }),
  pickFolder: async () => {
    const response = await request<{ path: string }>("/api/settings/pick-folder", { method: "POST" });
    return response.path;
  },
  createSendJob: (payload: CreateSendJobRequest) =>
    request<SendJob>("/api/send-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  getSendJob: (jobId: string) => request<SendJob>(`/api/send-jobs/${encodeURIComponent(jobId)}`),
  cancelSendJob: (jobId: string) =>
    request<SendJob>(`/api/send-jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
};
