"""Heat exchanger geometry builders."""

from __future__ import annotations

import math

from nova.core.geometry_engine.primitives import GeometryBuilder, MeshSolid, _cq


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
        heat_transfer_area_m2: float | None = None,
    ) -> MeshSolid:
        x, y, z = bounds
        wall_mm = max(2.0, thickness_mm)
        channel_dia_mm = max(1.4, min(2.0, wall_mm * 0.8))
        pitch_mm = channel_dia_mm + wall_mm
        margin_mm = wall_mm + channel_dia_mm / 2.0
        hot_y = self._centered_positions(y, margin_mm, pitch_mm)
        cold_x = self._centered_positions(x, margin_mm, pitch_mm)
        z_layers = self._centered_positions(z, margin_mm, pitch_mm)
        hot_z = z_layers[::2]
        cold_z = z_layers[1::2]
        cq = _cq()
        core = cq.Workplane("XY").box(x, y, z)
        cut_tools = []
        overcut_mm = 2.0
        for z_pos in hot_z:
            for y_pos in hot_y:
                cut_tools.append(
                    cq.Solid.makeCylinder(
                        channel_dia_mm / 2.0,
                        x + 2.0 * overcut_mm,
                        pnt=(-x / 2.0 - overcut_mm, y_pos, z_pos),
                        dir=(1.0, 0.0, 0.0),
                    )
                )
        for z_pos in cold_z:
            for x_pos in cold_x:
                cut_tools.append(
                    cq.Solid.makeCylinder(
                        channel_dia_mm / 2.0,
                        y + 2.0 * overcut_mm,
                        pnt=(x_pos, -y / 2.0 - overcut_mm, z_pos),
                        dir=(0.0, 1.0, 0.0),
                    )
                )
        if cut_tools:
            core = core.cut(cq.Workplane("XY").add(cq.Compound.makeCompound(cut_tools)))
        core = self._add_industrial_features(core, bounds)
        result = MeshSolid(core, "gyroid_crossflow_heat_exchanger")
        result.metadata.update(
            {
                "architecture": "gyroid",
                "geometry_type": "gyroid_crossflow_microchannel_fallback",
                "bounds_mm": bounds,
                "resolution": resolution,
                "heat_transfer_area_m2": heat_transfer_area_m2,
                "min_wall_thickness_mm": wall_mm,
                "min_channel_diameter_mm": channel_dia_mm,
                "hot_flow_region": {"axis": "X", "channel_count": len(hot_z) * len(hot_y)},
                "cold_flow_region": {"axis": "Y", "channel_count": len(cold_z) * len(cold_x)},
                "channel_pitch_mm": pitch_mm,
                "manifold_headers": {
                    "hot_inlet": {
                        "face": "-X",
                        "stub_diameter_mm": 15.0,
                        "stub_length_mm": 20.0,
                        "flow_axis": "X",
                    },
                    "hot_outlet": {
                        "face": "+X",
                        "stub_diameter_mm": 15.0,
                        "stub_length_mm": 20.0,
                        "flow_axis": "X",
                    },
                    "cold_inlet": {
                        "face": "-Y",
                        "stub_diameter_mm": 15.0,
                        "stub_length_mm": 20.0,
                        "flow_axis": "Y",
                    },
                    "cold_outlet": {
                        "face": "+Y",
                        "stub_diameter_mm": 15.0,
                        "stub_length_mm": 20.0,
                        "flow_axis": "Y",
                    },
                },
                "mounting_brackets": {
                    "count": 2,
                    "type": "L-shaped side flange",
                    "bolt_hole_count": 4,
                    "bolt_hole_diameter_mm": 5.0,
                },
                "tpms_note": "CadQuery fallback: dense cross-flow microchannel core with separated hot/cold passages.",
            }
        )
        return result

    def _add_industrial_features(self, core, bounds: tuple[float, float, float]):
        x, y, z = bounds
        cq = _cq()
        header_depth_mm = 6.0
        header_overlap_mm = 1.0
        stub_dia_mm = 15.0
        stub_radius_mm = stub_dia_mm / 2.0
        stub_length_mm = 20.0
        stub_overlap_mm = 2.0
        header_z_span = max(24.0, z * 0.72)
        header_y_span = max(24.0, y * 0.82)
        header_x_span = max(24.0, x * 0.82)
        hot_stub_z = min(z * 0.24, z / 2.0 - stub_radius_mm - 1.0)
        cold_stub_z = -hot_stub_z

        components = []
        for sign in (-1.0, 1.0):
            x_center = sign * (x / 2.0 + header_depth_mm / 2.0 - header_overlap_mm)
            components.append(cq.Workplane("XY").box(header_depth_mm, header_y_span, header_z_span).translate((x_center, 0.0, 0.0)))
            pipe_start_x = sign * (x / 2.0 + header_depth_mm - stub_overlap_mm)
            components.append(
                cq.Workplane("XY").add(
                    cq.Solid.makeCylinder(
                        stub_radius_mm,
                        stub_length_mm + stub_overlap_mm,
                        pnt=(pipe_start_x, 0.0, hot_stub_z),
                        dir=(sign, 0.0, 0.0),
                    )
                )
            )

            y_center = sign * (y / 2.0 + header_depth_mm / 2.0 - header_overlap_mm)
            components.append(cq.Workplane("XY").box(header_x_span, header_depth_mm, header_z_span).translate((0.0, y_center, 0.0)))
            pipe_start_y = sign * (y / 2.0 + header_depth_mm - stub_overlap_mm)
            components.append(
                cq.Workplane("XY").add(
                    cq.Solid.makeCylinder(
                        stub_radius_mm,
                        stub_length_mm + stub_overlap_mm,
                        pnt=(0.0, pipe_start_y, cold_stub_z),
                        dir=(0.0, sign, 0.0),
                    )
                )
            )
            components.append(self._mounting_bracket(sign, x, y, z, header_depth_mm))

        result = core
        for component in components:
            result = result.union(component)
        return result

    def _mounting_bracket(self, side_sign: float, x: float, y: float, z: float, header_depth_mm: float):
        cq = _cq()
        bracket_width_mm = min(34.0, max(24.0, x * 0.42))
        leg_depth_mm = 5.0
        leg_height_mm = 18.0
        foot_depth_mm = 18.0
        foot_thickness_mm = 5.0
        overlap_mm = 1.0
        bolt_dia_mm = 5.0
        side_y = side_sign * (y / 2.0 + header_depth_mm)
        leg = (
            cq.Workplane("XY")
            .box(bracket_width_mm, leg_depth_mm, leg_height_mm)
            .translate((0.0, side_y + side_sign * (leg_depth_mm / 2.0 - overlap_mm), -z / 2.0 + leg_height_mm / 2.0 - overlap_mm))
        )
        foot = (
            cq.Workplane("XY")
            .box(bracket_width_mm + 6.0, foot_depth_mm, foot_thickness_mm)
            .translate(
                (
                    0.0,
                    side_y + side_sign * (foot_depth_mm / 2.0 - overlap_mm),
                    -z / 2.0 - foot_thickness_mm / 2.0 + overlap_mm,
                )
            )
        )
        bracket = leg.union(foot)
        hole_y = side_y + side_sign * (foot_depth_mm * 0.55)
        hole_z_start = -z / 2.0 - foot_thickness_mm - 1.5
        holes = [
            cq.Solid.makeCylinder(
                bolt_dia_mm / 2.0,
                foot_thickness_mm + 4.0,
                pnt=(x_pos, hole_y, hole_z_start),
                dir=(0.0, 0.0, 1.0),
            )
            for x_pos in (-bracket_width_mm * 0.28, bracket_width_mm * 0.28)
        ]
        return bracket.cut(cq.Workplane("XY").add(cq.Compound.makeCompound(holes)))

    @staticmethod
    def _centered_positions(span_mm: float, margin_mm: float, pitch_mm: float) -> list[float]:
        usable = span_mm - 2.0 * margin_mm
        count = max(1, int(math.floor(usable / pitch_mm)) + 1)
        if count == 1:
            return [0.0]
        actual_pitch = usable / (count - 1)
        return [-usable / 2.0 + index * actual_pitch for index in range(count)]

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
