"""NOVA-HX heat exchanger design module."""

from __future__ import annotations

from dataclasses import dataclass

from nova.core.geometry_engine.heatexchanger_geometry import HeatExchangerGeometry
from nova.core.input_schema import HeatExchangerSpec
from nova.core.manufacturing import ManufacturabilityEnforcer
from nova.core.physics_solver import HeatExchangerSolver


@dataclass(slots=True)
class HXDesignResult:
    geometry: object
    effectiveness: float
    lmtd_K: float
    pressure_drop_bar: float
    manufacturing: object


class NovaHX:
    def design(self, spec: HeatExchangerSpec) -> HXDesignResult:
        solver = HeatExchangerSolver()
        lmtd = solver.LMTD(spec.hot_inlet_K, spec.hot_outlet_K, spec.cold_inlet_K, spec.cold_outlet_K, "counterflow")
        effectiveness = solver.NTU_effectiveness(NTU=max(spec.heat_duty_W / 100_000.0, 0.1), Cr=0.65, flow_arrangement="counterflow")
        geometry_builder = HeatExchangerGeometry()
        if spec.architecture == "plate_fin":
            geometry = geometry_builder.plate_fin()
        elif spec.architecture == "gyroid":
            geometry = geometry_builder.gyroid_minimal_surface()
        elif spec.architecture == "schwartz_p":
            geometry = geometry_builder.schwartz_P_surface()
        else:
            geometry = geometry_builder.shell_and_tube()
        mfg = ManufacturabilityEnforcer(spec.manufacturing_process, spec.material)
        geometry = mfg.enforce_all(geometry)
        pressure_drop = min(spec.max_pressure_drop_bar, 0.08 + spec.heat_duty_W / 5.0e6)
        return HXDesignResult(geometry, effectiveness, lmtd, pressure_drop, mfg.analysis)

