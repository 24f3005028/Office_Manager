import { useState } from "react";
import type { Contact, DocumentRecord } from "@/lib/api/types";
import { countUnverifiedDocuments, groupDocumentsByDate } from "@/lib/documents";
import { formatPhoneNumber } from "@/lib/phone";

export const MAX_CAPTION_LENGTH = 4096;

interface SendConfirmationProps {
  contact: Contact;
  documents: DocumentRecord[];
  defaultMessage: string;
  submitting: boolean;
  onCancel: () => void;
  onConfirm: (message: string) => void;
}

export function SendConfirmation({
  contact,
  documents,
  defaultMessage,
  submitting,
  onCancel,
  onConfirm,
}: SendConfirmationProps) {
  const [message, setMessage] = useState(defaultMessage);
  const trimmedMessage = message.trim();
  const dateGroups = groupDocumentsByDate(documents);
  const unverifiedCount = countUnverifiedDocuments(documents);

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="confirmation-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <div className="modal-icon" aria-hidden="true">→</div>
        <p className="eyebrow">Final check</p>
        <h2 id="confirm-title">Send these documents?</h2>
        <p className="modal-copy">
          You are about to queue <strong>{documents.length} {documents.length === 1 ? "document" : "documents"}</strong> for
          <strong> {contact.name}</strong>. They are sent date by date, oldest first. Within each date: Bills folder
          1 → 2, CN folder 1 → 2, then DN folder 1 → 2. One date message is sent before that date&apos;s documents.
        </p>
        <div className="confirmation-dates" aria-label="Document dates in send order">
          {dateGroups.map((group) => (
            <span className="date-chip" key={group.key}>
              {group.label}
              <small>{group.documents.length}</small>
            </span>
          ))}
        </div>
        {unverifiedCount > 0 && (
          <p className="confirmation-warning">
            {unverifiedCount} {unverifiedCount === 1 ? "document uses a" : "documents use a"} file
            date because no printed voucher date could be read from the PDF.
          </p>
        )}
        <div className="confirmation-summary">
          <div><span>Recipient</span><strong>{contact.name}<small className="summary-subline">{formatPhoneNumber(contact.phone_display ?? contact.number) ?? "Phone number unavailable"}</small></strong></div>
          <div><span>Documents</span><strong>{documents.length}</strong></div>
        </div>
        <div className="caption-field">
          <label htmlFor="confirm-message">Opening message sent first, before date headers and documents</label>
          <textarea
            id="confirm-message"
            value={message}
            rows={3}
            maxLength={MAX_CAPTION_LENGTH}
            onChange={(event) => setMessage(event.target.value)}
            disabled={submitting}
          />
          <span className="caption-count">{message.length} / {MAX_CAPTION_LENGTH}</span>
        </div>
        <div className="modal-actions">
          <button className="button button-secondary" type="button" onClick={onCancel} disabled={submitting}>
            Go back
          </button>
          <button
            className="button button-primary"
            type="button"
            onClick={() => onConfirm(trimmedMessage || defaultMessage)}
            disabled={submitting}
          >
            {submitting ? <><span className="spinner" /> Queueing…</> : <>Confirm &amp; send <span aria-hidden="true">↗</span></>}
          </button>
        </div>
      </section>
    </div>
  );
}
