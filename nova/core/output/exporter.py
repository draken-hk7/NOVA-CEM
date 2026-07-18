"""Geometry and performance artifact exporters."""

from __future__ import annotations

import math
import textwrap
import zipfile
from pathlib import Path
from typing import Any

from nova.core.geometry_engine.primitives import MeshSolid
from nova.core.manufacturing import validate_for_stl_export
from nova.core.output.technical_drawing import TechnicalDrawingData, TechnicalDrawingGenerator, write_vector_pdf, write_vector_pdf_pages
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
        technical_drawing_data = self._generate_technical_drawing(run_result, path)
        payload = self.generate_json_data(run_result)
        if run_result.module == "rocket-engine":
            self._write_professional_rocket_report(
                path,
                run_result=run_result,
                payload=payload,
                thermal_map_data=thermal_map_data,
                technical_drawing_data=technical_drawing_data,
            )
            return
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

    def _generate_technical_drawing(self, run_result: CEMRunResult, report_path: str) -> TechnicalDrawingData | None:
        if run_result.module != "rocket-engine":
            return None
        generator = TechnicalDrawingGenerator()
        data = generator.from_run_result(run_result)
        if data is None:
            return None
        drawing_svg = Path(report_path).with_name("engineering_drawing.svg")
        drawing_pdf = Path(report_path).with_name("engineering_drawing.pdf")
        drawing_svg.write_text(generator.to_svg(data), encoding="utf-8")
        write_vector_pdf(
            drawing_pdf,
            generator.pdf_commands(data, scale=72.0 / 25.4),
            media_box=(594.0 * 72.0 / 25.4, 420.0 * 72.0 / 25.4),
        )
        run_result.files["engineering_drawing"] = str(drawing_pdf)
        run_result.files["engineering_drawing_svg"] = str(drawing_svg)
        return data

    def _write_professional_rocket_report(
        self,
        path: str,
        *,
        run_result: CEMRunResult,
        payload: dict,
        thermal_map_data: ThermalMapData | None,
        technical_drawing_data: TechnicalDrawingData | None,
    ) -> None:
        metadata = _rocket_metadata(payload)
        analysis = _mapping(metadata.get("aerospace_analysis"))
        pages = [
            _report_cover_page(run_result, payload),
            _report_manufacturing_page(payload, metadata),
            _report_drawing_page(technical_drawing_data),
            _report_thermal_page(thermal_map_data),
            _report_analysis_page(analysis, metadata),
        ]
        write_vector_pdf_pages(path, pages)

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


def _report_cover_page(run_result: CEMRunResult, payload: dict) -> list[str]:
    performance = _mapping(_mapping(payload.get("design")).get("performance"))
    inputs = _mapping(payload.get("inputs"))
    metadata = _rocket_metadata(payload)
    nozzle = _mapping(metadata.get("nozzle"))
    return [
        *_report_header("NOVA-CEM ROCKET ENGINE DESIGN REPORT", "01 / 05", "EXECUTIVE DESIGN SUMMARY"),
        _report_text(48, 665, 16, f"{run_result.job_id}", bold=True),
        _report_text(48, 642, 9, "Traceable preliminary aerospace engineering output. Qualification and acceptance testing remain required before operational use."),
        *_report_table(
            48,
            560,
            "PERFORMANCE",
            [
                ("Specific impulse", _unit(performance.get("specific_impulse_s"), "s")),
                ("Thrust", _unit(performance.get("thrust_N"), "N")),
                ("Chamber temperature", _unit(performance.get("chamber_temp_K"), "K")),
                ("Chamber pressure", _unit(performance.get("chamber_pressure_bar"), "bar")),
                ("Mass flow", _unit(performance.get("mass_flow_rate_kg_s"), "kg/s")),
            ],
            accent=(0.10, 0.49, 0.41),
        ),
        *_report_table(
            330,
            560,
            "DESIGN INPUTS",
            [
                ("Propellant", _text_value(inputs.get("propellant"))),
                ("Material", _text_value(inputs.get("material"))),
                ("Cooling", _text_value(inputs.get("cooling"))),
                ("Process", _text_value(inputs.get("manufacturing_process"))),
                ("Geometry backend", _text_value(metadata.get("geometry_backend", "cadquery"))),
            ],
            accent=(0.13, 0.33, 0.60),
        ),
        *_report_table(
            48,
            350,
            "MANUFACTURING SUMMARY",
            [
                ("Estimated engine mass", _unit(_mapping(payload.get("design")).get("mass_kg"), "kg")),
                ("Estimated print time", _unit(_mapping(_mapping(payload.get("design")).get("manufacturing")).get("estimated_print_time_hours"), "h")),
                ("Wall thickness", _unit(nozzle.get("min_wall_thickness_mm", metadata.get("chamber_wall_thickness_mm")), "mm")),
                ("Cooling wall", _unit(nozzle.get("cooling_channel_wall_mm", metadata.get("cooling_channel_wall_mm", nozzle.get("min_wall_thickness_mm"))), "mm")),
                ("Report pages", "5 vector pages"),
            ],
            accent=(0.69, 0.28, 0.19),
        ),
        _report_text(48, 168, 11, "Report sequence", bold=True),
        _report_text(48, 146, 9, "01 Summary | 02 Validation | 03 Engineering Drawing | 04 Thermal Map | 05 Aerospace Screening"),
        _report_text(48, 112, 8, "Document control: NOVA-CEM v1.0 | traceable to job metadata | dimensions in millimetres unless noted."),
        *_report_footer("NOVA-CEM v1.0 | Preliminary engineering only"),
    ]


def _report_manufacturing_page(payload: dict, metadata: dict) -> list[str]:
    design = _mapping(payload.get("design"))
    validation = _mapping(design.get("validation"))
    feed = _mapping(metadata.get("feed_pressure_budget"))
    nozzle = _mapping(metadata.get("nozzle"))
    manifold = _mapping(metadata.get("manifold"))
    tolerance_rows = [
        ("Throat diameter", "+/-0.05 mm"),
        ("Cooling channel width", "+/-0.10 mm"),
        ("Wall thickness", "+/-0.05 mm"),
        ("Flange bolt-hole position", "+/-0.10 mm"),
        ("Coolant port thread", "M8x1.25"),
    ]
    pressure_rows = [
        ("Chamber pressure", _unit(feed.get("chamber_pressure_bar"), "bar")),
        ("Injector drop (20%)", _unit(feed.get("injector_drop_bar"), "bar")),
        ("Cooling channel drop", _unit(feed.get("cooling_channel_drop_bar"), "bar")),
        ("Line losses (5%)", _unit(feed.get("line_losses_bar"), "bar")),
        ("Required tank pressure", _unit(feed.get("required_tank_pressure_bar"), "bar")),
    ]
    validation_rows = [
        (str(item.get("name", "check")), "PASS" if item.get("passed") else "WARNING")
        for item in validation.get("checks", [])
        if isinstance(item, dict)
    ] or [("Structural validation", "No validation data")]
    coolant_ports = _mapping(nozzle.get("coolant_ports"))
    port_rows = []
    for name, port in coolant_ports.items():
        if isinstance(port, dict):
            port_rows.append((f"Coolant {name}", f"DIA {_number(port.get('diameter_mm')):.1f} mm | {port.get('thread_spec', 'M8x1.25')}"))
    if manifold:
        port_rows.append(("Oxidizer manifold", f"DIA {_number(_mapping(manifold.get('oxidizer_manifold')).get('diameter_mm')):.1f} mm"))
        port_rows.append(("Fuel manifold", f"DIA {_number(_mapping(manifold.get('fuel_manifold')).get('diameter_mm')):.1f} mm"))
    return [
        *_report_header("MANUFACTURING, PRESSURE BUDGET AND VALIDATION", "02 / 05", "CONTROLLED DESIGN REQUIREMENTS"),
        *_report_table(48, 635, "CRITICAL TOLERANCES", tolerance_rows, accent=(0.69, 0.28, 0.19)),
        *_report_table(330, 635, "PRESSURE-FED PROPULSION BUDGET", pressure_rows, accent=(0.13, 0.33, 0.60)),
        *_report_table(48, 380, "VALIDATION RESULTS", validation_rows[:6], accent=(0.10, 0.49, 0.41)),
        *_report_table(330, 380, "INTERFACES", port_rows[:6] or [("Interfaces", "No port metadata")], accent=(0.42, 0.32, 0.60)),
        _report_text(48, 135, 8, "Manufacturing note: tolerance values are design targets. Production release requires process capability, inspection, proof and leak testing."),
        *_report_footer("NOVA-CEM v1.0 | Manufacturing and validation"),
    ]


def _report_drawing_page(data: TechnicalDrawingData | None) -> list[str]:
    commands = [*_report_header("ENGINEERING DRAWING", "03 / 05", "A2 ISO 128 DRAWING REDUCED FOR REPORT"), _report_text(48, 690, 9, "Standalone A2 drawing is included as engineering_drawing.pdf and engineering_drawing.svg in this job output.")]
    if data is None:
        commands.append(_report_text(48, 640, 12, "Engineering drawing data was not available for this geometry mode.", bold=True))
    else:
        commands.extend(TechnicalDrawingGenerator().pdf_commands(data, scale=0.95, offset=(15.0, 118.0)))
    commands.extend(_report_footer("NOVA-CEM v1.0 | Engineering drawing"))
    return commands


def _report_thermal_page(data: ThermalMapData | None) -> list[str]:
    commands = [*_report_header("THERMAL MAP", "04 / 05", "BARTZ HEAT-FLUX SCREENING"), _report_text(42, 690, 9, "Wall temperature distribution with throat, peak heat flux and coolant-interface markers.")]
    if data is None:
        commands.append(_report_text(48, 640, 12, "Thermal map data was not available.", bold=True))
    else:
        commands.extend(_thermal_map_pdf_commands(data)[2:])
    commands.extend(_report_footer("NOVA-CEM v1.0 | Thermal screening"))
    return commands


def _report_analysis_page(analysis: dict, metadata: dict) -> list[str]:
    stability = _mapping(analysis.get("combustion_stability"))
    fatigue = _mapping(analysis.get("thermal_fatigue"))
    ignition = _mapping(analysis.get("ignition"))
    mode_rows = []
    for mode in stability.get("modes", []):
        if isinstance(mode, dict):
            status = "RISK" if mode.get("within_coupling_band") and not mode.get("is_reference") else "REFERENCE" if mode.get("is_reference") else "CLEAR"
            mode_rows.append((f"{mode.get('family', 'mode')} {mode.get('order', '')}", f"{_number(mode.get('frequency_hz')):.0f} Hz | {status}"))
    if not mode_rows:
        mode_rows = [("Acoustic modes", "No analysis data")]
    fatigue_rows = [
        ("Temperature delta", _unit(fatigue.get("temperature_delta_K"), "K")),
        ("Thermal stress", _unit(fatigue.get("thermal_stress_MPa"), "MPa")),
        ("Estimated thermal cycles", _text_value(fatigue.get("estimated_cycles"))),
        ("Recommended firings", _text_value(fatigue.get("recommended_firings"))),
    ]
    ignition_rows = [
        ("Recommended igniter", _text_value(ignition.get("recommended_igniter"))),
        ("Minimum spark energy", _unit(ignition.get("minimum_spark_energy_J"), "J")),
        ("Design spark energy", _unit(ignition.get("design_spark_energy_J"), "J")),
        ("Placement", f"Z {_number(ignition.get('placement_z_mm')):.1f} mm | {_number(ignition.get('placement_angle_deg')):.0f} deg"),
    ]
    risk_text = "STABILITY RISK DETECTED. Recommend baffled injector and acoustic validation." if stability.get("stability_risk") else "No coupled acoustic mode is within the +/-10% screening band."
    return [
        *_report_header("AEROSPACE SCREENING ANALYSIS", "05 / 05", "COMBUSTION STABILITY, FATIGUE AND IGNITION"),
        _report_text(48, 675, 11, risk_text, bold=True),
        _report_text(48, 652, 8, _text_value(stability.get("recommendation"))),
        *_report_table(48, 595, "COMBUSTION ACOUSTIC MODES", mode_rows[:5], accent=(0.69, 0.28, 0.19) if stability.get("stability_risk") else (0.10, 0.49, 0.41)),
        *_report_table(330, 595, "THERMAL FATIGUE SCREEN", fatigue_rows, accent=(0.42, 0.32, 0.60)),
        *_report_table(48, 350, "IGNITION SYSTEM SIZING", ignition_rows, accent=(0.13, 0.33, 0.60)),
        _report_text(48, 150, 8, "Thermal-fatigue screening only. Establish life with material coupons and duty-cycle testing."),
        _report_text(48, 132, 8, "Install upstream of the throat with local protection; verify ignition transient margins during hot-fire."),
        _report_text(48, 108, 8, "Screening only; validate using qualified materials, combustion dynamics and hot-fire data."),
        *_report_footer("NOVA-CEM v1.0 | Aerospace screening analysis"),
    ]


def _report_header(title: str, page_number: str, subtitle: str) -> list[str]:
    return [
        "0.06 0.10 0.13 rg 0 730 612 62 re f",
        "0.10 0.49 0.41 rg 0 726 612 4 re f",
        _report_text(42, 766, 18, title, bold=True, color=(1.0, 1.0, 1.0)),
        _report_text(42, 745, 8, subtitle, color=(0.78, 0.87, 0.84)),
        _report_text(544, 746, 8, page_number, color=(1.0, 1.0, 1.0)),
    ]


def _report_footer(text: str) -> list[str]:
    return [
        "0.84 0.88 0.89 RG 0.5 w 42 42 m 570 42 l S",
        _report_text(42, 25, 7.5, text, color=(0.30, 0.36, 0.40)),
    ]


def _report_table(x: float, y: float, title: str, rows: list[tuple[str, str]], *, accent: tuple[float, float, float]) -> list[str]:
    row_height = 25.0
    height = 28.0 + row_height * len(rows)
    commands = [
        f"{accent[0]:.3f} {accent[1]:.3f} {accent[2]:.3f} rg {x:.2f} {y - 28:.2f} 234 28 re f",
        _report_text(x + 11, y - 18, 9, title, bold=True, color=(1.0, 1.0, 1.0)),
        "0.84 0.88 0.89 RG 0.60 w " + f"{x:.2f} {y - height:.2f} 234 {height:.2f} re S",
    ]
    for index, (label, value) in enumerate(rows):
        row_top = y - 28 - index * row_height
        if index % 2 == 0:
            commands.append(f"0.96 0.97 0.98 rg {x + 0.6:.2f} {row_top - row_height + 0.6:.2f} 232.8 {row_height - 1.2:.2f} re f")
        commands.append(f"0.86 0.89 0.90 RG 0.30 w {x:.2f} {row_top - row_height:.2f} m {x + 234:.2f} {row_top - row_height:.2f} l S")
        commands.append(_report_text(x + 10, row_top - 16, 8.3, _ellipsize(label, 25), bold=True))
        commands.append(_report_text(x + 120, row_top - 16, 8.3, _ellipsize(value, 22)))
    return commands


def _report_text(x: float, y: float, size: float, value: str, *, bold: bool = False, color: tuple[float, float, float] = (0.09, 0.13, 0.16)) -> str:
    font = "F2" if bold else "F1"
    safe = str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg BT /{font} {size:.2f} Tf {x:.2f} {y:.2f} Td ({safe}) Tj ET"


def _mapping(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _unit(value: Any, unit: str) -> str:
    number = _number(value)
    return f"{number:.3f} {unit}" if unit else f"{number:.3f}"


def _text_value(value: Any) -> str:
    if value is None or value == "":
        return "--"
    return str(value)


def _ellipsize(value: Any, maximum: int) -> str:
    text = str(value)
    return text if len(text) <= maximum else f"{text[: max(1, maximum - 3)]}..."
