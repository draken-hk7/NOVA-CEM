"""Isentropic one-dimensional nozzle flow relations."""

from __future__ import annotations

import math

from nova.core.exceptions import PhysicsViolationError


class NozzleFlowSolver:
    def mach_to_area_ratio(self, mach: float, gamma: float = 1.4) -> float:
        if mach <= 0.0:
            raise PhysicsViolationError("Mach number must be positive", requirement="Mach")
        exponent = (gamma + 1.0) / (2.0 * (gamma - 1.0))
        term = (2.0 / (gamma + 1.0)) * (1.0 + 0.5 * (gamma - 1.0) * mach**2)
        return (1.0 / mach) * term**exponent

    def area_ratio_to_mach(
        self,
        area_ratio: float,
        supersonic: bool = True,
        gamma: float = 1.4,
        tol: float = 1.0e-10,
    ) -> float:
        if area_ratio < 1.0:
            raise PhysicsViolationError(
                "Nozzle area ratio cannot be below one for isentropic throat reference",
                requirement="area ratio",
                actual=area_ratio,
                limit=1.0,
            )
        if abs(area_ratio - 1.0) < tol:
            return 1.0

        def residual(mach: float) -> float:
            return self.mach_to_area_ratio(mach, gamma) - area_ratio

        if supersonic:
            lo, hi = 1.0 + 1.0e-9, 2.0
            while residual(hi) < 0.0:
                hi *= 1.8
                if hi > 100.0:
                    raise PhysicsViolationError("Failed to bracket supersonic Mach solution")
        else:
            lo, hi = 1.0e-8, 1.0 - 1.0e-9

        for _ in range(200):
            mid = 0.5 * (lo + hi)
            value = residual(mid)
            if abs(value) < tol:
                return mid
            if supersonic:
                if value < 0.0:
                    lo = mid
                else:
                    hi = mid
            else:
                if value > 0.0:
                    lo = mid
                else:
                    hi = mid
        return 0.5 * (lo + hi)

    def pressure_ratio_from_mach(self, mach: float, gamma: float = 1.4) -> float:
        return (1.0 + 0.5 * (gamma - 1.0) * mach**2) ** (-gamma / (gamma - 1.0))

    def throat_area(self, thrust_N: float, chamber_pressure_bar: float, Cf: float) -> float:
        if thrust_N <= 0.0 or chamber_pressure_bar <= 0.0 or Cf <= 0.0:
            raise PhysicsViolationError("Thrust, chamber pressure, and Cf must be positive")
        chamber_pressure_Pa = chamber_pressure_bar * 1.0e5
        return thrust_N / (Cf * chamber_pressure_Pa)

    def thrust_coefficient(
        self,
        gamma: float,
        expansion_ratio: float,
        ambient_pressure_bar: float,
        chamber_pressure_bar: float = 50.0,
    ) -> float:
        if gamma <= 1.0:
            raise PhysicsViolationError("Specific heat ratio must exceed one", requirement="gamma")
        if expansion_ratio < 1.0:
            raise PhysicsViolationError("Expansion ratio must be at least one")
        exit_mach = self.area_ratio_to_mach(expansion_ratio, supersonic=True, gamma=gamma)
        pe_pc = self.pressure_ratio_from_mach(exit_mach, gamma)
        pa_pc = ambient_pressure_bar / chamber_pressure_bar
        momentum = math.sqrt(
            (2.0 * gamma**2 / (gamma - 1.0))
            * (2.0 / (gamma + 1.0)) ** ((gamma + 1.0) / (gamma - 1.0))
            * (1.0 - pe_pc ** ((gamma - 1.0) / gamma))
        )
        pressure = (pe_pc - pa_pc) * expansion_ratio
        return momentum + pressure

    def mass_flow_rate(self, throat_area_m2: float, chamber_pressure_bar: float, c_star_m_s: float) -> float:
        if throat_area_m2 <= 0.0 or chamber_pressure_bar <= 0.0 or c_star_m_s <= 0.0:
            raise PhysicsViolationError("Throat area, chamber pressure, and c-star must be positive")
        return chamber_pressure_bar * 1.0e5 * throat_area_m2 / c_star_m_s

