"""Heat-exchanger fluid-dynamics and thermal design formulae."""

from __future__ import annotations

import math
from typing import Any

from nova.core.exceptions import PhysicsViolationError


class HeatExchangerSolver:
    def NTU_effectiveness(self, NTU: float, Cr: float, flow_arrangement: str) -> float:
        if NTU < 0.0 or not (0.0 <= Cr <= 1.0):
            raise PhysicsViolationError("NTU must be non-negative and Cr in [0, 1]")
        if flow_arrangement == "parallel":
            return (1.0 - math.exp(-NTU * (1.0 + Cr))) / (1.0 + Cr)
        if flow_arrangement == "counterflow":
            if abs(1.0 - Cr) < 1.0e-12:
                return NTU / (1.0 + NTU)
            return (1.0 - math.exp(-NTU * (1.0 - Cr))) / (1.0 - Cr * math.exp(-NTU * (1.0 - Cr)))
        if flow_arrangement == "crossflow":
            return 1.0 - math.exp((math.exp(-Cr * NTU) - 1.0) / max(Cr, 1.0e-12))
        raise PhysicsViolationError(f"Unsupported flow arrangement: {flow_arrangement}")

    def pressure_drop_channel(self, geometry: Any, fluid: Any, flow_rate: float) -> float:
        if flow_rate <= 0.0:
            raise PhysicsViolationError("Flow rate must be positive")
        diameter_m = float(getattr(geometry, "hydraulic_diameter_mm", 1.0)) * 1.0e-3
        length_m = float(getattr(geometry, "length_mm", 100.0)) * 1.0e-3
        area_m2 = float(getattr(geometry, "channel_area_mm2", 1.0)) * 1.0e-6
        density = float(getattr(fluid, "density_kg_m3", 997.0))
        viscosity = float(getattr(fluid, "viscosity_Pa_s", 8.9e-4))
        velocity = flow_rate / (density * area_m2)
        reynolds = density * velocity * diameter_m / viscosity
        friction = 64.0 / reynolds if reynolds < 2300.0 else 0.3164 / reynolds**0.25
        return friction * (length_m / diameter_m) * 0.5 * density * velocity**2 / 1.0e5

    def LMTD(
        self,
        T_h_in: float,
        T_h_out: float,
        T_c_in: float,
        T_c_out: float,
        flow_type: str,
    ) -> float:
        if flow_type == "counterflow":
            delta_1 = T_h_in - T_c_out
            delta_2 = T_h_out - T_c_in
        elif flow_type == "parallel":
            delta_1 = T_h_in - T_c_in
            delta_2 = T_h_out - T_c_out
        else:
            raise PhysicsViolationError(f"Unsupported LMTD flow type: {flow_type}")
        if delta_1 <= 0.0 or delta_2 <= 0.0:
            raise PhysicsViolationError("Terminal temperature differences must be positive")
        if abs(delta_1 - delta_2) < 1.0e-12:
            return delta_1
        return (delta_1 - delta_2) / math.log(delta_1 / delta_2)

