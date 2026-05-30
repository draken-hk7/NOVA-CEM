"""Command-line interface for NOVA."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from nova.core.input_schema import HotFireTestResult, RocketEngineSpec
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult, ProcessParams
from nova.feedback import FeedbackIngester
from nova.modules.nova_rp import NovaRP


def parse_quantity(value: str, unit: str) -> float:
    cleaned = value.strip().lower().replace(unit.lower(), "")
    return float(cleaned)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova")
    sub = parser.add_subparsers(dest="command", required=True)

    design = sub.add_parser("design")
    design_sub = design.add_subparsers(dest="design_type", required=True)
    rocket = design_sub.add_parser("rocket-engine")
    rocket.add_argument("--thrust", required=True, help="Target thrust, e.g. 5000N")
    rocket.add_argument("--propellant", required=True, choices=["kerolox", "methalox", "hypergolic", "solid"])
    rocket.add_argument("--chamber-pressure", type=float, default=50.0)
    rocket.add_argument("--expansion-ratio", type=float, default=8.0)
    rocket.add_argument("--material", default="copper", choices=["copper", "inconel", "inconel718", "titanium", "steel"])
    rocket.add_argument("--process", default="lpbf", choices=["lpbf", "ebm", "directed_energy", "machined"])
    rocket.add_argument("--output-dir", default="outputs/cli")

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
    job_id = str(uuid.uuid4())
    output_dir = Path(args.output_dir) / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    spec = RocketEngineSpec(
        thrust_N=parse_quantity(args.thrust, "n"),
        chamber_pressure_bar=args.chamber_pressure,
        propellant=args.propellant,
        expansion_ratio=args.expansion_ratio,
        material=args.material,
        manufacturing_process=args.process,
    )
    design = NovaRP().design(spec)
    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    stl = output_dir / "engine.stl"
    step = output_dir / "engine.step"
    obj = output_dir / "engine.obj"
    report = output_dir / "report.pdf"
    data = output_dir / "data.json"
    exporter.to_stl(design.geometry, str(stl))
    exporter.to_step(design.geometry, str(step))
    exporter.to_obj(design.geometry, str(obj))
    run = CEMRunResult(job_id=job_id, module="rocket-engine", inputs=spec.model_dump(), design=design)
    reporter.generate_pdf_report(run, str(report))
    data.write_text(json.dumps(reporter.generate_json_data(run), indent=2), encoding="utf-8")
    print(json.dumps({"job_id": job_id, "output_dir": str(output_dir), "stl": str(stl), "step": str(step), "report": str(report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

