import pytest

from nova.core.analysis import analyze_combustion_stability, estimate_thermal_fatigue_life, size_ignition_system
from nova.core.geometry_engine.picogk_bridge import PicoGKBridge


def test_combustion_stability_reports_longitudinal_tangential_and_radial_modes():
    result = analyze_combustion_stability(
        chamber_length_mm=100.0,
        chamber_radius_mm=58.6,
        speed_of_sound_m_s=1000.0,
    )

    assert result.chamber_acoustic_frequency_hz == pytest.approx(5000.0)
    assert {mode.family for mode in result.modes} == {"longitudinal", "tangential", "radial"}
    assert result.stability_risk
    assert "baffled injector" in result.recommendation


def test_fatigue_and_ignition_screens_return_traceable_outputs():
    fatigue = estimate_thermal_fatigue_life(
        material="inconel",
        peak_wall_temperature_K=1120.0,
        coolant_temperature_K=380.0,
    )
    ignition = size_ignition_system(
        chamber_pressure_bar=50.0,
        chamber_length_mm=80.0,
        chamber_radius_mm=28.0,
        propellant="kerolox",
        thrust_N=5000.0,
    )

    assert fatigue.estimated_cycles > 0
    assert fatigue.recommended_firings > 0
    assert ignition.minimum_spark_energy_J > 0.0
    assert ignition.design_spark_energy_J == pytest.approx(3.0 * ignition.minimum_spark_energy_J)
    assert ignition.recommended_igniter in {"spark", "torch", "pyrotechnic"}


def test_picogk_bridge_keeps_cadquery_fallback_available():
    bridge = PicoGKBridge(backend="cadquery")
    sentinel = object()

    assert bridge.status.requested_backend == "cadquery"
    assert bridge.status.active_backend == "cadquery"
    assert bridge.build_rocket_nozzle(lambda: sentinel, nozzle_type="bell") is sentinel
