"""NOVA-EA electromagnetic actuator design module."""

from __future__ import annotations

from dataclasses import dataclass

from nova.core.geometry_engine.primitives import GeometryBuilder
from nova.core.input_schema import ElectromagneticActuatorSpec
from nova.core.physics_solver import EMSolver


@dataclass(slots=True)
class EADesignResult:
    geometry: object
    turns: int
    phase_current_A: float
    copper_loss_W: float
    back_emf_V: float


class NovaEA:
    def design(self, spec: ElectromagneticActuatorSpec) -> EADesignResult:
        turns = max(12, int(spec.target_torque_Nm * 18.0 / max(spec.max_current_A, 1.0)))
        current = min(spec.max_current_A, spec.target_torque_Nm * 3.2)
        resistance = 0.012 * turns
        solver = EMSolver()
        geometry = GeometryBuilder().cylinder(radius=max(12.0, spec.target_torque_Nm), height=40.0)
        geometry.name = "electromagnetic_actuator_core"
        geometry.metadata.update({"turns": turns, "current_A": current})
        return EADesignResult(
            geometry=geometry,
            turns=turns,
            phase_current_A=current,
            copper_loss_W=solver.copper_loss(resistance, current),
            back_emf_V=solver.back_emf(Kv=120.0, rpm=spec.rpm),
        )

