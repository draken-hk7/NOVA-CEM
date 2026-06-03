"""Propellant manifold geometry for rocket injector assemblies."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from nova.core.geometry_engine.primitives import GeometryBuilder, MeshSolid, _cq


OXIDIZER_PORT_DIAMETER_MM = 12.0
OXIDIZER_PORT_THREAD_SPEC = "M12x1.5 standard"
FUEL_PORT_DIAMETER_MM = 10.0
FUEL_PORT_THREAD_SPEC = "M10x1.25 standard"
MANIFOLD_FEED_COUNT = 8
BOOLEAN_OVERLAP_MM = 1.0


@dataclass(slots=True)
class PropellantManifoldResult:
    solid: MeshSolid
    metadata: dict


class PropellantManifoldGeometry:
    """Build and attach injector-side fuel and oxidizer manifolds."""

    def __init__(self) -> None:
        self.builder = GeometryBuilder()

    def attach_to_injector(
        self,
        injector: MeshSolid,
        *,
        injector_outer_radius_mm: float,
        injector_thickness_mm: float,
        element_positions_mm: list[list[float]] | np.ndarray,
        oxidizer_post_dia_mm: float,
        fuel_annulus_gap_mm: float,
    ) -> PropellantManifoldResult:
        if min(injector_outer_radius_mm, injector_thickness_mm, oxidizer_post_dia_mm, fuel_annulus_gap_mm) <= 0.0:
            raise ValueError("Injector manifold dimensions must be positive")

        cq = _cq()
        feed_targets = self._feed_targets(element_positions_mm, injector_outer_radius_mm)
        oxidizer_tube_radius = max(OXIDIZER_PORT_DIAMETER_MM * 0.34 + 0.8, min(5.8, max(3.2, injector_outer_radius_mm * 0.12)))
        oxidizer_major_radius = injector_outer_radius_mm + oxidizer_tube_radius * 0.25
        oxidizer_center_z = -injector_thickness_mm - oxidizer_tube_radius + BOOLEAN_OVERLAP_MM
        fuel_plenum_radius = max(
            oxidizer_post_dia_mm * 2.5,
            min(injector_outer_radius_mm * 0.54, self._max_target_radius(feed_targets) + fuel_annulus_gap_mm * 2.0),
        )
        fuel_plenum_height = max(4.5, injector_thickness_mm * 0.72)
        fuel_center_z = -injector_thickness_mm - fuel_plenum_height / 2.0 + BOOLEAN_OVERLAP_MM
        oxidizer_feed_diameter = max(1.0, min(oxidizer_post_dia_mm * 1.35, oxidizer_tube_radius * 0.78))
        fuel_feed_diameter = max(0.8, min(fuel_annulus_gap_mm * 2.2, fuel_plenum_radius * 0.26))

        oxidizer_ring = MeshSolid(
            cq.Workplane("XY").add(
                cq.Solid.makeTorus(
                    oxidizer_major_radius,
                    oxidizer_tube_radius,
                    pnt=(0.0, 0.0, oxidizer_center_z),
                    dir=(0.0, 0.0, 1.0),
                )
            ),
            "oxidizer_toroidal_manifold",
            {},
        )
        fuel_plenum = self.builder.cylinder(
            fuel_plenum_radius,
            fuel_plenum_height + BOOLEAN_OVERLAP_MM,
            center=(0.0, 0.0, fuel_center_z),
            segments=96,
        )
        fuel_plenum.name = "fuel_cylindrical_manifold"
        assembly = self.builder.boolean_union(injector, oxidizer_ring, fuel_plenum)

        for target in feed_targets:
            assembly = self.builder.boolean_subtract(
                assembly,
                self._oxidizer_feed_hole(
                    target=target,
                    outer_radius_mm=oxidizer_major_radius + oxidizer_tube_radius + BOOLEAN_OVERLAP_MM,
                    z_mm=max(oxidizer_center_z, -injector_thickness_mm * 0.58),
                    diameter_mm=oxidizer_feed_diameter,
                ),
            )
            assembly = self.builder.boolean_subtract(
                assembly,
                self._fuel_feed_passage(
                    target=target,
                    diameter_mm=fuel_feed_diameter,
                    z_min_mm=-injector_thickness_mm - fuel_plenum_height - BOOLEAN_OVERLAP_MM,
                    height_mm=injector_thickness_mm + fuel_plenum_height + 2.0 * BOOLEAN_OVERLAP_MM,
                ),
            )

        oxidizer_port_axis = (1.0, 0.0, 0.0)
        fuel_port_axis = (-1.0, 0.0, 0.0)
        oxidizer_outer_radius = oxidizer_major_radius + oxidizer_tube_radius
        assembly = self.builder.boolean_union(
            assembly,
            self._radial_cylinder(
                radius_mm=OXIDIZER_PORT_DIAMETER_MM / 2.0,
                length_mm=16.0 + BOOLEAN_OVERLAP_MM,
                start_radius_mm=oxidizer_outer_radius - BOOLEAN_OVERLAP_MM,
                direction=oxidizer_port_axis,
                z_mm=oxidizer_center_z,
                name="oxidizer_inlet_boss",
            ),
        )
        assembly = self.builder.boolean_subtract(
            assembly,
            self._radial_cylinder(
                radius_mm=OXIDIZER_PORT_DIAMETER_MM * 0.34,
                length_mm=oxidizer_tube_radius * 1.8 + 18.0,
                start_radius_mm=oxidizer_major_radius - oxidizer_tube_radius * 0.45,
                direction=oxidizer_port_axis,
                z_mm=oxidizer_center_z,
                name="oxidizer_inlet_bore",
            ),
        )
        fuel_boss_start = fuel_plenum_radius - BOOLEAN_OVERLAP_MM
        fuel_boss_length = oxidizer_outer_radius - fuel_plenum_radius + 14.0 + BOOLEAN_OVERLAP_MM
        assembly = self.builder.boolean_union(
            assembly,
            self._radial_cylinder(
                radius_mm=FUEL_PORT_DIAMETER_MM / 2.0,
                length_mm=fuel_boss_length,
                start_radius_mm=fuel_boss_start,
                direction=fuel_port_axis,
                z_mm=fuel_center_z,
                name="fuel_inlet_boss",
            ),
        )
        assembly = self.builder.boolean_subtract(
            assembly,
            self._radial_cylinder(
                radius_mm=FUEL_PORT_DIAMETER_MM * 0.32,
                length_mm=fuel_boss_length + 2.0,
                start_radius_mm=fuel_plenum_radius * 0.18,
                direction=fuel_port_axis,
                z_mm=fuel_center_z,
                name="fuel_inlet_bore",
            ),
        )

        flow_area_mm2 = MANIFOLD_FEED_COUNT * (
            math.pi * (oxidizer_feed_diameter / 2.0) ** 2 + math.pi * (fuel_feed_diameter / 2.0) ** 2
        )
        manifold_wall_thickness = min(
            oxidizer_tube_radius - OXIDIZER_PORT_DIAMETER_MM * 0.34,
            FUEL_PORT_DIAMETER_MM / 2.0 - FUEL_PORT_DIAMETER_MM * 0.32,
            max(0.6, fuel_annulus_gap_mm),
        )
        metadata = {
            "type": "dual_propellant_injector_manifold",
            "oxidizer_manifold": {
                "shape": "toroidal",
                "diameter_mm": 2.0 * oxidizer_major_radius,
                "tube_diameter_mm": 2.0 * oxidizer_tube_radius,
                "feed_hole_count": MANIFOLD_FEED_COUNT,
                "feed_hole_diameter_mm": oxidizer_feed_diameter,
                "feed_hole_flow_area_mm2": MANIFOLD_FEED_COUNT * math.pi * (oxidizer_feed_diameter / 2.0) ** 2,
            },
            "fuel_manifold": {
                "shape": "cylindrical",
                "diameter_mm": 2.0 * fuel_plenum_radius,
                "height_mm": fuel_plenum_height,
                "feed_passage_count": MANIFOLD_FEED_COUNT,
                "feed_passage_diameter_mm": fuel_feed_diameter,
                "feed_passage_flow_area_mm2": MANIFOLD_FEED_COUNT * math.pi * (fuel_feed_diameter / 2.0) ** 2,
            },
            "ports": {
                "oxidizer_inlet": {
                    "diameter_mm": OXIDIZER_PORT_DIAMETER_MM,
                    "thread_spec": OXIDIZER_PORT_THREAD_SPEC,
                    "position_mm": [oxidizer_outer_radius + 16.0, 0.0, oxidizer_center_z],
                },
                "fuel_inlet": {
                    "diameter_mm": FUEL_PORT_DIAMETER_MM,
                    "thread_spec": FUEL_PORT_THREAD_SPEC,
                    "position_mm": [-(oxidizer_outer_radius + 14.0), 0.0, fuel_center_z],
                },
            },
            "flow_area_mm2": flow_area_mm2,
            "min_wall_thickness_mm": manifold_wall_thickness,
            "required_min_wall_thickness_mm": 0.4,
            "feed_targets_mm": [[float(x), float(y)] for x, y in feed_targets],
        }
        self._require_single_valid_solid(assembly)
        assembly.name = injector.name
        assembly.metadata.update(injector.metadata)
        assembly.metadata["propellant_manifold"] = metadata
        assembly.metadata["manifold_diameter_mm"] = metadata["oxidizer_manifold"]["diameter_mm"]
        assembly.metadata["manifold_flow_area_mm2"] = flow_area_mm2
        assembly.metadata["manifold_wall_thickness_mm"] = manifold_wall_thickness
        assembly.metadata["manifold_min_wall_thickness_mm"] = metadata["required_min_wall_thickness_mm"]
        assembly.metadata["minimum_local_thickness_mm"] = min(
            float(assembly.metadata.get("minimum_local_thickness_mm", assembly.metadata.get("min_wall_thickness_mm", manifold_wall_thickness))),
            manifold_wall_thickness,
        )
        return PropellantManifoldResult(assembly, metadata)

    def _oxidizer_feed_hole(
        self,
        *,
        target: tuple[float, float],
        outer_radius_mm: float,
        z_mm: float,
        diameter_mm: float,
    ) -> MeshSolid:
        target_radius = max(math.hypot(target[0], target[1]), 1.0)
        direction = (target[0] / target_radius, target[1] / target_radius, 0.0)
        end = max(target_radius * 0.55, target_radius - diameter_mm)
        return self._radial_cylinder(
            radius_mm=diameter_mm / 2.0,
            length_mm=max(1.0, outer_radius_mm - end),
            start_radius_mm=end,
            direction=direction,
            z_mm=z_mm,
            name="oxidizer_radial_feed_hole",
        )

    @staticmethod
    def _fuel_feed_passage(
        *,
        target: tuple[float, float],
        diameter_mm: float,
        z_min_mm: float,
        height_mm: float,
    ) -> MeshSolid:
        cq = _cq()
        shape = cq.Solid.makeCylinder(
            diameter_mm / 2.0,
            height_mm,
            pnt=(target[0], target[1], z_min_mm),
            dir=(0.0, 0.0, 1.0),
        )
        return MeshSolid(cq.Workplane("XY").add(shape), "fuel_feed_passage", {"diameter_mm": diameter_mm})

    @staticmethod
    def _radial_cylinder(
        *,
        radius_mm: float,
        length_mm: float,
        start_radius_mm: float,
        direction: tuple[float, float, float],
        z_mm: float,
        name: str,
    ) -> MeshSolid:
        cq = _cq()
        start = (direction[0] * start_radius_mm, direction[1] * start_radius_mm, z_mm)
        shape = cq.Solid.makeCylinder(radius_mm, length_mm, pnt=start, dir=direction)
        return MeshSolid(cq.Workplane("XY").add(shape), name, {"radius_mm": radius_mm, "height_mm": length_mm})

    @staticmethod
    def _feed_targets(
        element_positions_mm: list[list[float]] | np.ndarray,
        injector_outer_radius_mm: float,
    ) -> list[tuple[float, float]]:
        positions = np.asarray(element_positions_mm, dtype=float)
        if positions.size == 0:
            positions = np.empty((0, 2), dtype=float)
        positions = positions.reshape((-1, 2))
        radial_positions = [tuple(row) for row in positions if math.hypot(float(row[0]), float(row[1])) > 1.0e-6]
        if len(radial_positions) < MANIFOLD_FEED_COUNT:
            radius = injector_outer_radius_mm * 0.42
            return [
                (radius * math.cos(2.0 * math.pi * i / MANIFOLD_FEED_COUNT), radius * math.sin(2.0 * math.pi * i / MANIFOLD_FEED_COUNT))
                for i in range(MANIFOLD_FEED_COUNT)
            ]

        targets: list[tuple[float, float]] = []
        used: set[int] = set()
        for i in range(MANIFOLD_FEED_COUNT):
            target_angle = 2.0 * math.pi * i / MANIFOLD_FEED_COUNT
            best_index = min(
                (index for index in range(len(radial_positions)) if index not in used),
                key=lambda index: _angle_delta(math.atan2(radial_positions[index][1], radial_positions[index][0]), target_angle),
            )
            used.add(best_index)
            targets.append(radial_positions[best_index])
        return [(float(x), float(y)) for x, y in targets]

    @staticmethod
    def _max_target_radius(targets: list[tuple[float, float]]) -> float:
        return max((math.hypot(x, y) for x, y in targets), default=0.0)

    @staticmethod
    def _require_single_valid_solid(solid: MeshSolid) -> None:
        shape = solid.shape
        if not shape.isValid() or len(shape.Solids()) != 1:
            raise ValueError("Propellant manifold failed to produce one valid watertight injector solid")


def _angle_delta(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2.0 * math.pi) - math.pi)
