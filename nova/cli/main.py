"""Command-line interface for NOVA."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from nova.core.input_schema import HeatExchangerSpec, HotFireTestResult, RocketEngineSpec
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult, ProcessParams
from nova.feedback import FeedbackIngester
from nova.modules.nova_hx import NovaHX
from nova.modules.nova_rp import NovaRP


DEFAULT_CLI_MESH_TOLERANCE_MM = 0.5
FAST_CLI_MESH_TOLERANCE_MM = 1.0


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

    export = sub.add_parser("export")
    export.add_argument("job_id")
    export.add_argument("--format", nargs="+", default=["stl", "step", "report"])

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
    if args.command == "feedback" and args.feedback_command == "ingest":
        payload = json.loads(Path(args.test_data).read_text(encoding="utf-8"))
        FeedbackIngester().ingest_hot_fire_data(HotFireTestResult(**payload))
        FeedbackIngester().recalibrate_model()
        print("feedback accepted")
        return 0
    if args.command == "export":
        print(f"export lookup for job {args.job_id}: use API output directory artifacts")
        return 0
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


if __name__ == "__main__":
    raise SystemExit(main())
