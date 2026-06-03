"""Command-line interface for NOVA."""

from __future__ import annotations

import argparse
import json
import math
import struct
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from nova.core.input_schema import ActuatorSpec, HeatExchangerSpec, HotFireTestResult, RocketEngineSpec
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult, ProcessParams
from nova.feedback import FeedbackIngester
from nova.modules.nova_ea import NovaEA
from nova.modules.nova_hx import NovaHX
from nova.modules.nova_rp import NovaRP


DEFAULT_CLI_MESH_TOLERANCE_MM = 0.5
FAST_CLI_MESH_TOLERANCE_MM = 1.0
HX_ASSEMBLY_OFFSET_MM = 150.0


class StlTriangle(NamedTuple):
    normal: tuple[float, float, float]
    vertices: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


def parse_quantity(value: str, unit: str) -> float:
    cleaned = value.strip().lower().replace(unit.lower(), "")
    return float(cleaned)


def _format_number_token(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}".replace(".", "p")


def _rocket_output_name(spec: RocketEngineSpec, timestamp: datetime | None = None) -> str:
    stamp = (timestamp or datetime.now()).strftime("%Y-%m-%d_%H%M")
    thrust = _format_number_token(spec.thrust_N)
    pressure = _format_number_token(spec.chamber_pressure_bar)
    return f"{spec.propellant}_{thrust}N_{pressure}bar_{stamp}"


def _unique_output_dir(base_dir: Path, name: str) -> Path:
    candidate = base_dir / name
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        candidate = base_dir / f"{name}_{index:02d}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not create a unique output directory for {name}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova")
    sub = parser.add_subparsers(dest="command", required=True)

    design = sub.add_parser("design")
    design_sub = design.add_subparsers(dest="design_type", required=True)
    rocket = design_sub.add_parser("rocket-engine")
    rocket.add_argument("--thrust", required=True, help="Target thrust, e.g. 5000N")
    rocket.add_argument("--propellant", required=True, choices=["kerolox", "methalox", "hydrolox", "hypergolic", "solid"])
    rocket.add_argument("--chamber-pressure", type=float, default=50.0)
    rocket.add_argument("--expansion-ratio", type=float, default=None)
    rocket.add_argument("--material", default="copper", choices=["copper", "inconel", "inconel718", "titanium", "steel"])
    rocket.add_argument("--process", default="lpbf", choices=["lpbf", "ebm", "directed_energy", "machined"])
    rocket.add_argument("--output-dir", default="outputs/cli")
    rocket.add_argument("--fast", action="store_true", help="Generate a coarse 4-channel, 1 mm mesh preview.")

    hx = design_sub.add_parser("heat-exchanger")
    hx.add_argument("--duty", type=float, required=True, help="Heat duty in kW.")
    hx.add_argument("--hot-fluid", required=True, choices=["air", "exhaust", "water"])
    hx.add_argument("--cold-fluid", required=True, choices=["hydrogen", "water", "helium"])
    hx.add_argument("--hot-inlet", type=float, required=True, help="Hot inlet temperature in C.")
    hx.add_argument("--hot-outlet", type=float, required=True, help="Hot outlet temperature in C.")
    hx.add_argument("--cold-inlet", type=float, required=True, help="Cold inlet temperature in C.")
    hx.add_argument("--max-pressure", type=float, default=1.0, help="Maximum pressure drop in bar.")
    hx.add_argument("--material", default="inconel", choices=["inconel", "steel", "copper"])
    hx.add_argument("--process", default="lpbf", choices=["lpbf", "ebm", "directed_energy", "machined"])
    hx.add_argument("--output-dir", default="outputs/cli")

    actuator = design_sub.add_parser("actuator")
    actuator.add_argument("--force", type=float, required=True, help="Required actuation force in N.")
    actuator.add_argument("--stroke", type=float, required=True, help="Actuator stroke in mm.")
    actuator.add_argument("--voltage", type=float, default=24.0, help="Operating voltage in V.")
    actuator.add_argument("--response-time", type=float, default=50.0, help="Maximum response time in ms.")
    actuator.add_argument("--material", default="steel", choices=["steel", "inconel", "aluminum"])
    actuator.add_argument("--max-temp", type=float, default=120.0, help="Operating temperature in C.")
    actuator.add_argument("--output-dir", default="outputs/cli")

    export = sub.add_parser("export")
    export.add_argument("job_id")
    export.add_argument("--format", nargs="+", default=["stl", "step", "report"])

    assemble = sub.add_parser("assemble")
    assemble.add_argument("--engine", required=True, help="Rocket engine job id or output folder.")
    assemble.add_argument("--hx", required=True, help="Heat exchanger job id or output folder.")
    assemble.add_argument("--output", required=True, help="Assembly STL output path.")

    feedback = sub.add_parser("feedback")
    feedback_sub = feedback.add_subparsers(dest="feedback_command", required=True)
    ingest = feedback_sub.add_parser("ingest")
    ingest.add_argument("--test-data", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("stl_file")
    validate.add_argument("--process", default="lpbf")
    validate.add_argument("--material", default="copper")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "design" and args.design_type == "rocket-engine":
        return _design_rocket(args)
    if args.command == "design" and args.design_type == "heat-exchanger":
        return _design_heat_exchanger(args)
    if args.command == "design" and args.design_type == "actuator":
        return _design_actuator(args)
    if args.command == "feedback" and args.feedback_command == "ingest":
        payload = json.loads(Path(args.test_data).read_text(encoding="utf-8"))
        FeedbackIngester().ingest_hot_fire_data(HotFireTestResult(**payload))
        FeedbackIngester().recalibrate_model()
        print("feedback accepted")
        return 0
    if args.command == "export":
        print(f"export lookup for job {args.job_id}: use API output directory artifacts")
        return 0
    if args.command == "assemble":
        return _assemble_jobs(args)
    if args.command == "validate":
        exists = Path(args.stl_file).exists()
        print(json.dumps({"stl_file": args.stl_file, "exists": exists, "process": args.process, "material": args.material}))
        return 0 if exists else 2
    parser.error("Unsupported command")
    return 2


def _design_rocket(args: argparse.Namespace) -> int:
    spec_data = {
        "thrust_N": parse_quantity(args.thrust, "n"),
        "chamber_pressure_bar": args.chamber_pressure,
        "propellant": args.propellant,
        "material": args.material,
        "manufacturing_process": args.process,
    }
    if args.expansion_ratio is not None:
        spec_data["expansion_ratio"] = args.expansion_ratio
    spec = RocketEngineSpec(**spec_data)
    output_name = _rocket_output_name(spec)
    output_dir = _unique_output_dir(Path(args.output_dir), output_name)
    output_dir.mkdir(parents=True, exist_ok=False)
    job_id = output_dir.name
    channel_count = NovaRP.FAST_PREVIEW_COOLING_CHANNELS if args.fast else None
    mesh_tolerance_mm = FAST_CLI_MESH_TOLERANCE_MM if args.fast else DEFAULT_CLI_MESH_TOLERANCE_MM
    design = NovaRP().design(spec, cooling_channel_count=channel_count)
    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    stl = output_dir / "engine.stl"
    step = output_dir / "engine.step"
    obj = output_dir / "engine.obj"
    report = output_dir / "report.pdf"
    data = output_dir / "data.json"
    exporter.to_stl(design.geometry, str(stl), tolerance=mesh_tolerance_mm)
    exporter.to_step(design.geometry, str(step))
    exporter.to_obj(design.geometry, str(obj), tolerance=mesh_tolerance_mm)
    run = CEMRunResult(job_id=job_id, module="rocket-engine", inputs=spec.model_dump(), design=design)
    reporter.generate_pdf_report(run, str(report))
    data.write_text(json.dumps(reporter.generate_json_data(run), indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "job_id": job_id,
                "output_dir": str(output_dir),
                "stl": str(stl),
                "step": str(step),
                "report": str(report),
                "mesh_tolerance_mm": mesh_tolerance_mm,
                "cooling_channels": design.metadata["nozzle"].get("n_cooling_channels"),
            }
        )
    )
    return 0


def _design_heat_exchanger(args: argparse.Namespace) -> int:
    spec = HeatExchangerSpec(
        hot_fluid=args.hot_fluid,
        cold_fluid=args.cold_fluid,
        duty_kW=args.duty,
        hot_inlet_temp_C=args.hot_inlet,
        hot_outlet_temp_C=args.hot_outlet,
        cold_inlet_temp_C=args.cold_inlet,
        max_pressure_bar=args.max_pressure,
        material=args.material,
        manufacturing_process=args.process,
    )
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    output_name = f"hx_{spec.hot_fluid}_{spec.cold_fluid}_{_format_number_token(spec.duty_kW)}kW_{stamp}"
    output_dir = _unique_output_dir(Path(args.output_dir), output_name)
    output_dir.mkdir(parents=True, exist_ok=False)
    job_id = output_dir.name
    design = NovaHX().design(spec)
    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    stl = output_dir / "heat_exchanger.stl"
    step = output_dir / "heat_exchanger.step"
    report = output_dir / "report.pdf"
    data = output_dir / "data.json"
    exporter.to_stl(design.geometry, str(stl), tolerance=FAST_CLI_MESH_TOLERANCE_MM)
    exporter.to_step(design.geometry, str(step))
    run = CEMRunResult(job_id=job_id, module="heat-exchanger", inputs=spec.model_dump(), design=design)
    reporter.generate_pdf_report(run, str(report))
    data.write_text(json.dumps(reporter.generate_json_data(run), indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "job_id": job_id,
                "output_dir": str(output_dir),
                "stl": str(stl),
                "step": str(step),
                "report": str(report),
                "effectiveness": design.performance.effectiveness,
                "ntu": design.performance.ntu,
                "required_area_m2": design.performance.required_area_m2,
                "pressure_drop_bar": design.performance.pressure_drop_bar,
            }
        )
    )
    return 0


def _design_actuator(args: argparse.Namespace) -> int:
    spec = ActuatorSpec(
        actuator_type="solenoid",
        force_N=args.force,
        stroke_mm=args.stroke,
        voltage_V=args.voltage,
        response_time_ms=args.response_time,
        material=args.material,
        max_temp_C=args.max_temp,
    )
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    output_name = f"actuator_{_format_number_token(spec.force_N)}N_{_format_number_token(spec.stroke_mm)}mm_{stamp}"
    output_dir = _unique_output_dir(Path(args.output_dir), output_name)
    output_dir.mkdir(parents=True, exist_ok=False)
    job_id = output_dir.name
    design = NovaEA().design(spec)
    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    stl = output_dir / "actuator.stl"
    step = output_dir / "actuator.step"
    report = output_dir / "report.pdf"
    data = output_dir / "data.json"
    exporter.to_stl(design.geometry, str(stl), tolerance=FAST_CLI_MESH_TOLERANCE_MM)
    exporter.to_step(design.geometry, str(step))
    run = CEMRunResult(job_id=job_id, module="actuator", inputs=spec.model_dump(), design=design)
    reporter.generate_pdf_report(run, str(report))
    data.write_text(json.dumps(reporter.generate_json_data(run), indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "job_id": job_id,
                "output_dir": str(output_dir),
                "stl": str(stl),
                "step": str(step),
                "report": str(report),
                "force_output_N": design.performance.force_output_N,
                "current_draw_A": design.performance.current_draw_A,
                "power_consumption_W": design.performance.power_consumption_W,
                "response_time_ms": design.performance.response_time_ms,
            }
        )
    )
    return 0


def _assemble_jobs(args: argparse.Namespace) -> int:
    engine_dir = _resolve_job_dir(args.engine)
    hx_dir = _resolve_job_dir(args.hx)
    engine_stl = _find_stl(engine_dir, ("engine.stl",))
    hx_stl = _find_stl(hx_dir, ("heat_exchanger.stl", "hx.stl"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    engine_triangles = _read_stl_triangles(engine_stl)
    hx_triangles = _translate_triangles(_read_stl_triangles(hx_stl), (HX_ASSEMBLY_OFFSET_MM, 0.0, 0.0))
    _write_ascii_multi_body_stl(
        output,
        [
            ("nova_engine", engine_triangles),
            ("nova_heat_exchanger", hx_triangles),
        ],
    )
    report = output.with_suffix(".pdf")
    _write_assembly_report(engine_dir, hx_dir, engine_stl, hx_stl, output, report)
    print(
        json.dumps(
            {
                "engine_job": str(engine_dir),
                "hx_job": str(hx_dir),
                "output": str(output),
                "report": str(report),
                "hx_offset_mm": [HX_ASSEMBLY_OFFSET_MM, 0.0, 0.0],
                "engine_triangles": len(engine_triangles),
                "hx_triangles": len(hx_triangles),
            }
        )
    )
    return 0


def _resolve_job_dir(job_id_or_path: str) -> Path:
    direct = Path(job_id_or_path)
    if direct.is_dir():
        return direct
    is_short_job_id = (
        bool(job_id_or_path)
        and len(job_id_or_path) <= 160
        and not direct.is_absolute()
        and "/" not in job_id_or_path
        and "\\" not in job_id_or_path
    )
    candidates = [
        Path("outputs/cli") / job_id_or_path,
        Path("outputs/jobs") / job_id_or_path,
        Path("outputs/web/jobs") / job_id_or_path,
        Path("outputs/test-artifacts") / job_id_or_path,
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    outputs = Path("outputs")
    if is_short_job_id and outputs.exists():
        for candidate in outputs.rglob(job_id_or_path):
            if candidate.is_dir():
                return candidate
    raise FileNotFoundError(f"Could not find job output folder: {job_id_or_path}")


def _find_stl(job_dir: Path, preferred_names: tuple[str, ...]) -> Path:
    for name in preferred_names:
        candidate = job_dir / name
        if candidate.exists():
            return candidate
    stls = sorted(job_dir.glob("*.stl"))
    if stls:
        return stls[0]
    raise FileNotFoundError(f"No STL artifact found in {job_dir}")


def _read_stl_triangles(path: Path) -> list[StlTriangle]:
    data = path.read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        expected_size = 84 + count * 50
        if expected_size == len(data):
            triangles: list[StlTriangle] = []
            offset = 84
            for _ in range(count):
                values = struct.unpack_from("<12f", data, offset)
                normal = (values[0], values[1], values[2])
                vertices = (
                    (values[3], values[4], values[5]),
                    (values[6], values[7], values[8]),
                    (values[9], values[10], values[11]),
                )
                triangles.append(StlTriangle(normal, vertices))
                offset += 50
            return triangles
    return _read_ascii_stl_triangles(data.decode("utf-8", errors="ignore"))


def _read_ascii_stl_triangles(text: str) -> list[StlTriangle]:
    vertices: list[tuple[float, float, float]] = []
    triangles: list[StlTriangle] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0].lower() == "vertex":
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            if len(vertices) == 3:
                triangle_vertices = (vertices[0], vertices[1], vertices[2])
                triangles.append(StlTriangle(_triangle_normal(triangle_vertices), triangle_vertices))
                vertices = []
    if not triangles:
        raise ValueError("STL file did not contain any triangles")
    return triangles


def _translate_triangles(
    triangles: list[StlTriangle],
    offset: tuple[float, float, float],
) -> list[StlTriangle]:
    return [
        StlTriangle(
            triangle.normal,
            tuple(
                (vertex[0] + offset[0], vertex[1] + offset[1], vertex[2] + offset[2])
                for vertex in triangle.vertices
            ),
        )
        for triangle in triangles
    ]


def _write_ascii_multi_body_stl(path: Path, bodies: list[tuple[str, list[StlTriangle]]]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        for name, triangles in bodies:
            handle.write(f"solid {name}\n")
            for triangle in triangles:
                normal = _triangle_normal(triangle.vertices)
                handle.write(f"  facet normal {normal[0]:.9e} {normal[1]:.9e} {normal[2]:.9e}\n")
                handle.write("    outer loop\n")
                for vertex in triangle.vertices:
                    handle.write(f"      vertex {vertex[0]:.9e} {vertex[1]:.9e} {vertex[2]:.9e}\n")
                handle.write("    endloop\n")
                handle.write("  endfacet\n")
            handle.write(f"endsolid {name}\n")


def _triangle_normal(
    vertices: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]],
) -> tuple[float, float, float]:
    a, b, c = vertices
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length == 0.0:
        return (0.0, 0.0, 0.0)
    return (nx / length, ny / length, nz / length)


def _write_assembly_report(
    engine_dir: Path,
    hx_dir: Path,
    engine_stl: Path,
    hx_stl: Path,
    assembly_stl: Path,
    report_path: Path,
) -> None:
    engine_data = _read_job_data(engine_dir)
    hx_data = _read_job_data(hx_dir)
    lines = [
        "NOVA Assembly Report",
        f"Engine job: {engine_dir.name}",
        f"Heat exchanger job: {hx_dir.name}",
        f"Assembly STL: {assembly_stl}",
        f"Engine STL: {engine_stl}",
        f"Heat exchanger STL: {hx_stl}",
        f"Heat exchanger offset: +{HX_ASSEMBLY_OFFSET_MM:.1f} mm X from engine centerline",
        "",
        "Engine Summary:",
    ]
    lines.extend(_summary_lines(engine_data))
    lines.extend(["", "Heat Exchanger Summary:"])
    lines.extend(_summary_lines(hx_data))
    engine_report = engine_dir / "report.pdf"
    hx_report = hx_dir / "report.pdf"
    lines.extend(["", "Source Reports:"])
    lines.append(f"  Engine report: {engine_report if engine_report.exists() else 'not found'}")
    lines.append(f"  Heat exchanger report: {hx_report if hx_report.exists() else 'not found'}")
    PerformanceReporter()._write_minimal_pdf(str(report_path), "\n".join(lines))


def _read_job_data(job_dir: Path) -> dict:
    data = job_dir / "data.json"
    if not data.exists():
        return {}
    try:
        return json.loads(data.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _summary_lines(payload: dict) -> list[str]:
    performance = payload.get("design", {}).get("performance", {}) if payload else {}
    if not performance:
        return ["  No data.json performance summary available."]
    lines = []
    for key, value in performance.items():
        if isinstance(value, dict):
            continue
        lines.append(f"  {key}: {value}")
    return lines or ["  No scalar performance metrics available."]


if __name__ == "__main__":
    raise SystemExit(main())
