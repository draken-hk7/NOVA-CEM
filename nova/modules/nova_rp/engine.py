"""NOVA-RP deterministic rocket engine design pipeline."""

from __future__ import annotations

import math

import numpy as np

from nova.core.exceptions import PhysicsViolationError
from nova.core.geometry_engine.primitives import GeometryBuilder, MeshSolid
from nova.core.geometry_engine.rocket_geometry import InjectorHeadGeometry, RocketNozzleGeometry
from nova.core.input_schema import RocketEngineSpec
from nova.core.knowledge_engine.rules import PROCESS_RULES, RocketHeuristics, get_material_properties
from nova.core.manufacturing import ManufacturabilityEnforcer
from nova.core.physics_solver import CombustionSolver, CoolingChannelSolver, NozzleFlowSolver, StructuralSolver
from nova.core.types import CoolantProperties, EngineDesignResult, EnginePerformance, TraceEntry


class NovaRP:
    """Full deterministic rocket engine design from a typed requirement spec."""

    def design(self, spec: RocketEngineSpec) -> EngineDesignResult:
        combustion_solver = CombustionSolver()
        nozzle_solver = NozzleFlowSolver()
        combustion = combustion_solver.solve(
            spec.propellant,
            self._optimal_OF(spec),
            spec.chamber_pressure_bar,
            expansion_ratio=spec.expansion_ratio,
        )

        throat_area_m2 = nozzle_solver.throat_area(spec.thrust_N, spec.chamber_pressure_bar, combustion.Cf)
        throat_radius_mm = math.sqrt(throat_area_m2 / math.pi) * 1000.0
        chamber_radius_mm = throat_radius_mm * RocketHeuristics.chamber_contraction_ratio(spec.thrust_N) ** 0.5
        wall_thickness_mm = self._wall_thickness(spec, chamber_radius_mm)
        n_channels = self._n_cooling_channels(spec, chamber_radius_mm, wall_thickness_mm)
        chamber_length_mm = self._chamber_length(throat_radius_mm, chamber_radius_mm)

        if spec.nozzle_type == "bell":
            nozzle_geo = RocketNozzleGeometry().bell_nozzle(
                throat_radius_mm=throat_radius_mm,
                chamber_radius_mm=chamber_radius_mm,
                expansion_ratio=spec.expansion_ratio,
                chamber_length_mm=chamber_length_mm,
                wall_thickness_mm=wall_thickness_mm,
                n_cooling_channels=n_channels,
            )
        else:
            nozzle_geo = RocketNozzleGeometry().aerospike_nozzle(
                throat_radius_mm=throat_radius_mm,
                expansion_ratio=spec.expansion_ratio,
                length_mm=chamber_length_mm * 1.7,
                wall_thickness_mm=wall_thickness_mm,
            )

        self._check_envelope_constraints(spec, nozzle_geo.solid)
        heat_flux = self._bartz_heat_flux(combustion, throat_radius_mm)
        cooling = CoolingChannelSolver().solve_channel(
            heat_flux_W_m2=heat_flux,
            channel_geometry=nozzle_geo.channels,
            coolant=CoolantProperties.for_propellant(spec.propellant),
            flow_rate_kg_s=self._coolant_flow_rate(spec, combustion),
        )
        material = get_material_properties(spec.material)
        if cooling.max_wall_temperature_K > material["max_service_temp_K"]:
            raise PhysicsViolationError(
                "Predicted wall temperature exceeds material service temperature",
                requirement="thermal service limit",
                actual=cooling.max_wall_temperature_K,
                limit=material["max_service_temp_K"],
                unit=" K",
            )

        structural = StructuralSolver().validate_chamber(nozzle_geo, spec, combustion)
        if not structural.passed:
            raise PhysicsViolationError(
                "Chamber structural factor of safety is below requirement",
                requirement="factor of safety",
                actual=structural.factor_of_safety,
                limit=spec.safety_factor,
            )

        injector = InjectorHeadGeometry().coaxial_swirler_injector(
            n_elements=RocketHeuristics.injector_element_count(spec.thrust_N, spec.chamber_pressure_bar),
            element_pitch_mm=max(2.0, throat_radius_mm * 0.18),
            oxidizer_post_dia_mm=max(0.45, throat_radius_mm * 0.035),
            fuel_annulus_gap_mm=max(0.25, throat_radius_mm * 0.018),
            manifold_thickness_mm=max(6.0, wall_thickness_mm * 2.2),
            outer_radius_mm=float(nozzle_geo.metadata.get("injector_flange_outer_radius_mm", chamber_radius_mm)),
        )

        full_engine = self._assemble(nozzle_geo.solid, injector.solid)
        mfg = ManufacturabilityEnforcer(spec.manufacturing_process, spec.material)
        final_geometry = mfg.enforce_all(full_engine)
        performance = EnginePerformance(
            specific_impulse_s=combustion.Isp,
            thrust_N=spec.thrust_N,
            chamber_temp_K=combustion.T_c,
            mass_flow_rate_kg_s=spec.thrust_N / (combustion.Isp * 9.80665),
            chamber_pressure_bar=spec.chamber_pressure_bar,
            expansion_ratio=spec.expansion_ratio,
            thrust_coefficient=combustion.Cf,
        )
        trace = [
            TraceEntry("target thrust", "At = F / (Cf Pc)", "throat_radius_mm", throat_radius_mm, "mm"),
            TraceEntry("expansion ratio", "re = rt sqrt(epsilon)", "exit_radius_mm", nozzle_geo.metadata.get("exit_radius_mm", 0.0), "mm"),
            TraceEntry("chamber pressure", "thin-wall pressure vessel sizing", "wall_thickness_mm", wall_thickness_mm, "mm"),
            TraceEntry("heat flux", "Bartz-style throat heat-flux estimate", "n_cooling_channels", n_channels, "count"),
            TraceEntry("manufacturing process", "DfAM minimum wall/channel enforcement", "process", spec.manufacturing_process),
        ]
        return EngineDesignResult(
            geometry=final_geometry,
            performance=performance,
            thermal=cooling,
            structural=structural,
            manufacturing=mfg.analysis,
            mass_kg=final_geometry.mass_properties.mass,
            injector=injector,
            trace=trace,
            metadata={"combustion": combustion, "nozzle": nozzle_geo.metadata},
        )

    def _optimal_OF(self, spec: RocketEngineSpec) -> float:
        return CombustionSolver.optimal_OF(spec.propellant)

    def _chamber_length(self, throat_radius_mm: float, chamber_radius_mm: float) -> float:
        characteristic_length_mm = 950.0
        throat_area = math.pi * throat_radius_mm**2
        chamber_area = math.pi * chamber_radius_mm**2
        return max(35.0, characteristic_length_mm * throat_area / chamber_area)

    def _wall_thickness(self, spec: RocketEngineSpec, chamber_radius_mm: float) -> float:
        material = get_material_properties(spec.material)
        rules = PROCESS_RULES[spec.manufacturing_process]
        pressure_MPa = spec.chamber_pressure_bar * 0.1
        allowable_hoop_MPa = material["yield_strength_mpa"] / spec.safety_factor * 0.82
        pressure_wall = pressure_MPa * chamber_radius_mm / allowable_hoop_MPa
        thermal_margin = 0.35 if spec.cooling == "regenerative" else 0.9
        return max(rules.MIN_WALL_THICKNESS_MM, pressure_wall + thermal_margin)

    def _n_cooling_channels(self, spec: RocketEngineSpec, chamber_radius_mm: float, wall_thickness_mm: float) -> int:
        if spec.cooling != "regenerative":
            return 1
        heat_flux_MW_m2 = 2.0 * (spec.chamber_pressure_bar / 30.0) ** 0.8
        pitch = RocketHeuristics.cooling_channel_pitch_mm(heat_flux_MW_m2)
        circumference = 2.0 * math.pi * (chamber_radius_mm + wall_thickness_mm)
        return max(12, min(360, int(circumference / pitch)))

    def _bartz_heat_flux(self, combustion: object, throat_radius_mm: float) -> np.ndarray:
        return CoolingChannelSolver.bartz_heat_flux(
            chamber_temperature_K=combustion.T_c,
            wall_temperature_K=650.0,
            chamber_pressure_bar=combustion.chamber_pressure_bar,
            throat_radius_mm=throat_radius_mm,
        )

    def _coolant_flow_rate(self, spec: RocketEngineSpec, combustion: object) -> float:
        if spec.cooling != "regenerative":
            return 0.02
        engine_mdot = spec.thrust_N / (combustion.Isp * 9.80665)
        fuel_fraction = 1.0 / (1.0 + self._optimal_OF(spec))
        return max(0.03, 0.85 * fuel_fraction * engine_mdot)

    def _assemble(self, nozzle: MeshSolid, injector: MeshSolid, turbopump: object | None = None) -> MeshSolid:
        del turbopump
        assembled = GeometryBuilder().boolean_union(nozzle, injector)
        shape = assembled.shape
        if not shape.isValid() or len(shape.Solids()) != 1:
            raise ValueError("CadQuery engine assembly failed to produce a single valid solid")
        assembled.name = "nova_rp_engine"
        assembled.metadata.update({"assembly": "nozzle + injector", "module": "nova_rp"})
        return assembled

    def _check_envelope_constraints(self, spec: RocketEngineSpec, solid: MeshSolid) -> None:
        lo, hi = solid.bounds_mm
        diameter = max(hi[0] - lo[0], hi[1] - lo[1])
        length = hi[2] - lo[2]
        if spec.max_outer_diameter_mm is not None and diameter > spec.max_outer_diameter_mm:
            raise PhysicsViolationError(
                "Generated engine exceeds maximum outer diameter",
                requirement="max outer diameter",
                actual=diameter,
                limit=spec.max_outer_diameter_mm,
                unit=" mm",
            )
        if spec.length_constraint_mm is not None and length > spec.length_constraint_mm:
            raise PhysicsViolationError(
                "Generated engine exceeds length constraint",
                requirement="length",
                actual=length,
                limit=spec.length_constraint_mm,
                unit=" mm",
            )
