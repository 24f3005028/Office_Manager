"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { Icon } from "@/components/layout/icons";
import { displayDate } from "@/lib/date";
import { api } from "@/lib/api/client";
import type { PounchaRun, PounchaStatus } from "@/lib/api/types";

const columns = ["Date", "Bill no.", "Party", "Transport", "Vehicle", "Station", "Narration"];
const stages: Record<string, string> = {
  preparing: "Reading the sheet", exporting: "Exporting the BUSY Sales ledger",
  parsing: "Reading bill details", comparing: "Finding missing bills",
  appending: "Appending new bills", verifying: "Verifying the saved rows", complete: "Complete",
};

function today() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "The sync request failed. Refresh the status before trying again.";
}

export function PounchaSyncPage() {
  const [status, setStatus] = useState<PounchaStatus | null>(null);
  const [run, setRun] = useState<PounchaRun | null>(null);
  const [mode, setMode] = useState("continue");
  const [source, setSource] = useState("busy");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState(today);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const value = await api.getPounchaStatus();
      setStatus(value);
      setRun((current) => current ?? value.recent_runs[0] ?? null);
      setError(null);
    } catch (reason) { setError(errorText(reason)); }
    finally { setLoading(false); }
  }, []);

  // Reading status never exports from BUSY or queues a sync.
  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    let cancelled = false;
    let timer: number;
    const poll = async () => {
      try {
        const next = await api.getPounchaRun(run.run_id);
        if (cancelled) return;
        setRun(next);
        if (["queued", "running"].includes(next.status)) timer = window.setTimeout(() => void poll(), 1500);
        else void refresh();
      } catch (reason) {
        if (!cancelled) {
          setError(errorText(reason));
          timer = window.setTimeout(() => void poll(), 3000);
        }
      }
    };
    timer = window.setTimeout(() => void poll(), 1000);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [run?.run_id, run?.status, refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  const active = status?.recent_runs.find((item) => ["queued", "running", "needs_review"].includes(item.status));
  const blocked = busy || loading || Boolean(active) || Boolean(run && ["queued", "running", "needs_review"].includes(run.status));
  const chosenStart = mode === "custom" ? start : status?.last_date ?? "";
  const valid = Boolean(chosenStart && end && chosenStart <= end && end <= today() && (source === "busy" || file));

  async function submit(preview: boolean) {
    if (!valid || blocked) return;
    setBusy(true);
    setError(null);
    setReviewed(false);
    try {
      const payload = { start_date: mode === "custom" ? start : undefined, end_date: end, preview_only: preview };
      const next = source === "upload" && file ? await api.uploadPouncha(file, payload) : await api.runPouncha(payload);
      setRun(next);
    } catch (reason) { setError(errorText(reason)); void refresh(); }
    finally { setBusy(false); }
  }

  async function review(release: boolean) {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      if (release) {
        await api.releasePouncha(run.run_id);
        setRun(await api.getPounchaRun(run.run_id));
      } else setRun(await api.verifyPouncha(run.run_id));
      await refresh();
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }

  const running = Boolean(run && ["queued", "running"].includes(run.status));
  const resultTitle = !run ? "" : running ? (run.preview_only ? "Preparing your preview…" : "Updating your sheet…")
    : run.status === "success" ? (run.preview_only ? "Preview is ready" : run.appended_count ? "Pouncha sheet updated" : "Your sheet is up to date")
    : run.status === "needs_review" ? "Check the sheet before trying again" : run.status === "reviewed" ? "Review completed" : "The update could not finish";
  return <AppShell>
    <div className="dashboard-intro"><div><p className="eyebrow">Google Sheets</p><h2>Update Pouncha sheet</h2><p className="intro-copy">Choose the dates. We will add the missing sales bills from BUSY.</p></div><span className="status-pill neutral">Only runs when you click</span></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    <div className="pouncha-layout">
      <section className="panel pouncha-card" aria-labelledby="sync-options">
        <div className="section-heading"><div><p className="eyebrow">Step 1</p><h2 id="sync-options">Which bills should we check?</h2></div><span className="step-number">1</span></div>
        <fieldset className="choice-group"><legend>Choose a date range</legend>
          <label className="choice-card"><input type="radio" name="sync-range" checked={mode === "continue"} disabled={blocked} onChange={() => setMode("continue")} /><span><strong>Continue from the last update</strong><small>Recommended. Bills already in the sheet will be skipped.</small></span></label>
          <label className="choice-card"><input type="radio" name="sync-range" checked={mode === "custom"} disabled={blocked} onChange={() => setMode("custom")} /><span><strong>Choose different dates</strong><small>Use this to check older bills or a specific period.</small></span></label>
        </fieldset>
        <div className="pouncha-fields">
          {mode === "custom" ? <label>From<input type="date" value={start} disabled={blocked} onChange={(event) => setStart(event.target.value)} max={end} /></label> : <label>Starting from<input type="text" value={status?.last_date ? displayDate(status.last_date) : loading ? "Checking the sheet…" : "Choose different dates"} readOnly disabled /></label>}
          <label>Up to this date<input type="date" value={end} disabled={blocked} onChange={(event) => setEnd(event.target.value)} max={today()} /></label>
        </div>
        {chosenStart && end && chosenStart > end && <p className="field-error" role="alert">The end date must be the same as or after the start date.</p>}
        {source === "upload" && <label className="pouncha-upload">Choose the original BUSY Excel export (.xlsx)<input type="file" accept=".xlsx" disabled={blocked} onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>}
        <div className="pouncha-primary-action"><button className="button button-primary" disabled={blocked || !valid || Boolean(status?.sheet_error)} onClick={() => void submit(false)}>{busy ? <><span className="spinner" /> Starting…</> : <><Icon name="sync" /> Update sheet</>}</button><p>{running ? "An update is in progress. Please wait." : run?.status === "needs_review" || active?.status === "needs_review" ? "Resolve the review below before another update." : "Keep BUSY open and let the update finish before using its window."}</p></div>
        <details className="advanced-options"><summary>More options: preview or use an Excel file</summary><label className="field-label" htmlFor="sync-source">Get bills from</label><select id="sync-source" value={source} disabled={blocked} onChange={(event) => setSource(event.target.value)}><option value="busy">BUSY on this computer</option><option value="upload">An exported Excel file</option></select><button className="button button-secondary" disabled={blocked || !valid || Boolean(status?.sheet_error)} onClick={() => void submit(true)}>Preview without updating the sheet</button></details>
      </section>
      <aside className="panel pouncha-card pouncha-sheet-card" aria-label="Current sheet status">
        <div className="pouncha-row"><h3>Already in your sheet</h3><span className={`status-pill ${status?.sheet_error ? "warning" : status ? "success" : "neutral"}`}>{loading ? "Checking…" : status?.sheet_error ? "Check connection" : status ? "Connected" : "Not connected"}</span></div>
        {status?.sheet_error ? <p className="inline-error">{status.sheet_error}</p> : <dl className="sheet-summary"><div><dt>Last bill number</dt><dd>{status?.last_bill ?? "—"}</dd></div><div><dt>Latest bill date</dt><dd>{status?.last_date ? displayDate(status.last_date) : "—"}</dd></div><div><dt>Total bills saved</dt><dd>{status?.bill_count?.toLocaleString("en-IN") ?? "—"}</dd></div></dl>}
        <p className="sheet-note">Existing bills and your remarks stay in place. We only add missing bills.</p>
        {status && <a href={status.sheet_url} target="_blank" rel="noreferrer">Open POUNCHA 26-27 <Icon name="arrow" width="17" height="17" /></a>}
        <div><button className="button button-quiet" disabled={loading || busy} onClick={() => void refresh()}>{loading ? "Checking sheet…" : "Check sheet again"}</button></div>
      </aside>
    </div>
    {run && <section className="panel pouncha-card" aria-live="polite" aria-busy={running}>
      <div className="pouncha-result-title"><span className={`result-icon ${run.status}`}>{running ? <span className="spinner dark" /> : run.status === "success" ? <Icon name="check" /> : <Icon name="help" />}</span><div><h2>{resultTitle}</h2><p className="muted-text">{run.start_date ? displayDate(run.start_date) : "Last saved date"} to {displayDate(run.end_date)}{run.preview_only ? " · Preview only" : ""}</p></div></div>
      {running && <div className="result-progress">{stages[run.stage] ?? "Working…"}<p className="muted-text">Please leave BUSY and the keyboard alone until this is finished.</p></div>}
      <div className="pouncha-metrics run-metrics"><div><span>Bills checked</span><strong>{run.exported_count}</strong></div><div><span>Already saved</span><strong>{run.existing_count}</strong></div><div><span>New bills found</span><strong>{run.new_count}</strong></div><div><span>Added to sheet</span><strong>{run.appended_count}</strong></div></div>
      {run.error && <div className="notice notice-error" role="alert"><strong>What to do next</strong><p>{run.error}</p>{run.status === "failed" && <p>After fixing the problem, use Update sheet above to try again.</p>}</div>}
      {run.status === "success" && <div className="notice notice-success">{run.preview_only ? "Nothing was changed. Check the new bills below, then use Update sheet when you are ready." : run.appended_count ? `All done. ${run.appended_count} new bills were added and checked.` : "No missing bills were found for these dates."}</div>}
      {run.warnings.length > 0 && <details><summary>{run.warnings.length} existing bills need a check</summary><p className="muted-text">These bills have different details. Their saved rows were not changed.</p><ul>{run.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details>}
      {run.status === "needs_review" && <div className="notice notice-error"><p>Some bills may already have been saved. Check the Google Sheet before starting again.</p><button className="button button-secondary" disabled={busy} onClick={() => void review(false)}>Check whether the bills were saved</button><details><summary>I checked the sheet myself</summary><label className="pouncha-review"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} /> I have checked the sheet and want to allow another update.</label><button className="button button-danger-quiet" disabled={busy || !reviewed} onClick={() => void review(true)}>Finish review and allow updates</button></details></div>}
      {run.preview.length > 0 && <details open={run.preview_only}><summary>View new bills{run.new_count > 100 ? " (first 100)" : ""}</summary><div className="pouncha-table-wrap"><table className="pouncha-table"><thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead><tbody>{run.preview.map((row) => <tr key={row[1]}>{row.map((cell, index) => <td key={index}>{cell || "—"}</td>)}</tr>)}</tbody></table></div></details>}
    </section>}
    {status && status.recent_runs.length > 0 && <details className="panel pouncha-card"><summary>Previous updates ({status.recent_runs.length})</summary><ul className="pouncha-history">{status.recent_runs.map((item) => <li key={item.run_id}><button disabled={busy || running} onClick={() => { setRun(item); setReviewed(false); }}><span><strong>{item.start_date ? displayDate(item.start_date) : "Continue"} to {displayDate(item.end_date)}</strong><small>{item.preview_only ? "Preview" : `${item.appended_count} bills added`}</small></span><span className={`status-pill ${item.status === "success" ? "success" : item.status === "failed" || item.status === "needs_review" ? "warning" : "neutral"}`}>{item.status === "success" ? "Completed" : item.status === "failed" ? "Not completed" : item.status === "needs_review" ? "Check needed" : item.status === "reviewed" ? "Reviewed" : "In progress"}</span></button></li>)}</ul></details>}
  </AppShell>;
}
