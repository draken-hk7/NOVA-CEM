"""NOVA-HX heat exchanger design module."""

from __future__ import annotations

from dataclasses import dataclass, field

from nova.core.geometry_engine.heatexchanger_geometry import HeatExchangerGeometry
from nova.core.input_schema import HeatExchangerSpec
from nova.core.knowledge_engine.rules import get_material_properties
from nova.core.manufacturing import ManufacturabilityEnforcer
from nova.core.physics_solver import HeatExchangerSolver


@dataclass(slots=True)
class HXPerformance:
    effectiveness: float
    ntu: float
    required_area_m2: float
    pressure_drop_bar: float
    hot_pressure_drop_bar: float
    cold_pressure_drop_bar: float
    hot_mass_flow_kg_s: float
    cold_mass_flow_kg_s: float
    hot_outlet_temp_C: float
    cold_outlet_temp_C: float
    overall_heat_transfer_coefficient_W_m2K: float
    dimensions_mm: dict[str, float]
    mass_kg: float


@dataclass(slots=True)
class HXDesignResult:
    geometry: object
    performance: HXPerformance
    manufacturing: object
    mass_kg: float
    metadata: dict = field(default_factory=dict)


class NovaHX:
    def design(self, spec: HeatExchangerSpec) -> HXDesignResult:
        solver = HeatExchangerSolver()
        calculation = solver.design_ntu_effectiveness(
            hot_fluid=spec.hot_fluid,
            cold_fluid=spec.cold_fluid,
            duty_kW=spec.duty_kW,
            hot_inlet_temp_C=spec.hot_inlet_temp_C,
            hot_outlet_temp_C=spec.hot_outlet_temp_C,
            cold_inlet_temp_C=spec.cold_inlet_temp_C,
            max_pressure_bar=spec.max_pressure_bar,
            material=spec.material,
        )
        dimensions = calculation.dimensions_mm
        geometry = HeatExchangerGeometry().gyroid_minimal_surface(
            bounds=(dimensions["width_mm"], dimensions["height_mm"], dimensions["depth_mm"]),
            resolution=24,
            thickness_mm=max(0.8, calculation.hydraulic_diameter_mm * 0.45),
            heat_transfer_area_m2=calculation.required_area_m2,
        )
        geometry.metadata.update(
            {
                "module": "nova_hx",
                "hot_fluid": spec.hot_fluid,
                "cold_fluid": spec.cold_fluid,
                "duty_kW": spec.duty_kW,
                "dimensions_mm": dimensions,
                "hydraulic_diameter_mm": calculation.hydraulic_diameter_mm,
                "required_area_m2": calculation.required_area_m2,
                "effectiveness": calculation.effectiveness,
                "ntu": calculation.ntu,
                "pressure_drop_bar": calculation.pressure_drop_bar,
                "max_pressure_bar": spec.max_pressure_bar,
            }
        )
        mfg = ManufacturabilityEnforcer(spec.manufacturing_process, spec.material)
        geometry = mfg.enforce_all(geometry)
        density = float(get_material_properties(spec.material)["density_kg_m3"])
        mass_kg = geometry.volume_mm3 * 1.0e-9 * density
        performance = HXPerformance(
            effectiveness=calculation.effectiveness,
            ntu=calculation.ntu,
            required_area_m2=calculation.required_area_m2,
            pressure_drop_bar=calculation.pressure_drop_bar,
            hot_pressure_drop_bar=calculation.hot_pressure_drop_bar,
            cold_pressure_drop_bar=calculation.cold_pressure_drop_bar,
            hot_mass_flow_kg_s=calculation.hot_mass_flow_kg_s,
            cold_mass_flow_kg_s=calculation.cold_mass_flow_kg_s,
            hot_outlet_temp_C=calculation.hot_outlet_temp_C,
            cold_outlet_temp_C=calculation.cold_outlet_temp_C,
            overall_heat_transfer_coefficient_W_m2K=calculation.overall_heat_transfer_coefficient_W_m2K,
            dimensions_mm=dimensions,
            mass_kg=mass_kg,
        )
        return HXDesignResult(
            geometry=geometry,
            performance=performance,
            manufacturing=mfg.analysis,
            mass_kg=mass_kg,
            metadata={
                "architecture": "gyroid",
                "hot_fluid": spec.hot_fluid,
                "cold_fluid": spec.cold_fluid,
                "dimensions_mm": dimensions,
                "required_area_m2": calculation.required_area_m2,
            },
        )
