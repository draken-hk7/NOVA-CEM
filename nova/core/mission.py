"""Mission-level calculations for NOVA engine designs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping


G0_M_S2 = 9.81
DEFAULT_OF_RATIOS = {
    "kerolox": 2.56,
    "methalox": 3.55,
    "hydrolox": 5.50,
    "hypergolic": 1.65,
    "solid": 2.50,
}
HYDROGEN_LOWER_HEATING_VALUE_KWH_KG = 33.33
DEFAULT_ELECTROLYSIS_EFFICIENCY = 0.65
DAYS_PER_MONTH = 30.4375


@dataclass(slots=True)
class TrajectoryPoint:
    time_s: float
    altitude_m: float
    velocity_m_s: float
    phase: str


@dataclass(slots=True)
class MissionResult:
    engine_job_id: str
    vehicle_mass_kg: float
    propellant_mass_kg: float
    dry_mass_kg: float
    wet_mass_kg: float
    specific_impulse_s: float
    thrust_N: float
    mass_flow_rate_kg_s: float
    delta_v_m_s: float
    burn_time_s: float
    thrust_to_weight: float
    max_altitude_m: float
    hydrogen_mass_needed_kg_s: float
    of_ratio: float
    can_liftoff: bool
    burnout_altitude_m: float
    coast_altitude_m: float
    planned_launches_per_month: float
    hydrogen_per_launch_kg: float
    hydrogen_monthly_kg: float
    solar_energy_kwh_per_day: float
    trajectory: list[TrajectoryPoint] = field(default_factory=list)


def calculate_mission(
    engine_payload: Mapping[str, Any],
    *,
    vehicle_mass_kg: float,
    propellant_mass_kg: float,
    engine_job_id: str = "",
    planned_launches_per_month: float = 1.0,
) -> MissionResult:
    """Calculate mission metrics from a NOVA rocket engine job payload."""

    dry_mass = _positive(vehicle_mass_kg, "vehicle_mass_kg")
    propellant_mass = _positive(propellant_mass_kg, "propellant_mass_kg")
    wet_mass = dry_mass + propellant_mass
    performance = _engine_performance(engine_payload)
    isp = _positive(_first_number(performance, "specific_impulse_s", "Isp"), "specific_impulse_s")
    thrust = _positive(_first_number(performance, "thrust_N", "thrust"), "thrust_N")
    mass_flow_rate = _first_number(performance, "mass_flow_rate_kg_s", "mass_flow_rate")
    if mass_flow_rate is None or mass_flow_rate <= 0.0 or not math.isfinite(mass_flow_rate):
        mass_flow_rate = thrust / (isp * G0_M_S2)
    mass_flow_rate = _positive(mass_flow_rate, "mass_flow_rate_kg_s")

    delta_v = isp * G0_M_S2 * math.log(wet_mass / dry_mass)
    burn_time = propellant_mass / mass_flow_rate
    thrust_to_weight = thrust / (wet_mass * G0_M_S2)
    of_ratio = _of_ratio(engine_payload)
    hydrogen_mass_needed = mass_flow_rate / (1.0 + of_ratio)
    trajectory, burnout_altitude, coast_altitude = _simulate_vertical_trajectory(
        thrust_N=thrust,
        mass_flow_rate_kg_s=mass_flow_rate,
        dry_mass_kg=dry_mass,
        wet_mass_kg=wet_mass,
        burn_time_s=burn_time,
        thrust_to_weight=thrust_to_weight,
    )
    max_altitude = max((point.altitude_m for point in trajectory), default=0.0)
    launches = _positive(planned_launches_per_month, "planned_launches_per_month")
    hydrogen_per_launch = hydrogen_mass_needed * burn_time
    hydrogen_monthly = hydrogen_per_launch * launches
    solar_energy_kwh_per_day = hydrogen_monthly * HYDROGEN_LOWER_HEATING_VALUE_KWH_KG / (DEFAULT_ELECTROLYSIS_EFFICIENCY * DAYS_PER_MONTH)

    return MissionResult(
        engine_job_id=engine_job_id,
        vehicle_mass_kg=dry_mass,
        propellant_mass_kg=propellant_mass,
        dry_mass_kg=dry_mass,
        wet_mass_kg=wet_mass,
        specific_impulse_s=isp,
        thrust_N=thrust,
        mass_flow_rate_kg_s=mass_flow_rate,
        delta_v_m_s=delta_v,
        burn_time_s=burn_time,
        thrust_to_weight=thrust_to_weight,
        max_altitude_m=max_altitude,
        hydrogen_mass_needed_kg_s=hydrogen_mass_needed,
        of_ratio=of_ratio,
        can_liftoff=thrust_to_weight > 1.0,
        burnout_altitude_m=burnout_altitude,
        coast_altitude_m=coast_altitude,
        planned_launches_per_month=launches,
        hydrogen_per_launch_kg=hydrogen_per_launch,
        hydrogen_monthly_kg=hydrogen_monthly,
        solar_energy_kwh_per_day=solar_energy_kwh_per_day,
        trajectory=trajectory,
    )


def mission_report_text(result: MissionResult) -> str:
    liftoff = "yes" if result.can_liftoff else "no"
    return "\n".join(
        [
            "NOVA Mission Report",
            f"Engine job: {result.engine_job_id or 'unknown'}",
            "",
            "Inputs:",
            f"  Vehicle dry mass: {result.vehicle_mass_kg:.3f} kg",
            f"  Propellant mass: {result.propellant_mass_kg:.3f} kg",
            f"  Wet mass: {result.wet_mass_kg:.3f} kg",
            f"  Engine Isp: {result.specific_impulse_s:.3f} s",
            f"  Engine thrust: {result.thrust_N:.3f} N",
            f"  Engine mass flow: {result.mass_flow_rate_kg_s:.6f} kg/s",
            "",
            "Mission Performance:",
            f"  Delta-V: {result.delta_v_m_s:.3f} m/s",
            f"  Burn time: {result.burn_time_s:.3f} s",
            f"  Thrust-to-weight ratio: {result.thrust_to_weight:.3f}",
            f"  Can lift off: {liftoff}",
            f"  Screening trajectory max altitude: {result.max_altitude_m:.3f} m",
            f"  Burnout altitude: {result.burnout_altitude_m:.3f} m",
            f"  Coast altitude gain: {result.coast_altitude_m:.3f} m",
            f"  Hydrogen mass needed per second: {result.hydrogen_mass_needed_kg_s:.6f} kg/s",
            f"  O/F ratio used for hydrogen estimate: {result.of_ratio:.3f}",
            "",
            "Hydrogen Production Planning:",
            f"  Planned launches per month: {result.planned_launches_per_month:.2f}",
            f"  Hydrogen per launch: {result.hydrogen_per_launch_kg:.3f} kg",
            f"  Hydrogen per month: {result.hydrogen_monthly_kg:.3f} kg",
            f"  Solar electricity required: {result.solar_energy_kwh_per_day:.3f} kWh/day at 65% electrolysis efficiency",
            "",
            "Model Notes:",
            "  Delta-V uses Isp * 9.81 * ln(wet_mass / dry_mass).",
            "  Altitude is a vertical screening trajectory with powered ascent and ballistic coast; drag and guidance losses are not modeled.",
            "  Hydrogen-production energy uses 33.33 kWh/kg LHV and 65% electrolysis efficiency.",
        ]
    )


def _engine_performance(engine_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    design = engine_payload.get("design", {})
    if isinstance(design, Mapping):
        performance = design.get("performance", {})
        if isinstance(performance, Mapping) and performance:
            return performance
    metrics = engine_payload.get("metrics", {})
    if isinstance(metrics, Mapping) and metrics:
        return metrics
    raise ValueError("Engine job payload does not contain performance data")


def _of_ratio(engine_payload: Mapping[str, Any]) -> float:
    design = engine_payload.get("design", {})
    if isinstance(design, Mapping):
        metadata = design.get("metadata", {})
        if isinstance(metadata, Mapping):
            combustion = metadata.get("combustion", {})
            if isinstance(combustion, Mapping):
                ratio = _as_float(combustion.get("OF_ratio"))
                if ratio is not None and ratio > 0.0:
                    return ratio
    inputs = engine_payload.get("inputs", {})
    if isinstance(inputs, Mapping):
        propellant = str(inputs.get("propellant", "")).lower()
        if propellant in DEFAULT_OF_RATIOS:
            return DEFAULT_OF_RATIOS[propellant]
    parameters = engine_payload.get("parameters", {})
    if isinstance(parameters, Mapping):
        propellant = str(parameters.get("propellant", "")).lower()
        if propellant in DEFAULT_OF_RATIOS:
            return DEFAULT_OF_RATIOS[propellant]
    return DEFAULT_OF_RATIOS["hydrolox"]


def _simulate_vertical_trajectory(
    *,
    thrust_N: float,
    mass_flow_rate_kg_s: float,
    dry_mass_kg: float,
    wet_mass_kg: float,
    burn_time_s: float,
    thrust_to_weight: float,
) -> tuple[list[TrajectoryPoint], float, float]:
    if thrust_to_weight <= 1.0:
        return [TrajectoryPoint(0.0, 0.0, 0.0, "grounded")], 0.0, 0.0
    points = [TrajectoryPoint(0.0, 0.0, 0.0, "powered")]
    altitude = 0.0
    velocity = 0.0
    time_s = 0.0
    steps = min(360, max(30, int(math.ceil(burn_time_s / 0.12))))
    dt = burn_time_s / steps
    for index in range(1, steps + 1):
        remaining_mass = max(dry_mass_kg, wet_mass_kg - mass_flow_rate_kg_s * time_s)
        acceleration = thrust_N / remaining_mass - G0_M_S2
        next_velocity = max(velocity + acceleration * dt, 0.0)
        altitude += 0.5 * (velocity + next_velocity) * dt
        velocity = next_velocity
        time_s = min(index * dt, burn_time_s)
        points.append(TrajectoryPoint(time_s, max(altitude, 0.0), velocity, "powered"))
    burnout_altitude = max(altitude, 0.0)
    coast_start = altitude
    coast_time = max(velocity / G0_M_S2, 0.0)
    coast_steps = min(180, max(12, int(math.ceil(coast_time / 0.18)))) if coast_time > 0.0 else 0
    coast_dt = coast_time / coast_steps if coast_steps else 0.0
    for index in range(1, coast_steps + 1):
        next_velocity = max(velocity - G0_M_S2 * coast_dt, 0.0)
        altitude += 0.5 * (velocity + next_velocity) * coast_dt
        velocity = next_velocity
        time_s = burn_time_s + index * coast_dt
        points.append(TrajectoryPoint(time_s, max(altitude, 0.0), velocity, "coast"))
    return points, burnout_altitude, max(altitude - coast_start, 0.0)


def _first_number(payload: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _as_float(payload.get(key))
        if value is not None:
            return value
    return None


def _positive(value: float | None, name: str) -> float:
    if value is None or value <= 0.0 or not math.isfinite(value):
        raise ValueError(f"{name} must be positive")
    return float(value)


def _as_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None
