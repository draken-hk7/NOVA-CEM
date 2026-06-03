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
    assert result.metadata["nozzle"]["n_cooling_channels"] == 8
    assert result.performance.expansion_ratio == 20.0
    assert result.metadata["nozzle"]["expansion_ratio"] == 20.0
    assert result.performance.thrust_N == 5000.0
    assert result.performance.specific_impulse_s > 250.0
    assert result.structural.passed
    assert result.validation.passed
    assert len(result.validation.checks) == 3
    assert result.manufacturing.passed
    assert result.trace

    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    artifact_dir = Path("outputs/test-artifacts")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stl = artifact_dir / "engine.stl"
    step = artifact_dir / "engine.step"
    report = artifact_dir / "report.pdf"
    exporter.to_stl(result.geometry, str(stl))
    exporter.to_step(result.geometry, str(step))
    reporter.generate_pdf_report(CEMRunResult("test-job", "rocket-engine", spec.model_dump(), result), str(report))
    assert stl.exists() and stl.stat().st_size > 0
    assert step.exists() and step.stat().st_size > 0
    assert report.exists() and report.stat().st_size > 0
    assert b"Structural Validation" in report.read_bytes()


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
    assert result.validation.passed
    assert set(files) == {"report", "json"}
    assert set(urls) == {"report"}
    assert (artifact_dir / "report.pdf").exists()


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
