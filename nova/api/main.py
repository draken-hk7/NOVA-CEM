"""FastAPI wrapper for NOVA design jobs."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from nova.core.input_schema import (
    EngineDesignResponse,
    FeedbackResponse,
    HeatExchangerSpec,
    HotFireTestResult,
    HXDesignResponse,
    JobStatus,
    RocketEngineSpec,
)
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult, to_jsonable
from nova.feedback import FeedbackIngester
from nova.modules.nova_hx import NovaHX
from nova.modules.nova_rp import NovaRP

app = FastAPI(title="NOVA CEM API", version="1.0")

JOB_ROOT = Path("outputs/jobs")
JOBS: dict[str, dict] = {}


@app.post("/design/rocket-engine", response_model=EngineDesignResponse)
async def design_rocket_engine(spec: RocketEngineSpec) -> EngineDesignResponse:
    """Submit a rocket engine spec. Returns design files and performance data."""

    job_id = str(uuid.uuid4())
    job_dir = JOB_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    JOBS[job_id] = {"status": "running", "module": "nova_rp", "dir": str(job_dir)}
    try:
        design = NovaRP().design(spec)
        files = _export_design(job_id, "rocket-engine", spec.model_dump(), design, job_dir)
        JOBS[job_id].update({"status": "completed", "files": files, "design": design})
        warnings = [warning.message for warning in design.manufacturing.warnings]
        warnings.extend(check.message for check in design.validation.checks if not check.passed)
        return EngineDesignResponse(job_id=job_id, status="completed", performance=to_jsonable(design.performance), files=files, warnings=warnings)
    except Exception as exc:
        JOBS[job_id].update({"status": "failed", "detail": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/design/heat-exchanger", response_model=HXDesignResponse)
async def design_heat_exchanger(spec: HeatExchangerSpec) -> HXDesignResponse:
    job_id = str(uuid.uuid4())
    job_dir = JOB_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    JOBS[job_id] = {"status": "running", "module": "nova_hx", "dir": str(job_dir)}
    try:
        design = NovaHX().design(spec)
        exporter = GeometryExporter()
        stl = job_dir / "heat_exchanger.stl"
        step = job_dir / "heat_exchanger.step"
        report = job_dir / "report.pdf"
        data = job_dir / "data.json"
        exporter.to_stl(design.geometry, str(stl))
        exporter.to_step(design.geometry, str(step))
        run = CEMRunResult(job_id=job_id, module="heat-exchanger", inputs=spec.model_dump(), design=design)
        reporter = PerformanceReporter()
        reporter.generate_pdf_report(run, str(report))
        data.write_text(__import__("json").dumps(reporter.generate_json_data(run), indent=2), encoding="utf-8")
        files = {"stl": str(stl), "step": str(step), "report": str(report), "json": str(data)}
        JOBS[job_id].update({"status": "completed", "files": files, "design": design})
        return HXDesignResponse(job_id=job_id, status="completed", performance=to_jsonable(design.performance), files=files)
    except Exception as exc:
        JOBS[job_id].update({"status": "failed", "detail": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/design/{job_id}/status", response_model=JobStatus)
async def get_design_status(job_id: str) -> JobStatus:
    job = JOBS.get(job_id)
    if not job:
        return JobStatus(job_id=job_id, status="not_found", detail="Unknown job id")
    return JobStatus(job_id=job_id, status=job["status"], detail=job.get("detail", ""))


@app.get("/design/{job_id}/download/stl")
async def download_stl(job_id: str) -> FileResponse:
    path = _file_for(job_id, "stl")
    return FileResponse(path, media_type="model/stl", filename=Path(path).name)


@app.get("/design/{job_id}/download/report")
async def download_report(job_id: str) -> FileResponse:
    path = _file_for(job_id, "report")
    return FileResponse(path, media_type="application/pdf", filename=Path(path).name)


@app.post("/feedback/hot-fire", response_model=FeedbackResponse)
async def submit_test_data(data: HotFireTestResult) -> FeedbackResponse:
    ingester = FeedbackIngester()
    ingester.ingest_hot_fire_data(data)
    ingester.recalibrate_model()
    return FeedbackResponse(accepted=True, records=1, message="Hot-fire data ingested and coefficients recalibrated")


def _export_design(job_id: str, module: str, inputs: dict, design: object, job_dir: Path) -> dict[str, str]:
    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    stl = job_dir / "engine.stl"
    step = job_dir / "engine.step"
    obj = job_dir / "engine.obj"
    threemf = job_dir / "engine.3mf"
    report = job_dir / "report.pdf"
    data = job_dir / "data.json"
    files: dict[str, str] = {}
    if getattr(design, "geometry", None) is not None:
        exporter.to_stl(design.geometry, str(stl))
        exporter.to_step(design.geometry, str(step))
        exporter.to_obj(design.geometry, str(obj))
        exporter.to_3mf(design.geometry, str(threemf))
        files.update({"stl": str(stl), "step": str(step), "obj": str(obj), "3mf": str(threemf)})
    run = CEMRunResult(job_id=job_id, module=module, inputs=inputs, design=design, files=files)
    reporter.generate_pdf_report(run, str(report))
    data.write_text(__import__("json").dumps(reporter.generate_json_data(run), indent=2), encoding="utf-8")
    files.update({"report": str(report), "json": str(data)})
    return files


def _file_for(job_id: str, kind: str) -> str:
    job = JOBS.get(job_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Completed job not found")
    files = job.get("files", {})
    if kind not in files:
        raise HTTPException(status_code=404, detail=f"{kind} artifact not found")
    return files[kind]
