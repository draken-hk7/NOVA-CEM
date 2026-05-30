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
    assert 3500.0 < result.T_c < 3800.0
    assert 260.0 < result.Isp < 290.0
    assert 1.15 < result.gamma < 1.25
    assert result.Cf == pytest.approx(1.53, rel=0.03)


def test_combustion_solver_returns_reference_ranges_for_hydrolox():
    result = CombustionSolver().solve("hydrolox", OF_ratio=5.50, chamber_pressure_bar=50.0)
    assert result.T_c == pytest.approx(3500.0, rel=0.02)
    assert result.Isp == pytest.approx(450.0, rel=0.02)
    assert result.gamma == pytest.approx(1.26, rel=0.01)
    assert result.molecular_weight_g_mol == pytest.approx(10.0, rel=0.02)


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


def test_em_solver_copper_loss_and_back_emf():
    solver = EMSolver()
    assert solver.copper_loss(0.2, 10.0) == pytest.approx(20.0)
    assert solver.back_emf(100.0, 3000.0) == pytest.approx(30.0)
