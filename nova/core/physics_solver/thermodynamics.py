"""Deterministic rocket combustion approximations.

This module is not a replacement for NASA CEA. It is a compact, deterministic
CEA-like engineering model calibrated around common propellant families so the
rest of NOVA can perform sizing and validation without network calls.
"""

from __future__ import annotations

import math

from nova.core.exceptions import PhysicsViolationError
from nova.core.types import CombustionResult

G0 = 9.80665


PROPELLANT_DATA = {
    "kerolox": {
        "optimal_OF": 2.56,
        "of_width": 0.75,
        "T_c_K": 3670.0,
        "gamma": 1.205,
        "molecular_weight_g_mol": 22.4,
        "Cp_J_kgK": 3650.0,
        "c_star_m_s": 1780.0,
        "Cf": 1.53,
        "efficiency": 0.970,
    },
    "methalox": {
        "optimal_OF": 3.55,
        "of_width": 0.90,
        "T_c_K": 3560.0,
        "gamma": 1.220,
        "molecular_weight_g_mol": 20.2,
        "Cp_J_kgK": 3820.0,
        "c_star_m_s": 1860.0,
        "Cf": 1.57,
        "efficiency": 0.975,
    },
    "hypergolic": {
        "optimal_OF": 2.05,
        "of_width": 0.65,
        "T_c_K": 3350.0,
        "gamma": 1.185,
        "molecular_weight_g_mol": 24.8,
        "Cp_J_kgK": 3300.0,
        "c_star_m_s": 1660.0,
        "Cf": 1.50,
        "efficiency": 0.955,
    },
    "solid": {
        "optimal_OF": 1.00,
        "of_width": 0.55,
        "T_c_K": 3250.0,
        "gamma": 1.170,
        "molecular_weight_g_mol": 28.0,
        "Cp_J_kgK": 2900.0,
        "c_star_m_s": 1520.0,
        "Cf": 1.43,
        "efficiency": 0.940,
    },
}


class CombustionSolver:
    """Compact CEA-equivalent solver for first-order rocket sizing."""

    def solve(
        self,
        propellant: str,
        OF_ratio: float,
        chamber_pressure_bar: float,
    ) -> CombustionResult:
        if propellant not in PROPELLANT_DATA:
            raise PhysicsViolationError(f"Unsupported propellant: {propellant}")
        if OF_ratio <= 0.0:
            raise PhysicsViolationError(
                "Oxidizer/fuel ratio must be positive",
                requirement="OF ratio",
                actual=OF_ratio,
                limit=0.0,
            )
        if chamber_pressure_bar <= 0.0:
            raise PhysicsViolationError(
                "Chamber pressure must be positive",
                requirement="chamber pressure",
                actual=chamber_pressure_bar,
                limit=0.0,
                unit=" bar",
            )

        data = PROPELLANT_DATA[propellant]
        of_error = (OF_ratio - data["optimal_OF"]) / data["of_width"]
        mixture_efficiency = max(0.55, 1.0 - 0.045 * of_error**2)
        pressure_factor = 1.0 + 0.018 * math.log(max(chamber_pressure_bar, 1.0) / 30.0)
        pressure_factor = min(max(pressure_factor, 0.93), 1.08)

        combustion_efficiency = data["efficiency"] * mixture_efficiency
        T_c = data["T_c_K"] * (0.985 + 0.015 * mixture_efficiency) * pressure_factor**0.05
        gamma = data["gamma"] * (1.0 - 0.006 * max(of_error, 0.0))
        molecular_weight = data["molecular_weight_g_mol"] * (1.0 + 0.015 * of_error)
        c_star = data["c_star_m_s"] * pressure_factor * combustion_efficiency
        Cf = data["Cf"] * (0.990 + 0.010 * pressure_factor)
        exhaust_velocity = c_star * Cf
        Isp = exhaust_velocity / G0

        return CombustionResult(
            propellant=propellant,
            OF_ratio=OF_ratio,
            chamber_pressure_bar=chamber_pressure_bar,
            T_c=T_c,
            Isp=Isp,
            exhaust_velocity_m_s=exhaust_velocity,
            gamma=gamma,
            molecular_weight_g_mol=molecular_weight,
            Cp_J_kgK=data["Cp_J_kgK"],
            c_star_m_s=c_star,
            Cf=Cf,
            combustion_efficiency=combustion_efficiency,
        )

    @staticmethod
    def optimal_OF(propellant: str) -> float:
        if propellant not in PROPELLANT_DATA:
            raise PhysicsViolationError(f"Unsupported propellant: {propellant}")
        return float(PROPELLANT_DATA[propellant]["optimal_OF"])

