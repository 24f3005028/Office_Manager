import type { DocumentRecord, DocumentType } from "./api/types";

const categoryOrder: Record<DocumentType, number> = {
  bill: 0,
  credit_note: 1,
  debit_note: 2,
};

function naturalParts(value: string): Array<string | number> {
  return value
    .toLocaleLowerCase()
    .split(/(\d+)/)
    .filter(Boolean)
    .map((part) => (/^\d+$/.test(part) ? Number(part) : part));
}

function compareNatural(left: string, right: string): number {
  const leftParts = naturalParts(left);
  const rightParts = naturalParts(right);
  for (let index = 0; index < Math.max(leftParts.length, rightParts.length); index += 1) {
    const leftPart = leftParts[index];
    const rightPart = rightParts[index];
    if (leftPart === undefined) return -1;
    if (rightPart === undefined) return 1;
    if (leftPart === rightPart) continue;
    if (typeof leftPart === "number" && typeof rightPart === "number") return leftPart - rightPart;
    return String(leftPart).localeCompare(String(rightPart));
  }
  return 0;
}

export function sortDocuments(documents: DocumentRecord[]): DocumentRecord[] {
  return [...documents].sort((left, right) => {
    // Sending is type-major: bills, credit notes, then debit notes. This is
    // also the backend's durable send order, so preview and delivery agree.
    const categoryComparison =
      (categoryOrder[left.category as DocumentType] ?? 99) -
      (categoryOrder[right.category as DocumentType] ?? 99);
    if (categoryComparison !== 0) return categoryComparison;
    const nameComparison = compareNatural(left.file_name, right.file_name);
    if (nameComparison !== 0) return nameComparison;
    const dateComparison = modifiedAtMs(left.modified_at) - modifiedAtMs(right.modified_at);
    if (dateComparison !== 0) return dateComparison;
    return compareNatural(left.relative_path ?? "", right.relative_path ?? "");
  });
}

function modifiedAtMs(value?: string): number {
  if (!value) return Number.MAX_SAFE_INTEGER;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER;
}

export function formatDateLabel(modifiedAt?: string): string | null {
  if (!modifiedAt || !Number.isFinite(Date.parse(modifiedAt))) return null;
  const value = new Date(modifiedAt);
  const day = String(value.getDate()).padStart(2, "0");
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const year = String(value.getFullYear()).slice(-2);
  return `${day}.${month}.${year}`;
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
