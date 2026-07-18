"""Aerospace-style technical drawing generation for NOVA rocket engines.

The drawing is deliberately generated from the design metadata rather than a
screen capture of the mesh.  That keeps dimensions traceable to the same
parameters used by the sizing and manufacturing calculations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable


A2_WIDTH_MM = 594.0
A2_HEIGHT_MM = 420.0
MM_TO_POINT = 72.0 / 25.4


@dataclass(slots=True)
class TechnicalDrawingData:
    """Traceable dimensions and notes rendered on an A2 engineering drawing."""

    job_id: str
    part_name: str
    material: str
    drawing_date: str
    scale: str
    thrust_N: float
    specific_impulse_s: float
    chamber_pressure_bar: float
    overall_length_mm: float
    chamber_length_mm: float
    chamber_diameter_mm: float
    throat_diameter_mm: float
    nozzle_exit_diameter_mm: float
    wall_thickness_mm: float
    cooling_channel_width_mm: float
    cooling_channel_depth_mm: float
    flange_bolt_circle_mm: float
    flange_hole_count: int
    injector_hole_count: int
    manifold_diameter_mm: float
    coolant_ports: dict[str, dict[str, Any]] = field(default_factory=dict)


class TechnicalDrawingGenerator:
    """Create ISO 128-inspired SVG and vector PDF technical drawings."""

    def from_run_result(self, run_result: Any) -> TechnicalDrawingData | None:
        if getattr(run_result, "module", "") != "rocket-engine":
            return None
        design = getattr(run_result, "design", None)
        if design is None:
            return None

        metadata = getattr(design, "metadata", {}) or {}
        nozzle = _mapping(metadata.get("nozzle"))
        geometry = getattr(design, "geometry", None)
        if not nozzle:
            nozzle = _mapping(getattr(geometry, "metadata", {}) or {})
        if not nozzle:
            return None

        performance = getattr(design, "performance", None)
        manufacturing = getattr(design, "manufacturing", None)
        injector = getattr(design, "injector", None)
        manifold = _mapping(metadata.get("manifold"))
        if not manifold:
            manifold = _mapping(_mapping(getattr(injector, "metadata", {})).get("propellant_manifold"))
        oxidizer = _mapping(manifold.get("oxidizer_manifold"))
        ports = _mapping(nozzle.get("coolant_ports"))

        chamber_radius = _number(nozzle.get("chamber_radius_mm"), 25.0)
        throat_radius = _number(nozzle.get("throat_radius_mm"), chamber_radius * 0.4)
        exit_radius = _number(nozzle.get("exit_radius_mm"), throat_radius * 1.5)
        total_length = _number(nozzle.get("total_length_mm"), 120.0)
        chamber_length = _number(nozzle.get("chamber_length_mm"), total_length * 0.35)
        wall = _number(nozzle.get("min_wall_thickness_mm"), _number(getattr(geometry, "metadata", {}).get("chamber_wall_thickness_mm") if geometry else None, 0.6))
        channel_width = _number(nozzle.get("channel_width_mm"), max(0.8, 0.30 * wall))
        channel_depth = _number(nozzle.get("channel_depth_mm"), max(0.5, min(0.75, 0.22 * wall)))
        flange_outer_radius = _number(nozzle.get("injector_flange_outer_radius_mm"), chamber_radius + wall + 10.0)
        bolt_circle = _number(nozzle.get("injector_bolt_circle_diameter_mm"), 2.0 * max(flange_outer_radius - 4.0, 1.0))
        bolt_count = int(round(_number(nozzle.get("injector_bolt_hole_count"), max(6.0, math.ceil(2.0 * math.pi * flange_outer_radius / 26.0)))))
        thrust = _number(getattr(performance, "thrust_N", None), 0.0)
        scale = "1:2" if thrust <= 500.0 else "1:4"

        return TechnicalDrawingData(
            job_id=str(getattr(run_result, "job_id", "NOVA-JOB")),
            part_name="NOVA REGENERATIVELY COOLED ROCKET ENGINE",
            material=str(getattr(manufacturing, "material", metadata.get("material", "inconel"))).upper(),
            drawing_date=date.today().isoformat(),
            scale=scale,
            thrust_N=thrust,
            specific_impulse_s=_number(getattr(performance, "specific_impulse_s", None), 0.0),
            chamber_pressure_bar=_number(getattr(performance, "chamber_pressure_bar", None), _number(nozzle.get("chamber_pressure_bar"), 0.0)),
            overall_length_mm=total_length,
            chamber_length_mm=chamber_length,
            chamber_diameter_mm=2.0 * chamber_radius,
            throat_diameter_mm=2.0 * throat_radius,
            nozzle_exit_diameter_mm=2.0 * exit_radius,
            wall_thickness_mm=wall,
            cooling_channel_width_mm=channel_width,
            cooling_channel_depth_mm=channel_depth,
            flange_bolt_circle_mm=bolt_circle,
            flange_hole_count=max(bolt_count, 1),
            injector_hole_count=int(getattr(injector, "n_elements", 0) or 0),
            manifold_diameter_mm=_number(oxidizer.get("diameter_mm"), 2.0 * chamber_radius),
            coolant_ports=ports,
        )

    def generate_svg(self, run_result: Any, path: str | Path) -> TechnicalDrawingData | None:
        data = self.from_run_result(run_result)
        if data is None:
            return None
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.to_svg(data), encoding="utf-8")
        return data

    def generate_pdf(self, run_result: Any, path: str | Path) -> TechnicalDrawingData | None:
        data = self.from_run_result(run_result)
        if data is None:
            return None
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_vector_pdf(
            destination,
            self.pdf_commands(data, scale=MM_TO_POINT),
            media_box=(A2_WIDTH_MM * MM_TO_POINT, A2_HEIGHT_MM * MM_TO_POINT),
        )
        return data

    def to_svg(self, data: TechnicalDrawingData) -> str:
        profile = _profile_path(data, x=58.0, y=114.0, width=260.0, height=86.0)
        section = _section_path(data, x=58.0, y=245.0, width=260.0, height=92.0)
        top = _top_view(data, center_x=397.0, center_y=165.0)
        dimensions = _svg_dimensions(data)
        port_notes = _port_notes(data)
        return "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" width="594mm" height="420mm" viewBox="0 0 594 420" role="img" aria-label="NOVA aerospace engineering drawing">',
                "<title>NOVA-CEM Aerospace Engineering Drawing</title>",
                "<defs><marker id=\"arrow\" markerWidth=\"5\" markerHeight=\"5\" refX=\"4\" refY=\"2.5\" orient=\"auto-start-reverse\"><path d=\"M 0 0 L 5 2.5 L 0 5 z\" fill=\"#16202a\"/></marker></defs>",
                '<rect width="594" height="420" fill="#ffffff"/>',
                '<rect x="10" y="10" width="574" height="400" fill="none" stroke="#16202a" stroke-width="0.6"/>',
                '<rect x="14" y="14" width="566" height="392" fill="none" stroke="#16202a" stroke-width="0.2"/>',
                '<g font-family="Arial, Helvetica, sans-serif" fill="#16202a">',
                '<text x="23" y="31" font-size="5.2" font-weight="700">NOVA-CEM | AEROSPACE ENGINEERING DRAWING</text>',
                '<text x="23" y="40" font-size="3.1">ISO 128 presentation | all dimensions in mm | theoretical design output - qualification required before flight use</text>',
                '<text x="58" y="106" font-size="4.2" font-weight="700">FRONT PROFILE</text>',
                f'<path d="{profile}" fill="none" stroke="#16202a" stroke-width="0.7"/>',
                '<path d="M 45 157 H 330" fill="none" stroke="#4c5965" stroke-width="0.28" stroke-dasharray="7 2 1 2"/>',
                '<path d="M 58 129 H 318" fill="none" stroke="#62717d" stroke-width="0.25" stroke-dasharray="3 2"/>',
                '<text x="58" y="237" font-size="4.2" font-weight="700">SECTION A-A</text>',
                f'<path d="{section}" fill="#eef3f6" stroke="#16202a" stroke-width="0.7"/>',
                '<path d="M 45 290 H 330" fill="none" stroke="#4c5965" stroke-width="0.28" stroke-dasharray="7 2 1 2"/>',
                _svg_cooling_channels(data),
                _svg_injector_and_manifold(data),
                '<text x="354" y="69" font-size="4.2" font-weight="700">TOP PLAN VIEW</text>',
                top,
                _svg_surface_finish(335.0, 278.0, "Ra 0.8 SEALING FACES"),
                _svg_surface_finish(335.0, 291.0, "Ra 3.2 GENERAL SURFACES"),
                *dimensions,
                *port_notes,
                *_svg_notes(data),
                _svg_title_block(data),
                "</g>",
                "</svg>",
            ]
        )

    def pdf_commands(self, data: TechnicalDrawingData, *, scale: float = 1.0, offset: tuple[float, float] = (0.0, 0.0)) -> list[str]:
        """Return vector PDF commands in drawing-coordinate millimetres."""

        ox, oy = offset
        commands = [f"q {scale:.6f} 0 0 {scale:.6f} {ox:.3f} {oy:.3f} cm"]
        commands.extend(
            [
                "1 1 1 rg 0 0 594 420 re f",
                "0.09 0.13 0.16 RG 0.60 w 10 10 574 400 re S",
                "0.09 0.13 0.16 RG 0.20 w 14 14 566 392 re S",
                "BT /F2 5.2 Tf 23 389 Td (NOVA-CEM | AEROSPACE ENGINEERING DRAWING) Tj ET",
                "BT /F1 3.1 Tf 23 380 Td (ISO 128 presentation | all dimensions in mm | qualification required before flight use) Tj ET",
                "BT /F2 4.2 Tf 58 314 Td (FRONT PROFILE) Tj ET",
            ]
        )
        commands.extend(_pdf_profile(data, x=58.0, y=220.0, width=260.0, height=86.0))
        commands.extend(["0.30 0.35 0.40 RG 0.28 w [7 2 1 2] 0 d 45 263 m 330 263 l S [] 0 d"])
        commands.extend(["BT /F2 4.2 Tf 58 183 Td (SECTION A-A) Tj ET"])
        commands.extend(_pdf_section(data, x=58.0, y=83.0, width=260.0, height=92.0))
        commands.extend(["0.30 0.35 0.40 RG 0.28 w [7 2 1 2] 0 d 45 129 m 330 129 l S [] 0 d"])
        commands.extend(_pdf_cooling_channels(data))
        commands.extend(_pdf_injector_and_manifold(data))
        commands.extend(["BT /F2 4.2 Tf 354 351 Td (TOP PLAN VIEW) Tj ET"])
        commands.extend(_pdf_top_view(data, center_x=397.0, center_y=255.0))
        commands.extend(_pdf_dimension_commands(data))
        commands.extend(_pdf_notes(data))
        commands.extend(_pdf_title_block(data))
        commands.append("Q")
        return commands


def write_vector_pdf(path: str | Path, page_commands: Iterable[str], *, media_box: tuple[float, float] = (612.0, 792.0)) -> None:
    """Write a small self-contained vector PDF without an optional dependency."""

    content = "\n".join(page_commands).encode("latin-1", errors="replace")
    width, height = media_box
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [5 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> endobj\n",
        (
            f"5 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.3f} {height:.3f}] "
            "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents 6 0 R >> endobj\n"
        ).encode("ascii"),
        f"6 0 obj << /Length {len(content)} >> stream\n".encode("ascii") + content + b"\nendstream endobj\n",
    ]
    _write_pdf_objects(path, objects)


def write_vector_pdf_pages(path: str | Path, pages: list[Iterable[str]], *, media_box: tuple[float, float] = (612.0, 792.0)) -> None:
    """Write a compact multi-page PDF used by the NOVA professional report."""

    width, height = media_box
    page_object_numbers = [5 + index * 2 for index in range(len(pages))]
    kids = " ".join(f"{number} 0 R" for number in page_object_numbers)
    objects: list[bytes] = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        f"2 0 obj << /Type /Pages /Kids [{kids}] /Count {len(pages)} >> endobj\n".encode("ascii"),
        b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> endobj\n",
    ]
    for index, commands in enumerate(pages):
        page_number = 5 + index * 2
        content_number = page_number + 1
        content = "\n".join(commands).encode("latin-1", errors="replace")
        objects.append(
            (
                f"{page_number} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.3f} {height:.3f}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_number} 0 R >> endobj\n"
            ).encode("ascii")
        )
        objects.append(f"{content_number} 0 obj << /Length {len(content)} >> stream\n".encode("ascii") + content + b"\nendstream endobj\n")
    _write_pdf_objects(path, objects)


def _write_pdf_objects(path: str | Path, objects: list[bytes]) -> None:
    output = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    Path(path).write_bytes(output)


def _profile_path(data: TechnicalDrawingData, *, x: float, y: float, width: float, height: float) -> str:
    points = _profile_points(data, x=x, y=y, width=width, height=height)
    top = " L ".join(f"{px:.2f} {py:.2f}" for px, py in points)
    bottom = " L ".join(f"{px:.2f} {2 * y + height - py:.2f}" for px, py in reversed(points))
    return f"M {top} L {bottom} Z"


def _section_path(data: TechnicalDrawingData, *, x: float, y: float, width: float, height: float) -> str:
    return _profile_path(data, x=x, y=y, width=width, height=height)


def _profile_points(data: TechnicalDrawingData, *, x: float, y: float, width: float, height: float) -> list[tuple[float, float]]:
    chamber_fraction = min(max(data.chamber_length_mm / max(data.overall_length_mm, 1.0), 0.18), 0.58)
    throat_fraction = min(max(chamber_fraction + 0.18, 0.42), 0.72)
    chamber_half = max(12.0, height * 0.39)
    throat_half = max(3.0, chamber_half * data.throat_diameter_mm / max(data.chamber_diameter_mm, 1.0))
    exit_half = max(throat_half * 1.4, chamber_half * data.nozzle_exit_diameter_mm / max(data.chamber_diameter_mm, 1.0))
    center = y + height * 0.5
    return [
        (x, center - chamber_half),
        (x + width * chamber_fraction, center - chamber_half),
        (x + width * throat_fraction, center - throat_half),
        (x + width, center - exit_half),
    ]


def _top_view(data: TechnicalDrawingData, *, center_x: float, center_y: float) -> str:
    outer = 44.0
    bolt = min(outer - 5.0, 0.5 * outer * data.flange_bolt_circle_mm / max(data.chamber_diameter_mm + 24.0, 1.0))
    holes = []
    for index in range(data.flange_hole_count):
        theta = 2.0 * math.pi * index / data.flange_hole_count
        holes.append(f'<circle cx="{center_x + bolt * math.cos(theta):.2f}" cy="{center_y + bolt * math.sin(theta):.2f}" r="1.8" fill="none" stroke="#16202a" stroke-width="0.45"/>')
    return "\n".join(
        [
            f'<circle cx="{center_x}" cy="{center_y}" r="{outer}" fill="none" stroke="#16202a" stroke-width="0.7"/>',
            f'<circle cx="{center_x}" cy="{center_y}" r="{outer - 10.0}" fill="none" stroke="#62717d" stroke-width="0.3" stroke-dasharray="3 2"/>',
            f'<circle cx="{center_x}" cy="{center_y}" r="{outer - 22.0}" fill="#eef3f6" stroke="#16202a" stroke-width="0.6"/>',
            f'<path d="M {center_x - outer - 8:.2f} {center_y:.2f} H {center_x + outer + 8:.2f} M {center_x:.2f} {center_y - outer - 8:.2f} V {center_y + outer + 8:.2f}" fill="none" stroke="#4c5965" stroke-width="0.28" stroke-dasharray="7 2 1 2"/>',
            *holes,
            f'<text x="{center_x - 35:.2f}" y="{center_y + outer + 12:.2f}" font-size="3.0">Injector flange and bolt pattern</text>',
        ]
    )


def _svg_dimensions(data: TechnicalDrawingData) -> list[str]:
    text = "#16202a"
    return [
        _svg_dimension(58, 208, 318, 208, f"OAL {data.overall_length_mm:.1f}", text),
        _svg_dimension(58, 215, 58 + 260 * data.chamber_length_mm / max(data.overall_length_mm, 1.0), 215, f"CHAMBER L {data.chamber_length_mm:.1f}", text),
        _svg_dimension(42, 114, 42, 200, f"CHAMBER DIA {data.chamber_diameter_mm:.2f}", text, vertical=True),
        _svg_dimension(326, 151, 326, 163, f"THROAT DIA {data.throat_diameter_mm:.2f}", text, vertical=True),
        _svg_dimension(324, 120, 324, 194, f"EXIT DIA {data.nozzle_exit_diameter_mm:.2f}", text, vertical=True),
        _svg_dimension(453, 103, 453, 227, f"BCD {data.flange_bolt_circle_mm:.2f} / {data.flange_hole_count}X", text, vertical=True),
    ]


def _svg_dimension(x1: float, y1: float, x2: float, y2: float, label: str, color: str, *, vertical: bool = False) -> str:
    label_x = (x1 + x2) / 2.0 + (4.0 if vertical else 0.0)
    label_y = (y1 + y2) / 2.0 - (2.0 if vertical else 3.0)
    transform = f' transform="rotate(-90 {label_x:.2f} {label_y:.2f})"' if vertical else ""
    return "\n".join(
        [
            f'<path d="M {x1:.2f} {y1:.2f} L {x2:.2f} {y2:.2f}" fill="none" stroke="{color}" stroke-width="0.28" marker-start="url(#arrow)" marker-end="url(#arrow)"/>',
            f'<text x="{label_x:.2f}" y="{label_y:.2f}" font-size="2.9" text-anchor="middle" fill="{color}"{transform}>{_escape(label)}</text>',
        ]
    )


def _svg_cooling_channels(data: TechnicalDrawingData) -> str:
    channels = []
    for index in range(8):
        x = 118 + index * 14.5
        channels.append(f'<rect x="{x:.2f}" y="264" width="{max(1.2, data.cooling_channel_width_mm * 1.4):.2f}" height="20" fill="#7fb3d5" stroke="#16202a" stroke-width="0.22"/>')
    return "\n".join(
        [
            *channels,
            f'<text x="185" y="304" font-size="3.1">Cooling channels: W {data.cooling_channel_width_mm:.2f} / D {data.cooling_channel_depth_mm:.2f}</text>',
            f'<text x="185" y="310" font-size="3.1">Wall {data.wall_thickness_mm:.2f} +/-0.05</text>',
        ]
    )


def _svg_injector_and_manifold(data: TechnicalDrawingData) -> str:
    injector_holes = []
    for index in range(max(min(data.injector_hole_count, 12), 1)):
        injector_holes.append(f'<circle cx="{72 + index * 3.0:.2f}" cy="290" r="0.7" fill="#16202a"/>')
    return "\n".join(
        [
            '<rect x="58" y="274" width="42" height="32" fill="#dce8ec" stroke="#16202a" stroke-width="0.6"/>',
            '<circle cx="91" cy="290" r="13" fill="none" stroke="#b74e3f" stroke-width="1.6"/>',
            *injector_holes,
            f'<text x="58" y="322" font-size="3.1">Injector holes: {data.injector_hole_count}</text>',
            f'<text x="58" y="328" font-size="3.1">Oxidizer manifold DIA {data.manifold_diameter_mm:.2f}</text>',
        ]
    )


def _svg_surface_finish(x: float, y: float, label: str) -> str:
    return f'<path d="M {x} {y} l 4 -5 l 4 5" fill="none" stroke="#16202a" stroke-width="0.45"/><text x="{x + 11}" y="{y}" font-size="3.0">{label}</text>'


def _port_notes(data: TechnicalDrawingData) -> list[str]:
    lines: list[str] = []
    y = 307.0
    for name, port in sorted(data.coolant_ports.items()):
        position = port.get("position_mm", []) if isinstance(port, dict) else []
        z_value = _number(port.get("z_mm") if isinstance(port, dict) else None, position[2] if len(position) > 2 else 0.0)
        thread = str(port.get("thread_spec", "M8x1.25") if isinstance(port, dict) else "M8x1.25")
        diameter = _number(port.get("diameter_mm") if isinstance(port, dict) else None, 8.0)
        lines.append(f'<text x="335" y="{y:.2f}" font-size="3.0">COOLANT {name.upper()}: DIA {diameter:.1f}, {thread}, Z {z_value:.1f}</text>')
        y += 6.0
    return lines or ['<text x="335" y="307" font-size="3.0">COOLANT PORT DATA NOT AVAILABLE</text>']


def _svg_notes(data: TechnicalDrawingData) -> list[str]:
    notes = [
        "CRITICAL TOLERANCES",
        "1. THROAT DIA +/-0.05",
        "2. COOLING CHANNEL WIDTH +/-0.10",
        "3. WALL THICKNESS +/-0.05",
        "4. FLANGE BOLT HOLE POSITION +/-0.10",
        "5. COOLANT PORT THREAD M8x1.25",
        "HIDDEN LINES: DASHED | CENTER LINES: DASH-DOT",
    ]
    return [f'<text x="335" y="{337 + index * 6:.2f}" font-size="2.8" font-weight="{700 if index == 0 else 400}">{note}</text>' for index, note in enumerate(notes)]


def _svg_title_block(data: TechnicalDrawingData) -> str:
    return "\n".join(
        [
            '<rect x="396" y="12" width="184" height="77" fill="#ffffff" stroke="#16202a" stroke-width="0.6"/>',
            '<path d="M 396 28 H 580 M 396 43 H 580 M 396 57 H 580 M 396 70 H 580 M 458 12 V 89" fill="none" stroke="#16202a" stroke-width="0.28"/>',
            '<text x="400" y="23" font-size="4.0" font-weight="700">NOVA-CEM v1.0</text>',
            f'<text x="400" y="37" font-size="3.2">PART: {_escape(data.part_name)}</text>',
            f'<text x="400" y="52" font-size="3.2">JOB ID: {_escape(data.job_id)}</text>',
            f'<text x="400" y="66" font-size="3.2">MATERIAL: {_escape(data.material)}</text>',
            f'<text x="400" y="80" font-size="3.2">DATE: {_escape(data.drawing_date)}</text>',
            f'<text x="463" y="23" font-size="3.2">SCALE: {_escape(data.scale)}</text>',
            f'<text x="463" y="37" font-size="3.2">ISP: {data.specific_impulse_s:.1f} s</text>',
            f'<text x="463" y="52" font-size="3.2">THRUST: {data.thrust_N:.1f} N</text>',
            f'<text x="463" y="66" font-size="3.2">PC: {data.chamber_pressure_bar:.2f} bar</text>',
            '<text x="463" y="80" font-size="3.2">SHEET: 1 / 1</text>',
        ]
    )


def _pdf_profile(data: TechnicalDrawingData, *, x: float, y: float, width: float, height: float) -> list[str]:
    points = _profile_points(data, x=x, y=y, width=width, height=height)
    mirrored = [(px, 2 * y + height - py) for px, py in reversed(points)]
    commands = ["0.09 0.13 0.16 RG 0.70 w", f"{points[0][0]:.2f} {points[0][1]:.2f} m"]
    commands.extend(f"{px:.2f} {py:.2f} l" for px, py in points[1:] + mirrored)
    commands.extend(["h S"])
    return commands


def _pdf_section(data: TechnicalDrawingData, *, x: float, y: float, width: float, height: float) -> list[str]:
    commands = ["0.93 0.95 0.96 rg"] + _pdf_profile(data, x=x, y=y, width=width, height=height)[:-1] + ["h B"]
    return commands


def _pdf_cooling_channels(data: TechnicalDrawingData) -> list[str]:
    commands = ["0.50 0.70 0.84 rg 0.09 0.13 0.16 RG 0.22 w"]
    width = max(1.2, data.cooling_channel_width_mm * 1.4)
    for index in range(8):
        commands.append(f"{118 + index * 14.5:.2f} 136 {width:.2f} 20 re B")
    commands.extend(
        [
            _pdf_text(185, 115, 3.1, f"Cooling channels: W {data.cooling_channel_width_mm:.2f} / D {data.cooling_channel_depth_mm:.2f}"),
            _pdf_text(185, 109, 3.1, f"Wall {data.wall_thickness_mm:.2f} +/-0.05"),
        ]
    )
    return commands


def _pdf_injector_and_manifold(data: TechnicalDrawingData) -> list[str]:
    commands = ["0.86 0.91 0.93 rg 0.09 0.13 0.16 RG 0.60 w 58 113 42 32 re B", "0.72 0.31 0.25 RG 1.60 w", _pdf_circle(91, 129, 13, "S")]
    for index in range(max(min(data.injector_hole_count, 12), 1)):
        commands.extend(["0.09 0.13 0.16 rg", _pdf_circle(72 + index * 3.0, 129, 0.70, "f")])
    commands.extend(
        [
            _pdf_text(58, 97, 3.1, f"Injector holes: {data.injector_hole_count}"),
            _pdf_text(58, 91, 3.1, f"Oxidizer manifold DIA {data.manifold_diameter_mm:.2f}"),
        ]
    )
    return commands


def _pdf_top_view(data: TechnicalDrawingData, *, center_x: float, center_y: float) -> list[str]:
    outer = 44.0
    bolt = min(outer - 5.0, 0.5 * outer * data.flange_bolt_circle_mm / max(data.chamber_diameter_mm + 24.0, 1.0))
    commands = [
        "0.09 0.13 0.16 RG 0.70 w",
        _pdf_circle(center_x, center_y, outer, "S"),
        "0.38 0.44 0.49 RG 0.30 w [3 2] 0 d",
        _pdf_circle(center_x, center_y, outer - 10.0, "S"),
        "[] 0 d 0.93 0.95 0.96 rg 0.09 0.13 0.16 RG 0.60 w",
        _pdf_circle(center_x, center_y, outer - 22.0, "B"),
        "0.30 0.35 0.40 RG 0.28 w [7 2 1 2] 0 d " + f"{center_x - outer - 8:.2f} {center_y:.2f} m {center_x + outer + 8:.2f} {center_y:.2f} l {center_x:.2f} {center_y - outer - 8:.2f} m {center_x:.2f} {center_y + outer + 8:.2f} l S [] 0 d",
    ]
    for index in range(data.flange_hole_count):
        theta = 2.0 * math.pi * index / data.flange_hole_count
        commands.extend(["0.09 0.13 0.16 RG 0.45 w", _pdf_circle(center_x + bolt * math.cos(theta), center_y + bolt * math.sin(theta), 1.8, "S")])
    commands.append(_pdf_text(center_x - 35, center_y - outer - 12, 3.0, "Injector flange and bolt pattern"))
    return commands


def _pdf_dimension_commands(data: TechnicalDrawingData) -> list[str]:
    return [
        _pdf_dimension(58, 212, 318, 212, f"OAL {data.overall_length_mm:.1f}"),
        _pdf_dimension(58, 219, 58 + 260 * data.chamber_length_mm / max(data.overall_length_mm, 1.0), 219, f"CHAMBER L {data.chamber_length_mm:.1f}"),
        _pdf_text(28, 263, 2.9, f"CHAMBER DIA {data.chamber_diameter_mm:.2f}"),
        _pdf_text(300, 270, 2.9, f"THROAT DIA {data.throat_diameter_mm:.2f}"),
        _pdf_text(300, 226, 2.9, f"EXIT DIA {data.nozzle_exit_diameter_mm:.2f}"),
        _pdf_text(449, 285, 2.9, f"BCD {data.flange_bolt_circle_mm:.2f} / {data.flange_hole_count}X"),
        _pdf_text(346, 142, 3.0, "Ra 0.8 SEALING FACES"),
        _pdf_text(346, 130, 3.0, "Ra 3.2 GENERAL SURFACES"),
    ]


def _pdf_notes(data: TechnicalDrawingData) -> list[str]:
    commands: list[str] = []
    y = 113.0
    for name, port in sorted(data.coolant_ports.items()):
        position = port.get("position_mm", []) if isinstance(port, dict) else []
        z_value = _number(port.get("z_mm") if isinstance(port, dict) else None, position[2] if len(position) > 2 else 0.0)
        thread = str(port.get("thread_spec", "M8x1.25") if isinstance(port, dict) else "M8x1.25")
        diameter = _number(port.get("diameter_mm") if isinstance(port, dict) else None, 8.0)
        commands.append(_pdf_text(335, y, 3.0, f"COOLANT {name.upper()}: DIA {diameter:.1f}, {thread}, Z {z_value:.1f}"))
        y -= 6.0
    if not data.coolant_ports:
        commands.append(_pdf_text(335, 113, 3.0, "COOLANT PORT DATA NOT AVAILABLE"))
    notes = [
        "CRITICAL TOLERANCES",
        "1. THROAT DIA +/-0.05",
        "2. COOLING CHANNEL WIDTH +/-0.10",
        "3. WALL THICKNESS +/-0.05",
        "4. FLANGE BOLT HOLE POSITION +/-0.10",
        "5. COOLANT PORT THREAD M8x1.25",
        "HIDDEN LINES: DASHED | CENTER LINES: DASH-DOT",
    ]
    commands.extend(_pdf_text(335, 83 - index * 6, 2.8, note, bold=index == 0) for index, note in enumerate(notes))
    return commands


def _pdf_title_block(data: TechnicalDrawingData) -> list[str]:
    lines = [
        "0.09 0.13 0.16 RG 0.60 w 396 12 184 77 re S",
        "0.09 0.13 0.16 RG 0.28 w 396 28 m 580 28 l 396 43 m 580 43 l 396 57 m 580 57 l 396 70 m 580 70 l 458 12 m 458 89 l S",
        _pdf_text(400, 77, 4.0, "NOVA-CEM v1.0", bold=True),
        _pdf_text(400, 63, 3.2, f"PART: {data.part_name}"),
        _pdf_text(400, 48, 3.2, f"JOB ID: {data.job_id}"),
        _pdf_text(400, 34, 3.2, f"MATERIAL: {data.material}"),
        _pdf_text(400, 20, 3.2, f"DATE: {data.drawing_date}"),
        _pdf_text(463, 77, 3.2, f"SCALE: {data.scale}"),
        _pdf_text(463, 63, 3.2, f"ISP: {data.specific_impulse_s:.1f} s"),
        _pdf_text(463, 48, 3.2, f"THRUST: {data.thrust_N:.1f} N"),
        _pdf_text(463, 34, 3.2, f"PC: {data.chamber_pressure_bar:.2f} bar"),
        _pdf_text(463, 20, 3.2, "SHEET: 1 / 1"),
    ]
    return lines


def _pdf_dimension(x1: float, y1: float, x2: float, y2: float, label: str) -> str:
    text_x = (x1 + x2) * 0.5 - max(len(label) * 0.72, 8.0)
    return "\n".join(
        [
            "0.09 0.13 0.16 RG 0.28 w",
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S",
            f"{x1:.2f} {y1:.2f} m {x1 + 2.2:.2f} {y1 + 1.2:.2f} l {x1 + 2.2:.2f} {y1 - 1.2:.2f} l h f",
            f"{x2:.2f} {y2:.2f} m {x2 - 2.2:.2f} {y2 + 1.2:.2f} l {x2 - 2.2:.2f} {y2 - 1.2:.2f} l h f",
            _pdf_text(text_x, y1 + 3.0, 2.9, label),
        ]
    )


def _pdf_text(x: float, y: float, size: float, value: str, *, bold: bool = False) -> str:
    font = "F2" if bold else "F1"
    return f"0.09 0.13 0.16 rg BT /{font} {size:.2f} Tf {x:.2f} {y:.2f} Td ({_pdf_escape(value)}) Tj ET"


def _pdf_circle(x: float, y: float, radius: float, paint_operator: str) -> str:
    """Approximate a circle with four cubic Bezier segments in raw PDF syntax."""

    control = radius * 0.5522847498
    return " ".join(
        [
            f"{x + radius:.3f} {y:.3f} m",
            f"{x + radius:.3f} {y + control:.3f} {x + control:.3f} {y + radius:.3f} {x:.3f} {y + radius:.3f} c",
            f"{x - control:.3f} {y + radius:.3f} {x - radius:.3f} {y + control:.3f} {x - radius:.3f} {y:.3f} c",
            f"{x - radius:.3f} {y - control:.3f} {x - control:.3f} {y - radius:.3f} {x:.3f} {y - radius:.3f} c",
            f"{x + control:.3f} {y - radius:.3f} {x + radius:.3f} {y - control:.3f} {x + radius:.3f} {y:.3f} c",
            f"h {paint_operator}",
        ]
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _escape(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _pdf_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
