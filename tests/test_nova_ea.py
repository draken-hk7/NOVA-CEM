from pathlib import Path

from nova.core.input_schema import ActuatorSpec
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult
from nova.modules.nova_ea import NovaEA


def test_nova_ea_design_generates_solenoid_geometry_and_report():
    spec = ActuatorSpec(
        force_N=50.0,
        stroke_mm=10.0,
        voltage_V=24.0,
        response_time_ms=50.0,
        material="steel",
        max_temp_C=180.0,
    )

    result = NovaEA().design(spec)

    assert result.geometry.is_watertight
    assert len(result.geometry.shape.Solids()) == 1
    assert result.geometry.metadata["geometry_type"] == "solenoid_valve_actuator"
    assert "return spring cavity" in result.geometry.metadata["features"]
    assert result.performance.force_output_N >= spec.force_N
    assert result.performance.current_draw_A > 0.0
    assert result.performance.power_consumption_W > 0.0
    assert result.performance.response_time_ms <= spec.response_time_ms
    assert result.performance.coil_resistance_ohm > 0.0
    assert result.mass_kg > 0.0

    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    artifact_dir = Path("outputs/test-artifacts/ea")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stl = artifact_dir / "actuator.stl"
    step = artifact_dir / "actuator.step"
    report = artifact_dir / "report.pdf"
    exporter.to_stl(result.geometry, str(stl), tolerance=1.0)
    exporter.to_step(result.geometry, str(step))
    reporter.generate_pdf_report(CEMRunResult("ea-test", "actuator", spec.model_dump(), result), str(report))

    assert stl.exists() and stl.stat().st_size > 0
    assert step.exists() and step.stat().st_size > 0
    assert report.exists() and report.stat().st_size > 0
    assert b"force_output_N" in report.read_bytes()
