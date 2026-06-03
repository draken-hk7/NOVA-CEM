"""Electromagnetic actuator sizing primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from nova.core.exceptions import PhysicsViolationError

MU0 = 4.0 * math.pi * 1.0e-7


@dataclass(slots=True)
class SolenoidSizingResult:
    coil_turns: int
    wire_gauge: str
    current_draw_A: float
    coil_resistance_ohm: float
    magnetic_flux_Wb: float
    flux_density_T: float
    inductance_H: float
    power_consumption_W: float
    heat_dissipation_W: float
    response_time_ms: float
    force_output_N: float
    dimensions_mm: dict[str, float]


class EMSolver:
    WIRE_GAUGES = [
        {"gauge": "AWG18", "ohm_per_m": 0.02095, "current_A": 14.0},
        {"gauge": "AWG20", "ohm_per_m": 0.0333, "current_A": 10.0},
        {"gauge": "AWG22", "ohm_per_m": 0.0529, "current_A": 7.0},
        {"gauge": "AWG24", "ohm_per_m": 0.0842, "current_A": 5.0},
        {"gauge": "AWG26", "ohm_per_m": 0.1339, "current_A": 3.5},
    ]

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

    def inductance(self, coil_turns: int, area_m2: float, magnetic_path_m: float, relative_permeability: float = 900.0) -> float:
        if coil_turns <= 0 or area_m2 <= 0.0 or magnetic_path_m <= 0.0:
            raise PhysicsViolationError("Inductance inputs must be positive")
        return MU0 * relative_permeability * coil_turns**2 * area_m2 / magnetic_path_m

    def solenoid_actuator(
        self,
        *,
        force_N: float,
        stroke_mm: float,
        voltage_V: float = 24.0,
        response_time_ms: float = 50.0,
        max_temp_C: float = 120.0,
    ) -> SolenoidSizingResult:
        if min(force_N, stroke_mm, voltage_V, response_time_ms) <= 0.0:
            raise PhysicsViolationError("Solenoid sizing inputs must be positive")
        core_radius_mm = max(6.0, min(24.0, 5.0 + 0.18 * math.sqrt(force_N) + 0.08 * stroke_mm))
        air_gap_m = stroke_mm * 1.0e-3
        core_area_m2 = math.pi * (core_radius_mm * 1.0e-3) ** 2
        target_flux_density_T = min(1.45, math.sqrt(2.0 * MU0 * force_N / core_area_m2))
        required_amp_turns = target_flux_density_T * air_gap_m / (MU0 * 0.82)
        coil_radius_mm = core_radius_mm + 7.0
        coil_length_mm = max(22.0, stroke_mm * 2.4 + 18.0)
        magnetic_path_m = max(0.025, (coil_length_mm + 2.0 * core_radius_mm) * 1.0e-3)

        best: dict[str, float | int | str] | None = None
        for wire in self.WIRE_GAUGES:
            for turns in range(80, 2401, 20):
                mean_turn_length_m = 2.0 * math.pi * coil_radius_mm * 1.0e-3 * (1.0 + turns / 12000.0)
                resistance = wire["ohm_per_m"] * mean_turn_length_m * turns
                current = voltage_V / resistance
                if current > wire["current_A"] * 1.25:
                    continue
                amp_turns = turns * current
                if amp_turns < required_amp_turns:
                    continue
                equivalent_magnetic_path_m = air_gap_m + magnetic_path_m / 900.0
                inductance_H = self.inductance(turns, core_area_m2, equivalent_magnetic_path_m, relative_permeability=1.0)
                response_ms = 1000.0 * inductance_H / resistance
                if response_ms > response_time_ms:
                    continue
                power = voltage_V * current
                score = power + 0.012 * turns + 4.0 * response_ms
                if best is None or score < float(best["score"]):
                    best = {
                        "turns": turns,
                        "wire_gauge": wire["gauge"],
                        "current": current,
                        "resistance": resistance,
                        "inductance": inductance_H,
                        "response_ms": response_ms,
                        "score": score,
                    }

        if best is None:
            wire = self.WIRE_GAUGES[-1]
            turns = 2400
            mean_turn_length_m = 2.0 * math.pi * coil_radius_mm * 1.0e-3 * (1.0 + turns / 12000.0)
            resistance = wire["ohm_per_m"] * mean_turn_length_m * turns
            best = {
                "turns": turns,
                "wire_gauge": wire["gauge"],
                "current": voltage_V / resistance,
                "resistance": resistance,
                "inductance": self.inductance(
                    turns,
                    core_area_m2,
                    air_gap_m + magnetic_path_m / 900.0,
                    relative_permeability=1.0,
                ),
                "response_ms": 1000.0
                * self.inductance(turns, core_area_m2, air_gap_m + magnetic_path_m / 900.0, relative_permeability=1.0)
                / resistance,
            }

        turns = int(best["turns"])
        current = float(best["current"])
        resistance = float(best["resistance"])
        core_geometry = type(
            "SolenoidCoreGeometry",
            (),
            {
                "area_m2": core_area_m2,
                "gap_m": air_gap_m,
                "relative_permeability": 900.0 if max_temp_C < 650.0 else 420.0,
            },
        )()
        flux = self.magnetic_flux(turns, current, core_geometry)
        flux_density = flux / core_area_m2
        force_output = flux_density**2 * core_area_m2 / (2.0 * MU0)
        heat = self.copper_loss(resistance, current)
        outer_diameter_mm = 2.0 * (coil_radius_mm + 8.0)
        body_length_mm = coil_length_mm + stroke_mm + 26.0
        dimensions = {
            "outer_diameter_mm": outer_diameter_mm,
            "body_length_mm": body_length_mm,
            "core_diameter_mm": 2.0 * core_radius_mm,
            "coil_length_mm": coil_length_mm,
            "stroke_mm": stroke_mm,
        }
        return SolenoidSizingResult(
            coil_turns=turns,
            wire_gauge=str(best["wire_gauge"]),
            current_draw_A=current,
            coil_resistance_ohm=resistance,
            magnetic_flux_Wb=flux,
            flux_density_T=flux_density,
            inductance_H=float(best["inductance"]),
            power_consumption_W=voltage_V * current,
            heat_dissipation_W=heat,
            response_time_ms=float(best["response_ms"]),
            force_output_N=force_output,
            dimensions_mm=dimensions,
        )
