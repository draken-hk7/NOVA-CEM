import asyncio
from pathlib import Path
from types import SimpleNamespace

import nova.web.main as web_main


def test_dashboard_registers_all_design_routes():
    routes = {route.path for route in web_main.app.routes}

    assert "/api/design/rocket-engine" in routes
    assert "/api/design/heat-exchanger" in routes
    assert "/api/design/actuator" in routes


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
