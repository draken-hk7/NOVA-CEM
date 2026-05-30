"""Electromagnetic actuator sizing primitives."""

from __future__ import annotations

import math
from typing import Any

from nova.core.exceptions import PhysicsViolationError

MU0 = 4.0 * math.pi * 1.0e-7


class EMSolver:
    def magnetic_flux(self, coil_turns: int, current_A: float, core_geometry: Any) -> float:
        if coil_turns <= 0 or current_A < 0.0:
            raise PhysicsViolationError("Coil turns must be positive and current non-negative")
        area_m2 = float(getattr(core_geometry, "area_m2", 1.0e-4))
        gap_m = float(getattr(core_geometry, "gap_m", 1.0e-3))
        relative_permeability = float(getattr(core_geometry, "relative_permeability", 1000.0))
        reluctance = gap_m / (MU0 * area_m2) + 0.05 / (MU0 * relative_permeability * area_m2)
        return coil_turns * current_A / reluctance

    def back_emf(self, Kv: float, rpm: float) -> float:
        if Kv <= 0.0 or rpm < 0.0:
            raise PhysicsViolationError("Kv must be positive and rpm non-negative")
        return rpm / Kv

    def copper_loss(self, resistance_ohm: float, current_A: float) -> float:
        if resistance_ohm < 0.0 or current_A < 0.0:
            raise PhysicsViolationError("Resistance and current must be non-negative")
        return resistance_ohm * current_A**2

