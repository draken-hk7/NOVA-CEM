"""Aerospace design-screening analyses used by NOVA reports."""

from nova.core.analysis.combustion_stability import CombustionStabilityResult, analyze_combustion_stability
from nova.core.analysis.fatigue import ThermalFatigueResult, estimate_thermal_fatigue_life
from nova.core.analysis.ignition import IgnitionSizingResult, size_ignition_system

__all__ = [
    "CombustionStabilityResult",
    "IgnitionSizingResult",
    "ThermalFatigueResult",
    "analyze_combustion_stability",
    "estimate_thermal_fatigue_life",
    "size_ignition_system",
]
