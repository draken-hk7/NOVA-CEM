"""Pressure-vessel and thermal stress calculations."""

from __future__ import annotations

from typing import Any

from nova.core.exceptions import PhysicsViolationError
from nova.core.knowledge_engine.rules import get_material_properties
from nova.core.types import StructuralResult


class StructuralSolver:
    def hoop_stress(self, pressure_bar: float, radius_mm: float, wall_thickness_mm: float) -> float:
        if pressure_bar <= 0.0 or radius_mm <= 0.0 or wall_thickness_mm <= 0.0:
            raise PhysicsViolationError("Pressure, radius, and wall thickness must be positive")
        pressure_MPa = pressure_bar * 0.1
        return pressure_MPa * radius_mm / wall_thickness_mm

    def thermal_stress(self, delta_T: float, E: float, alpha: float, nu: float) -> float:
        if E <= 0.0 or alpha < 0.0 or not (0.0 <= nu < 0.5):
            raise PhysicsViolationError("Invalid thermoelastic properties")
        return E * alpha * delta_T / (1.0 - nu)

    def factor_of_safety(self, applied_stress: float, yield_strength: float) -> float:
        if applied_stress < 0.0 or yield_strength <= 0.0:
            raise PhysicsViolationError("Stress values must be non-negative and yield must be positive")
        if applied_stress == 0.0:
            return float("inf")
        return yield_strength / applied_stress

    def validate_chamber(self, nozzle_geo: Any, spec: Any, combustion: Any) -> StructuralResult:
        meta = getattr(nozzle_geo.solid, "metadata", {})
        chamber_radius_mm = float(meta.get("chamber_radius_mm", meta.get("max_radius_mm", 1.0)))
        wall_thickness_mm = float(meta.get("min_wall_thickness_mm", 1.0))
        material = get_material_properties(spec.material)
        hoop = self.hoop_stress(spec.chamber_pressure_bar, chamber_radius_mm, wall_thickness_mm)

        elastic_modulus_MPa = {
            "copper": 117_000.0,
            "inconel": 205_000.0,
            "inconel718": 205_000.0,
            "titanium": 114_000.0,
            "steel": 200_000.0,
        }.get(spec.material, 150_000.0)
        alpha = {
            "copper": 16.5e-6,
            "inconel": 13.0e-6,
            "inconel718": 13.0e-6,
            "titanium": 8.6e-6,
            "steel": 12.0e-6,
        }.get(spec.material, 12.0e-6)
        delta_T = max(combustion.T_c - 650.0, 0.0) * 0.0025
        thermal = self.thermal_stress(delta_T, elastic_modulus_MPa, alpha, 0.31)
        combined = hoop + thermal
        fos = self.factor_of_safety(combined, material["yield_strength_mpa"])
        return StructuralResult(
            hoop_stress_MPa=hoop,
            thermal_stress_MPa=thermal,
            combined_stress_MPa=combined,
            factor_of_safety=fos,
            max_allowable_stress_MPa=material["yield_strength_mpa"],
            passed=fos >= spec.safety_factor,
        )
