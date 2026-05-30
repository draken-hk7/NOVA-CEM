"""NASA CEA-backed rocket combustion and performance calculations."""

from __future__ import annotations

import contextlib
import io
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from nova.core.exceptions import PhysicsViolationError
from nova.core.types import CombustionResult

G0 = 9.80665
DEFAULT_CEA_EXPANSION_RATIO = 75.0


@dataclass(frozen=True, slots=True)
class CEAPropellant:
    reactants: tuple[str, str]
    reactant_temperatures_K: tuple[float, float]
    optimal_OF: float
    fuel_weights: tuple[float, float] = (1.0, 0.0)
    oxidizer_weights: tuple[float, float] = (0.0, 1.0)


CEA_PROPELLANTS: dict[str, CEAPropellant] = {
    "kerolox": CEAPropellant(("RP-1", "O2(L)"), (298.15, 90.17), 2.56),
    "methalox": CEAPropellant(("CH4(L)", "O2(L)"), (111.7, 90.17), 3.55),
    "hydrolox": CEAPropellant(("H2(L)", "O2(L)"), (20.27, 90.17), 5.50),
}


LEGACY_PROPELLANT_DATA = {
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


@lru_cache(maxsize=1)
def _import_cea() -> Any:
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            import cea
    except Exception as exc:  # pragma: no cover - environment dependent.
        raise PhysicsViolationError(
            "NASA CEA Python package is required for kerolox, methalox, and hydrolox combustion solves"
        ) from exc
    return cea


@lru_cache(maxsize=len(CEA_PROPELLANTS))
def _cea_solver(propellant: str) -> tuple[Any, Any, Any]:
    cea = _import_cea()
    data = CEA_PROPELLANTS[propellant]
    reactants = cea.Mixture(list(data.reactants))
    products = cea.Mixture(list(data.reactants), products_from_reactants=True)
    solver = cea.RocketSolver(products, reactants=reactants)
    return cea, reactants, solver


class CombustionSolver:
    """NASA CEA rocket solver wrapper for deterministic first-order sizing."""

    def solve(
        self,
        propellant: str,
        OF_ratio: float,
        chamber_pressure_bar: float,
        expansion_ratio: float = DEFAULT_CEA_EXPANSION_RATIO,
    ) -> CombustionResult:
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
        if expansion_ratio <= 1.0:
            raise PhysicsViolationError(
                "CEA expansion ratio must exceed one",
                requirement="expansion ratio",
                actual=expansion_ratio,
                limit=1.0,
            )

        if propellant in CEA_PROPELLANTS:
            return self._solve_with_cea(propellant, OF_ratio, chamber_pressure_bar, expansion_ratio)
        if propellant in LEGACY_PROPELLANT_DATA:
            return self._solve_legacy(propellant, OF_ratio, chamber_pressure_bar)
        raise PhysicsViolationError(f"Unsupported propellant: {propellant}")

    def _solve_with_cea(
        self,
        propellant: str,
        OF_ratio: float,
        chamber_pressure_bar: float,
        expansion_ratio: float,
    ) -> CombustionResult:
        cea, reactants, solver = _cea_solver(propellant)
        data = CEA_PROPELLANTS[propellant]
        solution = cea.RocketSolution(solver)
        fuel_weights = np.asarray(data.fuel_weights, dtype=float)
        oxidizer_weights = np.asarray(data.oxidizer_weights, dtype=float)
        reactant_temperatures = np.asarray(data.reactant_temperatures_K, dtype=float)
        weights = reactants.of_ratio_to_weights(oxidizer_weights, fuel_weights, OF_ratio)
        chamber_enthalpy = reactants.calc_property(cea.ENTHALPY, weights, reactant_temperatures) / cea.R

        solver.solve(
            solution,
            weights,
            chamber_pressure_bar,
            [10.0, 100.0, 1000.0],
            supar=[expansion_ratio],
            iac=True,
            hc=chamber_enthalpy,
        )
        if not solution.converged:
            raise PhysicsViolationError(
                "NASA CEA rocket solve failed to converge",
                requirement="CEA convergence",
            )

        chamber_index = 0
        exit_index = int(solution.num_pts - 1)
        exhaust_velocity_m_s = float(solution.Isp[exit_index])
        c_star = float(solution.c_star[chamber_index])
        cf = float(solution.coefficient_of_thrust[exit_index])
        return CombustionResult(
            propellant=propellant,
            OF_ratio=OF_ratio,
            chamber_pressure_bar=chamber_pressure_bar,
            T_c=float(solution.T[chamber_index]),
            Isp=exhaust_velocity_m_s / G0,
            exhaust_velocity_m_s=exhaust_velocity_m_s,
            gamma=float(solution.gamma_s[chamber_index]),
            molecular_weight_g_mol=float(solution.MW[chamber_index]),
            Cp_J_kgK=float(solution.cp_eq[chamber_index] * 1000.0),
            c_star_m_s=c_star,
            Cf=cf,
            combustion_efficiency=1.0,
        )

    def _solve_legacy(self, propellant: str, OF_ratio: float, chamber_pressure_bar: float) -> CombustionResult:
        data = LEGACY_PROPELLANT_DATA[propellant]
        of_error = (OF_ratio - data["optimal_OF"]) / data["of_width"]
        mixture_efficiency = max(0.55, 1.0 - 0.045 * of_error**2)
        pressure_factor = 1.0 + 0.018 * math.log(max(chamber_pressure_bar, 1.0) / 30.0)
        pressure_factor = min(max(pressure_factor, 0.93), 1.08)
        combustion_efficiency = data["efficiency"] * mixture_efficiency
        t_c = data["T_c_K"] * (0.985 + 0.015 * mixture_efficiency) * pressure_factor**0.05
        gamma = data["gamma"] * (1.0 - 0.006 * max(of_error, 0.0))
        molecular_weight = data["molecular_weight_g_mol"] * (1.0 + 0.015 * of_error)
        c_star = data["c_star_m_s"] * pressure_factor * combustion_efficiency
        cf = data["Cf"] * (0.990 + 0.010 * pressure_factor)
        exhaust_velocity = c_star * cf
        return CombustionResult(
            propellant=propellant,
            OF_ratio=OF_ratio,
            chamber_pressure_bar=chamber_pressure_bar,
            T_c=t_c,
            Isp=exhaust_velocity / G0,
            exhaust_velocity_m_s=exhaust_velocity,
            gamma=gamma,
            molecular_weight_g_mol=molecular_weight,
            Cp_J_kgK=data["Cp_J_kgK"],
            c_star_m_s=c_star,
            Cf=cf,
            combustion_efficiency=combustion_efficiency,
        )

    @staticmethod
    def optimal_OF(propellant: str) -> float:
        if propellant in CEA_PROPELLANTS:
            return CEA_PROPELLANTS[propellant].optimal_OF
        if propellant in LEGACY_PROPELLANT_DATA:
            return float(LEGACY_PROPELLANT_DATA[propellant]["optimal_OF"])
        raise PhysicsViolationError(f"Unsupported propellant: {propellant}")

