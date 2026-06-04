const statusEl = document.querySelector("#status");
const errorEl = document.querySelector("#error");
const activeJobEl = document.querySelector("#active-job");
const resultCardsEl = document.querySelector("#result-cards");
const validationResultsEl = document.querySelector("#validation-results");
const downloadButtonsEl = document.querySelector("#download-buttons");
const historyListEl = document.querySelector("#history-list");
const refreshHistoryButton = document.querySelector("#refresh-history");
const themeToggleButton = document.querySelector("#theme-toggle");
const searchFilterEl = document.querySelector("#history-search");
const moduleFilterEl = document.querySelector("#module-filter");
const propellantFilterEl = document.querySelector("#propellant-filter");
const dateFromFilterEl = document.querySelector("#date-from-filter");
const dateToFilterEl = document.querySelector("#date-to-filter");
const compareButton = document.querySelector("#compare-button");
const clearCompareButton = document.querySelector("#clear-compare");
const closeCompareButton = document.querySelector("#close-compare");
const compareCountEl = document.querySelector("#compare-count");
const comparePanelEl = document.querySelector("#compare-panel");
const compareContentEl = document.querySelector("#compare-content");
const stlPreviewSectionEl = document.querySelector("#stl-preview-section");
const stlViewerEl = document.querySelector("#stl-viewer");
const stlPreviewStatusEl = document.querySelector("#stl-preview-status");

const numberFormat = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 3
});

let allJobs = [];
const selectedJobIds = new Set();
let stlViewerState = null;

const modules = {
  "rocket-engine": {
    label: "Rocket Engine",
    form: document.querySelector("#engine-form"),
    button: document.querySelector("#engine-button"),
    endpoint: "/api/design/rocket-engine",
    metrics: [
      ["specific_impulse_s", "Isp", "s"],
      ["thrust_N", "Thrust", "N"],
      ["chamber_temp_K", "Chamber Temp", "K"],
      ["engine_mass_kg", "Engine Mass", "kg"],
      ["print_time_hours", "Print Time", "h"]
    ],
    payload(form) {
      const data = new FormData(form);
      return {
        propellant: data.get("propellant"),
        thrust_N: Number(data.get("thrust_N")),
        chamber_pressure_bar: Number(data.get("chamber_pressure_bar")),
        material: data.get("material")
      };
    }
  },
  "heat-exchanger": {
    label: "Heat Exchanger",
    form: document.querySelector("#hx-form"),
    button: document.querySelector("#hx-button"),
    endpoint: "/api/design/heat-exchanger",
    metrics: [
      ["effectiveness", "Effectiveness", ""],
      ["ntu", "NTU", ""],
      ["required_area_m2", "Required Area", "m2"],
      ["pressure_drop_bar", "Pressure Drop", "bar"],
      ["cold_outlet_temp_C", "Cold Outlet", "C"]
    ],
    payload(form) {
      const data = new FormData(form);
      return {
        hot_fluid: data.get("hot_fluid"),
        cold_fluid: data.get("cold_fluid"),
        duty_kW: Number(data.get("duty_kW")),
        hot_inlet_temp_C: Number(data.get("hot_inlet_temp_C")),
        hot_outlet_temp_C: Number(data.get("hot_outlet_temp_C")),
        cold_inlet_temp_C: Number(data.get("cold_inlet_temp_C"))
      };
    }
  },
  actuator: {
    label: "Actuator",
    form: document.querySelector("#actuator-form"),
    button: document.querySelector("#actuator-button"),
    endpoint: "/api/design/actuator",
    metrics: [
      ["force_output_N", "Force Output", "N"],
      ["current_draw_A", "Current Draw", "A"],
      ["power_consumption_W", "Power", "W"],
      ["response_time_ms", "Response Time", "ms"]
    ],
    payload(form) {
      const data = new FormData(form);
      return {
        force_N: Number(data.get("force_N")),
        stroke_mm: Number(data.get("stroke_mm")),
        voltage_V: Number(data.get("voltage_V")),
        response_time_ms: Number(data.get("response_time_ms")),
        material: data.get("material")
      };
    }
  }
};

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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function moduleLabel(module) {
  return modules[module]?.label || "Rocket Engine";
}

function metricDefinition(module) {
  return modules[module]?.metrics || modules["rocket-engine"].metrics;
}

function metricLabel(key) {
  for (const config of Object.values(modules)) {
    const metric = config.metrics.find(([metricKey]) => metricKey === key);
    if (metric) {
      return metric;
    }
  }
  return [key, key, ""];
}

function formatValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return value ?? "--";
  }
  return numberFormat.format(value);
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
          <strong>${escapeHtml(check.name)}</strong>
          <span>${status}</span>
          <p>${escapeHtml(check.message)}</p>
        </div>
      </article>
    `;
  }).join("");
}

function artifactLinks(files, labels) {
  return Object.entries(labels)
    .filter(([key]) => files?.[key])
    .map(([key, label]) => `<a href="${escapeHtml(files[key])}">${escapeHtml(label)}</a>`)
    .join("");
}

function stlDownloadUrl(job) {
  if (!job?.files?.stl) {
    return "";
  }
  if (!job.job_id) {
    return job.files.stl;
  }
  return `/download/${encodeURIComponent(job.job_id)}/stl`;
}

function clearSTLPreview() {
  if (stlViewerState?.animationFrame) {
    cancelAnimationFrame(stlViewerState.animationFrame);
  }
  if (stlViewerState?.resizeObserver) {
    stlViewerState.resizeObserver.disconnect();
  }
  if (stlViewerState?.geometry) {
    stlViewerState.geometry.dispose();
  }
  if (stlViewerState?.material) {
    stlViewerState.material.dispose();
  }
  if (stlViewerState?.renderer) {
    stlViewerState.renderer.dispose();
  }
  stlViewerState = null;
  stlViewerEl.replaceChildren();
}

function showSTLPreviewMessage(message, stlUrl = "") {
  stlViewerEl.replaceChildren();
  const wrapper = document.createElement("div");
  wrapper.className = "muted preview-message";
  const text = document.createElement("p");
  text.textContent = message;
  wrapper.appendChild(text);
  if (stlUrl) {
    const link = document.createElement("a");
    link.href = stlUrl;
    link.textContent = "Download STL to view in FreeCAD";
    wrapper.appendChild(link);
  }
  stlViewerEl.appendChild(wrapper);
}

function stlPreviewLibraryError() {
  if (!window.THREE) {
    return "Three.js failed to load from cdnjs: window.THREE is unavailable.";
  }
  if (!THREE.STLLoader) {
    return "Three.js STLLoader failed to load from cdnjs: THREE.STLLoader is unavailable.";
  }
  if (!THREE.OrbitControls) {
    return "Three.js OrbitControls failed to load from cdnjs: THREE.OrbitControls is unavailable.";
  }
  return "";
}

async function fetchSTLGeometry(stlUrl) {
  let response;
  try {
    response = await fetch(stlUrl, { credentials: "same-origin" });
  } catch (error) {
    throw new Error(`STL fetch failed for ${stlUrl}: ${error.message}`);
  }
  if (!response.ok) {
    throw new Error(`STL fetch failed for ${stlUrl}: ${response.status} ${response.statusText}`);
  }
  const buffer = await response.arrayBuffer();
  try {
    return new THREE.STLLoader().parse(buffer);
  } catch (error) {
    throw new Error(`STL parse failed for ${stlUrl}: ${error.message}`);
  }
}

async function renderSTLPreview(stlUrl, label) {
  clearSTLPreview();
  if (!stlUrl) {
    stlPreviewSectionEl.hidden = true;
    stlPreviewStatusEl.textContent = "No STL";
    return;
  }
  stlPreviewSectionEl.hidden = false;
  stlPreviewStatusEl.textContent = "Loading";

  const libraryError = stlPreviewLibraryError();
  if (libraryError) {
    stlPreviewStatusEl.textContent = "Preview unavailable";
    showSTLPreviewMessage(`${libraryError} Download STL to view in FreeCAD.`, stlUrl);
    return;
  }

  const state = {
    renderer: null,
    controls: null,
    geometry: null,
    material: null,
    animationFrame: null,
    resizeObserver: null
  };
  stlViewerState = state;

  let geometry;
  try {
    geometry = await fetchSTLGeometry(stlUrl);
  } catch (error) {
    if (stlViewerState !== state) {
      return;
    }
    stlPreviewStatusEl.textContent = "Preview failed";
    showSTLPreviewMessage(error.message, stlUrl);
    return;
  }
  if (stlViewerState !== state) {
    geometry.dispose();
    return;
  }
  state.geometry = geometry;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue("--field").trim() || "#ffffff");

  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 10000);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  stlViewerEl.appendChild(renderer.domElement);
  state.renderer = renderer;

  const hemiLight = new THREE.HemisphereLight(0xffffff, 0x64706a, 1.15);
  scene.add(hemiLight);
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.4);
  keyLight.position.set(1.8, -2.2, 2.8);
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0x88c8b8, 0.55);
  fillLight.position.set(-2.0, 1.5, 1.0);
  scene.add(fillLight);

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.enablePan = false;
  controls.minDistance = 0.35;
  state.controls = controls;

  function resizeRenderer() {
    const width = Math.max(220, Math.min(300, stlViewerEl.clientWidth || 300));
    const height = Math.max(220, Math.min(300, stlViewerEl.clientHeight || width));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  state.resizeObserver = new ResizeObserver(resizeRenderer);
  state.resizeObserver.observe(stlViewerEl);
  resizeRenderer();

  function animate() {
    if (stlViewerState !== state) {
      return;
    }
    state.animationFrame = requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }

  geometry.computeBoundingBox();
  geometry.computeVertexNormals();
  const bounds = geometry.boundingBox;
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  bounds.getSize(size);
  bounds.getCenter(center);
  geometry.translate(-center.x, -center.y, -center.z);

  const maxDimension = Math.max(size.x, size.y, size.z, 1);
  const material = new THREE.MeshStandardMaterial({
    color: 0x9fc7bd,
    metalness: 0.28,
    roughness: 0.46
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = label;
  scene.add(mesh);

  camera.position.set(maxDimension * 0.95, -maxDimension * 1.25, maxDimension * 0.72);
  camera.near = Math.max(maxDimension / 1000, 0.1);
  camera.far = maxDimension * 12;
  camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix();
  controls.target.set(0, 0, 0);
  controls.maxDistance = maxDimension * 5;
  controls.update();

  state.material = material;
  stlPreviewStatusEl.textContent = label;
  animate();
}

function renderResults(job) {
  const module = job.module || "rocket-engine";
  activeJobEl.textContent = `${moduleLabel(module)} - ${job.job_id}`;
  resultCardsEl.innerHTML = metricDefinition(module).map(([key, label, unit]) => {
    const value = job.metrics[key];
    return `
      <article class="metric-card">
        <span class="metric-label">${escapeHtml(label)}</span>
        <strong>${escapeHtml(formatValue(value))}</strong>
        <span class="metric-unit">${escapeHtml(unit)}</span>
      </article>
    `;
  }).join("");
  renderValidation(job.validation);

  downloadButtonsEl.classList.remove("muted");
  downloadButtonsEl.innerHTML = artifactLinks(job.files, {
    stl: "Download STL",
    step: "Download STEP",
    report: "Download PDF"
  }) || "No artifacts available";
  renderSTLPreview(stlDownloadUrl(job), `${moduleLabel(module)} - ${job.job_id}`);
}

function applyHistoryFilters() {
  const query = searchFilterEl.value.trim().toLowerCase();
  const moduleValue = moduleFilterEl.value;
  const propellantValue = propellantFilterEl.value;
  const fromValue = dateFromFilterEl.value ? new Date(`${dateFromFilterEl.value}T00:00:00`) : null;
  const toValue = dateToFilterEl.value ? new Date(`${dateToFilterEl.value}T23:59:59`) : null;

  return allJobs.filter((job) => {
    const module = job.module || "rocket-engine";
    const parameters = job.parameters || {};
    const created = new Date(job.created_at);
    const searchable = `${job.job_id} ${module} ${JSON.stringify(parameters)} ${JSON.stringify(job.metrics || {})}`.toLowerCase();

    if (query && !searchable.includes(query)) {
      return false;
    }
    if (moduleValue && module !== moduleValue) {
      return false;
    }
    if (propellantValue && parameters.propellant !== propellantValue) {
      return false;
    }
    if (fromValue && created < fromValue) {
      return false;
    }
    if (toValue && created > toValue) {
      return false;
    }
    return true;
  });
}

function renderFilteredHistory() {
  renderHistory(applyHistoryFilters());
}

function renderHistory(jobs) {
  selectedJobIds.forEach((jobId) => {
    if (!allJobs.some((job) => job.job_id === jobId)) {
      selectedJobIds.delete(jobId);
    }
  });
  updateCompareControls();

  if (!jobs.length) {
    historyListEl.innerHTML = '<p class="empty-state">No matching designs.</p>';
    return;
  }
  historyListEl.innerHTML = jobs.map((job) => {
    const module = job.module || "rocket-engine";
    const selected = selectedJobIds.has(job.job_id);
    const compareDisabled = selectedJobIds.size >= 3 && !selected;
    const protectedDelete = Boolean(job.starred);
    return `
      <article class="history-item ${job.starred ? "starred" : ""}">
        <label class="compare-pick">
          <input class="compare-checkbox" type="checkbox" data-job-id="${escapeHtml(job.job_id)}" ${selected ? "checked" : ""} ${compareDisabled ? "disabled" : ""}>
          <span>Compare</span>
        </label>
        <div>
          <p class="history-title">${escapeHtml(moduleLabel(module))} - ${escapeHtml(job.job_id)}</p>
          <p class="history-meta">${escapeHtml(job.created_at)}</p>
        </div>
        <div>
          <p class="history-meta">${escapeHtml(historyParameters(job))}</p>
          <p class="history-metrics">${escapeHtml(historyMetrics(job))}</p>
        </div>
        <div class="history-actions">
          ${artifactLinks(job.files, { stl: "STL", step: "STEP", report: "PDF" })}
          <button class="secondary star-action" type="button" data-job-id="${escapeHtml(job.job_id)}">${job.starred ? "Starred" : "Star"}</button>
          <button class="secondary danger-action" type="button" data-job-id="${escapeHtml(job.job_id)}" ${protectedDelete ? "disabled" : ""}>Delete</button>
        </div>
      </article>
    `;
  }).join("");
}

function historyParameters(job) {
  const p = job.parameters || {};
  switch (job.module || "rocket-engine") {
    case "heat-exchanger":
      return `${p.hot_fluid} to ${p.cold_fluid}, ${formatValue(p.duty_kW)} kW, ${formatValue(p.hot_inlet_temp_C)} C to ${formatValue(p.hot_outlet_temp_C)} C`;
    case "actuator":
      return `${p.actuator_type || "solenoid"}, ${formatValue(p.force_N)} N, ${formatValue(p.stroke_mm)} mm, ${formatValue(p.voltage_V)} V, ${p.material}`;
    default:
      return `${p.propellant}, ${formatValue(p.thrust_N)} N, ${formatValue(p.chamber_pressure_bar)} bar, ${p.material}`;
  }
}

function historyMetrics(job) {
  const m = job.metrics || {};
  switch (job.module || "rocket-engine") {
    case "heat-exchanger":
      return `effectiveness ${formatValue(m.effectiveness)}, NTU ${formatValue(m.ntu)}, pressure drop ${formatValue(m.pressure_drop_bar)} bar`;
    case "actuator":
      return `force ${formatValue(m.force_output_N)} N, current ${formatValue(m.current_draw_A)} A, power ${formatValue(m.power_consumption_W)} W`;
    default:
      return `Isp ${formatValue(m.specific_impulse_s)} s, mass ${formatValue(m.engine_mass_kg)} kg, print ${formatValue(m.print_time_hours)} h`;
  }
}

async function loadHistory() {
  const response = await fetch("/api/history");
  if (!response.ok) {
    throw new Error("Could not load job history");
  }
  const payload = await response.json();
  allJobs = payload.jobs || [];
  renderFilteredHistory();
}

function updateCompareControls() {
  compareCountEl.textContent = `${selectedJobIds.size} selected`;
  compareButton.disabled = selectedJobIds.size < 2;
}

function selectedJobs() {
  return allJobs.filter((job) => selectedJobIds.has(job.job_id));
}

function renderCompare() {
  const jobs = selectedJobs();
  if (jobs.length < 2) {
    comparePanelEl.hidden = true;
    return;
  }

  const metricKeys = [...new Set(jobs.flatMap((job) => metricDefinition(job.module || "rocket-engine").map(([key]) => key)))];
  compareContentEl.innerHTML = `
    <table class="compare-table">
      <thead>
        <tr>
          <th>Metric</th>
          ${jobs.map((job) => `<th>${escapeHtml(moduleLabel(job.module || "rocket-engine"))}<span>${escapeHtml(job.job_id)}</span></th>`).join("")}
        </tr>
      </thead>
      <tbody>
        <tr>
          <th>Created</th>
          ${jobs.map((job) => `<td>${escapeHtml(job.created_at)}</td>`).join("")}
        </tr>
        ${metricKeys.map((key) => {
          const [, label, unit] = metricLabel(key);
          return `
            <tr>
              <th>${escapeHtml(label)}</th>
              ${jobs.map((job) => `<td>${escapeHtml(formatValue(job.metrics?.[key]))}${unit ? ` ${escapeHtml(unit)}` : ""}</td>`).join("")}
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
  comparePanelEl.hidden = false;
}

async function setStarred(jobId, starred) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/star`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ starred })
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Could not update star");
  }
}

async function deleteJob(jobId) {
  const confirmed = window.confirm(`Delete job ${jobId}? This removes its output folder and history entry.`);
  if (!confirmed) {
    return;
  }
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE"
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Could not delete job");
  }
  selectedJobIds.delete(jobId);
  await loadHistory();
  renderCompare();
}

function bindDesignForm(module, config) {
  config.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setError("");
    setStatus(`Designing ${config.label}`);
    config.button.disabled = true;

    try {
      const response = await fetch(config.endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(config.payload(config.form))
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
      config.button.disabled = false;
    }
  });
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("nova-theme", theme);
  themeToggleButton.textContent = theme === "dark" ? "Light Mode" : "Dark Mode";
}

Object.entries(modules).forEach(([module, config]) => bindDesignForm(module, config));

for (const control of [searchFilterEl, moduleFilterEl, propellantFilterEl, dateFromFilterEl, dateToFilterEl]) {
  control.addEventListener("input", renderFilteredHistory);
  control.addEventListener("change", renderFilteredHistory);
}

historyListEl.addEventListener("change", (event) => {
  const checkbox = event.target.closest(".compare-checkbox");
  if (!checkbox) {
    return;
  }
  const jobId = checkbox.dataset.jobId;
  if (checkbox.checked && selectedJobIds.size >= 3 && !selectedJobIds.has(jobId)) {
    checkbox.checked = false;
    setError("Compare mode supports up to 3 jobs.");
    return;
  }
  if (checkbox.checked) {
    selectedJobIds.add(jobId);
  } else {
    selectedJobIds.delete(jobId);
  }
  renderFilteredHistory();
  renderCompare();
});

historyListEl.addEventListener("click", async (event) => {
  const starButton = event.target.closest(".star-action");
  const deleteButton = event.target.closest(".danger-action");
  try {
    if (starButton) {
      setError("");
      const job = allJobs.find((item) => item.job_id === starButton.dataset.jobId);
      await setStarred(starButton.dataset.jobId, !job?.starred);
      await loadHistory();
      setStatus("Ready");
    }
    if (deleteButton) {
      setError("");
      await deleteJob(deleteButton.dataset.jobId);
      setStatus("Ready");
    }
  } catch (error) {
    setError(error.message);
    setStatus("Failed");
  }
});

compareButton.addEventListener("click", renderCompare);

clearCompareButton.addEventListener("click", () => {
  selectedJobIds.clear();
  comparePanelEl.hidden = true;
  renderFilteredHistory();
});

closeCompareButton.addEventListener("click", () => {
  comparePanelEl.hidden = true;
});

themeToggleButton.addEventListener("click", () => {
  const current = document.documentElement.dataset.theme || "light";
  setTheme(current === "dark" ? "light" : "dark");
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

setTheme(localStorage.getItem("nova-theme") || "light");
loadHistory().catch((error) => {
  setError(error.message);
  setStatus("Failed");
});
