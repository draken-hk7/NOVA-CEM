from pathlib import Path

from nova.core.input_schema import RocketEngineSpec
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult
from nova.modules.nova_rp import NovaRP


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
    assert result.performance.thrust_N == 5000.0
    assert result.performance.specific_impulse_s > 250.0
    assert result.structural.passed
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
