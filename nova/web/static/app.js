const statusEl = document.querySelector("#status");
const serverStatusEl = document.querySelector("#server-status");
const summaryTotalJobsEl = document.querySelector("#summary-total-jobs");
const summaryTotalEnginesEl = document.querySelector("#summary-total-engines");
const summaryLastDesignEl = document.querySelector("#summary-last-design");
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
const stlFullscreenButton = document.querySelector("#stl-fullscreen-button");
const clipSliders = {
  x: document.querySelector("#clip-x-slider"),
  y: document.querySelector("#clip-y-slider"),
  z: document.querySelector("#clip-z-slider")
};
const clipValueEls = {
  x: document.querySelector("#clip-x-value"),
  y: document.querySelector("#clip-y-value"),
  z: document.querySelector("#clip-z-value")
};
const clipResetButton = document.querySelector("#clip-reset-button");
const sectionViewButtons = document.querySelectorAll("[data-section-view]");
const auxiliaryViewButtons = document.querySelectorAll("[data-aux-view]");
const flowToggleButton = document.querySelector("#flow-toggle-button");
const flowSpeedSlider = document.querySelector("#flow-speed-slider");
const flowSpeedValueEl = document.querySelector("#flow-speed-value");
const renderModeButton = document.querySelector("#render-mode-button");
const viewerTabButtons = document.querySelectorAll("[data-viewer-tab]");
const viewerPanels = document.querySelectorAll("[data-viewer-panel]");
const cadViewerEl = document.querySelector("#cad-viewer");
const cadViewerStatusEl = document.querySelector("#cad-viewer-status");
const designLogListEl = document.querySelector("#design-log-list");
const tabButtons = document.querySelectorAll(".tab-button");
const tabPanels = document.querySelectorAll("[data-tab-panel]");
const moduleForms = document.querySelectorAll("[data-module-form]");
const missionFormEl = document.querySelector("#mission-form");
const missionEngineJobSelectEl = document.querySelector("#mission_engine_job_id");
const missionButtonEl = document.querySelector("#mission-button");
const missionErrorEl = document.querySelector("#mission-error");
const missionActiveJobEl = document.querySelector("#mission-active-job");
const missionResultCardsEl = document.querySelector("#mission-result-cards");
const missionDownloadButtonsEl = document.querySelector("#mission-download-buttons");
const deleteModalBackdropEl = document.querySelector("#delete-modal-backdrop");
const deleteModalJobEl = document.querySelector("#delete-modal-job");
const deleteModalConfirmButton = document.querySelector("#delete-modal-confirm");
const deleteModalCancelButton = document.querySelector("#delete-modal-cancel");
const deleteModalCloseButton = document.querySelector("#delete-modal-close");

const numberFormat = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 3
});

let allJobs = [];
const selectedJobIds = new Set();
let stlViewerState = null;
let threeViewerLibrariesPromise = null;
let cadViewerLibraryPromise = null;
let chartLibraryPromise = null;
let compareRadarChart = null;
let pendingDeleteJobId = "";
let deleteModalPreviousFocus = null;
let activeDesignModule = "rocket-engine";

const THREE_VIEWER_SCRIPTS = [
  {
    label: "Three.js r128",
    url: "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js",
    isAvailable: () => Boolean(window.THREE && THREE.REVISION === "128"),
    globalName: "window.THREE revision 128"
  },
  {
    label: "Three.js r128 STLLoader",
    url: "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js",
    isAvailable: () => Boolean(window.THREE && THREE.REVISION === "128" && THREE.STLLoader),
    globalName: "THREE.STLLoader"
  },
  {
    label: "Three.js r128 OrbitControls",
    url: "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js",
    isAvailable: () => Boolean(window.THREE && THREE.REVISION === "128" && THREE.OrbitControls),
    globalName: "THREE.OrbitControls"
  }
];

const CAD_VIEWER_SCRIPT = {
  label: "Online 3D Viewer",
  url: "https://cdn.jsdelivr.net/npm/online-3d-viewer@0.18.0/build/engine/o3dv.min.js",
  isAvailable: () => Boolean(window.OV && window.OV.EmbeddedViewer),
  globalName: "OV.EmbeddedViewer"
};

const CHART_JS_SCRIPT = {
  label: "Chart.js",
  url: "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",
  isAvailable: () => Boolean(window.Chart),
  globalName: "window.Chart"
};

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
  },
  mission: {
    label: "Mission",
    metrics: [
      ["delta_v_m_s", "Delta-V", "m/s"],
      ["burn_time_s", "Burn Time", "s"],
      ["thrust_to_weight", "T/W", "ratio"],
      ["max_altitude_m", "Max Altitude", "m"],
      ["hydrogen_mass_needed_kg_s", "H2 Flow", "kg/s"]
    ]
  }
};

function setStatus(text) {
  statusEl.textContent = text;
}

function setServerStatus(online, text = "") {
  serverStatusEl.dataset.state = online ? "online" : "offline";
  serverStatusEl.textContent = text || (online ? "Server online" : "Server offline");
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

function setMissionError(message) {
  if (!message) {
    missionErrorEl.hidden = true;
    missionErrorEl.textContent = "";
    return;
  }
  missionErrorEl.hidden = false;
  missionErrorEl.textContent = message;
}

function setActiveModule(module) {
  activeDesignModule = module || activeDesignModule;
  moduleForms.forEach((form) => {
    const active = form.dataset.moduleForm === activeDesignModule;
    form.hidden = !active;
    form.classList.toggle("active", active);
  });
}

function setActiveTab(targetId, moduleTarget = "") {
  tabPanels.forEach((panel) => {
    const active = panel.id === targetId;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  tabButtons.forEach((button) => {
    const sameView = button.dataset.tabTarget === targetId;
    const sameModule = !button.dataset.moduleTarget || button.dataset.moduleTarget === (moduleTarget || activeDesignModule);
    const active = sameView && sameModule;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  if (moduleTarget) {
    setActiveModule(moduleTarget);
  }
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

function formatCompactNumber(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? (Number.isInteger(value) ? String(value) : numberFormat.format(value)) : "--";
  }
  return value ?? "--";
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value || "--";
  }
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "--";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${numberFormat.format(size)} ${units[unitIndex]}`;
}

function updateDashboardSummary() {
  const totalJobs = allJobs.length;
  const totalEngines = allJobs.filter((job) => (job.module || "rocket-engine") === "rocket-engine").length;
  const datedJobs = allJobs
    .map((job) => ({ job, date: new Date(job.created_at) }))
    .filter((item) => !Number.isNaN(item.date.getTime()))
    .sort((a, b) => b.date - a.date);
  summaryTotalJobsEl.textContent = String(totalJobs);
  summaryTotalEnginesEl.textContent = String(totalEngines);
  summaryLastDesignEl.textContent = datedJobs.length ? formatDateTime(datedJobs[0].job.created_at) : "No jobs";
}

function parseEngineJobTokens(jobId) {
  const match = String(jobId || "").match(/(kerolox|methalox|hydrolox|hypergolic|solid)[_-]([0-9]+(?:p[0-9]+|\.[0-9]+)?)N[_-]([0-9]+(?:p[0-9]+|\.[0-9]+)?)bar/i);
  if (!match) {
    return {};
  }
  return {
    propellant: match[1].toLowerCase(),
    thrust_N: Number(match[2].replace("p", ".")),
    chamber_pressure_bar: Number(match[3].replace("p", "."))
  };
}

function compactJobTime(job) {
  const created = new Date(job.created_at);
  if (!Number.isNaN(created.getTime())) {
    return created.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  const match = String(job.job_id || "").match(/_(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(?:\d{2})?/);
  return match ? `${match[2]}:${match[3]}` : "--:--";
}

function missionEngineLabel(job) {
  const parsed = parseEngineJobTokens(job.job_id);
  const parameters = job.parameters || {};
  const propellant = parameters.propellant || parsed.propellant || "engine";
  const thrust = Number(parameters.thrust_N ?? job.metrics?.thrust_N ?? parsed.thrust_N);
  const pressure = Number(parameters.chamber_pressure_bar ?? parsed.chamber_pressure_bar);
  return `${propellant} ${formatCompactNumber(thrust)}N ${formatCompactNumber(pressure)}bar ${compactJobTime(job)}`;
}

function populateMissionEngineOptions() {
  const previousValue = missionEngineJobSelectEl.value;
  const engineJobs = allJobs.filter((job) => (job.module || "rocket-engine") === "rocket-engine");
  missionEngineJobSelectEl.replaceChildren();

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = engineJobs.length ? "Select a rocket engine job" : "No rocket engine jobs yet";
  missionEngineJobSelectEl.appendChild(placeholder);

  for (const job of engineJobs) {
    const option = document.createElement("option");
    option.value = job.job_id;
    option.textContent = missionEngineLabel(job);
    option.title = job.job_id;
    missionEngineJobSelectEl.appendChild(option);
  }

  if (engineJobs.some((job) => job.job_id === previousValue)) {
    missionEngineJobSelectEl.value = previousValue;
  }
  missionEngineJobSelectEl.disabled = !engineJobs.length;
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

function timestampLabel() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function setDesignLog(entries) {
  const list = entries.length ? entries : [{ text: "No design running", state: "idle" }];
  designLogListEl.innerHTML = list.map((entry) => {
    const text = typeof entry === "string" ? entry : entry.text;
    const state = typeof entry === "string" ? "done" : entry.state || "done";
    const time = typeof entry === "string" ? timestampLabel() : entry.time || timestampLabel();
    return `<li class="${escapeHtml(state)}"><span>${escapeHtml(time)}</span>${escapeHtml(text)}</li>`;
  }).join("");
}

function appendDesignLog(text, state = "done") {
  const existingIdle = designLogListEl.querySelector(".idle");
  if (existingIdle) {
    designLogListEl.replaceChildren();
  }
  const item = document.createElement("li");
  item.className = state;
  const time = document.createElement("span");
  time.textContent = timestampLabel();
  item.appendChild(time);
  item.appendChild(document.createTextNode(text));
  designLogListEl.appendChild(item);
  designLogListEl.scrollTop = designLogListEl.scrollHeight;
}

function designLogSteps(module) {
  const shared = ["Checking input constraints", "Exporting artifacts", "Recording job history"];
  const moduleSteps = {
    "rocket-engine": [
      "Computing combustion",
      "Sizing throat and nozzle contour",
      "Solving cooling channel thermal loads",
      "Checking structure and manufacturability",
      "Generating engine geometry"
    ],
    "heat-exchanger": [
      "Computing NTU-effectiveness",
      "Sizing flow passages",
      "Estimating pressure drop",
      "Generating heat exchanger geometry"
    ],
    actuator: [
      "Solving electromagnetic force",
      "Sizing coil and wire gauge",
      "Checking response time and heating",
      "Generating actuator geometry"
    ]
  };
  return [...shared.slice(0, 1), ...(moduleSteps[module] || moduleSteps["rocket-engine"]), ...shared.slice(1)];
}

function startDesignLog(module) {
  setDesignLog([]);
  appendDesignLog(`${moduleLabel(module)} design started`, "running");
  return designLogSteps(module);
}

function finishDesignLog(job) {
  const entries = Array.isArray(job?.design_log) ? job.design_log : [];
  if (!entries.length) {
    appendDesignLog("Design completed", "done");
    return;
  }
  setDesignLog(entries.map((entry) => ({ text: `${entry} done`, state: "done" })));
}

function artifactDownloadUrl(job, artifact) {
  if (!job?.files?.[artifact]) {
    return "";
  }
  if (!job.job_id) {
    return job.files[artifact];
  }
  return `/download/${encodeURIComponent(job.job_id)}/${encodeURIComponent(artifact)}`;
}

function artifactLinks(job, labels) {
  return Object.entries(labels)
    .filter(([key]) => job?.files?.[key])
    .map(([key, label]) => {
      const href = artifactDownloadUrl(job, key);
      return `<a href="${escapeHtml(href)}" download data-job-id="${escapeHtml(job.job_id)}" data-artifact="${escapeHtml(key)}">${escapeHtml(label)}</a>`;
    })
    .join("");
}

function stlDownloadUrl(job) {
  return artifactDownloadUrl(job, "stl");
}

function updateClipControlLabels() {
  for (const axis of Object.keys(clipSliders)) {
    clipValueEls[axis].textContent = `${Number(clipSliders[axis].value).toFixed(0)}%`;
  }
}

function setClipControlValues(values) {
  for (const axis of Object.keys(clipSliders)) {
    clipSliders[axis].value = String(values[axis] ?? 0);
  }
  updateClipControlLabels();
  if (stlViewerState?.updateClipping) {
    stlViewerState.updateClipping();
  }
}

function updateFlowSpeedLabel() {
  flowSpeedValueEl.textContent = `${Number(flowSpeedSlider.value).toFixed(2).replace(/\.?0+$/, "")}x`;
}

function fullscreenSupported() {
  return Boolean(stlPreviewSectionEl.requestFullscreen && document.exitFullscreen);
}

function updateSTLFullscreenButton() {
  const active = document.fullscreenElement === stlPreviewSectionEl;
  stlFullscreenButton.hidden = stlPreviewSectionEl.hidden || !fullscreenSupported();
  stlFullscreenButton.textContent = active ? "Exit Fullscreen" : "Fullscreen";
  stlFullscreenButton.setAttribute("aria-pressed", String(active));
  if (stlViewerState?.resizeRenderer || stlViewerState?.fitCamera) {
    const refreshViewport = stlViewerState.fitCamera || stlViewerState.resizeRenderer;
    requestAnimationFrame(() => {
      if (stlViewerState?.fitCamera === refreshViewport || stlViewerState?.resizeRenderer === refreshViewport) {
        refreshViewport();
        stlViewerState?.renderer?.domElement?.focus?.();
      }
    });
  }
}

async function toggleSTLFullscreen() {
  if (!fullscreenSupported()) {
    setError("Fullscreen mode is not supported by this browser.");
    return;
  }
  try {
    if (document.fullscreenElement === stlPreviewSectionEl) {
      await document.exitFullscreen();
    } else {
      await stlPreviewSectionEl.requestFullscreen();
    }
  } catch (error) {
    setError(`Could not toggle fullscreen: ${error.message}`);
    setStatus("Failed");
  }
}

function clearSTLPreview() {
  if (stlViewerState?.animationFrame) {
    cancelAnimationFrame(stlViewerState.animationFrame);
  }
  if (stlViewerState?.resizeObserver) {
    stlViewerState.resizeObserver.disconnect();
  }
  if (stlViewerState?.flow?.dispose) {
    stlViewerState.flow.dispose();
  }
  if (stlViewerState?.geometry) {
    stlViewerState.geometry.dispose();
  }
  if (stlViewerState?.material) {
    stlViewerState.material.dispose();
  }
  if (stlViewerState?.clipHelperGroup) {
    stlViewerState.clipHelperGroup.children.forEach((child) => {
      child.geometry?.dispose();
      child.material?.dispose();
    });
  }
  if (stlViewerState?.renderer) {
    stlViewerState.renderer.dispose();
  }
  stlViewerState = null;
  stlViewerEl.replaceChildren();
  flowToggleButton.textContent = "Play flow";
  renderModeButton.hidden = true;
  renderModeButton.textContent = "Mode: Solid";
  updateSTLFullscreenButton();
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

function setViewerTab(tabName) {
  viewerTabButtons.forEach((button) => {
    const active = button.dataset.viewerTab === tabName;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  viewerPanels.forEach((panel) => {
    const active = panel.dataset.viewerPanel === tabName;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });
  if (tabName === "mesh" && stlViewerState?.fitCamera) {
    requestAnimationFrame(() => stlViewerState?.fitCamera?.());
  }
}

function showCADPreviewMessage(message, stepUrl = "") {
  cadViewerEl.replaceChildren();
  cadViewerStatusEl.textContent = message;
  const wrapper = document.createElement("div");
  wrapper.className = "muted preview-message";
  const text = document.createElement("p");
  text.textContent = message;
  wrapper.appendChild(text);
  if (stepUrl) {
    const link = document.createElement("a");
    link.href = stepUrl;
    link.textContent = "Download STEP to view in FreeCAD";
    wrapper.appendChild(link);
  }
  cadViewerEl.appendChild(wrapper);
}

async function renderCADPreview(job) {
  const stepUrl = artifactDownloadUrl(job, "step");
  cadViewerEl.replaceChildren();
  if (!stepUrl) {
    cadViewerStatusEl.textContent = "No STEP";
    showCADPreviewMessage("CAD preview is unavailable because this job has no STEP artifact.");
    return;
  }
  cadViewerStatusEl.textContent = "Loading CAD";
  try {
    await ensureCADViewerLibrary();
    if (!window.OV?.EmbeddedViewer) {
      throw new Error("OV.EmbeddedViewer is unavailable after loading Online 3D Viewer.");
    }
    const viewer = new window.OV.EmbeddedViewer(cadViewerEl, {
      backgroundColor: new window.OV.RGBAColor(18, 25, 22, 255),
      defaultColor: new window.OV.RGBColor(159, 199, 189)
    });
    viewer.LoadModelFromUrlList([stepUrl]);
    cadViewerStatusEl.textContent = `${moduleLabel(job.module || "rocket-engine")} CAD`;
  } catch (error) {
    showCADPreviewMessage(`CAD preview unavailable: ${error.message}`, stepUrl);
  }
}

function loadViewerScript(url, label) {
  return new Promise((resolve, reject) => {
    const existingScript = Array.from(document.scripts).find((script) => script.src === url);
    if (existingScript?.dataset.novaViewerLoaded === "true") {
      resolve();
      return;
    }
    if (existingScript?.dataset.novaViewerLoading === "true") {
      existingScript.addEventListener("load", () => resolve(), { once: true });
      existingScript.addEventListener("error", () => reject(new Error(`${label} failed to load from ${url}`)), { once: true });
      return;
    }
    if (existingScript) {
      existingScript.remove();
    }

    const script = document.createElement("script");
    script.src = url;
    script.async = false;
    script.dataset.novaViewerLoading = "true";
    script.onload = () => {
      script.dataset.novaViewerLoaded = "true";
      script.dataset.novaViewerLoading = "false";
      resolve();
    };
    script.onerror = () => {
      script.dataset.novaViewerLoading = "false";
      reject(new Error(`${label} failed to load from ${url}`));
    };
    document.head.appendChild(script);
  });
}

async function ensureThreeViewerLibraries() {
  if (!threeViewerLibrariesPromise) {
    threeViewerLibrariesPromise = (async () => {
      for (const asset of THREE_VIEWER_SCRIPTS) {
        if (!asset.isAvailable()) {
          await loadViewerScript(asset.url, asset.label);
        }
        if (!asset.isAvailable()) {
          throw new Error(`${asset.label} loaded from ${asset.url}, but ${asset.globalName} is unavailable.`);
        }
      }
    })().catch((error) => {
      threeViewerLibrariesPromise = null;
      throw error;
    });
  }
  return threeViewerLibrariesPromise;
}

async function ensureCADViewerLibrary() {
  if (!cadViewerLibraryPromise) {
    cadViewerLibraryPromise = (async () => {
      if (!CAD_VIEWER_SCRIPT.isAvailable()) {
        await loadViewerScript(CAD_VIEWER_SCRIPT.url, CAD_VIEWER_SCRIPT.label);
      }
      if (!CAD_VIEWER_SCRIPT.isAvailable()) {
        throw new Error(`${CAD_VIEWER_SCRIPT.label} loaded from ${CAD_VIEWER_SCRIPT.url}, but ${CAD_VIEWER_SCRIPT.globalName} is unavailable.`);
      }
    })().catch((error) => {
      cadViewerLibraryPromise = null;
      throw error;
    });
  }
  return cadViewerLibraryPromise;
}

async function ensureChartLibrary() {
  if (!chartLibraryPromise) {
    chartLibraryPromise = (async () => {
      if (!CHART_JS_SCRIPT.isAvailable()) {
        await loadViewerScript(CHART_JS_SCRIPT.url, CHART_JS_SCRIPT.label);
      }
      if (!CHART_JS_SCRIPT.isAvailable()) {
        throw new Error(`${CHART_JS_SCRIPT.label} loaded from ${CHART_JS_SCRIPT.url}, but ${CHART_JS_SCRIPT.globalName} is unavailable.`);
      }
    })().catch((error) => {
      chartLibraryPromise = null;
      throw error;
    });
  }
  return chartLibraryPromise;
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

async function renderSTLPreview(stlUrl, label, job = null) {
  clearSTLPreview();
  if (!stlUrl) {
    stlPreviewSectionEl.hidden = true;
    stlPreviewStatusEl.textContent = "No STL";
    updateSTLFullscreenButton();
    return;
  }
  stlPreviewSectionEl.hidden = false;
  stlPreviewStatusEl.textContent = "Loading";
  updateSTLFullscreenButton();

  const state = {
    renderer: null,
    controls: null,
    geometry: null,
    material: null,
    animationFrame: null,
    resizeObserver: null,
    resizeRenderer: null,
    fitCamera: null,
    updateClipping: null,
    applySectionView: null,
    applyAuxiliaryView: null,
    applyRenderMode: null,
    cycleRenderMode: null,
    renderMode: "solid",
    clipHelperGroup: null,
    flow: null
  };
  stlViewerState = state;

  try {
    await ensureThreeViewerLibraries();
  } catch (error) {
    if (stlViewerState !== state) {
      return;
    }
    stlPreviewStatusEl.textContent = "Preview unavailable";
    showSTLPreviewMessage(`${error.message} Download STL to view in FreeCAD.`, stlUrl);
    return;
  }

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
  renderer.localClippingEnabled = true;
  renderer.clippingPlanes = [];
  renderer.domElement.tabIndex = 0;
  renderer.domElement.style.touchAction = "none";
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
  controls.enableZoom = true;
  controls.zoomSpeed = 1.15;
  controls.minZoom = 0.2;
  controls.maxZoom = 8;
  if (THREE.TOUCH && controls.touches) {
    controls.touches.ONE = THREE.TOUCH.ROTATE;
    controls.touches.TWO = THREE.TOUCH.DOLLY_PAN;
  }
  controls.minDistance = 0.35;
  state.controls = controls;

  function viewerDimensions() {
    const rect = stlViewerEl.getBoundingClientRect();
    const fullscreen = document.fullscreenElement === stlPreviewSectionEl;
    const measuredWidth = Math.floor(rect.width || stlViewerEl.clientWidth || 300);
    const measuredHeight = Math.floor(rect.height || stlViewerEl.clientHeight || 300);
    if (fullscreen) {
      return {
        width: Math.max(320, measuredWidth),
        height: Math.max(240, measuredHeight)
      };
    }
    return {
      width: Math.max(220, Math.min(520, measuredWidth)),
      height: Math.max(220, Math.min(360, measuredHeight))
    };
  }

  function resizeRenderer() {
    const { width, height } = viewerDimensions();
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  state.resizeRenderer = resizeRenderer;
  state.resizeObserver = new ResizeObserver(resizeRenderer);
  state.resizeObserver.observe(stlViewerEl);
  resizeRenderer();

  const viewerClock = new THREE.Clock();

  function animate() {
    if (stlViewerState !== state) {
      return;
    }
    state.animationFrame = requestAnimationFrame(animate);
    const delta = Math.min(viewerClock.getDelta(), 0.05);
    if (state.flow?.update) {
      state.flow.update(delta);
    }
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
    roughness: 0.46,
    side: THREE.DoubleSide
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = label;
  scene.add(mesh);

  function applyRenderMode(mode) {
    const safeMode = ["solid", "wireframe", "xray"].includes(mode) ? mode : "solid";
    state.renderMode = safeMode;
    material.wireframe = safeMode === "wireframe";
    material.transparent = safeMode === "xray";
    material.opacity = safeMode === "xray" ? 0.3 : 1.0;
    material.depthWrite = safeMode !== "xray";
    material.needsUpdate = true;
    renderModeButton.hidden = false;
    renderModeButton.textContent = safeMode === "wireframe" ? "Mode: Wireframe" : safeMode === "xray" ? "Mode: X-ray" : "Mode: Solid";
    renderModeButton.setAttribute("aria-pressed", safeMode === "solid" ? "false" : "true");
  }

  function cycleRenderMode() {
    const next = state.renderMode === "solid" ? "wireframe" : state.renderMode === "wireframe" ? "xray" : "solid";
    applyRenderMode(next);
  }

  state.applyRenderMode = applyRenderMode;
  state.cycleRenderMode = cycleRenderMode;
  applyRenderMode("solid");

  const halfSize = {
    x: size.x / 2,
    y: size.y / 2,
    z: size.z / 2
  };
  const clipHelperGroup = new THREE.Group();
  scene.add(clipHelperGroup);
  state.clipHelperGroup = clipHelperGroup;

  function clearClipHelpers() {
    clipHelperGroup.children.forEach((child) => {
      child.geometry?.dispose();
      child.material?.dispose();
    });
    clipHelperGroup.clear();
  }

  function updateClipping() {
    const planes = [];
    clearClipHelpers();
    const axisNormals = {
      x: new THREE.Vector3(1, 0, 0),
      y: new THREE.Vector3(0, 1, 0),
      z: new THREE.Vector3(0, 0, 1)
    };
    const helperSize = Math.max(size.x, size.y, size.z, 1) * 1.04;
    for (const axis of Object.keys(clipSliders)) {
      const percent = Number(clipSliders[axis].value);
      if (!Number.isFinite(percent) || percent <= 0) {
        continue;
      }
      const extent = halfSize[axis] * 2 || 1;
      const position = -halfSize[axis] + extent * (Math.min(percent, 100) / 100);
      const plane = new THREE.Plane(axisNormals[axis], -position);
      const helper = new THREE.PlaneHelper(plane, helperSize, 0xffcf6e);
      helper.renderOrder = 5;
      planes.push(plane);
      clipHelperGroup.add(helper);
    }
    renderer.clippingPlanes = planes;
    updateClipControlLabels();
  }

  state.updateClipping = updateClipping;
  updateClipping();

  function createPropellantFlowSystem() {
    const particleCount = 360;
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);
    const progress = new Float32Array(particleCount);
    const phase = new Float32Array(particleCount);
    const kind = new Uint8Array(particleCount);
    const portIndex = new Uint8Array(particleCount);
    const extents = [Math.max(size.x, 1), Math.max(size.y, 1), Math.max(size.z, 1)];
    const primaryAxis = extents.indexOf(Math.max(...extents));
    const radialAxes = [0, 1, 2].filter((axis) => axis !== primaryAxis);
    const nozzleMetadata = job?.metadata?.nozzle || job?.metadata?.geometry || {};
    const numericMetadata = (key, fallback) => {
      const value = Number(nozzleMetadata?.[key]);
      return Number.isFinite(value) && value > 0 ? value : fallback;
    };
    const totalLengthMm = numericMetadata("total_length_mm", extents[primaryAxis]);
    const chamberLengthMm = numericMetadata("chamber_length_mm", totalLengthMm * 0.38);
    const convergenceLengthMm = numericMetadata("convergence_length_mm", totalLengthMm * 0.14);
    const chamberRadiusMm = numericMetadata("chamber_radius_mm", Math.min(extents[radialAxes[0]], extents[radialAxes[1]]) * 0.30);
    const throatRadiusMm = numericMetadata("throat_radius_mm", chamberRadiusMm * 0.42);
    const exitRadiusMm = numericMetadata("exit_radius_mm", chamberRadiusMm * 0.88);
    const maxRadiusMm = Math.max(chamberRadiusMm, throatRadiusMm, exitRadiusMm, 1);
    const radialFitScale = (Math.min(extents[radialAxes[0]], extents[radialAxes[1]]) * 0.44) / maxRadiusMm;
    const chamberEnd = Math.min(chamberLengthMm / totalLengthMm, 0.86);
    const throatAt = Math.min((chamberLengthMm + convergenceLengthMm) / totalLengthMm, 0.94);
    const flowGeometry = new THREE.BufferGeometry();
    const flowMaterial = new THREE.PointsMaterial({
      size: Math.max(maxDimension * 0.018, 0.75),
      vertexColors: true,
      transparent: true,
      opacity: 0.88,
      depthWrite: false,
      sizeAttenuation: true
    });
    const flowPoints = new THREE.Points(flowGeometry, flowMaterial);
    flowPoints.name = "NOVA propellant flow";
    flowPoints.renderOrder = 4;
    scene.add(flowPoints);

    let running = false;
    let speed = Number(flowSpeedSlider.value) || 1;

    function smoothstep(edge0, edge1, value) {
      const x = Math.min(Math.max((value - edge0) / (edge1 - edge0), 0), 1);
      return x * x * (3 - 2 * x);
    }

    function localNozzleRadiusMm(value) {
      if (value <= chamberEnd) {
        return chamberRadiusMm;
      }
      if (value <= throatAt) {
        const blend = smoothstep(chamberEnd, throatAt, value);
        return chamberRadiusMm + (throatRadiusMm - chamberRadiusMm) * blend;
      }
      const blend = smoothstep(throatAt, 1, value);
      return throatRadiusMm + (exitRadiusMm - throatRadiusMm) * blend;
    }

    function throatBoost(value) {
      return Math.exp(-Math.pow((value - throatAt) / 0.075, 2));
    }

    function localVelocityScale(value) {
      const localRadius = Math.max(localNozzleRadiusMm(value), throatRadiusMm * 0.8, 0.1);
      const areaRatio = Math.pow(chamberRadiusMm / localRadius, 2);
      return Math.min(4.2, 0.65 + areaRatio * 0.45 + throatBoost(value) * 1.8);
    }

    function setVectorComponent(index, axis, value) {
      positions[index * 3 + axis] = value;
    }

    function writeParticle(index) {
      const t = progress[index];
      const wallRadius = localNozzleRadiusMm(t) * radialFitScale;
      const inletBlend = 1 - smoothstep(0, Math.max(chamberEnd * 0.35, 0.12), t);
      const isOxidizer = kind[index] === 1;
      const coreRadius = Math.max(wallRadius * 0.16, maxDimension * 0.008);
      const fuelRadius = wallRadius * (0.84 + 0.05 * Math.sin(t * Math.PI * 10 + phase[index]));
      const inletRadius = isOxidizer ? coreRadius * 0.48 : wallRadius * 1.04;
      const radius = (isOxidizer ? coreRadius : fuelRadius) * (1 - inletBlend) + inletRadius * inletBlend;
      const baseAngle = isOxidizer ? phase[index] : (portIndex[index] / 8) * Math.PI * 2;
      const swirl = baseAngle + t * (isOxidizer ? 2.6 : 13.5);
      const axisStart = extents[primaryAxis] / 2;
      const axisPosition = axisStart - t * extents[primaryAxis];
      const fade = t > 0.82 ? Math.max(0, 1 - (t - 0.82) / 0.18) : 1;
      const radialA = Math.cos(swirl) * radius;
      const radialB = Math.sin(swirl) * radius * 0.74;

      setVectorComponent(index, primaryAxis, axisPosition);
      setVectorComponent(index, radialAxes[0], radialA);
      setVectorComponent(index, radialAxes[1], radialB);

      const colorOffset = index * 3;
      if (kind[index]) {
        colors[colorOffset] = 1.0 * fade;
        colors[colorOffset + 1] = 0.18 * fade;
        colors[colorOffset + 2] = 0.08 * fade;
      } else {
        colors[colorOffset] = 0.08 * fade;
        colors[colorOffset + 1] = 0.42 * fade;
        colors[colorOffset + 2] = 1.0 * fade;
      }
    }

    for (let index = 0; index < particleCount; index += 1) {
      kind[index] = index < particleCount / 2 ? 0 : 1;
      portIndex[index] = index % 8;
      progress[index] = (index / particleCount + Math.random() * 0.08) % 1;
      phase[index] = Math.random() * Math.PI * 2;
      writeParticle(index);
    }

    flowGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    flowGeometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

    function update(delta) {
      if (!running) {
        return;
      }
      for (let index = 0; index < particleCount; index += 1) {
        progress[index] += delta * 0.075 * speed * localVelocityScale(progress[index]);
        if (progress[index] > 1) {
          progress[index] -= Math.floor(progress[index]);
          phase[index] = Math.random() * Math.PI * 2;
        }
        writeParticle(index);
      }
      flowGeometry.attributes.position.needsUpdate = true;
      flowGeometry.attributes.color.needsUpdate = true;
    }

    function setRunning(value) {
      running = Boolean(value);
      flowToggleButton.textContent = running ? "Pause flow" : "Play flow";
    }

    function toggleRunning() {
      setRunning(!running);
    }

    function setSpeed(value) {
      speed = Math.min(Math.max(Number(value) || 1, 0.25), 3);
      updateFlowSpeedLabel();
    }

    function dispose() {
      scene.remove(flowPoints);
      flowGeometry.dispose();
      flowMaterial.dispose();
    }

    return {
      update,
      setRunning,
      toggleRunning,
      setSpeed,
      dispose
    };
  }

  state.flow = createPropellantFlowSystem();
  state.flow.setRunning(false);
  state.flow.setSpeed(Number(flowSpeedSlider.value));

  const modelRadius = Math.max(size.length() / 2, maxDimension / 2, 1);
  const currentCameraDirection = new THREE.Vector3(0.58, -0.76, 0.45).normalize();

  function fitCameraToObject(direction = currentCameraDirection) {
    resizeRenderer();
    currentCameraDirection.copy(direction).normalize();
    const fov = camera.fov * (Math.PI / 180);
    const horizontalFov = 2 * Math.atan(Math.tan(fov / 2) * camera.aspect);
    const limitingFov = Math.max(Math.min(fov, horizontalFov), 0.1);
    const distance = (modelRadius / Math.sin(limitingFov / 2)) * 1.22;
    camera.position.copy(currentCameraDirection.clone().multiplyScalar(distance));
    camera.near = Math.max(distance / 1000, 0.1);
    camera.far = Math.max(distance * 10, maxDimension * 12);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.maxDistance = distance * 5;
    controls.update();
  }

  function auxiliaryViewDirection(name) {
    const directions = {
      iso: new THREE.Vector3(0.58, -0.76, 0.45),
      front: new THREE.Vector3(0, -1, 0.08),
      right: new THREE.Vector3(1, 0, 0.08),
      top: new THREE.Vector3(0.08, -0.08, 1),
      "aux-a": new THREE.Vector3(0.82, -0.42, 0.38),
      "aux-b": new THREE.Vector3(-0.46, -0.74, 0.48)
    };
    return (directions[name] || directions.iso).normalize();
  }

  function applyAuxiliaryView(name) {
    fitCameraToObject(auxiliaryViewDirection(name));
  }

  function applySectionView(name) {
    const presets = {
      full: { x: 0, y: 0, z: 0, view: "iso" },
      "half-x": { x: 50, y: 0, z: 0, view: "aux-a" },
      "half-y": { x: 0, y: 50, z: 0, view: "aux-b" },
      "half-z": { x: 0, y: 0, z: 50, view: "iso" },
      quarter: { x: 50, y: 50, z: 0, view: "aux-a" }
    };
    const preset = presets[name] || presets.full;
    setClipControlValues(preset);
    applyAuxiliaryView(preset.view);
  }

  state.fitCamera = fitCameraToObject;
  state.applySectionView = applySectionView;
  state.applyAuxiliaryView = applyAuxiliaryView;
  fitCameraToObject();

  state.material = material;
  stlPreviewStatusEl.textContent = label;
  animate();
}

function renderResults(job) {
  const module = job.module || "rocket-engine";
  activeJobEl.textContent = `${moduleLabel(module)} - ${job.job_id}`;
  renderMetricCards(resultCardsEl, module, job.metrics || {});
  renderValidation(job.validation);
  finishDesignLog(job);

  downloadButtonsEl.classList.remove("muted");
  downloadButtonsEl.innerHTML = artifactLinks(job, {
    stl: "Download STL",
    step: "Download STEP",
    thermal_map: "Download Thermal Map",
    report: "Download PDF"
  }) || "No artifacts available";
  setViewerTab("mesh");
  renderSTLPreview(stlDownloadUrl(job), `${moduleLabel(module)} - ${job.job_id}`, job);
  renderCADPreview(job);
}

function renderMetricCards(container, module, metrics) {
  container.innerHTML = metricDefinition(module).map(([key, label, unit]) => {
    const value = metrics[key];
    return `
      <article class="metric-card">
        <span class="metric-label">${escapeHtml(label)}</span>
        <strong>${escapeHtml(formatValue(value))}</strong>
        <span class="metric-unit">${escapeHtml(unit)}</span>
      </article>
    `;
  }).join("");
}

function renderMissionResults(job) {
  missionActiveJobEl.textContent = `${moduleLabel(job.module)} - ${job.job_id}`;
  renderMetricCards(missionResultCardsEl, "mission", job.metrics || {});
  missionDownloadButtonsEl.classList.remove("muted");
  missionDownloadButtonsEl.innerHTML = artifactLinks(job, {
    report: "Download PDF"
  }) || "No mission report available";
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
    historyListEl.innerHTML = '<tr><td colspan="6"><p class="empty-state">No matching designs.</p></td></tr>';
    return;
  }
  historyListEl.innerHTML = jobs.map((job) => {
    const module = job.module || "rocket-engine";
    const selected = selectedJobIds.has(job.job_id);
    const compareDisabled = selectedJobIds.size >= 3 && !selected;
    const protectedDelete = Boolean(job.starred);
    return `
      <tr class="history-row ${job.starred ? "starred" : ""}">
        <td data-label="Name">
          <label class="compare-pick">
            <input class="compare-checkbox" type="checkbox" data-job-id="${escapeHtml(job.job_id)}" ${selected ? "checked" : ""} ${compareDisabled ? "disabled" : ""}>
            <span>
              <span class="history-name">${escapeHtml(jobDisplayName(job))}</span>
              <span class="history-id">${escapeHtml(job.job_id)}</span>
            </span>
          </label>
        </td>
        <td data-label="Module">${escapeHtml(moduleLabel(module))}</td>
        <td data-label="Date"><span class="history-date">${escapeHtml(formatDateTime(job.created_at))}</span></td>
        <td data-label="Key Metric"><span class="history-metric">${escapeHtml(historyPrimaryMetric(job))}</span></td>
        <td data-label="Size"><span class="history-size">${escapeHtml(formatBytes(job.size_bytes))}</span></td>
        <td data-label="Actions">
          <div class="history-actions">
          ${artifactLinks(job, { stl: "STL", step: "STEP", thermal_map: "Thermal", report: "PDF" })}
          <button class="secondary star-action" type="button" data-job-id="${escapeHtml(job.job_id)}">${job.starred ? "Starred" : "Star"}</button>
          <button class="secondary danger-action" type="button" data-job-id="${escapeHtml(job.job_id)}" ${protectedDelete ? "disabled" : ""}>Delete</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function jobDisplayName(job) {
  const module = job.module || "rocket-engine";
  const p = job.parameters || {};
  switch (module) {
    case "heat-exchanger":
      return `${p.hot_fluid || "hot"} to ${p.cold_fluid || "cold"} heat exchanger`;
    case "actuator":
      return `${p.material || "solenoid"} actuator ${formatCompactNumber(p.force_N)} N`;
    case "mission":
      return `Mission for ${p.engine_job_id || "engine"}`;
    default:
      return `${p.propellant || "engine"} ${formatCompactNumber(p.thrust_N)} N ${formatCompactNumber(p.chamber_pressure_bar)} bar`;
  }
}

function historyPrimaryMetric(job) {
  const m = job.metrics || {};
  switch (job.module || "rocket-engine") {
    case "heat-exchanger":
      return `Effectiveness ${formatValue(m.effectiveness)}, pressure drop ${formatValue(m.pressure_drop_bar)} bar`;
    case "actuator":
      return `Force ${formatValue(m.force_output_N)} N, current ${formatValue(m.current_draw_A)} A`;
    case "mission":
      return `Delta-V ${formatValue(m.delta_v_m_s)} m/s, T/W ${formatValue(m.thrust_to_weight)}`;
    default:
      return `Isp ${formatValue(m.specific_impulse_s)} s, thrust ${formatValue(m.thrust_N)} N`;
  }
}

function historyParameters(job) {
  const p = job.parameters || {};
  switch (job.module || "rocket-engine") {
    case "heat-exchanger":
      return `${p.hot_fluid} to ${p.cold_fluid}, ${formatValue(p.duty_kW)} kW, ${formatValue(p.hot_inlet_temp_C)} C to ${formatValue(p.hot_outlet_temp_C)} C`;
    case "actuator":
      return `${p.actuator_type || "solenoid"}, ${formatValue(p.force_N)} N, ${formatValue(p.stroke_mm)} mm, ${formatValue(p.voltage_V)} V, ${p.material}`;
    case "mission":
      return `engine ${p.engine_job_id}, dry ${formatValue(p.vehicle_mass_kg)} kg, propellant ${formatValue(p.propellant_mass_kg)} kg`;
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
    case "mission":
      return `delta-V ${formatValue(m.delta_v_m_s)} m/s, burn ${formatValue(m.burn_time_s)} s, T/W ${formatValue(m.thrust_to_weight)}`;
    default:
      return `Isp ${formatValue(m.specific_impulse_s)} s, mass ${formatValue(m.engine_mass_kg)} kg, print ${formatValue(m.print_time_hours)} h`;
  }
}

async function loadHistory() {
  try {
    const response = await fetch("/api/history");
    if (!response.ok) {
      throw new Error("Could not load job history");
    }
    const payload = await response.json();
    allJobs = payload.jobs || [];
    setServerStatus(true);
    updateDashboardSummary();
    populateMissionEngineOptions();
    renderFilteredHistory();
  } catch (error) {
    setServerStatus(false);
    throw error;
  }
}

function updateCompareControls() {
  compareCountEl.textContent = `${selectedJobIds.size} selected`;
  compareButton.disabled = selectedJobIds.size < 2;
}

function selectedJobs() {
  return allJobs.filter((job) => selectedJobIds.has(job.job_id));
}

function engineRadarMetrics(job) {
  const metrics = job.metrics || {};
  const massKg = Number(metrics.engine_mass_kg) || 1;
  const thrustN = Number(metrics.thrust_N) || 0;
  const thrustToWeight = thrustN / Math.max(massKg * 9.80665, 1);
  const printTimeHours = Number(metrics.print_time_hours) || 0;
  const costEstimate = massKg * 1200 + printTimeHours * 85;
  return {
    isp: Number(metrics.specific_impulse_s) || 0,
    thrustToWeight,
    chamberTemp: Number(metrics.chamber_temp_K) || 0,
    printTime: printTimeHours,
    costEstimate
  };
}

function normalizeRadarDatasets(jobs) {
  const values = jobs.map(engineRadarMetrics);
  const maxByKey = {
    isp: Math.max(...values.map((item) => item.isp), 1),
    thrustToWeight: Math.max(...values.map((item) => item.thrustToWeight), 1),
    chamberTemp: Math.max(...values.map((item) => item.chamberTemp), 1),
    printTime: Math.max(...values.map((item) => item.printTime), 1),
    costEstimate: Math.max(...values.map((item) => item.costEstimate), 1)
  };
  const palette = [
    ["rgba(79, 184, 158, 0.24)", "#4fb89e"],
    ["rgba(220, 121, 74, 0.20)", "#dc794a"],
    ["rgba(88, 133, 214, 0.20)", "#5885d6"]
  ];
  return jobs.map((job, index) => {
    const item = values[index];
    const [backgroundColor, borderColor] = palette[index % palette.length];
    return {
      label: jobDisplayName(job),
      data: [
        (item.isp / maxByKey.isp) * 100,
        (item.thrustToWeight / maxByKey.thrustToWeight) * 100,
        (item.chamberTemp / maxByKey.chamberTemp) * 100,
        (1 - item.printTime / maxByKey.printTime) * 100,
        (1 - item.costEstimate / maxByKey.costEstimate) * 100
      ].map((value) => Math.max(0, Math.min(100, value))),
      backgroundColor,
      borderColor,
      borderWidth: 2,
      pointRadius: 3
    };
  });
}

async function renderCompareRadarChart(jobs) {
  const canvas = document.querySelector("#compare-radar-chart");
  const status = document.querySelector("#compare-radar-status");
  if (compareRadarChart) {
    compareRadarChart.destroy();
    compareRadarChart = null;
  }
  if (!canvas) {
    return;
  }
  try {
    await ensureChartLibrary();
    compareRadarChart = new window.Chart(canvas, {
      type: "radar",
      data: {
        labels: ["Isp", "Thrust/Weight", "Chamber Temp", "Print Time", "Cost Estimate"],
        datasets: normalizeRadarDatasets(jobs)
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          r: {
            beginAtZero: true,
            max: 100,
            ticks: { display: false },
            pointLabels: { color: getComputedStyle(document.documentElement).getPropertyValue("--ink").trim() || "#17202a" },
            grid: { color: getComputedStyle(document.documentElement).getPropertyValue("--line").trim() || "#d8dfda" },
            angleLines: { color: getComputedStyle(document.documentElement).getPropertyValue("--line").trim() || "#d8dfda" }
          }
        },
        plugins: {
          legend: {
            labels: {
              color: getComputedStyle(document.documentElement).getPropertyValue("--ink").trim() || "#17202a"
            }
          },
          tooltip: {
            callbacks: {
              label(context) {
                return `${context.dataset.label}: ${formatValue(context.parsed.r)} normalized`;
              }
            }
          }
        }
      }
    });
    if (status) {
      status.textContent = "Normalized to the selected jobs; lower print time and cost score higher.";
    }
  } catch (error) {
    if (status) {
      status.textContent = `Radar chart unavailable: ${error.message}`;
    }
  }
}

function renderCompare() {
  const jobs = selectedJobs();
  if (jobs.length < 2) {
    comparePanelEl.hidden = true;
    return;
  }

  const metricKeys = [...new Set(jobs.flatMap((job) => metricDefinition(job.module || "rocket-engine").map(([key]) => key)))];
  compareContentEl.innerHTML = `
    <section class="compare-radar" aria-label="Engine comparison radar chart">
      <h3>Engine Comparison Radar</h3>
      <div class="radar-chart-frame">
        <canvas id="compare-radar-chart"></canvas>
      </div>
      <p id="compare-radar-status" class="muted">Loading radar chart</p>
    </section>
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
  renderCompareRadarChart(jobs);
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

function openDeleteModal(jobId) {
  pendingDeleteJobId = jobId;
  deleteModalPreviousFocus = document.activeElement;
  const job = allJobs.find((item) => item.job_id === jobId);
  deleteModalJobEl.textContent = job ? `${moduleLabel(job.module || "rocket-engine")} - ${job.job_id}` : jobId;
  deleteModalBackdropEl.hidden = false;
  document.body.classList.add("modal-open");
  deleteModalConfirmButton.disabled = false;
  deleteModalCancelButton.disabled = false;
  deleteModalConfirmButton.focus();
}

function closeDeleteModal() {
  pendingDeleteJobId = "";
  deleteModalBackdropEl.hidden = true;
  document.body.classList.remove("modal-open");
  if (deleteModalPreviousFocus?.focus) {
    deleteModalPreviousFocus.focus();
  }
  deleteModalPreviousFocus = null;
}

async function deleteJob(jobId) {
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

async function confirmDeleteJob() {
  if (!pendingDeleteJobId) {
    return;
  }
  const jobId = pendingDeleteJobId;
  setError("");
  setStatus("Deleting");
  deleteModalConfirmButton.disabled = true;
  deleteModalCancelButton.disabled = true;
  try {
    await deleteJob(jobId);
    closeDeleteModal();
    setStatus("Ready");
  } catch (error) {
    setError(error.message);
    setStatus("Failed");
    deleteModalConfirmButton.disabled = false;
    deleteModalCancelButton.disabled = false;
  }
}

function bindDesignForm(module, config) {
  config.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setError("");
    setStatus(`Designing ${config.label}`);
    config.button.disabled = true;
    const steps = startDesignLog(module);
    let stepIndex = 0;
    const logTimer = window.setInterval(() => {
      if (stepIndex < steps.length) {
        appendDesignLog(`${steps[stepIndex]}... done`, "done");
        stepIndex += 1;
      }
    }, 550);

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
      while (stepIndex < steps.length) {
        appendDesignLog(`${steps[stepIndex]}... done`, "done");
        stepIndex += 1;
      }
      renderResults(payload.job);
      await loadHistory();
      setStatus("Complete");
    } catch (error) {
      appendDesignLog(`Design failed: ${error.message}`, "failed");
      setError(error.message);
      setStatus("Failed");
    } finally {
      window.clearInterval(logTimer);
      config.button.disabled = false;
    }
  });
}

async function runMission(event) {
  event.preventDefault();
  setMissionError("");
  setError("");
  setStatus("Calculating mission");
  missionButtonEl.disabled = true;

  try {
    const data = new FormData(missionFormEl);
    const response = await fetch("/api/mission", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        engine_job_id: String(data.get("engine_job_id") || "").trim(),
        vehicle_mass_kg: Number(data.get("vehicle_mass_kg")),
        propellant_mass_kg: Number(data.get("propellant_mass_kg"))
      })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Mission calculation failed");
    }
    renderMissionResults(payload.job);
    await loadHistory();
    setStatus("Complete");
  } catch (error) {
    setMissionError(error.message);
    setStatus("Failed");
  } finally {
    missionButtonEl.disabled = false;
  }
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("nova-theme", theme);
  themeToggleButton.textContent = theme === "dark" ? "Light Mode" : "Dark Mode";
}

Object.entries(modules).forEach(([module, config]) => {
  if (config.form) {
    bindDesignForm(module, config);
  }
});

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setActiveTab(button.dataset.tabTarget, button.dataset.moduleTarget || "");
  });
});

missionFormEl.addEventListener("submit", runMission);

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
      openDeleteModal(deleteButton.dataset.jobId);
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

deleteModalCancelButton.addEventListener("click", closeDeleteModal);
deleteModalCloseButton.addEventListener("click", closeDeleteModal);
deleteModalConfirmButton.addEventListener("click", confirmDeleteJob);

deleteModalBackdropEl.addEventListener("click", (event) => {
  if (event.target === deleteModalBackdropEl) {
    closeDeleteModal();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !deleteModalBackdropEl.hidden) {
    closeDeleteModal();
  }
});

stlFullscreenButton.addEventListener("click", toggleSTLFullscreen);
document.addEventListener("fullscreenchange", updateSTLFullscreenButton);

renderModeButton.addEventListener("click", () => {
  if (stlViewerState?.cycleRenderMode) {
    stlViewerState.cycleRenderMode();
  }
});

viewerTabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setViewerTab(button.dataset.viewerTab || "mesh");
  });
});

for (const slider of Object.values(clipSliders)) {
  slider.addEventListener("input", () => {
    updateClipControlLabels();
    if (stlViewerState?.updateClipping) {
      stlViewerState.updateClipping();
    }
  });
}

clipResetButton.addEventListener("click", () => {
  setClipControlValues({ x: 0, y: 0, z: 0 });
});

sectionViewButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const preset = button.dataset.sectionView;
    if (stlViewerState?.applySectionView) {
      stlViewerState.applySectionView(preset);
      return;
    }
    const fallbackPresets = {
      full: { x: 0, y: 0, z: 0 },
      "half-x": { x: 50, y: 0, z: 0 },
      "half-y": { x: 0, y: 50, z: 0 },
      "half-z": { x: 0, y: 0, z: 50 },
      quarter: { x: 50, y: 50, z: 0 }
    };
    setClipControlValues(fallbackPresets[preset] || fallbackPresets.full);
  });
});

auxiliaryViewButtons.forEach((button) => {
  button.addEventListener("click", () => {
    if (stlViewerState?.applyAuxiliaryView) {
      stlViewerState.applyAuxiliaryView(button.dataset.auxView);
    }
  });
});

flowToggleButton.addEventListener("click", () => {
  if (stlViewerState?.flow) {
    stlViewerState.flow.toggleRunning();
  }
});

flowSpeedSlider.addEventListener("input", () => {
  updateFlowSpeedLabel();
  if (stlViewerState?.flow) {
    stlViewerState.flow.setSpeed(Number(flowSpeedSlider.value));
  }
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
updateClipControlLabels();
updateFlowSpeedLabel();
setActiveModule(activeDesignModule);
loadHistory().catch((error) => {
  setError(error.message);
  setStatus("Failed");
});
