"""Screening-level combustion chamber acoustic mode analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


FIRST_TANGENTIAL_BESSEL_DERIVATIVE_ZERO = 1.841183781
FIRST_RADIAL_BESSEL_DERIVATIVE_ZERO = 3.831705970


@dataclass(slots=True)
class AcousticMode:
    family: str
    order: int
    frequency_hz: float
    within_coupling_band: bool
    is_reference: bool = False


@dataclass(slots=True)
class CombustionStabilityResult:
    speed_of_sound_m_s: float
    chamber_length_mm: float
    chamber_radius_mm: float
    chamber_acoustic_frequency_hz: float
    modes: list[AcousticMode] = field(default_factory=list)
    stability_risk: bool = False
    recommendation: str = "Baseline injector acoustic screening passed."


def analyze_combustion_stability(
    *,
    chamber_length_mm: float,
    chamber_radius_mm: float,
    speed_of_sound_m_s: float,
    coupling_fraction: float = 0.10,
    longitudinal_orders: int = 3,
) -> CombustionStabilityResult:
    """Estimate longitudinal, tangential, and radial chamber acoustic modes.

    This is a design-screening model for a cylindrical chamber.  It flags
    non-reference modes that fall within +/-10% of the first longitudinal mode,
    a configuration that can couple energy into an injector/chamber resonance.
    It is not a replacement for a validated acoustic network or hot-fire test.
    """

    length_m = _positive(chamber_length_mm, "chamber_length_mm") / 1000.0
    radius_m = _positive(chamber_radius_mm, "chamber_radius_mm") / 1000.0
    speed = _positive(speed_of_sound_m_s, "speed_of_sound_m_s")
    reference = speed / (2.0 * length_m)
    modes: list[AcousticMode] = [
        AcousticMode("longitudinal", 1, reference, False, is_reference=True)
    ]
    coupling_band = abs(reference) * max(coupling_fraction, 0.0)
    for order in range(2, max(longitudinal_orders, 1) + 1):
        frequency = order * reference
        modes.append(AcousticMode("longitudinal", order, frequency, abs(frequency - reference) <= coupling_band))
    tangential = FIRST_TANGENTIAL_BESSEL_DERIVATIVE_ZERO * speed / (2.0 * math.pi * radius_m)
    radial = FIRST_RADIAL_BESSEL_DERIVATIVE_ZERO * speed / (2.0 * math.pi * radius_m)
    modes.append(AcousticMode("tangential", 1, tangential, abs(tangential - reference) <= coupling_band))
    modes.append(AcousticMode("radial", 1, radial, abs(radial - reference) <= coupling_band))
    risky = [mode for mode in modes if mode.within_coupling_band and not mode.is_reference]
    recommendation = (
        "Use a baffled injector face and validate with an acoustic network and instrumented hot-fire test."
        if risky
        else "No coupled non-reference mode is within the +/-10% screening band; retain acoustic margin through hot-fire validation."
    )
    return CombustionStabilityResult(
        speed_of_sound_m_s=speed,
        chamber_length_mm=chamber_length_mm,
        chamber_radius_mm=chamber_radius_mm,
        chamber_acoustic_frequency_hz=reference,
        modes=modes,
        stability_risk=bool(risky),
        recommendation=recommendation,
    )


def _positive(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be positive")
    return result
