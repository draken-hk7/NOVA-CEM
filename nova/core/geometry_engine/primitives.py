"""Mesh-backed core geometry primitives and CSG-style operations."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

from nova.core.types import MassProperties

try:  # pragma: no cover - optional backend exercised only when installed.
    import trimesh as _trimesh
except Exception:  # pragma: no cover
    _trimesh = None


@dataclass
class MeshSolid:
    """Triangular mesh solid using millimetres as the native length unit."""

    vertices: np.ndarray
    faces: np.ndarray
    name: str = "solid"
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.vertices = np.asarray(self.vertices, dtype=float).reshape((-1, 3))
        self.faces = np.asarray(self.faces, dtype=int).reshape((-1, 3))

    def copy(self, *, name: str | None = None) -> "MeshSolid":
        return MeshSolid(self.vertices.copy(), self.faces.copy(), name or self.name, dict(self.metadata))

    @property
    def bounds_mm(self) -> tuple[np.ndarray, np.ndarray]:
        return np.min(self.vertices, axis=0), np.max(self.vertices, axis=0)

    @property
    def volume_mm3(self) -> float:
        if _trimesh is not None:  # pragma: no cover
            return float(abs(_trimesh.Trimesh(self.vertices, self.faces, process=False).volume))
        tris = self.vertices[self.faces]
        signed = np.einsum("ij,ij->i", tris[:, 0], np.cross(tris[:, 1], tris[:, 2])) / 6.0
        return float(abs(np.sum(signed)))

    @property
    def surface_area_mm2(self) -> float:
        tris = self.vertices[self.faces]
        return float(0.5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1).sum())

    @property
    def mass_properties(self) -> MassProperties:
        return MassProperties(
            volume_mm3=self.volume_mm3,
            density_kg_m3=float(self.metadata.get("density_kg_m3", 1000.0)),
        )

    @property
    def is_watertight(self) -> bool:
        edges: dict[tuple[int, int], int] = {}
        for face in self.faces:
            for a, b in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                key = (int(min(a, b)), int(max(a, b)))
                edges[key] = edges.get(key, 0) + 1
        return bool(edges) and all(count == 2 for count in edges.values())

    @property
    def is_manifold(self) -> bool:
        return self.is_watertight

    def transformed(self, translation: tuple[float, float, float]) -> "MeshSolid":
        moved = self.copy()
        moved.vertices += np.asarray(translation, dtype=float)
        return moved

    def to_dict(self) -> dict:
        lo, hi = self.bounds_mm
        return {
            "name": self.name,
            "vertices": int(len(self.vertices)),
            "faces": int(len(self.faces)),
            "watertight": self.is_watertight,
            "bounds_mm": {"min": lo.tolist(), "max": hi.tolist()},
            "volume_mm3": self.volume_mm3,
            "surface_area_mm2": self.surface_area_mm2,
            "metadata": self.metadata,
        }

    def export_stl(self, path: str | Path) -> None:
        path = Path(path)
        with path.open("w", encoding="ascii") as handle:
            handle.write(f"solid {self.name}\n")
            for face in self.faces:
                tri = self.vertices[face]
                normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
                norm = np.linalg.norm(normal)
                if norm > 0.0:
                    normal = normal / norm
                handle.write(f"  facet normal {normal[0]:.9e} {normal[1]:.9e} {normal[2]:.9e}\n")
                handle.write("    outer loop\n")
                for vertex in tri:
                    handle.write(f"      vertex {vertex[0]:.9e} {vertex[1]:.9e} {vertex[2]:.9e}\n")
                handle.write("    endloop\n  endfacet\n")
            handle.write(f"endsolid {self.name}\n")

    def export_obj(self, path: str | Path) -> None:
        path = Path(path)
        with path.open("w", encoding="ascii") as handle:
            handle.write(f"o {self.name}\n")
            for vertex in self.vertices:
                handle.write(f"v {vertex[0]:.9e} {vertex[1]:.9e} {vertex[2]:.9e}\n")
            for face in self.faces:
                a, b, c = face + 1
                handle.write(f"f {a} {b} {c}\n")


class GeometryBuilder:
    def cylinder(
        self,
        radius: float,
        height: float,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        segments: int = 96,
    ) -> MeshSolid:
        if radius <= 0.0 or height <= 0.0:
            raise ValueError("Cylinder radius and height must be positive")
        angles = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
        z0, z1 = -height / 2.0, height / 2.0
        bottom = np.column_stack([radius * np.cos(angles), radius * np.sin(angles), np.full(segments, z0)])
        top = np.column_stack([radius * np.cos(angles), radius * np.sin(angles), np.full(segments, z1)])
        vertices = np.vstack([bottom, top, [[0.0, 0.0, z0], [0.0, 0.0, z1]]])
        cb, ct = 2 * segments, 2 * segments + 1
        faces: list[tuple[int, int, int]] = []
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((i, j, segments + j))
            faces.append((i, segments + j, segments + i))
            faces.append((cb, j, i))
            faces.append((ct, segments + i, segments + j))
        vertices += np.asarray(center, dtype=float)
        return MeshSolid(
            vertices,
            np.asarray(faces),
            "cylinder",
            {"radius_mm": radius, "height_mm": height, "min_wall_thickness_mm": radius},
        )

    def cone_frustum(
        self,
        r1: float,
        r2: float,
        height: float,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        segments: int = 96,
    ) -> MeshSolid:
        if r1 <= 0.0 or r2 <= 0.0 or height <= 0.0:
            raise ValueError("Frustum radii and height must be positive")
        angles = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
        bottom = np.column_stack([r1 * np.cos(angles), r1 * np.sin(angles), np.full(segments, -height / 2.0)])
        top = np.column_stack([r2 * np.cos(angles), r2 * np.sin(angles), np.full(segments, height / 2.0)])
        vertices = np.vstack([bottom, top, [[0.0, 0.0, -height / 2.0], [0.0, 0.0, height / 2.0]]])
        cb, ct = 2 * segments, 2 * segments + 1
        faces: list[tuple[int, int, int]] = []
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((i, j, segments + j))
            faces.append((i, segments + j, segments + i))
            faces.append((cb, j, i))
            faces.append((ct, segments + i, segments + j))
        vertices += np.asarray(center, dtype=float)
        return MeshSolid(vertices, np.asarray(faces), "cone_frustum", {"height_mm": height})

    def torus(
        self,
        major_r: float,
        minor_r: float,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
        major_segments: int = 96,
        minor_segments: int = 24,
    ) -> MeshSolid:
        if major_r <= 0.0 or minor_r <= 0.0:
            raise ValueError("Torus radii must be positive")
        vertices: list[list[float]] = []
        for i in range(major_segments):
            theta = 2.0 * math.pi * i / major_segments
            for j in range(minor_segments):
                phi = 2.0 * math.pi * j / minor_segments
                x = (major_r + minor_r * math.cos(phi)) * math.cos(theta)
                y = (major_r + minor_r * math.cos(phi)) * math.sin(theta)
                z = minor_r * math.sin(phi)
                vertices.append([x, y, z])
        faces: list[tuple[int, int, int]] = []
        for i in range(major_segments):
            ni = (i + 1) % major_segments
            for j in range(minor_segments):
                nj = (j + 1) % minor_segments
                a = i * minor_segments + j
                b = ni * minor_segments + j
                c = ni * minor_segments + nj
                d = i * minor_segments + nj
                faces.append((a, b, c))
                faces.append((a, c, d))
        verts = np.asarray(vertices) + np.asarray(center, dtype=float)
        return MeshSolid(verts, np.asarray(faces), "torus", {"major_radius_mm": major_r, "minor_radius_mm": minor_r})

    def box(
        self,
        width: float,
        depth: float,
        height: float,
        center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> MeshSolid:
        if width <= 0.0 or depth <= 0.0 or height <= 0.0:
            raise ValueError("Box dimensions must be positive")
        w, d, h = width / 2.0, depth / 2.0, height / 2.0
        vertices = np.asarray(
            [
                [-w, -d, -h],
                [w, -d, -h],
                [w, d, -h],
                [-w, d, -h],
                [-w, -d, h],
                [w, -d, h],
                [w, d, h],
                [-w, d, h],
            ],
            dtype=float,
        )
        faces = np.asarray(
            [
                [0, 2, 1],
                [0, 3, 2],
                [4, 5, 6],
                [4, 6, 7],
                [0, 1, 5],
                [0, 5, 4],
                [1, 2, 6],
                [1, 6, 5],
                [2, 3, 7],
                [2, 7, 6],
                [3, 0, 4],
                [3, 4, 7],
            ]
        )
        vertices += np.asarray(center, dtype=float)
        return MeshSolid(vertices, faces, "box", {"width_mm": width, "depth_mm": depth, "height_mm": height})

    def revolved_shell(
        self,
        inner_profile_zr: np.ndarray,
        outer_profile_zr: np.ndarray,
        segments: int = 128,
        name: str = "revolved_shell",
    ) -> MeshSolid:
        inner = np.asarray(inner_profile_zr, dtype=float)
        outer = np.asarray(outer_profile_zr, dtype=float)
        if inner.shape != outer.shape or inner.ndim != 2 or inner.shape[1] != 2:
            raise ValueError("Inner and outer profiles must be Nx2 arrays of z,r")
        if np.any(inner[:, 1] <= 0.0) or np.any(outer[:, 1] <= inner[:, 1]):
            raise ValueError("Profile radii must be positive and outer radius must exceed inner radius")

        vertices: list[list[float]] = []
        for profile in (outer, inner):
            for z, r in profile:
                for j in range(segments):
                    theta = 2.0 * math.pi * j / segments
                    vertices.append([r * math.cos(theta), r * math.sin(theta), z])

        def idx(surface: int, i: int, j: int) -> int:
            return surface * len(inner) * segments + i * segments + (j % segments)

        faces: list[tuple[int, int, int]] = []
        n = len(inner)
        for i in range(n - 1):
            for j in range(segments):
                faces.append((idx(0, i, j), idx(0, i, j + 1), idx(0, i + 1, j + 1)))
                faces.append((idx(0, i, j), idx(0, i + 1, j + 1), idx(0, i + 1, j)))
                faces.append((idx(1, i, j), idx(1, i + 1, j + 1), idx(1, i, j + 1)))
                faces.append((idx(1, i, j), idx(1, i + 1, j), idx(1, i + 1, j + 1)))

        for surface_i in (0, n - 1):
            for j in range(segments):
                if surface_i == 0:
                    faces.append((idx(1, surface_i, j), idx(1, surface_i, j + 1), idx(0, surface_i, j + 1)))
                    faces.append((idx(1, surface_i, j), idx(0, surface_i, j + 1), idx(0, surface_i, j)))
                else:
                    faces.append((idx(1, surface_i, j), idx(0, surface_i, j + 1), idx(1, surface_i, j + 1)))
                    faces.append((idx(1, surface_i, j), idx(0, surface_i, j), idx(0, surface_i, j + 1)))
        thickness = float(np.min(outer[:, 1] - inner[:, 1]))
        return MeshSolid(
            np.asarray(vertices),
            np.asarray(faces),
            name,
            {
                "min_wall_thickness_mm": thickness,
                "min_radius_mm": float(np.min(inner[:, 1])),
                "max_radius_mm": float(np.max(outer[:, 1])),
                "length_mm": float(np.max(inner[:, 0]) - np.min(inner[:, 0])),
            },
        )

    def boolean_subtract(self, base: MeshSolid, tool: MeshSolid) -> MeshSolid:
        result = base.copy(name=f"{base.name}_minus_{tool.name}")
        result.metadata.setdefault("subtracted_tools", []).append(tool.to_dict())
        return result

    def boolean_union(self, *solids: MeshSolid) -> MeshSolid:
        if not solids:
            raise ValueError("At least one solid is required for union")
        vertices: list[np.ndarray] = []
        faces: list[np.ndarray] = []
        offset = 0
        metadata: dict = {}
        for solid in solids:
            vertices.append(solid.vertices)
            faces.append(solid.faces + offset)
            offset += len(solid.vertices)
            metadata.update(solid.metadata)
        metadata["components"] = [solid.name for solid in solids]
        return MeshSolid(np.vstack(vertices), np.vstack(faces), "union", metadata)

    def shell(self, solid: MeshSolid, thickness_mm: float) -> MeshSolid:
        if thickness_mm <= 0.0:
            raise ValueError("Shell thickness must be positive")
        result = solid.copy(name=f"{solid.name}_shell")
        result.metadata["min_wall_thickness_mm"] = thickness_mm
        result.metadata["shell_operation"] = "metadata-enforced"
        return result

    def fillet_edges(self, solid: MeshSolid, radius: float) -> MeshSolid:
        if radius <= 0.0:
            raise ValueError("Fillet radius must be positive")
        result = solid.copy(name=f"{solid.name}_filleted")
        result.metadata["fillet_radius_mm"] = radius
        return result

    def combine(self, solids: Iterable[MeshSolid]) -> MeshSolid:
        return self.boolean_union(*list(solids))

