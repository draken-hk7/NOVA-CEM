"""NOVA-RP deterministic rocket engine design pipeline."""

from __future__ import annotations

import math
import os
from types import SimpleNamespace

import numpy as np

from nova.core.exceptions import PhysicsViolationError
from nova.core.geometry_engine.primitives import GeometryBuilder, MeshSolid
from nova.core.geometry_engine.rocket_geometry import InjectorHeadGeometry, RocketNozzleGeometry
from nova.core.input_schema import RocketEngineSpec
from nova.core.knowledge_engine.rules import (
    PROCESS_RULES,
    RocketHeuristics,
    get_material_properties,
    normalize_material,
)
from nova.core.manufacturing import ManufacturabilityEnforcer, ManufacturingValidator
from nova.core.physics_solver import CombustionSolver, CoolingChannelSolver, NozzleFlowSolver, StructuralSolver
from nova.core.types import (
    ChannelGeometry,
    CoolantProperties,
    EngineDesignResult,
    EnginePerformance,
    InjectorResult,
    ManufacturingAnalysis,
    TraceEntry,
)


class NovaRP:
    """Full deterministic rocket engine design from a typed requirement spec."""

    DEFAULT_COOLING_CHANNELS = 8
    FAST_PREVIEW_COOLING_CHANNELS = 4
    DEFAULT_EXPANSION_RATIOS = {
        "kerolox": 20.0,
        "methalox": 20.0,
        "hydrolox": 40.0,
    }
    GEOMETRY_DISABLED_VALUES = {"0", "false", "no", "off"}

    def design(self, spec: RocketEngineSpec, cooling_channel_count: int | None = None) -> EngineDesignResult:
        combustion_solver = CombustionSolver()
        nozzle_solver = NozzleFlowSolver()
        expansion_ratio = self._effective_expansion_ratio(spec)
        combustion = combustion_solver.solve(
            spec.propellant,
            self._optimal_OF(spec),
            spec.chamber_pressure_bar,
            expansion_ratio=expansion_ratio,
        )

        throat_area_m2 = nozzle_solver.throat_area(spec.thrust_N, spec.chamber_pressure_bar, combustion.Cf)
        throat_radius_mm = math.sqrt(throat_area_m2 / math.pi) * 1000.0
        chamber_radius_mm = throat_radius_mm * RocketHeuristics.chamber_contraction_ratio(spec.thrust_N) ** 0.5
        wall_thickness_mm = self._wall_thickness(spec, chamber_radius_mm)
        n_channels = self._n_cooling_channels(spec, chamber_radius_mm, wall_thickness_mm, cooling_channel_count)
        chamber_length_mm = self._chamber_length(throat_radius_mm, chamber_radius_mm)
        if not self._geometry_enabled():
            return self._design_physics_only(
                spec=spec,
                combustion=combustion,
                expansion_ratio=expansion_ratio,
                throat_radius_mm=throat_radius_mm,
                chamber_radius_mm=chamber_radius_mm,
                wall_thickness_mm=wall_thickness_mm,
                n_channels=n_channels,
                chamber_length_mm=chamber_length_mm,
            )

        if spec.nozzle_type == "bell":
            nozzle_geo = RocketNozzleGeometry().bell_nozzle(
                throat_radius_mm=throat_radius_mm,
                chamber_radius_mm=chamber_radius_mm,
                expansion_ratio=expansion_ratio,
                chamber_length_mm=chamber_length_mm,
                wall_thickness_mm=wall_thickness_mm,
                n_cooling_channels=n_channels,
            )
        else:
            nozzle_geo = RocketNozzleGeometry().aerospike_nozzle(
                throat_radius_mm=throat_radius_mm,
                expansion_ratio=expansion_ratio,
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
        final_geometry.metadata.update(
            {
                "material": spec.material,
                "manufacturing_process": spec.manufacturing_process,
                "chamber_pressure_bar": spec.chamber_pressure_bar,
                "chamber_radius_mm": chamber_radius_mm,
                "chamber_wall_thickness_mm": wall_thickness_mm,
                "actual_chamber_wall_thickness_mm": wall_thickness_mm,
                "cooling_channel_wall_mm": nozzle_geo.channels.wall_thickness_mm,
                "minimum_local_thickness_mm": min(
                    wall_thickness_mm,
                    nozzle_geo.channels.wall_thickness_mm,
                    float(final_geometry.metadata.get("min_wall_thickness_mm", wall_thickness_mm)),
                ),
            }
        )
        validation = ManufacturingValidator().validate(final_geometry)
        performance = EnginePerformance(
            specific_impulse_s=combustion.Isp,
            thrust_N=spec.thrust_N,
            chamber_temp_K=combustion.T_c,
            mass_flow_rate_kg_s=spec.thrust_N / (combustion.Isp * 9.80665),
            chamber_pressure_bar=spec.chamber_pressure_bar,
            expansion_ratio=expansion_ratio,
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
            validation=validation,
        )

    def _optimal_OF(self, spec: RocketEngineSpec) -> float:
        return CombustionSolver.optimal_OF(spec.propellant)

    def _effective_expansion_ratio(self, spec: RocketEngineSpec) -> float:
        if "expansion_ratio" in spec.model_fields_set:
            return spec.expansion_ratio
        return self.DEFAULT_EXPANSION_RATIOS.get(spec.propellant, spec.expansion_ratio)

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

    def _n_cooling_channels(
        self,
        spec: RocketEngineSpec,
        chamber_radius_mm: float,
        wall_thickness_mm: float,
        requested_count: int | None = None,
    ) -> int:
        del chamber_radius_mm, wall_thickness_mm
        if spec.cooling != "regenerative":
            return 1
        if requested_count is not None:
            if requested_count <= 0:
                raise ValueError("cooling_channel_count must be positive")
            return int(requested_count)
        return self.DEFAULT_COOLING_CHANNELS

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

    def _geometry_enabled(self) -> bool:
        value = os.getenv("NOVA_GEOMETRY_ENABLED", "true").strip().lower()
        return value not in self.GEOMETRY_DISABLED_VALUES

    def _design_physics_only(
        self,
        *,
        spec: RocketEngineSpec,
        combustion: object,
        expansion_ratio: float,
        throat_radius_mm: float,
        chamber_radius_mm: float,
        wall_thickness_mm: float,
        n_channels: int,
        chamber_length_mm: float,
    ) -> EngineDesignResult:
        metadata, channels = self._physics_only_nozzle_metadata(
            spec=spec,
            throat_radius_mm=throat_radius_mm,
            chamber_radius_mm=chamber_radius_mm,
            expansion_ratio=expansion_ratio,
            chamber_length_mm=chamber_length_mm,
            wall_thickness_mm=wall_thickness_mm,
            n_channels=n_channels,
        )
        self._check_physics_only_envelope_constraints(spec, metadata)
        heat_flux = self._bartz_heat_flux(combustion, throat_radius_mm)
        cooling = CoolingChannelSolver().solve_channel(
            heat_flux_W_m2=heat_flux,
            channel_geometry=channels,
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

        validation_metadata = self._validation_metadata(spec, metadata, wall_thickness_mm, channels)
        nozzle_proxy = SimpleNamespace(solid=SimpleNamespace(metadata=validation_metadata))
        structural = StructuralSolver().validate_chamber(nozzle_proxy, spec, combustion)
        if not structural.passed:
            raise PhysicsViolationError(
                "Chamber structural factor of safety is below requirement",
                requirement="factor of safety",
                actual=structural.factor_of_safety,
                limit=spec.safety_factor,
            )

        mass_kg, manufacturing = self._physics_only_manufacturing(spec, metadata, wall_thickness_mm)
        validation = ManufacturingValidator().validate(SimpleNamespace(metadata=validation_metadata))
        performance = EnginePerformance(
            specific_impulse_s=combustion.Isp,
            thrust_N=spec.thrust_N,
            chamber_temp_K=combustion.T_c,
            mass_flow_rate_kg_s=spec.thrust_N / (combustion.Isp * 9.80665),
            chamber_pressure_bar=spec.chamber_pressure_bar,
            expansion_ratio=expansion_ratio,
            thrust_coefficient=combustion.Cf,
        )
        trace = [
            TraceEntry("target thrust", "At = F / (Cf Pc)", "throat_radius_mm", throat_radius_mm, "mm"),
            TraceEntry("expansion ratio", "physics-only contour estimate", "exit_radius_mm", metadata.get("exit_radius_mm", 0.0), "mm"),
            TraceEntry("chamber pressure", "thin-wall pressure vessel sizing", "wall_thickness_mm", wall_thickness_mm, "mm"),
            TraceEntry("heat flux", "Bartz-style throat heat-flux estimate", "n_cooling_channels", n_channels, "count"),
            TraceEntry("geometry mode", "NOVA_GEOMETRY_ENABLED=false", "cad_artifacts", "disabled"),
        ]
        return EngineDesignResult(
            geometry=None,
            performance=performance,
            thermal=cooling,
            structural=structural,
            manufacturing=manufacturing,
            mass_kg=mass_kg,
            injector=InjectorResult(
                solid=None,
                n_elements=RocketHeuristics.injector_element_count(spec.thrust_N, spec.chamber_pressure_bar),
                metadata={},
            ),
            trace=trace,
            metadata={"combustion": combustion, "nozzle": metadata, "geometry_enabled": False},
            validation=validation,
        )

    def _physics_only_nozzle_metadata(
        self,
        *,
        spec: RocketEngineSpec,
        throat_radius_mm: float,
        chamber_radius_mm: float,
        expansion_ratio: float,
        chamber_length_mm: float,
        wall_thickness_mm: float,
        n_channels: int,
    ) -> tuple[dict, ChannelGeometry]:
        if spec.nozzle_type == "bell":
            convergence_length = max(1.2 * chamber_radius_mm, 3.0 * (chamber_radius_mm - throat_radius_mm))
            contour = RocketHeuristics.rao_nozzle_contour(throat_radius_mm, expansion_ratio, n_points=160)
            nozzle_length = float(contour[-1, 0])
            exit_radius = float(contour[-1, 1])
            total_length = chamber_length_mm + convergence_length + nozzle_length + 6.0
        else:
            convergence_length = 0.0
            total_length = chamber_length_mm * 1.7
            exit_radius = throat_radius_mm * math.sqrt(expansion_ratio)

        channel_width = max(0.8, 0.30 * wall_thickness_mm)
        channel_depth_mm = max(0.5, min(0.75, 0.22 * wall_thickness_mm))
        outer_jacket_mm = max(0.6, 0.55 * wall_thickness_mm)
        helix_radius = chamber_radius_mm + wall_thickness_mm + channel_depth_mm / 2.0
        helix_pitch = max(total_length / 1.2, 80.0)
        turns = max(total_length / helix_pitch, 0.2)
        channel_length = math.hypot(total_length, 2.0 * math.pi * helix_radius * turns)
        metadata = {
            "geometry_type": f"{spec.nozzle_type}_physics_only",
            "geometry_enabled": False,
            "throat_radius_mm": throat_radius_mm,
            "chamber_radius_mm": chamber_radius_mm,
            "exit_radius_mm": exit_radius,
            "expansion_ratio": expansion_ratio,
            "chamber_length_mm": chamber_length_mm,
            "convergence_length_mm": convergence_length,
            "total_length_mm": total_length,
            "min_wall_thickness_mm": wall_thickness_mm,
            "min_channel_diameter_mm": min(channel_width, channel_depth_mm),
            "outer_jacket_mm": outer_jacket_mm,
            "n_cooling_channels": n_channels,
            "channel_pitch_mm": max(1.0, (2.0 * math.pi * (chamber_radius_mm + wall_thickness_mm)) / max(n_channels, 1)),
            "helix_pitch_mm": helix_pitch,
            "channel_cut_diameter_mm": min(channel_width, channel_depth_mm),
        }
        channels = ChannelGeometry(
            hydraulic_diameter_mm=2.0 * channel_width * channel_depth_mm / (channel_width + channel_depth_mm),
            length_mm=channel_length,
            n_channels=n_channels,
            channel_area_mm2=channel_width * channel_depth_mm,
            wall_thickness_mm=wall_thickness_mm,
        )
        return metadata, channels

    def _validation_metadata(
        self,
        spec: RocketEngineSpec,
        nozzle_metadata: dict,
        wall_thickness_mm: float,
        channels: ChannelGeometry,
    ) -> dict:
        return {
            **nozzle_metadata,
            "material": spec.material,
            "manufacturing_process": spec.manufacturing_process,
            "chamber_pressure_bar": spec.chamber_pressure_bar,
            "chamber_wall_thickness_mm": wall_thickness_mm,
            "actual_chamber_wall_thickness_mm": wall_thickness_mm,
            "cooling_channel_wall_mm": channels.wall_thickness_mm,
            "minimum_local_thickness_mm": min(wall_thickness_mm, channels.wall_thickness_mm),
        }

    def _physics_only_manufacturing(
        self,
        spec: RocketEngineSpec,
        metadata: dict,
        wall_thickness_mm: float,
    ) -> tuple[float, ManufacturingAnalysis]:
        material_key = normalize_material(spec.material)
        density = float(get_material_properties(spec.material)["density_kg_m3"])
        total_length = float(metadata["total_length_mm"])
        chamber_radius = float(metadata["chamber_radius_mm"])
        exit_radius = float(metadata["exit_radius_mm"])
        outer_jacket = float(metadata["outer_jacket_mm"])
        effective_wall = wall_thickness_mm + outer_jacket
        mean_radius = max(chamber_radius, (chamber_radius + exit_radius) / 2.0)
        shell_volume_mm3 = 2.0 * math.pi * mean_radius * effective_wall * total_length
        injector_radius = chamber_radius + wall_thickness_mm + outer_jacket + 10.0
        injector_volume_mm3 = math.pi * injector_radius**2 * max(6.0, wall_thickness_mm * 2.2)
        volume_mm3 = shell_volume_mm3 + injector_volume_mm3
        mass_kg = volume_mm3 * 1.0e-9 * density
        process_rate_cm3_h = {
            "lpbf": 7.0,
            "ebm": 12.0,
            "directed_energy": 30.0,
            "machined": 50.0,
        }.get(spec.manufacturing_process, 8.0)
        build_radius = max(chamber_radius, exit_radius) + effective_wall + 10.0
        build_volume_mm3 = (2.0 * build_radius) ** 2 * total_length
        manufacturing = ManufacturingAnalysis(
            process=spec.manufacturing_process,
            material=material_key,
            build_volume_mm3=build_volume_mm3,
            material_kg=mass_kg,
            estimated_print_time_hours=max((volume_mm3 / 1000.0) / process_rate_cm3_h, 0.05),
            passed=True,
        )
        return mass_kg, manufacturing

    def _check_physics_only_envelope_constraints(self, spec: RocketEngineSpec, metadata: dict) -> None:
        effective_radius = max(float(metadata["chamber_radius_mm"]), float(metadata["exit_radius_mm"]))
        effective_radius += float(metadata["min_wall_thickness_mm"]) + float(metadata["outer_jacket_mm"]) + 10.0
        diameter = 2.0 * effective_radius
        length = float(metadata["total_length_mm"])
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
