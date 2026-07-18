import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

import nova.web.main as web_main


def test_dashboard_registers_all_design_routes():
    routes = {route.path for route in web_main.app.routes}

    assert "/api/design/rocket-engine" in routes
    assert "/api/design/heat-exchanger" in routes
    assert "/api/design/actuator" in routes
    assert "/api/mission" in routes
    assert "/api/jobs/{job_id}" in routes
    assert "/api/jobs/{job_id}/star" in routes
    assert "/api/history/export.csv" in routes


def _configure_history(monkeypatch, name: str, jobs: list[dict]) -> Path:
    root = Path("outputs/test-artifacts/web-dashboard") / name
    index = root / "jobs.json"
    monkeypatch.setattr(web_main, "WEB_JOB_ROOT", root)
    monkeypatch.setattr(web_main, "JOB_INDEX", index)
    web_main._write_history(jobs)
    return root


def test_heat_exchanger_dashboard_endpoint_records_module_metrics(monkeypatch):
    records = []

    class FakeHX:
        def design(self, spec):
            assert spec.hot_fluid == "exhaust"
            return SimpleNamespace(
                performance=SimpleNamespace(
                    effectiveness=0.81234,
                    ntu=2.1456,
                    required_area_m2=0.12345,
                    pressure_drop_bar=0.03456,
                    cold_outlet_temp_C=123.456,
                ),
                mass_kg=1.2,
                validation=None,
            )

    monkeypatch.setattr(web_main, "WEB_JOB_ROOT", Path("outputs/test-artifacts/web-dashboard/jobs"))
    monkeypatch.setattr(web_main, "NovaHX", lambda: FakeHX())
    monkeypatch.setattr(
        web_main,
        "_export_module_artifacts",
        lambda job_id, module, inputs, design, job_dir, artifact_basename: {
            "stl": str(job_dir / f"{artifact_basename}.stl"),
            "step": str(job_dir / f"{artifact_basename}.step"),
            "report": str(job_dir / "report.pdf"),
        },
    )
    monkeypatch.setattr(web_main, "_prepend_history", lambda record: records.append(record))

    response = asyncio.run(
        web_main.design_heat_exchanger(
            web_main.DashboardHeatExchangerRequest(
                hot_fluid="exhaust",
                cold_fluid="hydrogen",
                duty_kW=10.0,
                hot_inlet_temp_C=800.0,
                hot_outlet_temp_C=200.0,
                cold_inlet_temp_C=20.0,
            )
        )
    )

    job = response["job"]
    assert job["module"] == "heat-exchanger"
    assert job["metrics"]["effectiveness"] == 0.812
    assert job["metrics"]["cold_outlet_temp_C"] == 123.46
    assert set(job["files"]) == {"stl", "step", "report"}
    assert records[0]["module"] == "heat-exchanger"


def test_actuator_dashboard_endpoint_records_module_metrics(monkeypatch):
    records = []

    class FakeEA:
        def design(self, spec):
            assert spec.material == "steel"
            return SimpleNamespace(
                performance=SimpleNamespace(
                    force_output_N=55.432,
                    current_draw_A=3.2109,
                    power_consumption_W=77.789,
                    response_time_ms=42.424,
                ),
                mass_kg=0.8,
                validation=None,
            )

    monkeypatch.setattr(web_main, "WEB_JOB_ROOT", Path("outputs/test-artifacts/web-dashboard/jobs"))
    monkeypatch.setattr(web_main, "NovaEA", lambda: FakeEA())
    monkeypatch.setattr(
        web_main,
        "_export_module_artifacts",
        lambda job_id, module, inputs, design, job_dir, artifact_basename: {
            "stl": str(job_dir / f"{artifact_basename}.stl"),
            "step": str(job_dir / f"{artifact_basename}.step"),
            "report": str(job_dir / "report.pdf"),
        },
    )
    monkeypatch.setattr(web_main, "_prepend_history", lambda record: records.append(record))

    response = asyncio.run(
        web_main.design_actuator(
            web_main.DashboardActuatorRequest(
                force_N=50.0,
                stroke_mm=10.0,
                voltage_V=24.0,
                response_time_ms=50.0,
                material="steel",
            )
        )
    )

    job = response["job"]
    assert job["module"] == "actuator"
    assert job["metrics"]["force_output_N"] == 55.43
    assert job["metrics"]["current_draw_A"] == 3.211
    assert set(job["files"]) == {"stl", "step", "report"}
    assert records[0]["module"] == "actuator"


def test_mission_dashboard_endpoint_records_report_and_history(monkeypatch):
    root = _configure_history(monkeypatch, "mission", [])
    engine_dir = root / "engine-a"
    engine_dir.mkdir(parents=True, exist_ok=True)
    engine_payload = {
        "job_id": "engine-a",
        "module": "rocket-engine",
        "inputs": {"propellant": "hydrolox"},
        "design": {
            "performance": {
                "specific_impulse_s": 450.0,
                "thrust_N": 5000.0,
                "mass_flow_rate_kg_s": 1.2,
            },
            "metadata": {"combustion": {"OF_ratio": 5.5}},
        },
    }
    data_path = engine_dir / "data.json"
    data_path.write_text(json.dumps(engine_payload), encoding="utf-8")
    web_main._write_history(
        [
            {
                "job_id": "engine-a",
                "module": "rocket-engine",
                "created_at": "2026-06-03T12:00:00",
                "starred": False,
                "parameters": {"propellant": "hydrolox"},
                "metrics": {"specific_impulse_s": 450.0, "thrust_N": 5000.0},
                "validation": {"passed": True, "checks": []},
                "files": {"report": "/download/engine-a/report"},
                "artifact_paths": {"json": str(data_path)},
            }
        ]
    )

    response = asyncio.run(
        web_main.run_mission(
            web_main.DashboardMissionRequest(
                engine_job_id="engine-a",
                vehicle_mass_kg=50.0,
                propellant_mass_kg=20.0,
            )
        )
    )

    job = response["job"]
    history = web_main._read_history()
    mission_record = next(item for item in history if item["module"] == "mission")
    report = Path(mission_record["artifact_paths"]["report"])

    assert job["module"] == "mission"
    assert set(job["files"]) == {"report", "trajectory"}
    assert job["metrics"]["delta_v_m_s"] == pytest.approx(round(450.0 * 9.81 * math.log(70.0 / 50.0), 2))
    assert job["metrics"]["hydrogen_mass_needed_kg_s"] == pytest.approx(round(1.2 / 6.5, 6))
    assert report.name == "mission_report.pdf"
    assert report.exists() and b"NOVA Mission Report" in report.read_bytes()
    assert (Path(mission_record["artifact_paths"]["trajectory"])).exists()
    assert history[0]["module"] == "mission"


def test_starred_jobs_sort_first_and_public_history_includes_starred(monkeypatch):
    _configure_history(
        monkeypatch,
        "star-sort",
        [
            {
                "job_id": "new-engine",
                "module": "rocket-engine",
                "created_at": "2026-06-03T12:00:00",
                "starred": False,
                "parameters": {"propellant": "kerolox"},
                "metrics": {"specific_impulse_s": 300.0},
                "validation": {"passed": True, "checks": []},
                "files": {},
                "artifact_paths": {},
            },
            {
                "job_id": "old-hx",
                "module": "heat-exchanger",
                "created_at": "2026-06-03T10:00:00",
                "starred": False,
                "parameters": {"hot_fluid": "exhaust"},
                "metrics": {"effectiveness": 0.8},
                "validation": {"passed": True, "checks": []},
                "files": {},
                "artifact_paths": {},
            },
        ],
    )

    response = asyncio.run(web_main.star_job("old-hx", web_main.StarJobRequest(starred=True)))
    history = asyncio.run(web_main.history())["jobs"]

    assert response["job"]["starred"]
    assert [job["job_id"] for job in history] == ["old-hx", "new-engine"]
    assert json.loads(web_main.JOB_INDEX.read_text(encoding="utf-8"))["jobs"][0]["starred"]


def test_public_history_includes_size_and_thermal_map_download(monkeypatch):
    root = _configure_history(monkeypatch, "thermal-size", [])
    job_dir = root / "engine-a"
    job_dir.mkdir(parents=True, exist_ok=True)
    thermal_map = job_dir / "thermal_map.svg"
    report = job_dir / "report.pdf"
    thermal_map.write_text("<svg></svg>", encoding="utf-8")
    report.write_bytes(b"%PDF-1.4")
    files = {"thermal_map": str(thermal_map), "report": str(report)}
    web_main._write_history(
        [
            {
                "job_id": "engine-a",
                "module": "rocket-engine",
                "created_at": "2026-06-03T12:00:00",
                "starred": False,
                "parameters": {"propellant": "kerolox"},
                "metrics": {"specific_impulse_s": 300.0},
                "validation": {"passed": True, "checks": []},
                "metadata": {"nozzle": {"chamber_length_mm": 80.0}},
                "design_log": ["Computing combustion"],
                "files": web_main._download_urls("engine-a", files),
                "artifact_paths": files,
            }
        ]
    )

    history = asyncio.run(web_main.history())["jobs"]

    assert history[0]["files"]["thermal_map"] == "/download/engine-a/thermal_map"
    assert history[0]["size_bytes"] == thermal_map.stat().st_size + report.stat().st_size
    assert history[0]["metadata"]["nozzle"]["chamber_length_mm"] == 80.0
    assert history[0]["design_log"] == ["Computing combustion"]


def test_delete_job_removes_folder_and_history_but_blocks_starred(monkeypatch):
    root = _configure_history(
        monkeypatch,
        "delete",
        [
            {
                "job_id": "delete-me",
                "module": "actuator",
                "created_at": "2026-06-03T12:00:00",
                "starred": False,
                "parameters": {},
                "metrics": {},
                "validation": {"passed": True, "checks": []},
                "files": {},
                "artifact_paths": {},
            },
            {
                "job_id": "keep-me",
                "module": "rocket-engine",
                "created_at": "2026-06-03T11:00:00",
                "starred": True,
                "parameters": {},
                "metrics": {},
                "validation": {"passed": True, "checks": []},
                "files": {},
                "artifact_paths": {},
            },
        ],
    )
    (root / "delete-me").mkdir(parents=True, exist_ok=True)
    (root / "delete-me" / "artifact.stl").write_text("solid test\nendsolid test\n", encoding="ascii")
    (root / "keep-me").mkdir(parents=True, exist_ok=True)

    response = asyncio.run(web_main.delete_job("delete-me"))
    remaining_ids = [job["job_id"] for job in web_main._read_history()]

    assert response["deleted"]
    assert not (root / "delete-me").exists()
    assert remaining_ids == ["keep-me"]
    with pytest.raises(web_main.HTTPException) as exc:
        asyncio.run(web_main.delete_job("keep-me"))
    assert exc.value.status_code == 409
    assert (root / "keep-me").exists()


def test_export_history_csv_flattens_parameters_and_metrics(monkeypatch):
    _configure_history(
        monkeypatch,
        "csv",
        [
            {
                "job_id": "engine-a",
                "module": "rocket-engine",
                "created_at": "2026-06-03T12:00:00",
                "starred": True,
                "parameters": {"propellant": "methalox", "material": "inconel"},
                "metrics": {"specific_impulse_s": 330.0, "thrust_N": 5000.0},
                "validation": {"passed": True, "checks": []},
                "files": {},
                "artifact_paths": {},
            }
        ],
    )

    response = asyncio.run(web_main.export_history_csv())
    body = response.body.decode("utf-8")

    assert "job_id,module,starred,created_at" in body
    assert "parameter_propellant" in body
    assert "metric_specific_impulse_s" in body
    assert "engine-a,rocket-engine,True" in body


def test_dashboard_embeds_threejs_stl_viewer_assets():
    html = (web_main.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (web_main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    css = (web_main.STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert "cdnjs.cloudflare.com/ajax/libs/three.js" not in html
    assert "STLLoader.js" not in html
    assert "OrbitControls.js" not in html
    assert 'id="stl-viewer"' in html
    assert 'id="clip-x-slider" type="range" min="0" max="100" value="0"' in html
    assert 'id="clip-y-slider" type="range" min="0" max="100" value="0"' in html
    assert 'id="clip-z-slider" type="range" min="0" max="100" value="0"' in html
    assert 'id="clip-reset-button"' in html
    assert 'aria-label="Sectional view presets"' in html
    assert 'data-section-view="half-x"' in html
    assert 'data-section-view="quarter"' in html
    assert 'aria-label="Auxiliary view presets"' in html
    assert 'data-aux-view="aux-a"' in html
    assert 'data-aux-view="aux-b"' in html
    assert 'id="flow-toggle-button"' in html
    assert 'id="flow-speed-slider" type="range" min="0.25" max="3" step="0.25" value="1"' in html
    assert 'id="render-mode-button"' in html
    assert 'data-viewer-tab="mesh"' in html
    assert 'data-viewer-tab="cad"' in html
    assert 'id="cad-viewer"' in html
    assert 'id="design-log-list"' in html
    assert "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js" in js
    assert "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js" in js
    assert "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js" in js
    assert "https://cdn.jsdelivr.net/npm/online-3d-viewer@0.18.0/build/engine/o3dv.min.js" in js
    assert "https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js" in js
    assert 'document.createElement("script")' in js
    assert "script.onload" in js
    assert "script.onerror" in js
    assert "await loadViewerScript(asset.url, asset.label)" in js
    assert "ensureThreeViewerLibraries()" in js
    assert "new THREE.STLLoader()" in js
    assert "fetch(stlUrl, { credentials: \"same-origin\" })" in js
    assert "`/download/${encodeURIComponent(job.job_id)}/${encodeURIComponent(artifact)}`" in js
    assert "artifactDownloadUrl(job, \"stl\")" in js
    assert 'data-artifact="${escapeHtml(key)}"' in js
    assert "thermal_map: \"Download Thermal Map\"" in js
    assert "engineering_drawing: \"Download Drawing\"" in js
    assert "trajectory: \"Download Trajectory\"" in js
    assert "STL fetch failed for ${stlUrl}" in js
    assert "Download STL to view in FreeCAD" in js
    assert 'globalName: "THREE.STLLoader"' in js
    assert "but ${asset.globalName} is unavailable." in js
    assert "new THREE.WebGLRenderer" in js
    assert "new THREE.OrbitControls" in js
    assert "controls.enableZoom = true" in js
    assert "controls.touches.TWO = THREE.TOUCH.DOLLY_PAN" in js
    assert "renderer.clippingPlanes" in js
    assert "new THREE.Plane(" in js
    assert "new THREE.PlaneHelper" in js
    assert "clipHelperGroup" in js
    assert "clipCapMaterial" not in js
    assert "new THREE.PlaneGeometry" not in js
    assert "function applyRenderMode(mode)" in js
    assert "material.opacity = safeMode === \"xray\" ? 0.3 : 1.0" in js
    assert "renderModeButton.addEventListener(\"click\"" in js
    assert "OV.EmbeddedViewer" in js
    assert "viewer.LoadModelFromUrlList([stepUrl])" in js
    assert "setClipControlValues" in js
    assert "function applySectionView(name)" in js
    assert "function applyAuxiliaryView(name)" in js
    assert "function auxiliaryViewDirection(name)" in js
    assert "sectionViewButtons.forEach" in js
    assert "auxiliaryViewButtons.forEach" in js
    assert "new THREE.BufferGeometry()" in js
    assert "new THREE.PointsMaterial" in js
    assert "new THREE.Points(flowGeometry, flowMaterial)" in js
    assert "const particleCount = 360" in js
    assert "particleCount = 360" in js and 360 < 500
    assert "localNozzleRadiusMm" in js
    assert "job?.metadata?.nozzle" in js
    assert "flowToggleButton.addEventListener(\"click\"" in js
    assert "flowSpeedSlider.addEventListener(\"input\"" in js
    assert "clipResetButton.addEventListener(\"click\"" in js
    assert "renderSTLPreview(stlDownloadUrl(job), `${moduleLabel(module)} - ${job.job_id}`, job)" in js
    assert "renderCADPreview(job)" in js
    assert "appendDesignLog" in js
    assert "startDesignLog(module)" in js
    assert "new window.Chart" in js
    assert ".stl-viewer" in css
    assert ".cad-viewer" in css
    assert ".viewer-tabs" in css
    assert ".design-log-list" in css
    assert ".radar-chart-frame" in css
    assert ".viewer-controls" in css
    assert ".range-control" in css
    assert ".button-grid" in css
    assert ".preview-message a" in css
    assert "300px" in css


def test_dashboard_includes_sidebar_layout_mission_tab_and_metrics():
    html = (web_main.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (web_main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    css = (web_main.STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'class="brand-mark"' in html
    assert 'id="server-status"' in html
    assert 'id="summary-total-jobs"' in html
    assert 'id="summary-total-engines"' in html
    assert 'id="summary-last-design"' in html
    assert 'data-tab-target="design-view" data-module-target="rocket-engine"' in html
    assert 'data-tab-target="design-view" data-module-target="heat-exchanger"' in html
    assert 'data-tab-target="design-view" data-module-target="actuator"' in html
    assert 'id="mission-view"' in html
    assert 'id="mission-form"' in html
    assert '<select id="mission_engine_job_id" name="engine_job_id" required>' in html
    assert 'id="hx_duty_kW" name="duty_kW" type="number" min="0.001" step="any"' in html
    assert 'id="hx_hot_inlet_temp_C" name="hot_inlet_temp_C" type="number" step="any"' in html
    assert 'id="hx_hot_outlet_temp_C" name="hot_outlet_temp_C" type="number" step="any"' in html
    assert 'id="hx_cold_inlet_temp_C" name="cold_inlet_temp_C" type="number" step="any"' in html
    assert 'id="actuator_force_N" name="force_N" type="number" min="0.1" step="any"' in html
    assert 'id="actuator_stroke_mm" name="stroke_mm" type="number" min="0.1" step="any"' in html
    assert 'id="actuator_voltage_V" name="voltage_V" type="number" min="0.1" step="any"' in html
    assert 'id="actuator_response_time_ms" name="response_time_ms" type="number" min="0.1" step="any"' in html
    assert 'id="mission_vehicle_mass_kg" name="vehicle_mass_kg" type="number" min="0.001" step="any"' in html
    assert 'id="mission_propellant_mass_kg" name="propellant_mass_kg" type="number" min="0.001" step="any"' in html
    assert 'id="mission_launches_per_month" name="planned_launches_per_month" type="number" min="0.001" step="any"' in html
    assert 'id="mission-result-cards"' in html
    assert '<option value="mission">Mission</option>' in html
    assert '<th>Name</th>' in html
    assert '<th>Module</th>' in html
    assert '<th>Date</th>' in html
    assert '<th>Key Metric</th>' in html
    assert '<th>Size</th>' in html
    assert '<th>Actions</th>' in html
    assert 'id="analytics-view"' in html
    assert 'fetch("/api/mission"' in js
    assert "setServerStatus(true)" in js
    assert "updateDashboardSummary()" in js
    assert "setActiveModule(moduleTarget)" in js
    assert "formatBytes(job.size_bytes)" in js
    assert "populateMissionEngineOptions();" in js
    assert "missionEngineLabel(job)" in js
    assert "option.value = job.job_id" in js
    assert "option.textContent = missionEngineLabel(job)" in js
    assert "kerolox|methalox|hydrolox" in js
    assert "delta_v_m_s" in js
    assert "hydrogen_mass_needed_kg_s" in js
    assert "solar_energy_kwh_per_day" in js
    assert "renderMissionResults(payload.job)" in js
    assert ".dashboard-tabs" in css
    assert ".dashboard-layout" in css
    assert ".sidebar" in css
    assert ".mission-workspace" in css
    assert ".history-table" in css
    assert ".compare-panel" in css


def test_dashboard_uses_custom_delete_modal_and_stl_fullscreen_control():
    html = (web_main.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    js = (web_main.STATIC_DIR / "app.js").read_text(encoding="utf-8")
    css = (web_main.STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    assert 'id="delete-modal-backdrop"' in html
    assert 'role="dialog"' in html
    assert 'id="delete-modal-confirm"' in html
    assert 'id="stl-fullscreen-button"' in html
    assert "window.confirm" not in js
    assert "openDeleteModal(deleteButton.dataset.jobId)" in js
    assert "confirmDeleteJob" in js
    assert "requestFullscreen" in js
    assert "document.exitFullscreen" in js
    assert "function viewerDimensions()" in js
    assert "function fitCameraToObject(direction = currentCameraDirection)" in js
    assert "document.fullscreenElement === stlPreviewSectionEl" in js
    assert "state.resizeRenderer = resizeRenderer" in js
    assert "state.fitCamera = fitCameraToObject" in js
    assert 'document.addEventListener("fullscreenchange", updateSTLFullscreenButton)' in js
    assert ".modal-backdrop" in css
    assert ".modal-dialog" in css
    assert ".danger-primary" in css
    assert ".stl-preview-section:fullscreen" in css
    assert "height: calc(100vh - 330px)" in css
    assert ".viewer-action" in css
