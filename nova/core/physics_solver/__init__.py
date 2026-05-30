"""Analytical and numerical physics solvers."""

from nova.core.physics_solver.electromagnetics import EMSolver
from nova.core.physics_solver.fluid_dynamics import HeatExchangerSolver
from nova.core.physics_solver.heat_transfer import CoolingChannelSolver
from nova.core.physics_solver.nozzle_flow import NozzleFlowSolver
from nova.core.physics_solver.structural import StructuralSolver
from nova.core.physics_solver.thermodynamics import CombustionSolver

__all__ = [
    "CombustionSolver",
    "CoolingChannelSolver",
    "EMSolver",
    "HeatExchangerSolver",
    "NozzleFlowSolver",
    "StructuralSolver",
]

