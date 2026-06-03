from pathlib import Path

from nova.core.input_schema import HeatExchangerSpec
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult
from nova.modules.nova_hx import NovaHX


def _stl_triangle_count(path: Path) -> int:
    data = path.read_bytes()
    if data.startswith(b"solid"):
        return data.count(b"facet normal")
    return int.from_bytes(data[80:84], byteorder="little", signed=False)


def test_nova_hx_design_generates_gyroid_geometry_and_report():
    spec = HeatExchangerSpec(
        hot_fluid="exhaust",
        cold_fluid="hydrogen",
        duty_kW=10.0,
        hot_inlet_temp_C=800.0,
        hot_outlet_temp_C=200.0,
        cold_inlet_temp_C=20.0,
        max_pressure_bar=1.0,
        material="inconel",
    )

    result = NovaHX().design(spec)

    assert result.geometry.is_watertight
    assert len(result.geometry.shape.Solids()) == 1
    assert result.geometry.metadata["architecture"] == "gyroid"
    assert result.geometry.metadata["geometry_type"] == "gyroid_crossflow_microchannel_fallback"
    assert result.geometry.metadata["hot_flow_region"]["channel_count"] > 0
    assert result.geometry.metadata["cold_flow_region"]["channel_count"] > 0
    assert set(result.geometry.metadata["manifold_headers"]) == {"hot_inlet", "hot_outlet", "cold_inlet", "cold_outlet"}
    assert result.geometry.metadata["manifold_headers"]["hot_inlet"]["stub_diameter_mm"] == 15.0
    assert result.geometry.metadata["manifold_headers"]["cold_outlet"]["stub_length_mm"] == 20.0
    assert result.geometry.metadata["mounting_brackets"]["count"] == 2
    assert result.geometry.metadata["mounting_brackets"]["bolt_hole_count"] == 4
    assert result.performance.effectiveness > 0.0
    assert result.performance.ntu > 0.0
    assert result.performance.required_area_m2 > 0.0
    assert result.performance.pressure_drop_bar <= spec.max_pressure_bar
    assert result.mass_kg > 0.0

    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    artifact_dir = Path("outputs/test-artifacts/hx")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stl = artifact_dir / "heat_exchanger.stl"
    step = artifact_dir / "heat_exchanger.step"
    report = artifact_dir / "report.pdf"
    exporter.to_stl(result.geometry, str(stl), tolerance=1.0)
    exporter.to_step(result.geometry, str(step))
    reporter.generate_pdf_report(CEMRunResult("hx-test", "heat-exchanger", spec.model_dump(), result), str(report))

    assert stl.exists() and stl.stat().st_size > 0
    assert _stl_triangle_count(stl) >= 10_000
    assert step.exists() and step.stat().st_size > 0
    assert report.exists() and report.stat().st_size > 0
    assert b"required_area_m2" in report.read_bytes()
