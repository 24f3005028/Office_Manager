import type { SendJob } from "@/lib/api/types";

interface JobProgressProps {
  job: SendJob;
  cancelling: boolean;
  onCancel: () => void;
}

function statusCopy(status: string): string {
  if (status === "queued") return "Queued for sending";
  if (status === "running") return "Sending documents";
  if (status === "completed") return "All documents sent";
  if (status === "cancelled") return "Sending cancelled";
  if (status === "failed") return "Sending stopped";
  if (status === "needs_review") return "Delivery needs review";
  return "Updating send job";
}

export function JobProgress({ job, cancelling, onCancel }: JobProgressProps) {
  const sent = job.files.filter((file) => file.status === "sent").length;
  const finished = job.files.filter((file) => ["sent", "failed", "cancelled"].includes(file.status ?? "")).length;
  const percentage = job.files.length ? Math.round((finished / job.files.length) * 100) : 0;
  const active = job.status === "queued" || job.status === "running";
  const needsReview = job.status === "needs_review" || job.files.some((file) => file.status === "unknown");

  return (
    <section className={`job-card panel job-${job.status}`} aria-labelledby="job-heading">
      <div className="job-heading-row">
        <div>
          <p className="eyebrow">Send job</p>
          <h2 id="job-heading">{statusCopy(job.status)}</h2>
        </div>
        <span className={`job-status ${job.status}`}><span className="status-dot" />{job.status}</span>
      </div>
      <div className="progress-meta">
        <span>{sent} of {job.files.length} sent</span>
        <span>{percentage}%</span>
      </div>
      <div className="progress-track" aria-label={`${percentage}% complete`}>
        <span style={{ width: `${percentage}%` }} />
      </div>
      <ul className="job-file-list">
        {job.files.map((file) => (
          <li key={file.file_id}>
            <span className={`file-status ${file.status}`} aria-hidden="true">
              {file.status === "sent" ? "✓" : file.status === "failed" ? "!" : file.status === "unknown" ? "?" : file.status === "sending" ? "…" : "·"}
            </span>
            <span>{file.file_name ?? file.file_id}</span>
            <small>
              {file.error ?? (file.status ?? "queued")}
            </small>
          </li>
        ))}
      </ul>
      {job.error && <p className="inline-error">{job.error}</p>}
      {needsReview && <p className="review-note">A WhatsApp response was lost after a send may have started. This job is paused to prevent duplicate documents.</p>}
      {active && (
        <button className="button button-danger-quiet" type="button" onClick={onCancel} disabled={cancelling}>
          {cancelling ? "Cancelling…" : "Cancel send job"}
        </button>
      )}
    </section>
  );
}
