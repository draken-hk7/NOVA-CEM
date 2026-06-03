const statusEl = document.querySelector("#status");
const errorEl = document.querySelector("#error");
const activeJobEl = document.querySelector("#active-job");
const resultCardsEl = document.querySelector("#result-cards");
const validationResultsEl = document.querySelector("#validation-results");
const downloadButtonsEl = document.querySelector("#download-buttons");
const historyListEl = document.querySelector("#history-list");
const refreshHistoryButton = document.querySelector("#refresh-history");

const numberFormat = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 3
});

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

function moduleLabel(module) {
  return modules[module]?.label || "Rocket Engine";
}

function metricDefinition(module) {
  return modules[module]?.metrics || modules["rocket-engine"].metrics;
}

function formatValue(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
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
  const module = job.module || "rocket-engine";
  activeJobEl.textContent = `${moduleLabel(module)} - ${job.job_id}`;
  resultCardsEl.innerHTML = metricDefinition(module).map(([key, label, unit]) => {
    const value = job.metrics[key];
    return `
      <article class="metric-card">
        <span class="metric-label">${label}</span>
        <strong>${formatValue(value)}</strong>
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
  }) || "No artifacts available";
}

function renderHistory(jobs) {
  if (!jobs.length) {
    historyListEl.innerHTML = '<p class="empty-state">No designs yet.</p>';
    return;
  }
  historyListEl.innerHTML = jobs.map((job) => {
    const module = job.module || "rocket-engine";
    return `
      <article class="history-item">
        <div>
          <p class="history-title">${moduleLabel(module)} - ${job.job_id}</p>
          <p class="history-meta">${job.created_at}</p>
        </div>
        <div>
          <p class="history-meta">${historyParameters(job)}</p>
          <p class="history-metrics">${historyMetrics(job)}</p>
        </div>
        <div class="history-actions">${artifactLinks(job.files, { stl: "STL", step: "STEP", report: "PDF" })}</div>
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
  renderHistory(payload.jobs);
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

Object.entries(modules).forEach(([module, config]) => bindDesignForm(module, config));

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
