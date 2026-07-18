"""Structural and wall-thickness validation before additive export."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any
from warnings import warn

import numpy as np

from nova.core.analysis.combustion_stability import analyze_combustion_stability
from nova.core.geometry_engine.primitives import MeshSolid
from nova.core.knowledge_engine.rules import get_material_properties


LPBF_MIN_WALL_THICKNESS_MM = 0.4
MIN_COOLING_CHANNEL_WALL_MM = 0.5
MIN_MANIFOLD_WALL_THICKNESS_MM = 0.4
PRESSURE_VESSEL_SAFETY_FACTOR = 4.0
COMBUSTION_RESONANCE_MIN_HZ = 1000.0
COMBUSTION_RESONANCE_MAX_HZ = 5000.0


@dataclass(slots=True)
class CheckResult:
    name: str
    passed: bool
    actual_value: float | None
    minimum_value: float
    message: str


@dataclass(slots=True)
class ValidationResult:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)


class ManufacturingValidator:
    """Validate a CadQuery-backed engine solid against LPBF and pressure rules."""

    def validate(self, solid: MeshSolid) -> ValidationResult:
        checks = [
            self.minimum_wall_thickness_check(solid),
            self.pressure_vessel_check(solid),
            self.cooling_channel_wall_check(solid),
            self.manifold_wall_thickness_check(solid),
            self.combustion_stability_check(solid),
        ]
        return ValidationResult(passed=all(check.passed for check in checks), checks=checks)

    def minimum_wall_thickness_check(self, solid: MeshSolid) -> CheckResult:
        actual = self._minimum_local_thickness_mm(solid)
        passed = actual is not None and actual >= LPBF_MIN_WALL_THICKNESS_MM
        if actual is None:
            return CheckResult(
                name="Minimum wall thickness",
                passed=False,
                actual_value=None,
                minimum_value=LPBF_MIN_WALL_THICKNESS_MM,
                message="Could not determine minimum local wall thickness from the CadQuery solid.",
            )
        return CheckResult(
            name="Minimum wall thickness",
            passed=passed,
            actual_value=actual,
            minimum_value=LPBF_MIN_WALL_THICKNESS_MM,
            message=(
                f"Minimum local wall thickness is {actual:.3f} mm; "
                f"LPBF minimum is {LPBF_MIN_WALL_THICKNESS_MM:.3f} mm."
            ),
        )

    def pressure_vessel_check(self, solid: MeshSolid) -> CheckResult:
        metadata = solid.metadata
        actual = _first_float(
            metadata,
            "chamber_wall_thickness_mm",
            "actual_chamber_wall_thickness_mm",
            "min_wall_thickness_mm",
        )
        pressure_bar = _first_float(metadata, "chamber_pressure_bar")
        chamber_radius_mm = _first_float(metadata, "chamber_radius_mm")
        material_name = metadata.get("material") or metadata.get("normalized_material")
        if actual is None or pressure_bar is None or chamber_radius_mm is None or not material_name:
            return CheckResult(
                name="Pressure vessel wall",
                passed=True,
                actual_value=actual,
                minimum_value=0.0,
                message="Pressure vessel check skipped; chamber pressure, radius, material, or wall metadata is missing.",
            )

        yield_strength_mpa = float(get_material_properties(str(material_name))["yield_strength_mpa"])
        pressure_mpa = pressure_bar * 0.1
        minimum = (pressure_mpa * chamber_radius_mm) / (
            2.0 * yield_strength_mpa * PRESSURE_VESSEL_SAFETY_FACTOR
        )
        passed = actual >= minimum
        return CheckResult(
            name="Pressure vessel wall",
            passed=passed,
            actual_value=actual,
            minimum_value=minimum,
            message=(
                f"Chamber wall is {actual:.3f} mm; hoop-stress minimum is {minimum:.3f} mm "
                f"at safety factor {PRESSURE_VESSEL_SAFETY_FACTOR:.1f}."
            ),
        )

    def cooling_channel_wall_check(self, solid: MeshSolid) -> CheckResult:
        metadata = solid.metadata
        actual = _first_float(
            metadata,
            "cooling_channel_wall_mm",
            "channel_to_bore_wall_mm",
            "chamber_wall_thickness_mm",
        )
        n_channels = int(float(metadata.get("n_cooling_channels", metadata.get("n_cooling_channels_cut", 0)) or 0))
        if n_channels <= 0:
            return CheckResult(
                name="Cooling channel wall",
                passed=True,
                actual_value=None,
                minimum_value=MIN_COOLING_CHANNEL_WALL_MM,
                message="Cooling channel wall check skipped; no chamber cooling channels were detected.",
            )
        if actual is None:
            return CheckResult(
                name="Cooling channel wall",
                passed=False,
                actual_value=None,
                minimum_value=MIN_COOLING_CHANNEL_WALL_MM,
                message="Cooling channel wall check failed; channel-to-bore wall thickness metadata is missing.",
            )
        passed = actual >= MIN_COOLING_CHANNEL_WALL_MM
        return CheckResult(
            name="Cooling channel wall",
            passed=passed,
            actual_value=actual,
            minimum_value=MIN_COOLING_CHANNEL_WALL_MM,
            message=(
                f"Cooling-channel-to-bore wall is {actual:.3f} mm; "
                f"minimum is {MIN_COOLING_CHANNEL_WALL_MM:.3f} mm."
            ),
        )

    def manifold_wall_thickness_check(self, solid: MeshSolid) -> CheckResult:
        metadata = solid.metadata
        manifold = metadata.get("propellant_manifold", {})
        if not isinstance(manifold, dict) or not manifold:
            return CheckResult(
                name="Propellant manifold wall",
                passed=True,
                actual_value=None,
                minimum_value=MIN_MANIFOLD_WALL_THICKNESS_MM,
                message="Propellant manifold wall check skipped; no manifold metadata was detected.",
            )
        actual = _first_float(metadata, "manifold_wall_thickness_mm", "manifold_min_wall_thickness_mm")
        if actual is None:
            actual = _first_float(manifold, "min_wall_thickness_mm")
        minimum = _first_float(metadata, "manifold_min_wall_thickness_mm")
        if minimum is None:
            minimum = _first_float(manifold, "required_min_wall_thickness_mm") or MIN_MANIFOLD_WALL_THICKNESS_MM
        if actual is None:
            return CheckResult(
                name="Propellant manifold wall",
                passed=False,
                actual_value=None,
                minimum_value=minimum,
                message="Propellant manifold wall check failed; wall thickness metadata is missing.",
            )
        passed = actual >= minimum
        return CheckResult(
            name="Propellant manifold wall",
            passed=passed,
            actual_value=actual,
            minimum_value=minimum,
            message=(
                f"Propellant manifold wall is {actual:.3f} mm; "
                f"minimum is {minimum:.3f} mm."
            ),
        )

    def combustion_stability_check(self, solid: MeshSolid) -> CheckResult:
        metadata = solid.metadata
        chamber_length_mm = _first_float(metadata, "chamber_length_mm")
        chamber_radius_mm = _first_float(metadata, "chamber_radius_mm")
        speed_of_sound_m_s = _first_float(
            metadata,
            "combustion_gas_speed_of_sound_m_s",
            "combustion_speed_of_sound_m_s",
            "speed_of_sound_m_s",
        )
        if speed_of_sound_m_s is None:
            chamber_temp_K = _first_float(metadata, "chamber_temp_K", "combustion_temperature_K")
            gamma = _first_float(metadata, "combustion_gamma", "gamma") or 1.22
            gas_constant_J_kgK = _first_float(metadata, "combustion_gas_constant_J_kgK", "gas_constant_J_kgK") or 355.0
            if chamber_temp_K is not None:
                speed_of_sound_m_s = math.sqrt(max(gamma * gas_constant_J_kgK * chamber_temp_K, 0.0))
        if chamber_length_mm is None or chamber_length_mm <= 0.0 or speed_of_sound_m_s is None or speed_of_sound_m_s <= 0.0:
            return CheckResult(
                name="Combustion stability acoustic mode",
                passed=True,
                actual_value=None,
                minimum_value=COMBUSTION_RESONANCE_MAX_HZ,
                message=(
                    "Combustion stability check skipped; chamber length or combustion gas "
                    "speed-of-sound metadata is missing."
                ),
            )
        acoustic_frequency_hz = speed_of_sound_m_s / (2.0 * chamber_length_mm / 1000.0)
        in_problem_band = COMBUSTION_RESONANCE_MIN_HZ <= acoustic_frequency_hz <= COMBUSTION_RESONANCE_MAX_HZ
        stability_risk = False
        coupling_note = ""
        if chamber_radius_mm is not None and chamber_radius_mm > 0.0:
            analysis = analyze_combustion_stability(
                chamber_length_mm=chamber_length_mm,
                chamber_radius_mm=chamber_radius_mm,
                speed_of_sound_m_s=speed_of_sound_m_s,
            )
            risky_modes = [mode for mode in analysis.modes if mode.within_coupling_band and not mode.is_reference]
            stability_risk = analysis.stability_risk
            if risky_modes:
                coupling_note = " Coupled mode risk: " + ", ".join(
                    f"{mode.family} {mode.order} at {mode.frequency_hz:.0f} Hz" for mode in risky_modes
                ) + "."
        passed = not in_problem_band and not stability_risk
        return CheckResult(
            name="Combustion stability acoustic mode",
            passed=passed,
            actual_value=acoustic_frequency_hz,
            minimum_value=COMBUSTION_RESONANCE_MAX_HZ,
            message=(
                f"First longitudinal chamber acoustic mode is {acoustic_frequency_hz:.0f} Hz; "
                f"NOVA warns inside the {COMBUSTION_RESONANCE_MIN_HZ:.0f}-"
                f"{COMBUSTION_RESONANCE_MAX_HZ:.0f} Hz small-engine resonance band."
                f"{coupling_note}"
            ),
        )

    def _minimum_local_thickness_mm(self, solid: MeshSolid) -> float | None:
        metadata_min = _first_float(
            solid.metadata,
            "minimum_local_thickness_mm",
            "min_wall_thickness_mm",
            "chamber_wall_thickness_mm",
        )
        sampled_min = _sample_radial_wall_thickness(solid)
        values = [value for value in (metadata_min, sampled_min) if value is not None and math.isfinite(value)]
        return min(values) if values else None


def validate_for_stl_export(solid: MeshSolid) -> ValidationResult:
    """Run export-time validation and emit runtime warnings for failed checks."""

    result = ManufacturingValidator().validate(solid)
    if not result.passed:
        for check in result.checks:
            if not check.passed:
                warn(f"STL validation warning: {check.message}", RuntimeWarning, stacklevel=2)
    return result


def _first_float(metadata: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key not in metadata:
            continue
        try:
            return float(metadata[key])
        except (TypeError, ValueError):
            continue
    return None


def _sample_radial_wall_thickness(solid: MeshSolid) -> float | None:
    """Estimate local wall thickness by intersecting radial lines with the B-rep.

    The line queries use the CadQuery/OCP shape directly and work well for NOVA's
    axisymmetric chamber and nozzle shells. Metadata remains the final fallback
    for small injector/manifold details where ray sampling can miss the feature.
    """

    try:
        from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
        from OCP.gce import gce_MakeLin
        from OCP.gp import gp_Dir, gp_Pnt
    except Exception:
        return None

    try:
        shape = solid.shape
        lo, hi = solid.bounds_mm
    except Exception:
        return None

    z_min = float(solid.metadata.get("channel_cut_start_z_mm", lo[2]))
    z_max = float(solid.metadata.get("channel_cut_end_z_mm", hi[2]))
    if z_max <= z_min:
        z_min, z_max = float(lo[2]), float(hi[2])
    if z_max <= z_min:
        return None

    z_values = np.linspace(z_min + 0.05 * (z_max - z_min), z_max - 0.05 * (z_max - z_min), 9)
    angles = np.linspace(0.0, math.pi, 8, endpoint=False)
    min_interval: float | None = None

    for z in z_values:
        for angle in angles:
            direction = (math.cos(float(angle)), math.sin(float(angle)), 0.0)
            try:
                line = gce_MakeLin(gp_Pnt(0.0, 0.0, float(z)), gp_Dir(*direction)).Value()
                intersector = BRepIntCurveSurface_Inter()
                intersector.Init(shape.wrapped, line, 1.0e-4)
            except Exception:
                continue

            distances: list[float] = []
            while intersector.More():
                point = intersector.Pnt()
                distances.append(point.X() * direction[0] + point.Y() * direction[1])
                intersector.Next()
            for interval in _solid_intervals_from_line(distances):
                if min_interval is None or interval < min_interval:
                    min_interval = interval

    return min_interval


def _solid_intervals_from_line(distances: list[float]) -> list[float]:
    if len(distances) < 2:
        return []
    unique: list[float] = []
    for distance in sorted(distances):
        if not unique or abs(distance - unique[-1]) > 1.0e-3:
            unique.append(distance)
    intervals: list[float] = []
    for index in range(0, len(unique) - 1, 2):
        interval = unique[index + 1] - unique[index]
        if interval > 0.03:
            intervals.append(interval)
    return intervals
