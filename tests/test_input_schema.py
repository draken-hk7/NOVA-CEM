import pytest

from nova.core.input_schema import HeatExchangerSpec, RocketEngineSpec


def test_rocket_spec_accepts_valid_units_and_defaults():
    spec = RocketEngineSpec(thrust_N=5000.0, chamber_pressure_bar=50.0, propellant="kerolox")
    assert spec.expansion_ratio == 8.0
    assert spec.manufacturing_process == "lpbf"


def test_rocket_spec_rejects_material_pressure_violation():
    with pytest.raises(Exception) as exc:
        RocketEngineSpec(
            thrust_N=5000.0,
            chamber_pressure_bar=5000.0,
            propellant="kerolox",
            material="copper",
            safety_factor=2.0,
        )
    assert "Chamber pressure exceeds material yield limit" in str(exc.value)


def test_rocket_spec_rejects_process_incompatibility():
    with pytest.raises(Exception) as exc:
        RocketEngineSpec(
            thrust_N=5000.0,
            chamber_pressure_bar=50.0,
            propellant="kerolox",
            material="copper",
            manufacturing_process="ebm",
        )
    assert "not compatible" in str(exc.value)


def test_heat_exchanger_rejects_invalid_temperature_direction():
    with pytest.raises(Exception):
        HeatExchangerSpec(
            heat_duty_W=1000.0,
            hot_inlet_K=350.0,
            hot_outlet_K=360.0,
            cold_inlet_K=290.0,
            cold_outlet_K=310.0,
        )

