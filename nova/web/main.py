"""FastAPI web dashboard for NOVA design jobs."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nova.core.input_schema import ActuatorSpec, HeatExchangerSpec, RocketEngineSpec
from nova.core.output import GeometryExporter, PerformanceReporter
from nova.core.types import CEMRunResult, to_jsonable
from nova.modules.nova_ea import NovaEA
from nova.modules.nova_hx import NovaHX
from nova.modules.nova_rp import NovaRP


PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"
OUTPUT_DIR = os.getenv("NOVA_OUTPUT_DIR", "outputs/")
WEB_JOB_ROOT = Path(OUTPUT_DIR) / "web" / "jobs"
JOB_INDEX = WEB_JOB_ROOT / "jobs.json"

app = FastAPI(title="NOVA Web Dashboard", version="1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class DashboardEngineRequest(BaseModel):
    propellant: Literal["kerolox", "methalox", "hydrolox"]
    thrust_N: float = Field(..., gt=1.0)
    chamber_pressure_bar: float = Field(..., ge=1.0)
    material: Literal["copper", "inconel"]


class DashboardHeatExchangerRequest(BaseModel):
    hot_fluid: Literal["exhaust", "air", "water"]
    cold_fluid: Literal["hydrogen", "water", "helium"]
    duty_kW: float = Field(..., gt=0.001)
    hot_inlet_temp_C: float = Field(..., gt=-273.15)
    hot_outlet_temp_C: float = Field(..., gt=-273.15)
    cold_inlet_temp_C: float = Field(..., gt=-273.15)


class DashboardActuatorRequest(BaseModel):
    force_N: float = Field(..., gt=0.0)
    stroke_mm: float = Field(..., gt=0.0)
    voltage_V: float = Field(24.0, gt=0.0)
    response_time_ms: float = Field(50.0, gt=0.0)
    material: Literal["steel", "inconel", "aluminum"] = "steel"


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(INDEX_HTML, media_type="text/html")


@app.post("/api/design")
@app.post("/api/design/rocket-engine")
async def design_engine(request: DashboardEngineRequest) -> dict:
    spec = RocketEngineSpec(
        thrust_N=request.thrust_N,
        chamber_pressure_bar=request.chamber_pressure_bar,
        propellant=request.propellant,
        material=request.material,
        manufacturing_process="lpbf",
    )
    job_id = _unique_job_id("rocket-engine", f"{spec.propellant}_{spec.thrust_N:g}N_{spec.chamber_pressure_bar:g}bar")
    job_dir = WEB_JOB_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    try:
        design = NovaRP().design(spec)
        files = _export_dashboard_artifacts(job_id, spec, design, job_dir)
        record = _job_record(
            job_id=job_id,
            module="rocket-engine",
            parameters={
                "propellant": spec.propellant,
                "thrust_N": spec.thrust_N,
                "chamber_pressure_bar": spec.chamber_pressure_bar,
                "material": spec.material,
                "expansion_ratio": design.performance.expansion_ratio,
            },
            metrics=_engine_metrics(design),
            validation=_validation_results(design),
            files=files,
        )
        _prepend_history(record)
        return {"job": _public_record(record)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/design/heat-exchanger")
async def design_heat_exchanger(request: DashboardHeatExchangerRequest) -> dict:
    spec = HeatExchangerSpec(
        hot_fluid=request.hot_fluid,
        cold_fluid=request.cold_fluid,
        duty_kW=request.duty_kW,
        hot_inlet_temp_C=request.hot_inlet_temp_C,
        hot_outlet_temp_C=request.hot_outlet_temp_C,
        cold_inlet_temp_C=request.cold_inlet_temp_C,
        max_pressure_bar=1.0,
        material="inconel",
        manufacturing_process="lpbf",
    )
    job_id = _unique_job_id("heat-exchanger", f"hx_{spec.hot_fluid}_{spec.cold_fluid}_{spec.duty_kW:g}kW")
    job_dir = WEB_JOB_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    try:
        design = NovaHX().design(spec)
        files = _export_module_artifacts(job_id, "heat-exchanger", spec.model_dump(), design, job_dir, "heat_exchanger")
        record = _job_record(
            job_id=job_id,
            module="heat-exchanger",
            parameters=spec.model_dump(),
            metrics=_hx_metrics(design),
            validation=_validation_results(design),
            files=files,
        )
        _prepend_history(record)
        return {"job": _public_record(record)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/design/actuator")
async def design_actuator(request: DashboardActuatorRequest) -> dict:
    spec = ActuatorSpec(
        actuator_type="solenoid",
        force_N=request.force_N,
        stroke_mm=request.stroke_mm,
        voltage_V=request.voltage_V,
        response_time_ms=request.response_time_ms,
        material=request.material,
    )
    job_id = _unique_job_id("actuator", f"{spec.force_N:g}N_{spec.stroke_mm:g}mm")
    job_dir = WEB_JOB_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=False)

    try:
        design = NovaEA().design(spec)
        files = _export_module_artifacts(job_id, "actuator", spec.model_dump(), design, job_dir, "actuator")
        record = _job_record(
            job_id=job_id,
            module="actuator",
            parameters=spec.model_dump(),
            metrics=_actuator_metrics(design),
            validation=_validation_results(design),
            files=files,
        )
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
    return _export_module_artifacts(job_id, "rocket-engine", spec.model_dump(), design, job_dir, "engine")


def _export_module_artifacts(
    job_id: str,
    module: str,
    inputs: dict,
    design: object,
    job_dir: Path,
    artifact_basename: str,
) -> dict[str, str]:
    exporter = GeometryExporter()
    reporter = PerformanceReporter()
    stl = job_dir / f"{artifact_basename}.stl"
    step = job_dir / f"{artifact_basename}.step"
    report = job_dir / "report.pdf"
    data = job_dir / "data.json"

    files: dict[str, str] = {}
    if getattr(design, "geometry", None) is not None:
        exporter.to_stl(design.geometry, str(stl))
        exporter.to_step(design.geometry, str(step))
        files.update({"stl": str(stl), "step": str(step)})
    run = CEMRunResult(job_id=job_id, module=module, inputs=inputs, design=design)
    reporter.generate_pdf_report(run, str(report))
    data.write_text(json.dumps(reporter.generate_json_data(run), indent=2), encoding="utf-8")
    files.update({"report": str(report), "json": str(data)})
    return files


def _job_record(
    *,
    job_id: str,
    module: str,
    parameters: dict,
    metrics: dict[str, float],
    validation: dict,
    files: dict[str, str],
) -> dict:
    return {
        "job_id": job_id,
        "module": module,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "parameters": parameters,
        "metrics": metrics,
        "validation": validation,
        "files": _download_urls(job_id, files),
        "artifact_paths": files,
    }


def _engine_metrics(design: object) -> dict[str, float]:
    return {
        "specific_impulse_s": round(float(design.performance.specific_impulse_s), 2),
        "thrust_N": round(float(design.performance.thrust_N), 2),
        "chamber_temp_K": round(float(design.performance.chamber_temp_K), 2),
        "engine_mass_kg": round(float(design.mass_kg), 3),
        "print_time_hours": round(float(design.manufacturing.estimated_print_time_hours), 2),
    }


def _hx_metrics(design: object) -> dict[str, float]:
    return {
        "effectiveness": round(float(design.performance.effectiveness), 3),
        "ntu": round(float(design.performance.ntu), 3),
        "required_area_m2": round(float(design.performance.required_area_m2), 4),
        "pressure_drop_bar": round(float(design.performance.pressure_drop_bar), 4),
        "cold_outlet_temp_C": round(float(design.performance.cold_outlet_temp_C), 2),
    }


def _actuator_metrics(design: object) -> dict[str, float]:
    return {
        "force_output_N": round(float(design.performance.force_output_N), 2),
        "current_draw_A": round(float(design.performance.current_draw_A), 3),
        "power_consumption_W": round(float(design.performance.power_consumption_W), 2),
        "response_time_ms": round(float(design.performance.response_time_ms), 2),
    }


def _download_urls(job_id: str, files: dict[str, str]) -> dict[str, str]:
    urls = {"report": f"/download/{job_id}/report"}
    if "stl" in files:
        urls["stl"] = f"/download/{job_id}/stl"
    if "step" in files:
        urls["step"] = f"/download/{job_id}/step"
    return urls


def _public_record(record: dict) -> dict:
    return {
        "job_id": record["job_id"],
        "module": record.get("module", "rocket-engine"),
        "created_at": record["created_at"],
        "parameters": record["parameters"],
        "metrics": record["metrics"],
        "validation": record.get("validation"),
        "files": record["files"],
    }


def _validation_results(design: object) -> dict:
    validation = getattr(design, "validation", None)
    return to_jsonable(validation) if validation is not None else {"passed": True, "checks": []}


def _unique_job_id(module: str, label: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    base = _slug(f"{module}_{label}_{stamp}")
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
