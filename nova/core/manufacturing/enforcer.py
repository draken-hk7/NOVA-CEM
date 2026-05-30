"""Design-for-manufacturing enforcement."""

from __future__ import annotations

from typing import Any

from nova.core.geometry_engine.primitives import MeshSolid
from nova.core.knowledge_engine.rules import PROCESS_RULES, get_material_properties, normalize_material
from nova.core.types import ManufacturingAnalysis, ManufacturingWarning


class ManufacturabilityEnforcer:
    def __init__(self, process: str, material: str):
        if process not in PROCESS_RULES:
            raise ValueError(f"Unsupported manufacturing process: {process}")
        self.process = process
        self.material = normalize_material(material)
        self.rules = PROCESS_RULES[process]
        self.material_properties = get_material_properties(self.material)
        self.analysis = ManufacturingAnalysis(process=process, material=self.material, build_volume_mm3=0.0, material_kg=0.0, estimated_print_time_hours=0.0)

    def enforce_min_wall(self, solid: MeshSolid) -> MeshSolid:
        result = solid.copy(name=solid.name)
        min_wall = float(result.metadata.get("min_wall_thickness_mm", self.rules.MIN_WALL_THICKNESS_MM))
        if min_wall < self.rules.MIN_WALL_THICKNESS_MM:
            result.metadata["min_wall_thickness_mm"] = self.rules.MIN_WALL_THICKNESS_MM
            result.metadata.setdefault("manufacturing_adjustments", []).append(
                f"min wall raised from {min_wall:.3f} mm to {self.rules.MIN_WALL_THICKNESS_MM:.3f} mm"
            )
        return result

    def enforce_max_overhang(self, solid: MeshSolid, build_direction: tuple[float, float, float] = (0.0, 0.0, 1.0)) -> MeshSolid:
        result = solid.copy(name=solid.name)
        overhang = float(result.metadata.get("max_overhang_angle_deg", 0.0))
        if overhang > self.rules.MAX_OVERHANG_ANGLE_DEG:
            result.metadata["support_structures_required"] = True
        result.metadata["build_direction"] = build_direction
        return result

    def add_support_structures(self, solid: MeshSolid) -> MeshSolid:
        result = solid.copy(name=solid.name)
        if result.metadata.get("support_structures_required"):
            result.metadata.setdefault("manufacturing_adjustments", []).append("support structures added for overhang control")
        return result

    def enforce_min_channel_size(self, solid: MeshSolid) -> MeshSolid:
        result = solid.copy(name=solid.name)
        channel = float(result.metadata.get("min_channel_diameter_mm", self.rules.MIN_CHANNEL_DIAMETER_MM))
        if channel < self.rules.MIN_CHANNEL_DIAMETER_MM:
            result.metadata["min_channel_diameter_mm"] = self.rules.MIN_CHANNEL_DIAMETER_MM
            result.metadata.setdefault("manufacturing_adjustments", []).append(
                f"min channel raised from {channel:.3f} mm to {self.rules.MIN_CHANNEL_DIAMETER_MM:.3f} mm"
            )
        return result

    def compute_build_volume(self, solid: MeshSolid) -> float:
        lo, hi = solid.bounds_mm
        dims = hi - lo
        return float(dims[0] * dims[1] * dims[2])

    def estimate_print_time_hours(self, solid: MeshSolid) -> float:
        volume_cm3 = solid.volume_mm3 / 1000.0
        process_rate_cm3_h = {
            "lpbf": 7.0,
            "ebm": 12.0,
            "directed_energy": 30.0,
            "machined": 50.0,
        }.get(self.process, 8.0)
        return max(volume_cm3 / process_rate_cm3_h, 0.05)

    def estimate_material_kg(self, solid: MeshSolid) -> float:
        return solid.volume_mm3 * 1.0e-9 * self.material_properties["density_kg_m3"]

    def validate(self, solid: MeshSolid) -> list[ManufacturingWarning]:
        return self.rules.validate_geometry(solid)

    def enforce_all(self, solid: MeshSolid) -> MeshSolid:
        result = self.enforce_min_wall(solid)
        result = self.enforce_min_channel_size(result)
        result = self.enforce_max_overhang(result)
        result = self.add_support_structures(result)
        result.metadata["density_kg_m3"] = self.material_properties["density_kg_m3"]
        warnings = self.validate(result)
        self.analysis = ManufacturingAnalysis(
            process=self.process,
            material=self.material,
            build_volume_mm3=self.compute_build_volume(result),
            material_kg=self.estimate_material_kg(result),
            estimated_print_time_hours=self.estimate_print_time_hours(result),
            warnings=warnings,
            passed=not any(warning.severity == "error" for warning in warnings),
        )
        return result

    def enforce(self, solid: MeshSolid) -> MeshSolid:
        return self.enforce_all(solid)

