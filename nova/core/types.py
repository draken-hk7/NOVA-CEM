"""Shared typed result objects for the NOVA core."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any

import numpy as np


@dataclass(slots=True)
class TraceEntry:
    requirement: str
    calculation: str
    geometry_parameter: str
    value: float | str
    unit: str = ""


@dataclass(slots=True)
class ManufacturingWarning:
    code: str
    message: str
    severity: str = "warning"
    feature: str | None = None


@dataclass(slots=True)
class MassProperties:
    volume_mm3: float
    density_kg_m3: float

    @property
    def mass(self) -> float:
        return self.volume_mm3 * 1.0e-9 * self.density_kg_m3


@dataclass(slots=True)
class CombustionResult:
    propellant: str
    OF_ratio: float
    chamber_pressure_bar: float
    T_c: float
    Isp: float
    exhaust_velocity_m_s: float
    gamma: float
    molecular_weight_g_mol: float
    Cp_J_kgK: float
    c_star_m_s: float
    Cf: float
    combustion_efficiency: float


@dataclass(slots=True)
class ChannelGeometry:
    hydraulic_diameter_mm: float
    length_mm: float
    n_channels: int
    channel_area_mm2: float
    wall_thickness_mm: float
    roughness_um: float = 12.0


@dataclass(slots=True)
class CoolantProperties:
    name: str
    density_kg_m3: float
    viscosity_Pa_s: float
    thermal_conductivity_W_mK: float
    cp_J_kgK: float
    inlet_temperature_K: float = 293.15

    @classmethod
    def for_propellant(cls, propellant: str) -> "CoolantProperties":
        table = {
            "kerolox": cls("kerosene", 810.0, 1.9e-3, 0.145, 2100.0, 293.15),
            "methalox": cls("liquid methane", 422.0, 1.1e-4, 0.19, 3500.0, 112.0),
            "hydrolox": cls("liquid hydrogen", 70.8, 1.3e-5, 0.105, 14300.0, 20.3),
            "hypergolic": cls("fuel blend", 890.0, 8.0e-4, 0.18, 2300.0, 293.15),
            "solid": cls("ablative boundary", 1.0, 1.8e-5, 0.03, 1000.0, 293.15),
            "water": cls("water", 997.0, 8.9e-4, 0.6, 4182.0, 293.15),
        }
        return table.get(propellant, table["water"])


@dataclass(slots=True)
class CoolingResult:
    wall_temperature_K: np.ndarray
    coolant_temperature_K: np.ndarray
    pressure_drop_bar: float
    coolant_outlet_temperature_K: float
    max_wall_temperature_K: float
    reynolds_number: float
    nusselt_number: float


@dataclass(slots=True)
class StructuralResult:
    hoop_stress_MPa: float
    thermal_stress_MPa: float
    combined_stress_MPa: float
    factor_of_safety: float
    max_allowable_stress_MPa: float
    passed: bool


@dataclass(slots=True)
class ManufacturingAnalysis:
    process: str
    material: str
    build_volume_mm3: float
    material_kg: float
    estimated_print_time_hours: float
    warnings: list[ManufacturingWarning] = field(default_factory=list)
    passed: bool = True


@dataclass(slots=True)
class GeometryResult:
    solid: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RocketNozzleResult:
    solid: Any
    channels: ChannelGeometry
    channel_paths: list[np.ndarray]
    metadata: dict[str, Any]


@dataclass(slots=True)
class InjectorResult:
    solid: Any
    n_elements: int
    metadata: dict[str, Any]


@dataclass(slots=True)
class EnginePerformance:
    specific_impulse_s: float
    thrust_N: float
    chamber_temp_K: float
    mass_flow_rate_kg_s: float
    chamber_pressure_bar: float
    expansion_ratio: float
    thrust_coefficient: float


@dataclass(slots=True)
class EngineDesignResult:
    geometry: Any
    performance: EnginePerformance
    thermal: CoolingResult
    structural: StructuralResult
    manufacturing: ManufacturingAnalysis
    mass_kg: float
    injector: InjectorResult
    trace: list[TraceEntry] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProcessParams:
    layer_height_mm: float
    laser_power_W: float | None = None
    scan_speed_mm_s: float | None = None


@dataclass(slots=True)
class GCodeResult:
    path: str
    estimated_layers: int
    estimated_print_time_hours: float


@dataclass(slots=True)
class CEMRunResult:
    job_id: str
    module: str
    inputs: dict[str, Any]
    design: Any
    files: dict[str, str] = field(default_factory=dict)


def to_jsonable(value: Any) -> Any:
    """Convert NOVA result objects and arrays into JSON-compatible objects."""

    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return {item.name: to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value
