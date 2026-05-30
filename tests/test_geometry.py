import math

import pytest

from nova.core.geometry_engine.primitives import GeometryBuilder
from nova.core.geometry_engine.rocket_geometry import RocketNozzleGeometry


def test_cylinder_is_watertight_and_volume_matches_analytic():
    solid = GeometryBuilder().cylinder(radius=10.0, height=20.0, segments=128)
    assert solid.is_watertight
    assert solid.volume_mm3 == pytest.approx(math.pi * 10.0**2 * 20.0, rel=1.5e-3)


def test_revolved_bell_nozzle_is_watertight():
    result = RocketNozzleGeometry(segments=64).bell_nozzle(
        throat_radius_mm=8.0,
        chamber_radius_mm=26.0,
        expansion_ratio=6.0,
        chamber_length_mm=60.0,
        wall_thickness_mm=1.6,
        n_cooling_channels=32,
    )
    assert result.solid.is_watertight
    assert result.channels.n_channels == 32
    assert result.metadata["exit_radius_mm"] == pytest.approx(8.0 * math.sqrt(6.0))

