"""Strict input and API schemas for NOVA engineering jobs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nova.core.exceptions import PhysicsViolationError
from nova.core.knowledge_engine.rules import get_material_properties, normalize_material


def unit(unit_name: str) -> dict[str, str]:
    return {"unit": unit_name}


class EngineeringBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RocketEngineSpec(EngineeringBaseModel):
    thrust_N: float = Field(
        ...,
        gt=1.0,
        le=5.0e7,
        description="Target vacuum/near-sea-level thrust.",
        json_schema_extra=unit("N"),
    )
    chamber_pressure_bar: float = Field(
        ...,
        ge=1.0,
        le=5000.0,
        description="Combustion chamber stagnation pressure.",
        json_schema_extra=unit("bar"),
    )
    propellant: Literal["kerolox", "methalox", "hypergolic", "solid"]
    expansion_ratio: float = Field(
        8.0,
        ge=1.01,
        le=300.0,
        description="Nozzle exit area divided by throat area.",
        json_schema_extra=unit("dimensionless"),
    )
    nozzle_type: Literal["bell", "aerospike", "plug"] = "bell"
    material: Literal["copper", "inconel", "inconel718", "titanium", "steel"] = "copper"
    cooling: Literal["regenerative", "ablative", "film", "radiative"] = "regenerative"
    max_outer_diameter_mm: float | None = Field(
        None,
        gt=5.0,
        le=10000.0,
        description="Maximum allowable engine outer diameter.",
        json_schema_extra=unit("mm"),
    )
    length_constraint_mm: float | None = Field(
        None,
        gt=10.0,
        le=100000.0,
        description="Maximum allowable overall engine length.",
        json_schema_extra=unit("mm"),
    )
    manufacturing_process: Literal["lpbf", "ebm", "directed_energy", "machined"] = "lpbf"
    safety_factor: float = Field(
        2.0,
        ge=1.1,
        le=10.0,
        description="Minimum required structural safety factor.",
        json_schema_extra=unit("dimensionless"),
    )

    @model_validator(mode="after")
    def validate_physics_and_process(self) -> "RocketEngineSpec":
        material_key = normalize_material(self.material)
        material = get_material_properties(material_key)
        process = self.manufacturing_process
        if process not in material["compatible_processes"]:
            raise PhysicsViolationError(
                f"{self.material} is not compatible with {process}",
                requirement="material/process compatibility",
            )

        pressure_MPa = self.chamber_pressure_bar * 0.1
        allowable_MPa = material["yield_strength_mpa"] / self.safety_factor
        if pressure_MPa > allowable_MPa:
            raise PhysicsViolationError(
                "Chamber pressure exceeds material yield limit divided by safety factor",
                requirement="chamber pressure",
                actual=pressure_MPa,
                limit=allowable_MPa,
                unit=" MPa",
            )

        if self.propellant == "solid" and self.cooling == "regenerative":
            raise PhysicsViolationError(
                "Solid rocket motors cannot use regenerative liquid cooling",
                requirement="propellant/cooling compatibility",
            )
        if self.nozzle_type in {"aerospike", "plug"} and self.expansion_ratio < 3.0:
            raise PhysicsViolationError(
                "Aerospike/plug nozzles require a practical expansion ratio above 3",
                requirement="expansion ratio",
                actual=self.expansion_ratio,
                limit=3.0,
            )
        return self


class HeatExchangerSpec(EngineeringBaseModel):
    heat_duty_W: float = Field(..., gt=1.0, le=1.0e9, json_schema_extra=unit("W"))
    hot_inlet_K: float = Field(..., gt=1.0, le=2500.0, json_schema_extra=unit("K"))
    hot_outlet_K: float = Field(..., gt=1.0, le=2500.0, json_schema_extra=unit("K"))
    cold_inlet_K: float = Field(..., gt=1.0, le=2500.0, json_schema_extra=unit("K"))
    cold_outlet_K: float = Field(..., gt=1.0, le=2500.0, json_schema_extra=unit("K"))
    hot_fluid: str = Field("water", min_length=1)
    cold_fluid: str = Field("water", min_length=1)
    max_pressure_drop_bar: float = Field(1.0, gt=0.0, le=1000.0, json_schema_extra=unit("bar"))
    material: Literal["copper", "inconel", "inconel718", "titanium", "steel"] = "copper"
    architecture: Literal["shell_and_tube", "plate_fin", "gyroid", "schwartz_p"] = "shell_and_tube"
    manufacturing_process: Literal["lpbf", "ebm", "directed_energy", "machined"] = "lpbf"

    @model_validator(mode="after")
    def validate_heat_flow(self) -> "HeatExchangerSpec":
        if self.hot_outlet_K >= self.hot_inlet_K:
            raise PhysicsViolationError(
                "Hot stream outlet must be cooler than inlet",
                requirement="hot-side energy balance",
                actual=self.hot_outlet_K,
                limit=self.hot_inlet_K,
                unit=" K",
            )
        if self.cold_outlet_K <= self.cold_inlet_K:
            raise PhysicsViolationError(
                "Cold stream outlet must be warmer than inlet",
                requirement="cold-side energy balance",
                actual=self.cold_outlet_K,
                limit=self.cold_inlet_K,
                unit=" K",
            )
        return self


class ElectromagneticActuatorSpec(EngineeringBaseModel):
    target_torque_Nm: float = Field(..., gt=0.0, le=1.0e7, json_schema_extra=unit("N*m"))
    bus_voltage_V: float = Field(..., gt=0.0, le=50000.0, json_schema_extra=unit("V"))
    max_current_A: float = Field(..., gt=0.0, le=1.0e6, json_schema_extra=unit("A"))
    rpm: float = Field(3000.0, ge=0.0, le=250000.0, json_schema_extra=unit("rev/min"))
    duty_cycle: float = Field(1.0, gt=0.0, le=1.0, json_schema_extra=unit("fraction"))
    cooling: Literal["air", "liquid", "oil"] = "air"
    core_material: Literal["steel", "powder_iron", "ferrite"] = "steel"


class BioprintingScaffoldSpec(EngineeringBaseModel):
    bounds_mm: tuple[float, float, float] = Field(..., description="X/Y/Z build envelope.")
    pore_size_um: float = Field(..., ge=10.0, le=2000.0, json_schema_extra=unit("um"))
    porosity: float = Field(..., gt=0.05, lt=0.98, json_schema_extra=unit("fraction"))
    material: Literal["pegda", "collagen", "gelma", "plga"] = "gelma"
    architecture: Literal["gyroid", "lattice", "schwartz_p"] = "gyroid"

    @model_validator(mode="after")
    def validate_bounds(self) -> "BioprintingScaffoldSpec":
        if any(axis <= 0.0 for axis in self.bounds_mm):
            raise PhysicsViolationError("All scaffold bounds must be positive", requirement="bounds")
        return self


class HotFireTestResult(EngineeringBaseModel):
    engine_id: str
    measured_thrust_N: float = Field(..., gt=0.0, json_schema_extra=unit("N"))
    chamber_pressure_bar: float = Field(..., gt=0.0, json_schema_extra=unit("bar"))
    burn_time_s: float = Field(..., gt=0.0, json_schema_extra=unit("s"))
    measured_isp_s: float = Field(..., gt=0.0, json_schema_extra=unit("s"))
    max_wall_temperature_K: float = Field(..., gt=0.0, json_schema_extra=unit("K"))
    notes: str = ""


class ManufacturingReport(EngineeringBaseModel):
    part_id: str
    process: Literal["lpbf", "ebm", "directed_energy", "machined"]
    material: Literal["copper", "inconel", "inconel718", "titanium", "steel"]
    build_success: bool
    min_resolved_channel_mm: float = Field(..., gt=0.0, json_schema_extra=unit("mm"))
    measured_shrinkage_fraction: float = Field(0.0, ge=-0.2, le=0.2, json_schema_extra=unit("fraction"))
    notes: str = ""


class EngineDesignResponse(EngineeringBaseModel):
    job_id: str
    status: Literal["completed", "failed", "running", "queued"]
    performance: dict
    files: dict[str, str]
    warnings: list[str] = []


class HXDesignResponse(EngineeringBaseModel):
    job_id: str
    status: Literal["completed", "failed", "running", "queued"]
    performance: dict
    files: dict[str, str] = {}


class JobStatus(EngineeringBaseModel):
    job_id: str
    status: Literal["completed", "failed", "running", "queued", "not_found"]
    detail: str = ""


class FeedbackResponse(EngineeringBaseModel):
    accepted: bool
    records: int
    message: str

