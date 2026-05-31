"""FastAPI web dashboard for NOVA rocket engine design jobs."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nova.core.input_schema import RocketEngineSpec
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult, to_jsonable
from nova.modules.nova_rp import NovaRP


PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"
WEB_JOB_ROOT = Path("outputs/web/jobs")
JOB_INDEX = WEB_JOB_ROOT / "jobs.json"

app = FastAPI(title="NOVA Web Dashboard", version="1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class DashboardDesignRequest(BaseModel):
    propellant: Literal["kerolox", "methalox", "hydrolox"]
    thrust_N: float = Field(..., gt=1.0)
    chamber_pressure_bar: float = Field(..., ge=1.0)
    material: Literal["copper", "inconel"]


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(INDEX_HTML, media_type="text/html")


@app.post("/api/design")
async def design_engine(request: DashboardDesignRequest) -> dict:
    spec = RocketEngineSpec(
        thrust_N=request.thrust_N,
        chamber_pressure_bar=request.chamber_pressure_bar,
        propellant=request.propellant,
        material=request.material,
        manufacturing_process="lpbf",
    )
    job_id = _unique_job_id(spec)
    job_dir = WEB_JOB_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    try:
        design = NovaRP().design(spec)
        files = _export_dashboard_artifacts(job_id, spec, design, job_dir)
        record = {
            "job_id": job_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "parameters": {
                "propellant": spec.propellant,
                "thrust_N": spec.thrust_N,
                "chamber_pressure_bar": spec.chamber_pressure_bar,
                "material": spec.material,
                "expansion_ratio": design.performance.expansion_ratio,
            },
            "metrics": _metrics(design),
            "validation": _validation_results(design),
            "files": _download_urls(job_id),
            "artifact_paths": files,
        }
        _prepend_history(record)
        return {"job": _public_record(record)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/history")
async def history() -> dict:
    return {"jobs": [_public_record(job) for job in _read_history()]}


@app.get("/download/{job_id}/{artifact}")
async def download_artifact(job_id: str, artifact: Literal["stl", "step", "report"]) -> FileResponse:
    record = _find_job(job_id)
    path = _artifact_path(record, artifact)
    media_types = {
        "stl": "model/stl",
        "step": "application/step",
        "report": "application/pdf",
    }
    return FileResponse(path, media_type=media_types[artifact], filename=path.name)


def _export_dashboard_artifacts(job_id: str, spec: RocketEngineSpec, design: object, job_dir: Path) -> dict[str, str]:
    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    stl = job_dir / "engine.stl"
    step = job_dir / "engine.step"
    report = job_dir / "report.pdf"
    data = job_dir / "data.json"

    exporter.to_stl(design.geometry, str(stl))
    exporter.to_step(design.geometry, str(step))
    run = CEMRunResult(job_id=job_id, module="rocket-engine", inputs=spec.model_dump(), design=design)
    reporter.generate_pdf_report(run, str(report))
    data.write_text(json.dumps(reporter.generate_json_data(run), indent=2), encoding="utf-8")
    return {"stl": str(stl), "step": str(step), "report": str(report), "json": str(data)}


def _metrics(design: object) -> dict[str, float]:
    return {
        "specific_impulse_s": round(float(design.performance.specific_impulse_s), 2),
        "thrust_N": round(float(design.performance.thrust_N), 2),
        "chamber_temp_K": round(float(design.performance.chamber_temp_K), 2),
        "engine_mass_kg": round(float(design.mass_kg), 3),
        "print_time_hours": round(float(design.manufacturing.estimated_print_time_hours), 2),
    }


def _download_urls(job_id: str) -> dict[str, str]:
    return {
        "stl": f"/download/{job_id}/stl",
        "step": f"/download/{job_id}/step",
        "report": f"/download/{job_id}/report",
    }


def _public_record(record: dict) -> dict:
    return {
        "job_id": record["job_id"],
        "created_at": record["created_at"],
        "parameters": record["parameters"],
        "metrics": record["metrics"],
        "validation": record.get("validation"),
        "files": record["files"],
    }


def _validation_results(design: object) -> dict:
    validation = getattr(design, "validation", None)
    return to_jsonable(validation) if validation is not None else {"passed": True, "checks": []}


def _unique_job_id(spec: RocketEngineSpec) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = _slug(f"{spec.propellant}_{spec.thrust_N:g}N_{spec.chamber_pressure_bar:g}bar_{stamp}")
    candidate = base
    for index in range(2, 1000):
        if not (WEB_JOB_ROOT / candidate).exists():
            return candidate
        candidate = f"{base}_{index:02d}"
    raise FileExistsError(f"Could not create a unique job id for {base}")


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_")


def _read_history() -> list[dict]:
    if not JOB_INDEX.exists():
        return []
    try:
        payload = json.loads(JOB_INDEX.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    jobs = payload.get("jobs", [])
    return jobs if isinstance(jobs, list) else []


def _write_history(jobs: list[dict]) -> None:
    WEB_JOB_ROOT.mkdir(parents=True, exist_ok=True)
    JOB_INDEX.write_text(json.dumps({"jobs": jobs}, indent=2), encoding="utf-8")


def _prepend_history(record: dict) -> None:
    jobs = [job for job in _read_history() if job.get("job_id") != record["job_id"]]
    jobs.insert(0, record)
    _write_history(jobs)


def _find_job(job_id: str) -> dict:
    for job in _read_history():
        if job.get("job_id") == job_id:
            return job
    raise HTTPException(status_code=404, detail="Job not found")


def _artifact_path(record: dict, artifact: str) -> Path:
    paths = record.get("artifact_paths", {})
    if artifact not in paths:
        raise HTTPException(status_code=404, detail=f"{artifact} artifact not found")
    path = Path(paths[artifact]).resolve()
    root = WEB_JOB_ROOT.resolve()
    if not path.is_relative_to(root) or not path.exists():
        raise HTTPException(status_code=404, detail=f"{artifact} artifact not found")
    return path
