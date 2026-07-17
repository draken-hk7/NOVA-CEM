"""Geometry and performance artifact exporters."""

from __future__ import annotations

import math
import textwrap
import zipfile
from pathlib import Path
from typing import Any

from nova.core.geometry_engine.primitives import MeshSolid
from nova.core.manufacturing import validate_for_stl_export
from nova.core.output.thermal_map import ThermalMapData, ThermalMapGenerator
from nova.core.types import CEMRunResult, to_jsonable


CFD_PATCH_IDS = {
    "inlet": 1,
    "outlet": 2,
    "wall": 3,
    "cooling_inlet": 4,
    "cooling_outlet": 5,
    "internal_flow": 6,
}
MM_TO_M = 0.001


class GeometryExporter:
    def to_stl(
        self,
        solid: MeshSolid,
        path: str,
        binary: bool = True,
        *,
        tolerance: float | None = None,
        angular_tolerance: float | None = None,
    ) -> None:
        del binary
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs = {}
        if tolerance is not None:
            kwargs["tolerance"] = tolerance
        if angular_tolerance is not None:
            kwargs["angular_tolerance"] = angular_tolerance
        validate_for_stl_export(solid)
        solid.export_stl(path, **kwargs)

    def to_step(self, solid: MeshSolid, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        solid.export_step(path)

    def to_obj(self, solid: MeshSolid, path: str, *, tolerance: float | None = None) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs = {}
        if tolerance is not None:
            kwargs["tolerance"] = tolerance
        solid.export_obj(path, **kwargs)

    def to_3mf(self, solid: MeshSolid, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        vertices = "\n".join(f'<vertex x="{x:.9g}" y="{y:.9g}" z="{z:.9g}"/>' for x, y, z in solid.vertices)
        triangles = "\n".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in solid.faces)
        model = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model">
      <mesh><vertices>{vertices}</vertices><triangles>{triangles}</triangles></mesh>
    </object>
  </resources>
  <build><item objectid="1"/></build>
</model>
"""
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
            archive.writestr("3D/3dmodel.model", model)

    def to_cfd_mesh(
        self,
        design: Any,
        path: str,
        *,
        boundary_conditions_path: str | None = None,
        axial_segments: int = 40,
        radial_layers: int = 5,
        theta_segments: int = 32,
    ) -> dict[str, str]:
        """Export the engine internal flow volume as a Gmsh .msh CFD mesh."""

        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        mesh = _build_internal_flow_mesh(
            design,
            axial_segments=max(4, axial_segments),
            radial_layers=max(2, radial_layers),
            theta_segments=max(8, theta_segments),
        )
        path_obj.write_text(_format_gmsh_mesh(mesh), encoding="ascii")
        bc_path = Path(boundary_conditions_path) if boundary_conditions_path else path_obj.with_name("boundary_conditions.txt")
        bc_path.parent.mkdir(parents=True, exist_ok=True)
        bc_path.write_text(_format_boundary_conditions(design, path_obj), encoding="ascii")
        return {"cfd_mesh": str(path_obj), "boundary_conditions": str(bc_path)}


def _build_internal_flow_mesh(
    design: Any,
    *,
    axial_segments: int,
    radial_layers: int,
    theta_segments: int,
) -> dict[str, Any]:
    nozzle = _nozzle_metadata(design)
    profile = _internal_radius_profile(nozzle, axial_segments + 1)
    nodes: list[tuple[float, float, float]] = []
    center_nodes: dict[int, int] = {}
    ring_nodes: dict[tuple[int, int, int], int] = {}

    for iz, (z_mm, radius_mm) in enumerate(profile):
        center_nodes[iz] = _add_node(nodes, 0.0, 0.0, z_mm)
        for radial_index in range(1, radial_layers + 1):
            radius = radius_mm * radial_index / radial_layers
            for theta_index in range(theta_segments):
                theta = 2.0 * math.pi * theta_index / theta_segments
                ring_nodes[(iz, radial_index, theta_index)] = _add_node(
                    nodes,
                    radius * math.cos(theta),
                    radius * math.sin(theta),
                    z_mm,
                )

    elements: list[dict[str, Any]] = []
    volume_group = CFD_PATCH_IDS["internal_flow"]
    for iz in range(axial_segments):
        for theta_index in range(theta_segments):
            next_theta = (theta_index + 1) % theta_segments
            elements.append(
                _element(
                    6,
                    volume_group,
                    volume_group,
                    [
                        center_nodes[iz],
                        ring_nodes[(iz, 1, theta_index)],
                        ring_nodes[(iz, 1, next_theta)],
                        center_nodes[iz + 1],
                        ring_nodes[(iz + 1, 1, theta_index)],
                        ring_nodes[(iz + 1, 1, next_theta)],
                    ],
                )
            )
            for radial_index in range(1, radial_layers):
                elements.append(
                    _element(
                        5,
                        volume_group,
                        volume_group,
                        [
                            ring_nodes[(iz, radial_index, theta_index)],
                            ring_nodes[(iz, radial_index, next_theta)],
                            ring_nodes[(iz, radial_index + 1, next_theta)],
                            ring_nodes[(iz, radial_index + 1, theta_index)],
                            ring_nodes[(iz + 1, radial_index, theta_index)],
                            ring_nodes[(iz + 1, radial_index, next_theta)],
                            ring_nodes[(iz + 1, radial_index + 1, next_theta)],
                            ring_nodes[(iz + 1, radial_index + 1, theta_index)],
                        ],
                    )
                )

    _add_cap_elements(elements, center_nodes, ring_nodes, 0, radial_layers, theta_segments, "inlet")
    _add_cap_elements(elements, center_nodes, ring_nodes, axial_segments, radial_layers, theta_segments, "outlet")
    cooling_targets = _cooling_patch_targets(nozzle, profile, theta_segments)
    for iz in range(axial_segments):
        for theta_index in range(theta_segments):
            next_theta = (theta_index + 1) % theta_segments
            patch_name = cooling_targets.get((iz, theta_index), "wall")
            patch_group = CFD_PATCH_IDS[patch_name]
            elements.append(
                _element(
                    3,
                    patch_group,
                    patch_group,
                    [
                        ring_nodes[(iz, radial_layers, theta_index)],
                        ring_nodes[(iz, radial_layers, next_theta)],
                        ring_nodes[(iz + 1, radial_layers, next_theta)],
                        ring_nodes[(iz + 1, radial_layers, theta_index)],
                    ],
                )
            )

    return {"nodes": nodes, "elements": elements}


def _nozzle_metadata(design: Any) -> dict[str, Any]:
    metadata = getattr(design, "metadata", {}) or {}
    if isinstance(metadata, dict) and isinstance(metadata.get("nozzle"), dict):
        return metadata["nozzle"]
    geometry = getattr(design, "geometry", None)
    geometry_metadata = getattr(geometry, "metadata", {}) or {}
    if isinstance(geometry_metadata, dict):
        return geometry_metadata
    return {}


def _internal_radius_profile(nozzle: dict[str, Any], n_stations: int) -> list[tuple[float, float]]:
    chamber_radius = _positive_float(nozzle.get("chamber_radius_mm"), 25.0)
    throat_radius = _positive_float(nozzle.get("throat_radius_mm"), max(1.0, chamber_radius * 0.42))
    exit_radius = _positive_float(nozzle.get("exit_radius_mm"), max(throat_radius, chamber_radius * 0.8))
    chamber_length = _positive_float(nozzle.get("chamber_length_mm"), 35.0)
    convergence_length = _positive_float(nozzle.get("convergence_length_mm"), max(5.0, chamber_radius - throat_radius))
    total_length = _positive_float(nozzle.get("total_length_mm"), chamber_length + convergence_length + max(10.0, exit_radius))
    throat_z = min(chamber_length + convergence_length, total_length)
    profile: list[tuple[float, float]] = []
    for index in range(n_stations):
        z = total_length * index / max(n_stations - 1, 1)
        if z <= chamber_length:
            radius = chamber_radius
        elif z <= throat_z:
            progress = (z - chamber_length) / max(convergence_length, 1.0e-9)
            radius = throat_radius + (chamber_radius - throat_radius) * 0.5 * (1.0 + math.cos(math.pi * progress))
        else:
            progress = (z - throat_z) / max(total_length - throat_z, 1.0e-9)
            radius = throat_radius + (exit_radius - throat_radius) * (1.0 - (1.0 - progress) ** 1.6)
        profile.append((z, max(radius, 0.2)))
    return profile


def _cooling_patch_targets(
    nozzle: dict[str, Any],
    profile: list[tuple[float, float]],
    theta_segments: int,
) -> dict[tuple[int, int], str]:
    ports = nozzle.get("coolant_ports", {}) if isinstance(nozzle, dict) else {}
    length = profile[-1][0] if profile else 1.0
    fallback = {
        "cooling_outlet": {"z_mm": length * 0.08, "axis": [1.0, 0.0, 0.0]},
        "cooling_inlet": {"z_mm": length * 0.85, "axis": [-1.0, 0.0, 0.0]},
    }
    port_map = {
        "cooling_inlet": ports.get("inlet", fallback["cooling_inlet"]) if isinstance(ports, dict) else fallback["cooling_inlet"],
        "cooling_outlet": ports.get("outlet", fallback["cooling_outlet"]) if isinstance(ports, dict) else fallback["cooling_outlet"],
    }
    targets: dict[tuple[int, int], str] = {}
    for patch_name, port in port_map.items():
        if not isinstance(port, dict):
            continue
        z_mm = _positive_float(port.get("z_mm"), fallback[patch_name]["z_mm"])
        axis = port.get("axis", fallback[patch_name]["axis"])
        theta = _axis_theta(axis)
        axial_index = _nearest_axial_face(profile, z_mm)
        theta_index = int(round(theta / (2.0 * math.pi) * theta_segments)) % theta_segments
        targets[(axial_index, theta_index)] = patch_name
    return targets


def _nearest_axial_face(profile: list[tuple[float, float]], z_mm: float) -> int:
    mids = [(profile[index][0] + profile[index + 1][0]) * 0.5 for index in range(len(profile) - 1)]
    if not mids:
        return 0
    return min(range(len(mids)), key=lambda index: abs(mids[index] - z_mm))


def _axis_theta(axis: Any) -> float:
    try:
        x = float(axis[0])
        y = float(axis[1])
    except (TypeError, ValueError, IndexError):
        x, y = 1.0, 0.0
    return math.atan2(y, x) % (2.0 * math.pi)


def _add_cap_elements(
    elements: list[dict[str, Any]],
    center_nodes: dict[int, int],
    ring_nodes: dict[tuple[int, int, int], int],
    iz: int,
    radial_layers: int,
    theta_segments: int,
    patch_name: str,
) -> None:
    patch_group = CFD_PATCH_IDS[patch_name]
    for theta_index in range(theta_segments):
        next_theta = (theta_index + 1) % theta_segments
        elements.append(
            _element(
                2,
                patch_group,
                patch_group,
                [center_nodes[iz], ring_nodes[(iz, 1, next_theta)], ring_nodes[(iz, 1, theta_index)]],
            )
        )
        for radial_index in range(1, radial_layers):
            elements.append(
                _element(
                    3,
                    patch_group,
                    patch_group,
                    [
                        ring_nodes[(iz, radial_index, theta_index)],
                        ring_nodes[(iz, radial_index + 1, theta_index)],
                        ring_nodes[(iz, radial_index + 1, next_theta)],
                        ring_nodes[(iz, radial_index, next_theta)],
                    ],
                )
            )


def _add_node(nodes: list[tuple[float, float, float]], x_mm: float, y_mm: float, z_mm: float) -> int:
    nodes.append((x_mm * MM_TO_M, y_mm * MM_TO_M, z_mm * MM_TO_M))
    return len(nodes)


def _element(element_type: int, physical_group: int, elementary_group: int, nodes: list[int]) -> dict[str, Any]:
    return {
        "type": element_type,
        "physical": physical_group,
        "elementary": elementary_group,
        "nodes": nodes,
    }


def _format_gmsh_mesh(mesh: dict[str, Any]) -> str:
    lines = [
        "$MeshFormat",
        "2.2 0 8",
        "$EndMeshFormat",
        "$PhysicalNames",
        str(len(CFD_PATCH_IDS)),
        '2 1 "inlet"',
        '2 2 "outlet"',
        '2 3 "wall"',
        '2 4 "cooling_inlet"',
        '2 5 "cooling_outlet"',
        '3 6 "internal_flow"',
        "$EndPhysicalNames",
        "$Nodes",
        str(len(mesh["nodes"])),
    ]
    for index, (x, y, z) in enumerate(mesh["nodes"], start=1):
        lines.append(f"{index} {x:.9e} {y:.9e} {z:.9e}")
    lines.extend(["$EndNodes", "$Elements", str(len(mesh["elements"]))])
    for index, element in enumerate(mesh["elements"], start=1):
        nodes = " ".join(str(node) for node in element["nodes"])
        lines.append(f"{index} {element['type']} 2 {element['physical']} {element['elementary']} {nodes}")
    lines.extend(["$EndElements", ""])
    return "\n".join(lines)


def _format_boundary_conditions(design: Any, mesh_path: Path) -> str:
    performance = getattr(design, "performance", None)
    thermal = getattr(design, "thermal", None)
    chamber_pressure_bar = _positive_float(getattr(performance, "chamber_pressure_bar", None), 1.0)
    inlet_pressure_pa = chamber_pressure_bar * 1.0e5
    outlet_pressure_pa = 101325.0
    wall_temperature_k = _positive_float(getattr(thermal, "max_wall_temperature_K", None), _positive_float(getattr(performance, "chamber_temp_K", None), 650.0) * 0.25)
    mass_flow_rate = _positive_float(getattr(performance, "mass_flow_rate_kg_s", None), 0.0)
    return "\n".join(
        [
            "NOVA CFD Boundary Conditions",
            f"mesh_file: {mesh_path.name}",
            "mesh_format: Gmsh 2.2 ASCII",
            "mesh_units: m",
            "",
            "inlet:",
            "  patch: inlet",
            "  suggested_type: totalPressure",
            f"  inlet_pressure_Pa: {inlet_pressure_pa:.3f}",
            f"  mass_flow_rate_kg_s: {mass_flow_rate:.6f}",
            "",
            "outlet:",
            "  patch: outlet",
            "  suggested_type: fixedPressure",
            f"  outlet_pressure_Pa: {outlet_pressure_pa:.3f}",
            "",
            "wall:",
            "  patch: wall",
            "  suggested_velocity: noSlip",
            "  suggested_thermal_type: fixedTemperature",
            f"  wall_temperature_K: {wall_temperature_k:.3f}",
            "",
            "cooling_inlet:",
            "  patch: cooling_inlet",
            "  suggested_type: coupledWall",
            "",
            "cooling_outlet:",
            "  patch: cooling_outlet",
            "  suggested_type: coupledWall",
            "",
        ]
    )


def _positive_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0.0 and math.isfinite(result) else default


class PerformanceReporter:
    def generate_pdf_report(self, run_result: CEMRunResult, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        thermal_map_data = self._generate_thermal_map(run_result, path)
        payload = self.generate_json_data(run_result)
        lines = [
            "NOVA Computational Engineering Model Report",
            f"Job ID: {run_result.job_id}",
            f"Module: {run_result.module}",
            "",
            "Performance Summary:",
        ]
        performance = payload.get("design", {}).get("performance", {})
        for key, value in performance.items():
            lines.append(f"  {key}: {value}")
        lines.extend(["", "Manufacturing Summary:"])
        manufacturing = payload.get("design", {}).get("manufacturing", {})
        for key, value in manufacturing.items():
            if key != "warnings":
                lines.append(f"  {key}: {value}")
        if run_result.module == "rocket-engine":
            lines.extend(
                [
                    "",
                    "Tolerance Analysis:",
                    "  Throat diameter: +/-0.05 mm",
                    "  Cooling channel width: +/-0.10 mm",
                    "  Wall thickness: +/-0.05 mm",
                    "  Flange bolt-hole position: +/-0.10 mm",
                ]
            )
            feed_budget = _rocket_metadata(payload).get("feed_pressure_budget", {})
            if feed_budget:
                lines.extend(
                    [
                        "",
                        "Propellant Feed Pressure Budget:",
                        f"  Chamber pressure: {feed_budget.get('chamber_pressure_bar')} bar",
                        f"  Injector drop (20%): {feed_budget.get('injector_drop_bar')} bar",
                        f"  Cooling channel drop: {feed_budget.get('cooling_channel_drop_bar')} bar",
                        f"  Line losses (5%): {feed_budget.get('line_losses_bar')} bar",
                        f"  Required tank pressure: {feed_budget.get('required_tank_pressure_bar')} bar",
                    ]
                )
        ports = _rocket_metadata(payload).get("nozzle", {}).get("coolant_ports", {})
        if ports:
            lines.extend(["", "Coolant Ports:"])
            for name, port in ports.items():
                position = port.get("position_mm", [])
                position_text = ", ".join(f"{float(value):.2f}" for value in position)
                lines.append(
                    f"  {name}: diameter {port.get('diameter_mm')} mm, bore {port.get('bore_diameter_mm')} mm, "
                    f"thread {port.get('thread_spec')}, position [{position_text}] mm"
                )
        manifold = _rocket_metadata(payload).get("manifold", {})
        if manifold:
            lines.extend(["", "Propellant Manifold:"])
            oxidizer = manifold.get("oxidizer_manifold", {})
            fuel = manifold.get("fuel_manifold", {})
            lines.append(
                f"  Oxidizer ring diameter: {oxidizer.get('diameter_mm')} mm, "
                f"{oxidizer.get('feed_hole_count')} radial feed holes"
            )
            lines.append(
                f"  Fuel manifold diameter: {fuel.get('diameter_mm')} mm, "
                f"{fuel.get('feed_passage_count')} feed passages"
            )
            ports = manifold.get("ports", {})
            for name, port in ports.items():
                lines.append(
                    f"  {name}: diameter {port.get('diameter_mm')} mm, "
                    f"thread {port.get('thread_spec')}"
                )
            lines.append(f"  Total feed flow area: {manifold.get('flow_area_mm2')} mm^2")
        validation = payload.get("design", {}).get("validation")
        if validation:
            lines.extend(["", "Structural Validation:"])
            for check in validation.get("checks", []):
                status = "PASS" if check.get("passed") else "WARNING"
                lines.append(f"  [{status}] {check.get('name')}: {check.get('message')}")
        if thermal_map_data is not None:
            lines.extend(["", "Thermal Map:", "  Embedded thermal map image: thermal_map.svg"])
        self._write_minimal_pdf(path, "\n".join(lines), thermal_map_data=thermal_map_data)

    def generate_json_data(self, run_result: CEMRunResult) -> dict:
        return to_jsonable(run_result)

    def generate_cfd_mesh(self, design: Any, path: str) -> None:
        GeometryExporter().to_cfd_mesh(design, path)

    def _generate_thermal_map(self, run_result: CEMRunResult, report_path: str) -> ThermalMapData | None:
        if run_result.module != "rocket-engine":
            return None
        thermal_path = Path(report_path).with_name("thermal_map.svg")
        data = ThermalMapGenerator().generate_svg(run_result, thermal_path)
        if data is not None:
            run_result.files["thermal_map"] = str(thermal_path)
        return data

    def _write_minimal_pdf(self, path: str, text: str, thermal_map_data: ThermalMapData | None = None) -> None:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        wrapped = []
        for line in escaped.splitlines():
            wrapped.extend(textwrap.wrap(line, width=92) or [""])
        content_lines = ["BT", "/F1 10 Tf", "50 780 Td"]
        for i, line in enumerate(wrapped[:68]):
            if i:
                content_lines.append("0 -12 Td")
            content_lines.append(f"({line}) Tj")
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("latin-1", errors="replace")
        objects = self._pdf_objects(stream, thermal_map_data)
        offsets = []
        output = bytearray(b"%PDF-1.4\n")
        for obj in objects:
            offsets.append(len(output))
            output.extend(obj)
        xref = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
        Path(path).write_bytes(output)

    def _pdf_objects(self, text_stream: bytes, thermal_map_data: ThermalMapData | None) -> list[bytes]:
        if thermal_map_data is None:
            return [
                b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
                b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
                b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
                b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
                f"5 0 obj << /Length {len(text_stream)} >> stream\n".encode("ascii") + text_stream + b"\nendstream endobj\n",
            ]
        map_stream = "\n".join(_thermal_map_pdf_commands(thermal_map_data)).encode("latin-1", errors="replace")
        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
            b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
            f"5 0 obj << /Length {len(text_stream)} >> stream\n".encode("ascii") + text_stream + b"\nendstream endobj\n",
            b"6 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 7 0 R >> endobj\n",
            f"7 0 obj << /Length {len(map_stream)} >> stream\n".encode("ascii") + map_stream + b"\nendstream endobj\n",
        ]
        return objects


def _rocket_metadata(payload: dict) -> dict:
    design = payload.get("design", {})
    metadata = design.get("metadata", {})
    if isinstance(metadata, dict) and metadata:
        return metadata
    geometry = design.get("geometry", {})
    geometry_metadata = geometry.get("metadata", {}) if isinstance(geometry, dict) else {}
    return geometry_metadata if isinstance(geometry_metadata, dict) else {}


def _thermal_map_pdf_commands(data: ThermalMapData) -> list[str]:
    margin_left = 54.0
    plot_width = 504.0
    strip_y = 410.0
    strip_h = 82.0
    commands = [
        "BT /F1 18 Tf 42 740 Td (Embedded Thermal Map) Tj ET",
        "BT /F1 10 Tf 42 722 Td (Wall temperature distribution from injector to nozzle exit. Bartz heat flux peak is marked at the throat.) Tj ET",
    ]
    for index, point in enumerate(data.points[:-1]):
        next_point = data.points[index + 1]
        x = margin_left + plot_width * point.z_mm / data.length_mm
        x_next = margin_left + plot_width * next_point.z_mm / data.length_mm
        r, g, b = _hex_to_rgb(point.color)
        commands.append(f"{r:.4f} {g:.4f} {b:.4f} rg {x:.2f} {strip_y:.2f} {max(x_next - x, 0.8):.2f} {strip_h:.2f} re f")
    commands.extend(
        [
            f"0 0 0 RG {margin_left:.2f} {strip_y:.2f} {plot_width:.2f} {strip_h:.2f} re S",
            "0.10 0.13 0.16 rg",
            f"BT /F1 9 Tf {margin_left:.2f} {strip_y - 18:.2f} Td (Injector) Tj ET",
            f"BT /F1 9 Tf {margin_left + plot_width - 52:.2f} {strip_y - 18:.2f} Td (Nozzle exit) Tj ET",
            f"BT /F1 9 Tf 42 366 Td (Coolest {data.min_wall_temperature_K:.0f} K) Tj ET",
            f"BT /F1 9 Tf 180 366 Td (Hottest {data.max_wall_temperature_K:.0f} K) Tj ET",
            f"BT /F1 9 Tf 42 348 Td (Peak heat flux {data.peak_heat_flux_W_m2 / 1.0e6:.2f} MW/m2) Tj ET",
        ]
    )
    commands.extend(_pdf_marker("Throat", data.throat_z_mm, data.length_mm, margin_left, plot_width, strip_y, strip_h, (0.05, 0.08, 0.12), 526.0))
    commands.extend(_pdf_marker("Peak heat flux", data.peak_heat_flux_z_mm, data.length_mm, margin_left, plot_width, strip_y, strip_h, (0.84, 0.16, 0.16), 544.0))
    if data.cooling_inlet_z_mm is not None:
        commands.extend(_pdf_marker("Cooling inlet", data.cooling_inlet_z_mm, data.length_mm, margin_left, plot_width, strip_y, strip_h, (0.09, 0.41, 1.0), 390.0))
    if data.cooling_outlet_z_mm is not None:
        commands.extend(_pdf_marker("Cooling outlet", data.cooling_outlet_z_mm, data.length_mm, margin_left, plot_width, strip_y, strip_h, (0.09, 0.44, 0.42), 374.0))
    return commands


def _pdf_marker(
    label: str,
    z_mm: float,
    length_mm: float,
    margin_left: float,
    plot_width: float,
    strip_y: float,
    strip_h: float,
    rgb: tuple[float, float, float],
    text_y: float,
) -> list[str]:
    x = margin_left + plot_width * z_mm / max(length_mm, 1.0)
    safe_label = label.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return [
        f"{rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f} RG 1.5 w {x:.2f} {strip_y - 8:.2f} m {x:.2f} {strip_y + strip_h + 34:.2f} l S",
        f"{rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f} rg {x - 3:.2f} {strip_y + strip_h + 28:.2f} 6 6 re f",
        f"BT /F1 9 Tf {x + 6:.2f} {text_y:.2f} Td ({safe_label}) Tj ET",
    ]


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) / 255.0 for index in (0, 2, 4))
