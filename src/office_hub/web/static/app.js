const form = document.querySelector("#job-form");
const taskSelect = document.querySelector("#task-name");
const message = document.querySelector("#form-message");
const jobsList = document.querySelector("#jobs-list");

function showTaskFields() {
  document.querySelector("#whatsapp-fields").classList.toggle("hidden", taskSelect.value !== "whatsapp_pdf_sender");
  document.querySelector("#busy-fields").classList.toggle("hidden", taskSelect.value !== "busy_exporter");
  document.querySelector("#sheets-fields").classList.toggle("hidden", taskSelect.value !== "gsheets_sync");
}

function payloadForSelectedTask() {
  if (taskSelect.value === "whatsapp_pdf_sender") {
    const payload = {};
    const folder = document.querySelector("#billing-folder").value.trim();
    const targetDate = document.querySelector("#target-date").value;
    if (folder) payload.folder = folder;
    if (targetDate) payload.target_date = targetDate;
    return payload;
  }
  if (taskSelect.value === "busy_exporter") {
    const payload = {
      report_type: document.querySelector("#busy-report-type").value,
      start_date: document.querySelector("#start-date").value,
      end_date: document.querySelector("#end-date").value,
      mode: document.querySelector("#busy-mode").value,
    };
    const inputFile = document.querySelector("#busy-input-file").value.trim();
    if (inputFile) payload.input_file = inputFile;
    return payload;
  }
  const payload = { row_count: Number(document.querySelector("#row-count").value || 0) };
  const sheetId = document.querySelector("#sheet-id").value.trim();
  if (sheetId) payload.sheet_id = sheetId;
  return payload;
}

function setMessage(text, kind = "") {
  message.textContent = text;
  message.className = `form-message ${kind}`;
}

function statusMarkup(status) {
  return `<span class="status status-${status}">${status}</span>`;
}

function renderJobs(jobs) {
  if (!jobs.length) {
    jobsList.innerHTML = '<div class="empty-state">No jobs yet. Start with a dry run.</div>';
    return;
  }
  jobsList.innerHTML = jobs.map((job) => {
    const title = job.task_name.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
    const mode = job.dry_run ? " · dry run" : "";
    return `<div class="job-row" data-job-id="${job.id}">
      <div class="job-main"><strong>${title}</strong><small>${job.created_at}${mode}</small></div>
      ${statusMarkup(job.status)}
    </div>`;
  }).join("");
}

async function refreshJobs() {
  const response = await fetch("/api/jobs");
  if (response.ok) renderJobs(await response.json());
}

async function checkHealth() {
  const pill = document.querySelector("#health-pill");
  try {
    const response = await fetch("/health");
    if (!response.ok) throw new Error("health check failed");
    pill.classList.add("ok");
    pill.innerHTML = '<span class="dot"></span> Engine online';
  } catch (error) {
    pill.innerHTML = '<span class="dot"></span> Engine unavailable';
  }
}

taskSelect.addEventListener("change", showTaskFields);
document.querySelector("#refresh-jobs").addEventListener("click", refreshJobs);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("Queueing…");
  const dryRun = document.querySelector("#dry-run").checked;
  try {
    const response = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_name: taskSelect.value, payload: payloadForSelectedTask(), dry_run: dryRun }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Unable to queue job");
    setMessage(`Queued ${data.id.slice(0, 8)}…`, "success");
    await refreshJobs();
  } catch (error) {
    setMessage(error.message, "error");
  }
});

showTaskFields();
checkHealth();
setInterval(refreshJobs, 3000);
