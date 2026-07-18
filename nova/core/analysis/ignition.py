"""Ignition energy and installation sizing for NOVA rocket chambers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IgnitionSizingResult:
    recommended_igniter: str
    minimum_spark_energy_J: float
    design_spark_energy_J: float
    placement_z_mm: float
    placement_radius_mm: float
    placement_angle_deg: float
    installation_note: str


def size_ignition_system(
    *,
    chamber_pressure_bar: float,
    chamber_length_mm: float,
    chamber_radius_mm: float,
    propellant: str,
    thrust_N: float,
) -> IgnitionSizingResult:
    """Return a deterministic ignition sizing recommendation for early design."""

    pressure = max(float(chamber_pressure_bar), 1.0)
    length = max(float(chamber_length_mm), 1.0)
    radius = max(float(chamber_radius_mm), 1.0)
    volume_l = 3.141592653589793 * radius**2 * length / 1_000_000.0
    severity = 1.35 if propellant.lower() in {"hydrolox", "methalox"} else 1.0
    minimum_energy = max(0.020, 0.012 * pressure * max(volume_l, 0.05) * severity)
    if propellant.lower() == "hypergolic":
        igniter = "pyrotechnic"
    elif pressure > 65.0 or thrust_N > 8_000.0:
        igniter = "torch"
    else:
        igniter = "spark"
    return IgnitionSizingResult(
        recommended_igniter=igniter,
        minimum_spark_energy_J=minimum_energy,
        design_spark_energy_J=minimum_energy * 3.0,
        placement_z_mm=min(length * 0.18, max(3.0, length - 3.0)),
        placement_radius_mm=radius * 0.88,
        placement_angle_deg=35.0,
        installation_note="Install upstream of the throat with a protected local film/cooling path and verify ignition transient margins during hot-fire development.",
    )
