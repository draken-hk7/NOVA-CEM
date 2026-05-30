"""Heat exchanger geometry builders."""

from __future__ import annotations

import math

from nova.core.geometry_engine.primitives import GeometryBuilder, MeshSolid


class HeatExchangerGeometry:
    def __init__(self) -> None:
        self.builder = GeometryBuilder()

    def shell_and_tube(
        self,
        shell_dia_mm: float = 120.0,
        length_mm: float = 500.0,
        n_tubes: int = 19,
        tube_dia_mm: float = 8.0,
    ) -> MeshSolid:
        shell = self.builder.cylinder(shell_dia_mm / 2.0, length_mm, segments=96)
        pitch_radius = shell_dia_mm * 0.32
        tubes = []
        for i in range(n_tubes):
            angle = 2.0 * math.pi * i / max(n_tubes, 1)
            tube = self.builder.cylinder(
                tube_dia_mm / 2.0,
                length_mm * 1.02,
                center=(pitch_radius * math.cos(angle), pitch_radius * math.sin(angle), 0.0),
                segments=24,
            )
            tubes.append(tube)
        result = self.builder.boolean_union(shell, *tubes)
        result.name = "shell_and_tube_heat_exchanger"
        result.metadata.update(
            {
                "architecture": "shell_and_tube",
                "shell_dia_mm": shell_dia_mm,
                "length_mm": length_mm,
                "n_tubes": n_tubes,
                "tube_dia_mm": tube_dia_mm,
                "min_channel_diameter_mm": tube_dia_mm,
            }
        )
        return result

    def plate_fin(
        self,
        width_mm: float = 160.0,
        height_mm: float = 80.0,
        depth_mm: float = 300.0,
        n_fins: int = 24,
        fin_thickness_mm: float = 0.8,
    ) -> MeshSolid:
        plates = [self.builder.box(width_mm, fin_thickness_mm, depth_mm, center=(0.0, 0.0, 0.0))]
        spacing = height_mm / max(n_fins, 1)
        for i in range(n_fins):
            y = -height_mm / 2.0 + i * spacing
            plates.append(self.builder.box(width_mm, fin_thickness_mm, depth_mm, center=(0.0, y, 0.0)))
        result = self.builder.boolean_union(*plates)
        result.name = "plate_fin_heat_exchanger"
        result.metadata.update({"architecture": "plate_fin", "n_fins": n_fins, "min_wall_thickness_mm": fin_thickness_mm})
        return result

    def gyroid_minimal_surface(
        self,
        bounds: tuple[float, float, float] = (80.0, 80.0, 80.0),
        resolution: int = 24,
        thickness_mm: float = 1.0,
    ) -> MeshSolid:
        # First build uses a deterministic lattice envelope; an optional marching
        # cubes backend can replace this without changing the public interface.
        x, y, z = bounds
        struts = []
        for i in range(max(3, resolution // 6)):
            offset = -x / 2.0 + (i + 0.5) * x / max(3, resolution // 6)
            struts.append(self.builder.box(thickness_mm, y, thickness_mm, center=(offset, 0.0, 0.0)))
            struts.append(self.builder.box(x, thickness_mm, thickness_mm, center=(0.0, offset, 0.0)))
            struts.append(self.builder.box(thickness_mm, thickness_mm, z, center=(0.0, 0.0, offset)))
        result = self.builder.boolean_union(*struts)
        result.name = "gyroid_minimal_surface_proxy"
        result.metadata.update({"architecture": "gyroid", "bounds_mm": bounds, "resolution": resolution, "min_wall_thickness_mm": thickness_mm})
        return result

    def schwartz_P_surface(
        self,
        bounds: tuple[float, float, float] = (80.0, 80.0, 80.0),
        cell_size_mm: float = 20.0,
        thickness_mm: float = 1.0,
    ) -> MeshSolid:
        x, y, z = bounds
        cell = self.builder.box(cell_size_mm, cell_size_mm, thickness_mm)
        cells = []
        nx = max(1, int(x // cell_size_mm))
        ny = max(1, int(y // cell_size_mm))
        for ix in range(nx):
            for iy in range(ny):
                cells.append(cell.transformed((-x / 2 + ix * cell_size_mm, -y / 2 + iy * cell_size_mm, 0.0)))
        result = self.builder.boolean_union(*cells)
        result.name = "schwartz_p_surface_proxy"
        result.metadata.update({"architecture": "schwartz_p", "bounds_mm": bounds, "cell_size_mm": cell_size_mm, "min_wall_thickness_mm": thickness_mm})
        return result

