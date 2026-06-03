import math

import numpy as np
import pytest

from nova.core.physics_solver import (
    CombustionSolver,
    CoolingChannelSolver,
    EMSolver,
    HeatExchangerSolver,
    NozzleFlowSolver,
    StructuralSolver,
)
from nova.core.types import ChannelGeometry, CoolantProperties


def test_area_ratio_to_mach_matches_reference_gamma_14():
    solver = NozzleFlowSolver()
    supersonic = solver.area_ratio_to_mach(2.0, supersonic=True, gamma=1.4)
    subsonic = solver.area_ratio_to_mach(2.0, supersonic=False, gamma=1.4)
    assert supersonic == pytest.approx(2.1972, rel=2e-4)
    assert subsonic == pytest.approx(0.3059, rel=2e-4)
    assert solver.mach_to_area_ratio(supersonic, gamma=1.4) == pytest.approx(2.0, rel=1e-8)


def test_throat_area_uses_thrust_coefficient_relation():
    solver = NozzleFlowSolver()
    area = solver.throat_area(thrust_N=1000.0, chamber_pressure_bar=10.0, Cf=1.5)
    assert area == pytest.approx(1000.0 / (1.5 * 10.0e5))


def test_combustion_solver_returns_reference_ranges_for_kerolox():
    result = CombustionSolver().solve("kerolox", OF_ratio=2.56, chamber_pressure_bar=50.0)
    assert result.T_c == pytest.approx(3616.8, rel=0.01)
    assert result.Isp == pytest.approx(351.4, rel=0.01)
    assert result.gamma == pytest.approx(1.136, rel=0.01)
    assert result.molecular_weight_g_mol == pytest.approx(23.25, rel=0.01)
    assert result.Cf == pytest.approx(1.925, rel=0.01)


def test_combustion_solver_returns_reference_ranges_for_methalox():
    result = CombustionSolver().solve("methalox", OF_ratio=3.55, chamber_pressure_bar=50.0)
    assert result.T_c == pytest.approx(3516.2, rel=0.01)
    assert result.Isp == pytest.approx(362.0, rel=0.01)
    assert result.gamma == pytest.approx(1.128, rel=0.01)
    assert result.molecular_weight_g_mol == pytest.approx(21.97, rel=0.01)


def test_combustion_solver_returns_reference_ranges_for_hydrolox():
    result = CombustionSolver().solve("hydrolox", OF_ratio=5.50, chamber_pressure_bar=50.0)
    assert result.T_c == pytest.approx(3368.1, rel=0.01)
    assert result.Isp == pytest.approx(448.7, rel=0.01)
    assert result.gamma == pytest.approx(1.145, rel=0.01)
    assert result.molecular_weight_g_mol == pytest.approx(12.62, rel=0.01)


def test_cooling_channel_solver_has_positive_temperatures_and_pressure_drop():
    heat_flux = np.full(32, 2.0e6)
    channel = ChannelGeometry(
        hydraulic_diameter_mm=1.0,
        length_mm=300.0,
        n_channels=40,
        channel_area_mm2=0.8,
        wall_thickness_mm=1.2,
    )
    coolant = CoolantProperties.for_propellant("kerolox")
    result = CoolingChannelSolver().solve_channel(heat_flux, channel, coolant, flow_rate_kg_s=0.2)
    assert result.max_wall_temperature_K > coolant.inlet_temperature_K
    assert result.pressure_drop_bar > 0.0
    assert result.reynolds_number > 0.0


def test_structural_solver_known_hoop_stress():
    stress = StructuralSolver().hoop_stress(pressure_bar=50.0, radius_mm=50.0, wall_thickness_mm=5.0)
    assert stress == pytest.approx(50.0)
    assert StructuralSolver().factor_of_safety(stress, 250.0) == pytest.approx(5.0)


def test_heat_exchanger_lmtd_counterflow_known_case():
    lmtd = HeatExchangerSolver().LMTD(400.0, 330.0, 290.0, 320.0, "counterflow")
    expected = ((400.0 - 320.0) - (330.0 - 290.0)) / math.log((400.0 - 320.0) / (330.0 - 290.0))
    assert lmtd == pytest.approx(expected)


def test_heat_exchanger_ntu_design_returns_area_and_flows():
    result = HeatExchangerSolver().design_ntu_effectiveness(
        hot_fluid="exhaust",
        cold_fluid="hydrogen",
        duty_kW=10.0,
        hot_inlet_temp_C=800.0,
        hot_outlet_temp_C=200.0,
        cold_inlet_temp_C=20.0,
        max_pressure_bar=1.0,
        material="inconel",
    )

    assert result.effectiveness == pytest.approx(600.0 / 780.0)
    assert result.ntu > 3.0
    assert result.required_area_m2 > 0.1
    assert result.hot_mass_flow_kg_s > 0.0
    assert result.cold_mass_flow_kg_s > 0.0
    assert result.pressure_drop_bar <= 1.0


def test_em_solver_copper_loss_and_back_emf():
    solver = EMSolver()
    assert solver.copper_loss(0.2, 10.0) == pytest.approx(20.0)
    assert solver.back_emf(100.0, 3000.0) == pytest.approx(30.0)


def test_em_solver_solenoid_actuator_sizing_meets_force_and_response():
    result = EMSolver().solenoid_actuator(
        force_N=50.0,
        stroke_mm=10.0,
        voltage_V=24.0,
        response_time_ms=50.0,
        max_temp_C=180.0,
    )

    assert result.force_output_N >= 50.0
    assert result.response_time_ms <= 50.0
    assert result.coil_turns > 0
    assert result.current_draw_A > 0.0
    assert result.coil_resistance_ohm > 0.0
    assert result.power_consumption_W > 0.0
