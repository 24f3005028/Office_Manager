import type { DocumentRecord } from "@/lib/api/types";
import {
  dateSourceLabel,
  dateSourceTitle,
  documentDateLabel,
  documentDateValue,
  documentTypeLabel,
  formatBytes,
} from "@/lib/documents";

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
        <caption className="sr-only">
          Documents in send order: oldest accounting date first, then Bills folder 1 to 2,
          Credit notes folder 1 to 2 and Debit notes folder 1 to 2
        </caption>
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
            const dateLabel = documentDateLabel(document);
            const startsGroup =
              previous !== undefined &&
              documentDateValue(document) !== documentDateValue(previous);
            const badgeClass =
              document.date_source === "busy"
                ? "busy"
                : document.date_source === "pdf"
                  ? "pdf"
                  : "unverified";
            return (              <tr key={document.file_id} className={startsGroup ? "new-date-group" : undefined}>
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
                  <div className="date-cell">
                    {dateLabel ? <span className="date-tag">{dateLabel}</span> : "—"}
                    <span
                      className={`date-source-badge ${badgeClass}`}
                      title={dateSourceTitle(document)}
                    >
                      {dateSourceLabel(document)}
                    </span>
                  </div>
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
