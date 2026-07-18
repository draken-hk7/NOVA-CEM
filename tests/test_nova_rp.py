from pathlib import Path

from nova.core.input_schema import RocketEngineSpec
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult
from nova.modules.nova_rp import NovaRP
from nova.web.main import _download_urls, _export_dashboard_artifacts


def test_nova_rp_design_returns_geometry_performance_and_trace():
    spec = RocketEngineSpec(
        thrust_N=5000.0,
        chamber_pressure_bar=50.0,
        propellant="kerolox",
        material="inconel",
    )
    result = NovaRP().design(spec)
    assert result.geometry.is_watertight
    assert len(result.geometry.shape.Solids()) == 1
    assert result.geometry.metadata["propellant_manifold"]["oxidizer_manifold"]["feed_hole_count"] == 8
    assert result.geometry.metadata["propellant_manifold"]["ports"]["oxidizer_inlet"]["thread_spec"] == "M12x1.5 standard"
    assert result.geometry.metadata["propellant_manifold"]["ports"]["fuel_inlet"]["thread_spec"] == "M10x1.25 standard"
    assert result.metadata["manifold"]["flow_area_mm2"] > 0.0
    assert set(result.metadata["nozzle"]["coolant_ports"]) == {"inlet", "outlet"}
    assert result.metadata["nozzle"]["coolant_ports"]["inlet"]["thread_spec"] == "M8x1.25 standard"
    assert result.metadata["nozzle"]["n_cooling_channels"] == 8
    assert result.performance.expansion_ratio == 20.0
    assert result.metadata["nozzle"]["expansion_ratio"] == 20.0
    assert result.performance.thrust_N == 5000.0
    assert result.performance.specific_impulse_s > 250.0
    assert result.structural.passed
    assert not result.validation.passed
    assert len(result.validation.checks) == 5
    assert any(check.name == "Propellant manifold wall" and check.passed for check in result.validation.checks)
    stability_check = next(check for check in result.validation.checks if check.name == "Combustion stability acoustic mode")
    assert not stability_check.passed
    assert 1000.0 <= stability_check.actual_value <= 5000.0
    assert result.manufacturing.passed
    assert result.trace

    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    artifact_dir = Path("outputs/test-artifacts")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stl = artifact_dir / "engine.stl"
    step = artifact_dir / "engine.step"
    report = artifact_dir / "report.pdf"
    thermal_map = artifact_dir / "thermal_map.svg"
    exporter.to_stl(result.geometry, str(stl))
    exporter.to_step(result.geometry, str(step))
    run = CEMRunResult("test-job", "rocket-engine", spec.model_dump(), result)
    reporter.generate_pdf_report(run, str(report))
    assert stl.exists() and stl.stat().st_size > 0
    assert step.exists() and step.stat().st_size > 0
    assert report.exists() and report.stat().st_size > 0
    assert thermal_map.exists() and thermal_map.stat().st_size > 0
    assert run.files["thermal_map"] == str(thermal_map)
    drawing_pdf = artifact_dir / "engineering_drawing.pdf"
    drawing_svg = artifact_dir / "engineering_drawing.svg"
    assert drawing_pdf.exists() and drawing_pdf.stat().st_size > 0
    assert drawing_svg.exists() and drawing_svg.stat().st_size > 0
    assert run.files["engineering_drawing"] == str(drawing_pdf)
    assert run.files["engineering_drawing_svg"] == str(drawing_svg)
    svg = thermal_map.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "CoolingChannelSolver.bartz_heat_flux" in svg
    assert "Throat" in svg
    assert "Cooling inlet" in svg
    assert "Cooling outlet" in svg
    assert "Peak heat flux" in svg
    report_bytes = report.read_bytes()
    assert b"MANUFACTURING, PRESSURE BUDGET AND VALIDATION" in report_bytes
    assert b"CRITICAL TOLERANCES" in report_bytes
    assert b"ENGINEERING DRAWING" in report_bytes
    assert b"THERMAL MAP" in report_bytes
    assert b"AEROSPACE SCREENING ANALYSIS" in report_bytes
    assert b"/Count 5" in report_bytes
    drawing_svg_text = drawing_svg.read_text(encoding="utf-8")
    assert "FRONT PROFILE" in drawing_svg_text
    assert "SECTION A-A" in drawing_svg_text
    assert "TOP PLAN VIEW" in drawing_svg_text
    assert "M8x1.25" in drawing_svg_text


def test_nova_rp_cooling_channel_defaults_and_preview_override():
    spec = RocketEngineSpec(
        thrust_N=5000.0,
        chamber_pressure_bar=50.0,
        propellant="kerolox",
        material="inconel",
    )
    rp = NovaRP()
    assert rp._n_cooling_channels(spec, chamber_radius_mm=30.0, wall_thickness_mm=1.0) == 8
    assert rp._n_cooling_channels(spec, chamber_radius_mm=30.0, wall_thickness_mm=1.0, requested_count=4) == 4


def test_regenerative_cooling_channel_wall_has_validator_margin(monkeypatch):
    monkeypatch.setenv("NOVA_GEOMETRY_ENABLED", "false")
    spec = RocketEngineSpec(
        thrust_N=50.0,
        chamber_pressure_bar=10.0,
        propellant="kerolox",
        material="copper",
    )

    result = NovaRP().design(spec)
    cooling_check = next(check for check in result.validation.checks if check.name == "Cooling channel wall")

    stability_check = next(check for check in result.validation.checks if check.name == "Combustion stability acoustic mode")
    assert not result.validation.passed
    assert cooling_check.actual_value >= 0.6
    assert not stability_check.passed


def test_nova_rp_physics_only_mode_keeps_report_without_cad_artifacts(monkeypatch):
    monkeypatch.setenv("NOVA_GEOMETRY_ENABLED", "false")
    spec = RocketEngineSpec(
        thrust_N=5000.0,
        chamber_pressure_bar=50.0,
        propellant="kerolox",
        material="inconel",
    )

    result = NovaRP().design(spec)
    artifact_dir = Path("outputs/test-artifacts/physics-only")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    files = _export_dashboard_artifacts("physics-only-job", spec, result, artifact_dir)
    urls = _download_urls("physics-only-job", files)

    assert result.geometry is None
    assert result.performance.specific_impulse_s > 250.0
    assert result.mass_kg > 0.0
    stability_check = next(check for check in result.validation.checks if check.name == "Combustion stability acoustic mode")
    assert not result.validation.passed
    assert not stability_check.passed
    assert set(files) == {"thermal_map", "engineering_drawing", "engineering_drawing_svg", "report", "json"}
    assert set(urls) == {"thermal_map", "engineering_drawing", "report"}
    assert (artifact_dir / "report.pdf").exists()
    assert (artifact_dir / "thermal_map.svg").exists()


def test_nova_rp_propellant_expansion_ratio_defaults_and_explicit_override():
    rp = NovaRP()
    hydrolox = RocketEngineSpec(
        thrust_N=5000.0,
        chamber_pressure_bar=50.0,
        propellant="hydrolox",
        material="inconel",
    )
    kerolox = RocketEngineSpec(
        thrust_N=5000.0,
        chamber_pressure_bar=50.0,
        propellant="kerolox",
        material="inconel",
    )
    explicit = RocketEngineSpec(
        thrust_N=5000.0,
        chamber_pressure_bar=50.0,
        propellant="hydrolox",
        material="inconel",
        expansion_ratio=8.0,
    )

    assert rp._effective_expansion_ratio(hydrolox) == 40.0
    assert rp._effective_expansion_ratio(kerolox) == 20.0
    assert rp._effective_expansion_ratio(explicit) == 8.0
