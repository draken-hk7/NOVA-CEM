import pytest

from nova.core.input_schema import HeatExchangerSpec, RocketEngineSpec


def test_rocket_spec_accepts_valid_units_and_defaults():
    spec = RocketEngineSpec(thrust_N=5000.0, chamber_pressure_bar=50.0, propellant="kerolox")
    assert spec.expansion_ratio == 8.0
    assert spec.manufacturing_process == "lpbf"


def test_rocket_spec_accepts_hydrolox():
    spec = RocketEngineSpec(thrust_N=5000.0, chamber_pressure_bar=50.0, propellant="hydrolox")
    assert spec.propellant == "hydrolox"


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
            hot_fluid="exhaust",
            cold_fluid="hydrogen",
            duty_kW=10.0,
            hot_inlet_temp_C=350.0,
            hot_outlet_temp_C=360.0,
            cold_inlet_temp_C=20.0,
        )
