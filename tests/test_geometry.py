import math

import pytest

from nova.core.geometry_engine.primitives import GeometryBuilder
from nova.core.geometry_engine.rocket_geometry import InjectorHeadGeometry, RocketNozzleGeometry


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
    assert len(result.solid.shape.Solids()) == 1
    assert result.channels.n_channels == 32
    assert result.metadata["exit_radius_mm"] == pytest.approx(8.0 * math.sqrt(6.0))
    assert set(result.metadata["coolant_ports"]) == {"inlet", "outlet"}
    assert result.metadata["coolant_ports"]["inlet"]["diameter_mm"] == pytest.approx(8.0)
    assert result.metadata["coolant_ports"]["outlet"]["thread_spec"] == "M8x1.25 standard"


def test_injector_with_propellant_manifold_is_single_watertight_solid():
    result = InjectorHeadGeometry(segments=64).coaxial_swirler_injector(
        n_elements=19,
        element_pitch_mm=3.0,
        oxidizer_post_dia_mm=0.8,
        fuel_annulus_gap_mm=0.45,
        manifold_thickness_mm=7.0,
        outer_radius_mm=22.0,
    )

    manifold = result.metadata["propellant_manifold"]

    assert result.solid.is_watertight
    assert len(result.solid.shape.Solids()) == 1
    assert manifold["oxidizer_manifold"]["shape"] == "toroidal"
    assert manifold["oxidizer_manifold"]["feed_hole_count"] == 8
    assert manifold["fuel_manifold"]["feed_passage_count"] == 8
    assert manifold["ports"]["oxidizer_inlet"]["thread_spec"] == "M12x1.5 standard"
    assert manifold["ports"]["fuel_inlet"]["diameter_mm"] == pytest.approx(10.0)
    assert manifold["min_wall_thickness_mm"] >= manifold["required_min_wall_thickness_mm"]
