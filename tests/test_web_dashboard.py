import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import nova.web.main as web_main


def test_dashboard_registers_all_design_routes():
    routes = {route.path for route in web_main.app.routes}

    assert "/api/design/rocket-engine" in routes
    assert "/api/design/heat-exchanger" in routes
    assert "/api/design/actuator" in routes
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

    assert "cdnjs.cloudflare.com/ajax/libs/three.js" in html
    assert "three.min.js" in html
    assert "STLLoader.js" in html
    assert "OrbitControls.js" in html
    assert 'id="stl-viewer"' in html
    assert "new THREE.STLLoader()" in js
    assert "fetch(stlUrl, { credentials: \"same-origin\" })" in js
    assert "`/download/${encodeURIComponent(job.job_id)}/stl`" in js
    assert "STL fetch failed for ${stlUrl}" in js
    assert "Download STL to view in FreeCAD" in js
    assert "new THREE.WebGLRenderer" in js
    assert "new THREE.OrbitControls" in js
    assert "renderSTLPreview(stlDownloadUrl(job)" in js
    assert ".stl-viewer" in css
    assert ".preview-message a" in css
    assert "300px" in css
