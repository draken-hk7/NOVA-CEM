import pytest

from nova.core.geometry_engine.primitives import GeometryBuilder
from nova.core.manufacturing.validator import ManufacturingValidator, validate_for_stl_export


def _annotated_annular_wall(wall_mm: float):
    solid = GeometryBuilder().annular_cylinder(10.0, 10.0 - wall_mm, 6.0)
    solid.metadata.update(
        {
            "material": "inconel",
            "chamber_pressure_bar": 50.0,
            "chamber_radius_mm": 10.0 - wall_mm,
            "chamber_wall_thickness_mm": wall_mm,
            "cooling_channel_wall_mm": wall_mm,
            "n_cooling_channels": 8,
        }
    )
    return solid


def test_validator_passes_compliant_lpbf_engine_wall():
    result = ManufacturingValidator().validate(_annotated_annular_wall(1.0))

    assert result.passed
    assert [check.name for check in result.checks] == [
        "Minimum wall thickness",
        "Pressure vessel wall",
        "Cooling channel wall",
    ]


def test_validator_flags_thin_lpbf_and_cooling_walls():
    result = ManufacturingValidator().validate(_annotated_annular_wall(0.3))

    failed = {check.name for check in result.checks if not check.passed}
    assert not result.passed
    assert failed == {"Minimum wall thickness", "Cooling channel wall"}


def test_stl_export_validator_warns_on_failed_checks():
    with pytest.warns(RuntimeWarning, match="STL validation warning"):
        validate_for_stl_export(_annotated_annular_wall(0.3))
