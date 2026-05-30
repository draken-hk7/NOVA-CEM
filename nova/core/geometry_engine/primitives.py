"""CadQuery-backed core geometry primitives and CSG operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from nova.core.types import MassProperties


def _cq() -> Any:
    """Load CadQuery lazily so non-geometry modules can still import cleanly."""

    try:
        import cadquery as cq
    except Exception as exc:  # pragma: no cover - depends on local CAD runtime.
        raise RuntimeError(
            "CadQuery geometry backend is required. Install cadquery 2.7.x with "
            "its OCP runtime before generating NOVA geometry."
        ) from exc
    return cq


def _workplane_from_shape(shape: Any) -> Any:
    return _cq().Workplane("XY").add(shape)


@dataclass
class MeshSolid:
    """CadQuery B-rep solid using millimetres as the native length unit.

    The class keeps NOVA's original `MeshSolid` name for API compatibility, but
    the backend is now a real CadQuery `cq.Workplane`. Mesh vertices/faces are
    produced only on demand for OBJ/3MF handoff.
    """

    workplane: Any
    name: str = "solid"
    metadata: dict = field(default_factory=dict)
    _mesh_cache: tuple[np.ndarray, np.ndarray] | None = field(default=None, init=False, repr=False)

    def copy(self, *, name: str | None = None) -> "MeshSolid":
        return MeshSolid(self.workplane, name or self.name, dict(self.metadata))

    @property
    def shape(self) -> Any:
        return self.workplane.val()

    @property
    def bounds_mm(self) -> tuple[np.ndarray, np.ndarray]:
        box = self.shape.BoundingBox()
        return np.array([box.xmin, box.ymin, box.zmin], dtype=float), np.array([box.xmax, box.ymax, box.zmax], dtype=float)

    @property
    def volume_mm3(self) -> float:
        return float(abs(self.shape.Volume()))

    @property
    def surface_area_mm2(self) -> float:
        return float(self.shape.Area())

    @property
    def mass_properties(self) -> MassProperties:
        return MassProperties(
            volume_mm3=self.volume_mm3,
            density_kg_m3=float(self.metadata.get("density_kg_m3", 1000.0)),
        )

    @property
    def is_watertight(self) -> bool:
        shape = self.shape
        is_valid = bool(shape.isValid()) if hasattr(shape, "isValid") else True
        return is_valid and len(shape.Solids()) > 0

    @property
    def is_manifold(self) -> bool:
        return self.is_watertight

    @property
    def vertices(self) -> np.ndarray:
        return self._tessellated()[0]

    @property
    def faces(self) -> np.ndarray:
        return self._tessellated()[1]

    def transformed(self, translation: tuple[float, float, float]) -> "MeshSolid":
        return MeshSolid(self.workplane.translate(translation), self.name, dict(self.metadata))

    def export_stl(self, path: str | Path, *, tolerance: float = 0.05, angular_tolerance: float = 0.1) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _cq().exporters.export(
            self.workplane,
            str(path),
            exportType="STL",
            tolerance=tolerance,
            angularTolerance=angular_tolerance,
        )

    def export_step(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _cq().exporters.export(self.workplane, str(path), exportType="STEP")

    def export_obj(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        vertices, faces = self._tessellated()
        with path.open("w", encoding="ascii") as handle:
            handle.write(f"o {self.name}\n")
            for vertex in vertices:
                handle.write(f"v {vertex[0]:.9e} {vertex[1]:.9e} {vertex[2]:.9e}\n")
            for face in faces:
                a, b, c = face + 1
                handle.write(f"f {a} {b} {c}\n")

    def to_dict(self) -> dict:
        lo, hi = self.bounds_mm
        vertices, faces = self._tessellated()
        return {
            "name": self.name,
            "backend": "cadquery",
            "vertices": int(len(vertices)),
            "faces": int(len(faces)),
            "watertight": self.is_watertight,
            "bounds_mm": {"min": lo.tolist(), "max": hi.tolist()},
            "volume_mm3": self.volume_mm3,
            "surface_area_mm2": self.surface_area_mm2,
            "metadata": self.metadata,
        }

    def _tessellated(self, tolerance: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
        if self._mesh_cache is None:
            vertices, triangles = self.shape.tessellate(tolerance)
            self._mesh_cache = (
                np.asarray([[vertex.x, vertex.y, vertex.z] for vertex in vertices], dtype=float),
                np.asarray(triangles, dtype=int),
            )
        return self._mesh_cache


class GeometryBuilder:
    def cylinder(
        self,
        radius: float,
        height: float,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        segments: int = 96,
    ) -> MeshSolid:
        del segments
        if radius <= 0.0 or height <= 0.0:
            raise ValueError("Cylinder radius and height must be positive")
        wp = _cq().Workplane("XY").circle(radius).extrude(height).translate((center[0], center[1], center[2] - height / 2.0))
        return MeshSolid(wp, "cylinder", {"radius_mm": radius, "height_mm": height, "min_wall_thickness_mm": radius})

    def annular_cylinder(
        self,
        outer_radius: float,
        inner_radius: float,
        height: float,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> MeshSolid:
        if inner_radius <= 0.0 or outer_radius <= inner_radius or height <= 0.0:
            raise ValueError("Annular cylinder requires outer radius > inner radius > 0 and positive height")
        wp = (
            _cq()
            .Workplane("XY")
            .circle(outer_radius)
            .circle(inner_radius)
            .extrude(height)
            .translate((center[0], center[1], center[2] - height / 2.0))
        )
        return MeshSolid(
            wp,
            "annular_cylinder",
            {
                "outer_radius_mm": outer_radius,
                "inner_radius_mm": inner_radius,
                "height_mm": height,
                "min_wall_thickness_mm": outer_radius - inner_radius,
            },
        )

    def cone_frustum(
        self,
        r1: float,
        r2: float,
        height: float,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        segments: int = 96,
    ) -> MeshSolid:
        del segments
        if r1 <= 0.0 or r2 <= 0.0 or height <= 0.0:
            raise ValueError("Frustum radii and height must be positive")
        cq = _cq()
        shape = cq.Solid.makeCone(r1, r2, height, pnt=(0.0, 0.0, -height / 2.0), dir=(0.0, 0.0, 1.0))
        wp = _workplane_from_shape(shape).translate(center)
        return MeshSolid(wp, "cone_frustum", {"height_mm": height, "min_wall_thickness_mm": min(r1, r2)})

    def torus(
        self,
        major_r: float,
        minor_r: float,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        major_segments: int = 96,
        minor_segments: int = 24,
    ) -> MeshSolid:
        del major_segments, minor_segments
        if major_r <= 0.0 or minor_r <= 0.0:
            raise ValueError("Torus radii must be positive")
        cq = _cq()
        shape = cq.Solid.makeTorus(major_r, minor_r, pnt=(0.0, 0.0, 0.0), dir=(0.0, 0.0, 1.0))
        return MeshSolid(_workplane_from_shape(shape).translate(center), "torus", {"major_radius_mm": major_r, "minor_radius_mm": minor_r})

    def box(
        self,
        width: float,
        depth: float,
        height: float,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> MeshSolid:
        if width <= 0.0 or depth <= 0.0 or height <= 0.0:
            raise ValueError("Box dimensions must be positive")
        wp = _cq().Workplane("XY").box(width, depth, height).translate(center)
        return MeshSolid(wp, "box", {"width_mm": width, "depth_mm": depth, "height_mm": height})

    def revolved_shell(
        self,
        inner_profile_zr: np.ndarray,
        outer_profile_zr: np.ndarray,
        segments: int = 128,
        name: str = "revolved_shell",
    ) -> MeshSolid:
        del segments
        inner = np.asarray(inner_profile_zr, dtype=float)
        outer = np.asarray(outer_profile_zr, dtype=float)
        if inner.shape != outer.shape or inner.ndim != 2 or inner.shape[1] != 2:
            raise ValueError("Inner and outer profiles must be Nx2 arrays of z,r")
        if np.any(inner[:, 1] <= 0.0) or np.any(outer[:, 1] <= inner[:, 1]):
            raise ValueError("Profile radii must be positive and outer radius must exceed inner radius")

        cq = _cq()
        profile_points = [(float(r), float(z)) for z, r in outer]
        profile_points.extend((float(r), float(z)) for z, r in inner[::-1])
        wp = (
            cq.Workplane("XZ")
            .polyline(profile_points)
            .close()
            .revolve(360.0, axisStart=(0.0, 0.0), axisEnd=(0.0, 1.0))
        )
        thickness = float(np.min(outer[:, 1] - inner[:, 1]))
        return MeshSolid(
            wp,
            name,
            {
                "backend": "cadquery",
                "min_wall_thickness_mm": thickness,
                "min_radius_mm": float(np.min(inner[:, 1])),
                "max_radius_mm": float(np.max(outer[:, 1])),
                "length_mm": float(np.max(inner[:, 0]) - np.min(inner[:, 0])),
            },
        )

    def helical_tube(
        self,
        radius_mm: float,
        pitch_mm: float,
        height_mm: float,
        tube_diameter_mm: float,
        start_z: float = 0.0,
        lefthand: bool = False,
    ) -> MeshSolid:
        if min(radius_mm, pitch_mm, height_mm, tube_diameter_mm) <= 0.0:
            raise ValueError("Helical tube radius, pitch, height, and tube diameter must be positive")
        cq = _cq()
        path = cq.Wire.makeHelix(
            pitch=pitch_mm,
            height=height_mm,
            radius=radius_mm,
            center=(0.0, 0.0, start_z),
            dir=(0.0, 0.0, 1.0),
            lefthand=lefthand,
        )
        profile = cq.Workplane("XZ").center(radius_mm, start_z).circle(tube_diameter_mm / 2.0)
        wp = profile.sweep(path, isFrenet=True)
        return MeshSolid(
            wp,
            "helical_tube",
            {
                "helix_radius_mm": radius_mm,
                "pitch_mm": pitch_mm,
                "height_mm": height_mm,
                "tube_diameter_mm": tube_diameter_mm,
            },
        )

    def cut_helical_channels(
        self,
        solid: MeshSolid,
        n_channels: int,
        channel_diameter_mm: float,
        helix_radius_mm: float,
        pitch_mm: float,
        start_z: float,
        end_z: float,
    ) -> MeshSolid:
        if n_channels <= 0:
            raise ValueError("n_channels must be positive")
        height = end_z - start_z
        tool = self.helical_tube(helix_radius_mm, pitch_mm, height, channel_diameter_mm, start_z=start_z)
        cq = _cq()
        tools = [
            tool.workplane.rotate((0.0, 0.0, start_z), (0.0, 0.0, start_z + 1.0), 360.0 * i / n_channels).val()
            for i in range(n_channels)
        ]
        compound = cq.Compound.makeCompound(tools)
        cut = solid.workplane.cut(cq.Workplane("XY").add(compound))
        result = MeshSolid(cut, solid.name, dict(solid.metadata))
        result.metadata["n_cooling_channels_cut"] = n_channels
        result.metadata["channel_cut_diameter_mm"] = channel_diameter_mm
        result.metadata["helix_radius_mm"] = helix_radius_mm
        return result

    def cut_through_holes_z(
        self,
        solid: MeshSolid,
        points_xy: Iterable[tuple[float, float]],
        diameter_mm: float,
        depth_mm: float | None = None,
    ) -> MeshSolid:
        points = list(points_xy)
        if not points:
            return solid.copy()
        if diameter_mm <= 0.0:
            raise ValueError("Hole diameter must be positive")
        lo, hi = solid.bounds_mm
        depth = depth_mm or float((hi[2] - lo[2]) * 1.5)
        wp = solid.workplane.faces(">Z").workplane().pushPoints(points).hole(diameter_mm, depth)
        result = MeshSolid(wp, solid.name, dict(solid.metadata))
        result.metadata.setdefault("through_holes", []).append({"count": len(points), "diameter_mm": diameter_mm})
        return result

    def boolean_subtract(self, base: MeshSolid, tool: MeshSolid) -> MeshSolid:
        result = MeshSolid(base.workplane.cut(tool.workplane), f"{base.name}_minus_{tool.name}", dict(base.metadata))
        result.metadata.setdefault("subtracted_tools", []).append(tool.to_dict())
        return result

    def boolean_union(self, *solids: MeshSolid) -> MeshSolid:
        if not solids:
            raise ValueError("At least one solid is required for union")
        result_wp = solids[0].workplane
        metadata: dict = {}
        for solid in solids:
            metadata.update(solid.metadata)
        for solid in solids[1:]:
            result_wp = result_wp.union(solid.workplane)
        metadata["components"] = [solid.name for solid in solids]
        return MeshSolid(result_wp, "union", metadata)

    def shell(self, solid: MeshSolid, thickness_mm: float) -> MeshSolid:
        if thickness_mm <= 0.0:
            raise ValueError("Shell thickness must be positive")
        result = MeshSolid(solid.workplane.faces(">Z").shell(thickness_mm), f"{solid.name}_shell", dict(solid.metadata))
        result.metadata["min_wall_thickness_mm"] = thickness_mm
        result.metadata["shell_operation"] = "cadquery-shell"
        return result

    def fillet_edges(self, solid: MeshSolid, radius: float) -> MeshSolid:
        if radius <= 0.0:
            raise ValueError("Fillet radius must be positive")
        result = MeshSolid(solid.workplane.edges().fillet(radius), f"{solid.name}_filleted", dict(solid.metadata))
        result.metadata["fillet_radius_mm"] = radius
        return result

    def combine(self, solids: Iterable[MeshSolid]) -> MeshSolid:
        return self.boolean_union(*list(solids))
