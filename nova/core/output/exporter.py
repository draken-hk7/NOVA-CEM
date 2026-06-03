"""Geometry and performance artifact exporters."""

from __future__ import annotations

import textwrap
import zipfile
from pathlib import Path
from typing import Any

from nova.core.geometry_engine.primitives import MeshSolid
from nova.core.manufacturing import validate_for_stl_export
from nova.core.output.thermal_map import ThermalMapData, ThermalMapGenerator
from nova.core.types import CEMRunResult, to_jsonable


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
        ports = payload.get("design", {}).get("metadata", {}).get("nozzle", {}).get("coolant_ports", {})
        if ports:
            lines.extend(["", "Coolant Ports:"])
            for name, port in ports.items():
                position = port.get("position_mm", [])
                position_text = ", ".join(f"{float(value):.2f}" for value in position)
                lines.append(
                    f"  {name}: diameter {port.get('diameter_mm')} mm, bore {port.get('bore_diameter_mm')} mm, "
                    f"thread {port.get('thread_spec')}, position [{position_text}] mm"
                )
        manifold = payload.get("design", {}).get("metadata", {}).get("manifold", {})
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

    def generate_cfd_mesh(self, solid: MeshSolid, path: str) -> None:
        GeometryExporter().to_obj(solid, path)

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
