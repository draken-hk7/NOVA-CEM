const form = document.querySelector("#design-form");
const button = document.querySelector("#design-button");
const statusEl = document.querySelector("#status");
const errorEl = document.querySelector("#error");
const activeJobEl = document.querySelector("#active-job");
const resultCardsEl = document.querySelector("#result-cards");
const validationResultsEl = document.querySelector("#validation-results");
const downloadButtonsEl = document.querySelector("#download-buttons");
const historyListEl = document.querySelector("#history-list");
const refreshHistoryButton = document.querySelector("#refresh-history");

const numberFormat = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 2
});

const metrics = [
  ["specific_impulse_s", "Isp", "s"],
  ["thrust_N", "Thrust", "N"],
  ["chamber_temp_K", "Chamber Temp", "K"],
  ["engine_mass_kg", "Engine Mass", "kg"],
  ["print_time_hours", "Print Time", "h"]
];

function setStatus(text) {
  statusEl.textContent = text;
}

function setError(message) {
  if (!message) {
    errorEl.hidden = true;
    errorEl.textContent = "";
    return;
  }
  errorEl.hidden = false;
  errorEl.textContent = message;
}

function formPayload() {
  const data = new FormData(form);
  return {
    propellant: data.get("propellant"),
    thrust_N: Number(data.get("thrust_N")),
    chamber_pressure_bar: Number(data.get("chamber_pressure_bar")),
    material: data.get("material")
  };
}

function renderValidation(validation) {
  const checks = validation?.checks || [];
  if (!checks.length) {
    validationResultsEl.className = "validation-results muted";
    validationResultsEl.textContent = "No validation run";
    return;
  }
  validationResultsEl.className = "validation-results";
  validationResultsEl.innerHTML = checks.map((check) => {
    const passed = Boolean(check.passed);
    const icon = passed ? "&#10003;" : "!";
    const status = passed ? "Passed" : "Warning";
    return `
      <article class="validation-check ${passed ? "passed" : "failed"}">
        <span class="validation-icon" aria-hidden="true">${icon}</span>
        <div>
          <strong>${check.name}</strong>
          <span>${status}</span>
          <p>${check.message}</p>
        </div>
      </article>
    `;
  }).join("");
}

function artifactLinks(files, labels) {
  return Object.entries(labels)
    .filter(([key]) => files?.[key])
    .map(([key, label]) => `<a href="${files[key]}">${label}</a>`)
    .join("");
}

function renderResults(job) {
  activeJobEl.textContent = job.job_id;
  resultCardsEl.innerHTML = metrics.map(([key, label, unit]) => {
    const value = job.metrics[key];
    return `
      <article class="metric-card">
        <span class="metric-label">${label}</span>
        <strong>${numberFormat.format(value)}</strong>
        <span class="metric-unit">${unit}</span>
      </article>
    `;
  }).join("");
  renderValidation(job.validation);

  downloadButtonsEl.classList.remove("muted");
  downloadButtonsEl.innerHTML = artifactLinks(job.files, {
    stl: "Download STL",
    step: "Download STEP",
    report: "Download PDF"
  });
}

function renderHistory(jobs) {
  if (!jobs.length) {
    historyListEl.innerHTML = '<p class="empty-state">No designs yet.</p>';
    return;
  }
  historyListEl.innerHTML = jobs.map((job) => {
    const p = job.parameters;
    const m = job.metrics;
    return `
      <article class="history-item">
        <div>
          <p class="history-title">${job.job_id}</p>
          <p class="history-meta">${job.created_at}</p>
        </div>
        <div>
          <p class="history-meta">${p.propellant}, ${numberFormat.format(p.thrust_N)} N, ${numberFormat.format(p.chamber_pressure_bar)} bar, ${p.material}</p>
          <p class="history-metrics">Isp ${numberFormat.format(m.specific_impulse_s)} s, mass ${numberFormat.format(m.engine_mass_kg)} kg, print ${numberFormat.format(m.print_time_hours)} h</p>
        </div>
        <div class="history-actions">${artifactLinks(job.files, { stl: "STL", step: "STEP", report: "PDF" })}</div>
      </article>
    `;
  }).join("");
}

async function loadHistory() {
  const response = await fetch("/api/history");
  if (!response.ok) {
    throw new Error("Could not load job history");
  }
  const payload = await response.json();
  renderHistory(payload.jobs);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("");
  setStatus("Designing");
  button.disabled = true;

  try {
    const response = await fetch("/api/design", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(formPayload())
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Design failed");
    }
    renderResults(payload.job);
    await loadHistory();
    setStatus("Complete");
  } catch (error) {
    setError(error.message);
    setStatus("Failed");
  } finally {
    button.disabled = false;
  }
});

refreshHistoryButton.addEventListener("click", async () => {
  setStatus("Refreshing");
  try {
    await loadHistory();
    setStatus("Ready");
  } catch (error) {
    setError(error.message);
    setStatus("Failed");
  }
});

loadHistory().catch((error) => {
  setError(error.message);
  setStatus("Failed");
});
