"""Regenerative cooling and compact heat-transfer correlations."""

from __future__ import annotations

import math

import numpy as np

from nova.core.exceptions import PhysicsViolationError
from nova.core.types import ChannelGeometry, CoolantProperties, CoolingResult


class CoolingChannelSolver:
    def solve_channel(
        self,
        heat_flux_W_m2: np.ndarray,
        channel_geometry: ChannelGeometry,
        coolant: CoolantProperties,
        flow_rate_kg_s: float,
    ) -> CoolingResult:
        if flow_rate_kg_s <= 0.0:
            raise PhysicsViolationError("Coolant flow rate must be positive")
        q = np.asarray(heat_flux_W_m2, dtype=float)
        if q.size == 0 or np.any(q < 0.0):
            raise PhysicsViolationError("Heat flux array must be non-empty and non-negative")

        area_m2 = channel_geometry.channel_area_mm2 * 1.0e-6 * channel_geometry.n_channels
        diameter_m = channel_geometry.hydraulic_diameter_mm * 1.0e-3
        length_m = channel_geometry.length_mm * 1.0e-3
        if area_m2 <= 0.0 or diameter_m <= 0.0 or length_m <= 0.0:
            raise PhysicsViolationError("Channel geometry dimensions must be positive")

        velocity = flow_rate_kg_s / (coolant.density_kg_m3 * area_m2)
        reynolds = coolant.density_kg_m3 * velocity * diameter_m / coolant.viscosity_Pa_s
        prandtl = coolant.cp_J_kgK * coolant.viscosity_Pa_s / coolant.thermal_conductivity_W_mK
        if reynolds < 2300.0:
            nusselt = 3.66
            friction = 64.0 / max(reynolds, 1.0)
        else:
            nusselt = 0.023 * reynolds**0.8 * prandtl**0.4
            friction = 0.3164 / reynolds**0.25

        h_coolant = nusselt * coolant.thermal_conductivity_W_mK / diameter_m
        wetted_area_m2 = math.pi * diameter_m * length_m * channel_geometry.n_channels
        total_heat_W = float(np.mean(q) * wetted_area_m2)
        delta_T_coolant = total_heat_W / (flow_rate_kg_s * coolant.cp_J_kgK)
        coolant_temperature = np.linspace(
            coolant.inlet_temperature_K,
            coolant.inlet_temperature_K + delta_T_coolant,
            q.size,
        )
        wall_temperature = coolant_temperature + q / max(h_coolant, 1.0)
        pressure_drop_Pa = friction * (length_m / diameter_m) * 0.5 * coolant.density_kg_m3 * velocity**2

        return CoolingResult(
            wall_temperature_K=wall_temperature,
            coolant_temperature_K=coolant_temperature,
            pressure_drop_bar=pressure_drop_Pa / 1.0e5,
            coolant_outlet_temperature_K=float(coolant_temperature[-1]),
            max_wall_temperature_K=float(np.max(wall_temperature)),
            reynolds_number=float(reynolds),
            nusselt_number=float(nusselt),
        )

    @staticmethod
    def bartz_heat_flux(
        chamber_temperature_K: float,
        wall_temperature_K: float,
        chamber_pressure_bar: float,
        throat_radius_mm: float,
        n_points: int = 128,
    ) -> np.ndarray:
        if throat_radius_mm <= 0.0:
            raise PhysicsViolationError("Throat radius must be positive")
        base = 1.85e6 * (chamber_pressure_bar / 30.0) ** 0.8 * (25.0 / throat_radius_mm) ** 0.2
        thermal_drive = max(chamber_temperature_K - wall_temperature_K, 1.0) / 2800.0
        x = np.linspace(-1.0, 1.0, n_points)
        throat_peak = 1.0 + 1.4 * np.exp(-(x / 0.22) ** 2)
        return base * thermal_drive * throat_peak

