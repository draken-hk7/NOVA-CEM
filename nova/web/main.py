"""FastAPI web dashboard for NOVA design jobs."""

from __future__ import annotations

import json
import os
import re
import shutil
from csv import DictWriter
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nova.core.input_schema import ActuatorSpec, HeatExchangerSpec, RocketEngineSpec
from nova.core.mission import calculate_mission, mission_report_text
from nova.core.output import GeometryExporter, PerformanceReporter, generate_trajectory_svg
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


class DashboardMissionRequest(BaseModel):
    engine_job_id: str = Field(..., min_length=1)
    vehicle_mass_kg: float = Field(..., gt=0.0)
    propellant_mass_kg: float = Field(..., gt=0.0)
    planned_launches_per_month: float = Field(1.0, gt=0.0)


class StarJobRequest(BaseModel):
    starred: bool


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
            metadata=_design_metadata(design),
            design_log=_design_log(design),
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
            metadata=_design_metadata(design),
            design_log=_design_log(design),
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
            metadata=_design_metadata(design),
            design_log=_design_log(design),
        )
        _prepend_history(record)
        return {"job": _public_record(record)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/mission")
async def run_mission(request: DashboardMissionRequest) -> dict:
    try:
        engine_payload = _engine_payload_for_mission(request.engine_job_id)
        result = calculate_mission(
            engine_payload,
            vehicle_mass_kg=request.vehicle_mass_kg,
            propellant_mass_kg=request.propellant_mass_kg,
            engine_job_id=request.engine_job_id,
            planned_launches_per_month=request.planned_launches_per_month,
        )
        job_id = _unique_job_id(
            "mission",
            f"{request.engine_job_id}_{request.vehicle_mass_kg:g}kg_{request.propellant_mass_kg:g}kg",
        )
        job_dir = WEB_JOB_ROOT / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        files = _export_mission_artifacts(job_id, request, result, job_dir)
        record = _job_record(
            job_id=job_id,
            module="mission",
            parameters={
                "engine_job_id": request.engine_job_id,
                "vehicle_mass_kg": request.vehicle_mass_kg,
                "propellant_mass_kg": request.propellant_mass_kg,
                "planned_launches_per_month": request.planned_launches_per_month,
            },
            metrics=_mission_metrics(result),
            validation={"passed": True, "checks": []},
            files=files,
            metadata={},
            design_log=[
                "Loading engine performance",
                "Applying Tsiolkovsky rocket equation",
                "Estimating burn time and altitude",
            ],
        )
        _prepend_history(record)
        return {"job": _public_record(record), "mission": to_jsonable(result)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/history")
async def history() -> dict:
    return {"jobs": [_public_record(job) for job in _sorted_history(_read_history())]}


@app.get("/api/history/export.csv")
async def export_history_csv() -> Response:
    content = _history_csv(_sorted_history(_read_history()))
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="nova_history.csv"'},
    )


@app.patch("/api/jobs/{job_id}/star")
async def star_job(job_id: str, request: StarJobRequest) -> dict:
    jobs = _read_history()
    for job in jobs:
        if job.get("job_id") == job_id:
            job["starred"] = request.starred
            _write_history(_sorted_history(jobs))
            return {"job": _public_record(job)}
    raise HTTPException(status_code=404, detail="Job not found")


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str) -> dict:
    jobs = _read_history()
    record = next((job for job in jobs if job.get("job_id") == job_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if record.get("starred"):
        raise HTTPException(status_code=409, detail="Starred jobs are protected from deletion")

    _delete_job_folder(job_id)
    remaining = [job for job in jobs if job.get("job_id") != job_id]
    _write_history(_sorted_history(remaining))
    return {"deleted": True, "job_id": job_id}


@app.get("/download/{job_id}/{artifact}")
async def download_artifact(job_id: str, artifact: Literal["stl", "step", "report", "thermal_map", "engineering_drawing", "trajectory"]) -> FileResponse:
    record = _find_job(job_id)
    path = _artifact_path(record, artifact)
    media_types = {
        "stl": "model/stl",
        "step": "application/step",
        "report": "application/pdf",
        "thermal_map": "image/svg+xml",
        "engineering_drawing": "application/pdf",
        "trajectory": "image/svg+xml",
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
    run = CEMRunResult(job_id=job_id, module=module, inputs=inputs, design=design, files=files)
    reporter.generate_pdf_report(run, str(report))
    data.write_text(json.dumps(reporter.generate_json_data(run), indent=2), encoding="utf-8")
    files.update({"report": str(report), "json": str(data)})
    return files


def _export_mission_artifacts(
    job_id: str,
    request: DashboardMissionRequest,
    result: object,
    job_dir: Path,
) -> dict[str, str]:
    report = job_dir / "mission_report.pdf"
    trajectory = job_dir / "trajectory.svg"
    data = job_dir / "data.json"
    files = {"report": str(report), "trajectory": str(trajectory), "json": str(data)}
    PerformanceReporter()._write_minimal_pdf(str(report), mission_report_text(result))
    generate_trajectory_svg(result, trajectory)
    data.write_text(
        json.dumps(
            {
                "job_id": job_id,
                "module": "mission",
                "inputs": request.model_dump(),
                "mission": to_jsonable(result),
                "files": files,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return files


def _job_record(
    *,
    job_id: str,
    module: str,
    parameters: dict,
    metrics: dict[str, float],
    validation: dict,
    files: dict[str, str],
    metadata: dict | None = None,
    design_log: list[str] | None = None,
) -> dict:
    return {
        "job_id": job_id,
        "module": module,
        "starred": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "parameters": parameters,
        "metrics": metrics,
        "validation": validation,
        "metadata": metadata or {},
        "design_log": design_log or [],
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


def _mission_metrics(result: object) -> dict[str, float]:
    return {
        "delta_v_m_s": round(float(result.delta_v_m_s), 2),
        "burn_time_s": round(float(result.burn_time_s), 2),
        "thrust_to_weight": round(float(result.thrust_to_weight), 3),
        "max_altitude_m": round(float(result.max_altitude_m), 2),
        "hydrogen_mass_needed_kg_s": round(float(result.hydrogen_mass_needed_kg_s), 6),
        "burnout_altitude_m": round(float(result.burnout_altitude_m), 2),
        "coast_altitude_m": round(float(result.coast_altitude_m), 2),
        "solar_energy_kwh_per_day": round(float(result.solar_energy_kwh_per_day), 3),
    }


def _download_urls(job_id: str, files: dict[str, str]) -> dict[str, str]:
    urls = {"report": f"/download/{job_id}/report"}
    if "stl" in files:
        urls["stl"] = f"/download/{job_id}/stl"
    if "step" in files:
        urls["step"] = f"/download/{job_id}/step"
    if "thermal_map" in files:
        urls["thermal_map"] = f"/download/{job_id}/thermal_map"
    if "engineering_drawing" in files:
        urls["engineering_drawing"] = f"/download/{job_id}/engineering_drawing"
    if "trajectory" in files:
        urls["trajectory"] = f"/download/{job_id}/trajectory"
    return urls


def _public_record(record: dict) -> dict:
    return {
        "job_id": record["job_id"],
        "module": record.get("module", "rocket-engine"),
        "starred": bool(record.get("starred", False)),
        "created_at": record["created_at"],
        "parameters": record["parameters"],
        "metrics": record["metrics"],
        "validation": record.get("validation"),
        "metadata": record.get("metadata", {}),
        "design_log": record.get("design_log", []),
        "files": record["files"],
        "size_bytes": _job_size_bytes(record),
    }


def _job_size_bytes(record: dict) -> int:
    total = 0
    for value in record.get("artifact_paths", {}).values():
        path = Path(value)
        try:
            if path.exists() and path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _validation_results(design: object) -> dict:
    validation = getattr(design, "validation", None)
    return to_jsonable(validation) if validation is not None else {"passed": True, "checks": []}


def _design_metadata(design: object) -> dict:
    return to_jsonable(getattr(design, "metadata", {}) or {})


def _design_log(design: object) -> list[str]:
    trace = getattr(design, "trace", None) or []
    entries: list[str] = []
    for item in to_jsonable(trace):
        if not isinstance(item, dict):
            continue
        requirement = item.get("requirement", "design step")
        calculation = item.get("calculation", "calculation")
        parameter = item.get("geometry_parameter", "result")
        value = item.get("value", "")
        unit = item.get("unit", "")
        entries.append(f"{requirement}: {calculation} -> {parameter} {value} {unit}".strip())
    return entries


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
    _write_history(_sorted_history(jobs))


def _sorted_history(jobs: list[dict]) -> list[dict]:
    newest_first = sorted(jobs, key=lambda job: str(job.get("created_at", "")), reverse=True)
    return sorted(newest_first, key=lambda job: 0 if job.get("starred") else 1)


def _delete_job_folder(job_id: str) -> None:
    root = WEB_JOB_ROOT.resolve()
    job_dir = (WEB_JOB_ROOT / job_id).resolve()
    if not job_dir.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid job path")
    if job_dir.exists():
        shutil.rmtree(job_dir)


def _engine_payload_for_mission(engine_job_id: str) -> dict:
    if "/" in engine_job_id or "\\" in engine_job_id:
        raise HTTPException(status_code=400, detail="Engine job id must not contain path separators")
    try:
        record = _find_job(engine_job_id)
    except HTTPException:
        record = None
    if record is not None:
        if record.get("module", "rocket-engine") != "rocket-engine":
            raise HTTPException(status_code=400, detail="Mission calculator requires a rocket engine job")
        path_text = record.get("artifact_paths", {}).get("json")
        if path_text:
            path = Path(path_text).resolve()
            root = WEB_JOB_ROOT.resolve()
            if path.is_relative_to(root) and path.exists():
                return _read_json_file(path)
        return {
            "inputs": record.get("parameters", {}),
            "design": {"performance": record.get("metrics", {}), "metadata": {}},
        }

    for candidate in (
        WEB_JOB_ROOT / engine_job_id / "data.json",
        Path("outputs/cli") / engine_job_id / "data.json",
        Path("outputs/jobs") / engine_job_id / "data.json",
    ):
        if candidate.exists():
            payload = _read_json_file(candidate)
            if payload.get("module") not in (None, "rocket-engine"):
                raise HTTPException(status_code=400, detail="Mission calculator requires a rocket engine job")
            return payload
    raise HTTPException(status_code=404, detail="Engine job not found")


def _read_json_file(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {path.name}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {path.name}")
    return payload


def _history_csv(jobs: list[dict]) -> str:
    rows = [_flatten_history_row(job) for job in jobs]
    default_columns = ["job_id", "module", "starred", "created_at"]
    dynamic_columns = sorted({key for row in rows for key in row if key not in default_columns})
    columns = default_columns + dynamic_columns
    output = StringIO()
    writer = DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _flatten_history_row(job: dict) -> dict[str, object]:
    row = {
        "job_id": job.get("job_id", ""),
        "module": job.get("module", "rocket-engine"),
        "starred": bool(job.get("starred", False)),
        "created_at": job.get("created_at", ""),
    }
    for prefix, payload in (("parameter", job.get("parameters", {})), ("metric", job.get("metrics", {}))):
        if isinstance(payload, dict):
            for key, value in payload.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    row[f"{prefix}_{key}"] = value
    return row


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
