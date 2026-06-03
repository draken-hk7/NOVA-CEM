"""NOVA-EA electromagnetic actuator design module."""

from __future__ import annotations

from dataclasses import dataclass, field

from nova.core.geometry_engine.primitives import GeometryBuilder, MeshSolid, _cq
from nova.core.input_schema import ActuatorSpec
from nova.core.physics_solver import EMSolver


MATERIAL_DENSITY_KG_M3 = {
    "aluminum": 2700.0,
    "inconel": 8190.0,
    "steel": 7850.0,
}


@dataclass(slots=True)
class EAPerformance:
    force_output_N: float
    current_draw_A: float
    power_consumption_W: float
    response_time_ms: float
    coil_resistance_ohm: float
    coil_turns: int
    wire_gauge: str
    magnetic_flux_Wb: float
    flux_density_T: float
    inductance_H: float
    heat_dissipation_W: float
    dimensions_mm: dict[str, float]
    mass_kg: float


@dataclass(slots=True)
class EADesignResult:
    geometry: MeshSolid
    performance: EAPerformance
    manufacturing: dict
    mass_kg: float
    metadata: dict = field(default_factory=dict)


class NovaEA:
    def design(self, spec: ActuatorSpec) -> EADesignResult:
        sizing = EMSolver().solenoid_actuator(
            force_N=spec.force_N,
            stroke_mm=spec.stroke_mm,
            voltage_V=spec.voltage_V,
            response_time_ms=spec.response_time_ms,
            max_temp_C=spec.max_temp_C,
        )
        geometry = self._solenoid_geometry(sizing.dimensions_mm)
        density = MATERIAL_DENSITY_KG_M3[spec.material]
        geometry.metadata.update(
            {
                "module": "nova_ea",
                "actuator_type": spec.actuator_type,
                "material": spec.material,
                "density_kg_m3": density,
                "coil_turns": sizing.coil_turns,
                "wire_gauge": sizing.wire_gauge,
                "force_output_N": sizing.force_output_N,
                "current_draw_A": sizing.current_draw_A,
                "power_consumption_W": sizing.power_consumption_W,
                "response_time_ms": sizing.response_time_ms,
                "dimensions_mm": sizing.dimensions_mm,
                "features": [
                    "cylindrical coil housing",
                    "ferromagnetic plunger",
                    "return spring cavity",
                    "mounting flange",
                    "electrical connector port",
                ],
            }
        )
        mass_kg = geometry.volume_mm3 * 1.0e-9 * density
        performance = EAPerformance(
            force_output_N=sizing.force_output_N,
            current_draw_A=sizing.current_draw_A,
            power_consumption_W=sizing.power_consumption_W,
            response_time_ms=sizing.response_time_ms,
            coil_resistance_ohm=sizing.coil_resistance_ohm,
            coil_turns=sizing.coil_turns,
            wire_gauge=sizing.wire_gauge,
            magnetic_flux_Wb=sizing.magnetic_flux_Wb,
            flux_density_T=sizing.flux_density_T,
            inductance_H=sizing.inductance_H,
            heat_dissipation_W=sizing.heat_dissipation_W,
            dimensions_mm=sizing.dimensions_mm,
            mass_kg=mass_kg,
        )
        return EADesignResult(
            geometry=geometry,
            performance=performance,
            manufacturing={
                "material": spec.material,
                "estimated_heat_dissipation_W": sizing.heat_dissipation_W,
                "max_temp_C": spec.max_temp_C,
                "passed": sizing.response_time_ms <= spec.response_time_ms and sizing.force_output_N >= spec.force_N,
            },
            mass_kg=mass_kg,
            metadata={"actuator_type": spec.actuator_type, "material": spec.material},
        )

    def _solenoid_geometry(self, dimensions: dict[str, float]) -> MeshSolid:
        builder = GeometryBuilder()
        outer_radius = dimensions["outer_diameter_mm"] / 2.0
        body_length = dimensions["body_length_mm"]
        core_radius = dimensions["core_diameter_mm"] / 2.0
        stroke = dimensions["stroke_mm"]
        housing = builder.cylinder(radius=outer_radius, height=body_length, segments=96)
        spring_cavity = builder.cylinder(
            radius=max(2.5, core_radius * 0.62),
            height=max(8.0, body_length * 0.34),
            center=(0.0, 0.0, body_length * 0.28),
            segments=48,
        )
        housing = builder.boolean_subtract(housing, spring_cavity)
        flange = builder.annular_cylinder(
            outer_radius + 7.0,
            outer_radius * 0.62,
            6.0,
            center=(0.0, 0.0, -body_length / 2.0 + 3.0),
        )
        plunger = builder.cylinder(
            radius=max(2.0, core_radius * 0.45),
            height=stroke + 14.0,
            center=(0.0, 0.0, -body_length / 2.0 - stroke / 2.0),
            segments=64,
        )
        connector = self._electrical_connector(outer_radius=outer_radius, z_mm=0.0)
        assembly = builder.boolean_union(housing, flange, plunger, connector)
        assembly.name = "solenoid_valve_actuator"
        if not assembly.shape.isValid() or len(assembly.shape.Solids()) != 1:
            raise ValueError("Solenoid actuator geometry failed to produce one valid solid")
        assembly.metadata.update(
            {
                "geometry_type": "solenoid_valve_actuator",
                "outer_radius_mm": outer_radius,
                "body_length_mm": body_length,
                "core_radius_mm": core_radius,
                "spring_cavity_radius_mm": max(2.5, core_radius * 0.62),
                "mounting_flange_outer_radius_mm": outer_radius + 7.0,
                "electrical_connector_port": {"position_mm": [outer_radius + 8.0, 0.0, 0.0], "pin_count": 2},
                "min_wall_thickness_mm": 1.2,
                "min_channel_diameter_mm": 2.0,
            }
        )
        return assembly

    @staticmethod
    def _electrical_connector(*, outer_radius: float, z_mm: float) -> MeshSolid:
        cq = _cq()
        connector = (
            cq.Workplane("XY")
            .box(12.0, 10.0, 9.0)
            .translate((outer_radius + 5.5, 0.0, z_mm))
        )
        return MeshSolid(connector, "electrical_connector_port", {"connector": "two-pin"})
