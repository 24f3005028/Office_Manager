import type { DocumentRecord } from "@/lib/api/types";
import { documentTypeLabel, formatBytes, formatDateLabel } from "@/lib/documents";

interface DocumentPreviewTableProps {
  documents: DocumentRecord[];
}

export function DocumentPreviewTable({
  documents,
}: DocumentPreviewTableProps) {
  if (!documents.length) {
    return (
      <div className="empty-state">
        <div className="empty-icon" aria-hidden="true">⌁</div>
        <h3>No documents found</h3>
        <p>Try a different date range or include another document type.</p>
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table className="document-table">
        <caption className="sr-only">Documents ordered for preview and sending by document type and number</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Document</th>
            <th scope="col">Type</th>
            <th scope="col">Date</th>
            <th scope="col">Size</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((document, index) => {
            const previous = index > 0 ? documents[index - 1] : undefined;
            const dateLabel = formatDateLabel(document.modified_at);
            const startsGroup = dateLabel !== formatDateLabel(previous?.modified_at);
            return (
              <tr key={document.file_id} className={startsGroup ? "new-date-group" : undefined}>
                <td className="row-number">{String(index + 1).padStart(2, "0")}</td>
                <td>
                  <div className="file-cell">
                    <span className="pdf-icon">PDF</span>
                    <span>
                      <strong>{document.file_name}</strong>
                      <small>{document.relative_path ?? "Local document"}</small>
                    </span>
                  </div>
                </td>
                <td><span className="type-tag">{documentTypeLabel(document.category)}</span></td>
                <td className="muted-cell">
                  {dateLabel ? <span className="date-tag">{dateLabel}</span> : "—"}
                </td>
                <td className="muted-cell">{formatBytes(document.size_bytes)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
