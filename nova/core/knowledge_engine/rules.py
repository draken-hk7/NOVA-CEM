"""Executable deterministic engineering rules for NOVA."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from nova.core.types import ManufacturingWarning


MATERIAL_ALIASES = {
    "inconel": "inconel718",
}


MATERIAL_PROPERTIES: dict[str, dict[str, Any]] = {
    "copper": {
        "yield_strength_mpa": 210.0,
        "thermal_conductivity_W_mK": 400.0,
        "max_service_temp_K": 900.0,
        "density_kg_m3": 8960.0,
        "compatible_processes": ["lpbf", "machined"],
    },
    "inconel718": {
        "yield_strength_mpa": 1100.0,
        "thermal_conductivity_W_mK": 11.4,
        "max_service_temp_K": 1300.0,
        "density_kg_m3": 8190.0,
        "compatible_processes": ["lpbf", "ebm", "directed_energy", "machined"],
    },
    "titanium": {
        "yield_strength_mpa": 880.0,
        "thermal_conductivity_W_mK": 6.7,
        "max_service_temp_K": 870.0,
        "density_kg_m3": 4430.0,
        "compatible_processes": ["lpbf", "ebm", "machined"],
    },
    "steel": {
        "yield_strength_mpa": 520.0,
        "thermal_conductivity_W_mK": 16.0,
        "max_service_temp_K": 1050.0,
        "density_kg_m3": 7850.0,
        "compatible_processes": ["lpbf", "directed_energy", "machined"],
    },
}


def normalize_material(material: str) -> str:
    return MATERIAL_ALIASES.get(material, material)


def get_material_properties(material: str) -> dict[str, Any]:
    key = normalize_material(material)
    if key not in MATERIAL_PROPERTIES:
        raise KeyError(f"Unknown material: {material}")
    return MATERIAL_PROPERTIES[key]


def _metadata(geo: Any) -> dict[str, Any]:
    if hasattr(geo, "metadata"):
        return getattr(geo, "metadata") or {}
    if hasattr(geo, "solid") and hasattr(geo.solid, "metadata"):
        return geo.solid.metadata or {}
    return {}


class LPBFRules:
    MIN_WALL_THICKNESS_MM = 0.4
    MIN_CHANNEL_DIAMETER_MM = 0.5
    MAX_OVERHANG_ANGLE_DEG = 45.0
    MAX_UNSUPPORTED_SPAN_MM = 2.0
    LAYER_THICKNESS_MM = 0.04

    @staticmethod
    def validate_geometry(geo: Any) -> list[ManufacturingWarning]:
        meta = _metadata(geo)
        warnings: list[ManufacturingWarning] = []
        min_wall = float(meta.get("min_wall_thickness_mm", LPBFRules.MIN_WALL_THICKNESS_MM))
        if min_wall < LPBFRules.MIN_WALL_THICKNESS_MM:
            warnings.append(
                ManufacturingWarning(
                    "LPBF_MIN_WALL",
                    f"Wall thickness {min_wall:.3f} mm is below LPBF minimum.",
                    "error",
                    "wall",
                )
            )
        channel_dia = float(meta.get("min_channel_diameter_mm", LPBFRules.MIN_CHANNEL_DIAMETER_MM))
        if channel_dia < LPBFRules.MIN_CHANNEL_DIAMETER_MM:
            warnings.append(
                ManufacturingWarning(
                    "LPBF_MIN_CHANNEL",
                    f"Channel diameter {channel_dia:.3f} mm is below LPBF minimum.",
                    "error",
                    "cooling_channel",
                )
            )
        overhang = float(meta.get("max_overhang_angle_deg", 0.0))
        if overhang > LPBFRules.MAX_OVERHANG_ANGLE_DEG:
            warnings.append(
                ManufacturingWarning(
                    "LPBF_OVERHANG",
                    f"Overhang angle {overhang:.1f} deg exceeds self-supporting LPBF limit.",
                    "warning",
                    "outer_contour",
                )
            )
        span = float(meta.get("max_unsupported_span_mm", 0.0))
        if span > LPBFRules.MAX_UNSUPPORTED_SPAN_MM:
            warnings.append(
                ManufacturingWarning(
                    "LPBF_SPAN",
                    f"Unsupported span {span:.2f} mm exceeds LPBF rule.",
                    "warning",
                    "span",
                )
            )
        return warnings


class EBMRules(LPBFRules):
    MIN_WALL_THICKNESS_MM = 0.7
    MIN_CHANNEL_DIAMETER_MM = 0.8
    LAYER_THICKNESS_MM = 0.07


class DirectedEnergyRules(LPBFRules):
    MIN_WALL_THICKNESS_MM = 1.2
    MIN_CHANNEL_DIAMETER_MM = 1.5
    LAYER_THICKNESS_MM = 0.25


class MachinedRules(LPBFRules):
    MIN_WALL_THICKNESS_MM = 0.8
    MIN_CHANNEL_DIAMETER_MM = 1.0
    MAX_OVERHANG_ANGLE_DEG = 90.0
    LAYER_THICKNESS_MM = 0.1


PROCESS_RULES = {
    "lpbf": LPBFRules,
    "ebm": EBMRules,
    "directed_energy": DirectedEnergyRules,
    "machined": MachinedRules,
}


class RocketHeuristics:
    """Empirical rocket sizing heuristics used before detailed simulation."""

    @staticmethod
    def injector_element_count(thrust_N: float, chamber_pressure_bar: float) -> int:
        per_element_thrust = 120.0 * math.sqrt(max(chamber_pressure_bar, 1.0) / 30.0)
        count = max(1, int(math.ceil(thrust_N / per_element_thrust)))
        if count > 1 and count % 2 == 0:
            count += 1
        return min(count, 4095)

    @staticmethod
    def cooling_channel_pitch_mm(heat_flux_MW_m2: float) -> float:
        heat_flux = max(heat_flux_MW_m2, 0.1)
        return float(np.clip(3.2 - 0.28 * math.log(heat_flux), 0.8, 4.0))

    @staticmethod
    def chamber_contraction_ratio(thrust_N: float) -> float:
        if thrust_N < 1_000.0:
            return 6.0
        if thrust_N < 20_000.0:
            return 4.5
        return 3.5

    @staticmethod
    def rao_nozzle_contour(
        throat_radius_mm: float,
        expansion_ratio: float,
        n_points: int = 200,
    ) -> np.ndarray:
        """Return a Rao-style parabolic nozzle contour as columns z_mm, r_mm."""

        if throat_radius_mm <= 0.0:
            raise ValueError("throat_radius_mm must be positive")
        if expansion_ratio <= 1.0:
            raise ValueError("expansion_ratio must exceed 1")
        exit_radius = throat_radius_mm * math.sqrt(expansion_ratio)
        half_angle_deg = 15.0 if expansion_ratio <= 25.0 else 12.0
        conical_length = (exit_radius - throat_radius_mm) / math.tan(math.radians(half_angle_deg))
        length = 0.8 * conical_length
        x = np.linspace(0.0, 1.0, n_points)
        start_slope = math.tan(math.radians(30.0))
        end_slope = math.tan(math.radians(half_angle_deg * 0.45))
        h00 = 2 * x**3 - 3 * x**2 + 1
        h10 = x**3 - 2 * x**2 + x
        h01 = -2 * x**3 + 3 * x**2
        h11 = x**3 - x**2
        z = x * length
        r = (
            h00 * throat_radius_mm
            + h10 * length * start_slope
            + h01 * exit_radius
            + h11 * length * end_slope
        )
        r = np.maximum.accumulate(r)
        r[-1] = exit_radius
        return np.column_stack([z, r])

