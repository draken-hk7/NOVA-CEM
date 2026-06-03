"""Heat-exchanger fluid-dynamics and thermal design formulae."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from nova.core.exceptions import PhysicsViolationError


@dataclass(slots=True)
class HeatExchangerFluid:
    name: str
    density_kg_m3: float
    cp_J_kgK: float
    viscosity_Pa_s: float
    thermal_conductivity_W_mK: float


@dataclass(slots=True)
class HeatExchangerDesignCalculation:
    effectiveness: float
    ntu: float
    required_area_m2: float
    hot_mass_flow_kg_s: float
    cold_mass_flow_kg_s: float
    hot_pressure_drop_bar: float
    cold_pressure_drop_bar: float
    pressure_drop_bar: float
    hot_outlet_temp_C: float
    cold_outlet_temp_C: float
    overall_heat_transfer_coefficient_W_m2K: float
    dimensions_mm: dict[str, float]
    hydraulic_diameter_mm: float


class HeatExchangerSolver:
    FLUIDS = {
        "air": HeatExchangerFluid("air", 1.2, 1005.0, 1.8e-5, 0.026),
        "exhaust": HeatExchangerFluid("exhaust", 0.45, 1150.0, 4.0e-5, 0.055),
        "water": HeatExchangerFluid("water", 997.0, 4182.0, 8.9e-4, 0.6),
        "hydrogen": HeatExchangerFluid("hydrogen", 5.6, 14300.0, 1.3e-5, 0.105),
        "helium": HeatExchangerFluid("helium", 1.6, 5193.0, 2.0e-5, 0.151),
    }

    MATERIAL_CONDUCTIVITY_W_MK = {
        "copper": 400.0,
        "inconel": 11.4,
        "inconel718": 11.4,
        "steel": 16.0,
    }

    def NTU_effectiveness(self, NTU: float, Cr: float, flow_arrangement: str) -> float:
        if NTU < 0.0 or not (0.0 <= Cr <= 1.0):
            raise PhysicsViolationError("NTU must be non-negative and Cr in [0, 1]")
        if flow_arrangement == "parallel":
            return (1.0 - math.exp(-NTU * (1.0 + Cr))) / (1.0 + Cr)
        if flow_arrangement == "counterflow":
            if abs(1.0 - Cr) < 1.0e-12:
                return NTU / (1.0 + NTU)
            return (1.0 - math.exp(-NTU * (1.0 - Cr))) / (1.0 - Cr * math.exp(-NTU * (1.0 - Cr)))
        if flow_arrangement == "crossflow":
            return 1.0 - math.exp((math.exp(-Cr * NTU) - 1.0) / max(Cr, 1.0e-12))
        raise PhysicsViolationError(f"Unsupported flow arrangement: {flow_arrangement}")

    def design_ntu_effectiveness(
        self,
        *,
        hot_fluid: str,
        cold_fluid: str,
        duty_kW: float,
        hot_inlet_temp_C: float,
        hot_outlet_temp_C: float,
        cold_inlet_temp_C: float,
        max_pressure_bar: float,
        material: str,
    ) -> HeatExchangerDesignCalculation:
        if duty_kW <= 0.0:
            raise PhysicsViolationError("Heat duty must be positive")
        hot = self.fluid_properties(hot_fluid)
        cold = self.fluid_properties(cold_fluid)
        hot_delta_K = hot_inlet_temp_C - hot_outlet_temp_C
        if hot_delta_K <= 0.0:
            raise PhysicsViolationError("Hot outlet must be cooler than hot inlet")
        if hot_outlet_temp_C <= cold_inlet_temp_C:
            raise PhysicsViolationError("Hot outlet must remain above cold inlet for counterflow heat exchange")

        heat_duty_W = duty_kW * 1000.0
        hot_capacity_W_K = heat_duty_W / hot_delta_K
        cold_capacity_W_K = hot_capacity_W_K
        hot_mass_flow = hot_capacity_W_K / hot.cp_J_kgK
        cold_mass_flow = cold_capacity_W_K / cold.cp_J_kgK
        cold_outlet_temp_C = cold_inlet_temp_C + heat_duty_W / cold_capacity_W_K
        delta_t_max = hot_inlet_temp_C - cold_inlet_temp_C
        effectiveness = heat_duty_W / (min(hot_capacity_W_K, cold_capacity_W_K) * delta_t_max)
        if not (0.0 < effectiveness < 1.0):
            raise PhysicsViolationError("Requested heat duty and temperatures require impossible effectiveness")

        capacity_ratio = min(hot_capacity_W_K, cold_capacity_W_K) / max(hot_capacity_W_K, cold_capacity_W_K)
        ntu = self.NTU_from_effectiveness(effectiveness, capacity_ratio, "counterflow")
        overall_u = self.overall_heat_transfer_coefficient(hot, cold, material)
        required_area_m2 = ntu * min(hot_capacity_W_K, cold_capacity_W_K) / overall_u
        dimensions_mm = self.compact_gyroid_dimensions(required_area_m2)
        hydraulic_diameter_mm = max(1.4, min(dimensions_mm["width_mm"], dimensions_mm["height_mm"]) / 32.0)
        channel_area_mm2 = max(15.0, dimensions_mm["width_mm"] * dimensions_mm["height_mm"] * 0.035)
        channel_geometry = type(
            "HXChannelGeometry",
            (),
            {
                "hydraulic_diameter_mm": hydraulic_diameter_mm,
                "length_mm": dimensions_mm["depth_mm"] * 3.0,
                "channel_area_mm2": channel_area_mm2,
            },
        )()
        hot_drop = self.pressure_drop_channel(channel_geometry, hot, hot_mass_flow)
        cold_drop = self.pressure_drop_channel(channel_geometry, cold, cold_mass_flow)
        pressure_drop = max(hot_drop, cold_drop)
        if pressure_drop > max_pressure_bar:
            scale = math.sqrt(pressure_drop / max_pressure_bar)
            for key in dimensions_mm:
                dimensions_mm[key] *= scale
            channel_geometry.channel_area_mm2 *= scale**2
            channel_geometry.hydraulic_diameter_mm *= scale
            channel_geometry.length_mm *= scale
            hydraulic_diameter_mm = channel_geometry.hydraulic_diameter_mm
            hot_drop = self.pressure_drop_channel(channel_geometry, hot, hot_mass_flow)
            cold_drop = self.pressure_drop_channel(channel_geometry, cold, cold_mass_flow)
            pressure_drop = max(hot_drop, cold_drop)

        return HeatExchangerDesignCalculation(
            effectiveness=effectiveness,
            ntu=ntu,
            required_area_m2=required_area_m2,
            hot_mass_flow_kg_s=hot_mass_flow,
            cold_mass_flow_kg_s=cold_mass_flow,
            hot_pressure_drop_bar=hot_drop,
            cold_pressure_drop_bar=cold_drop,
            pressure_drop_bar=pressure_drop,
            hot_outlet_temp_C=hot_outlet_temp_C,
            cold_outlet_temp_C=cold_outlet_temp_C,
            overall_heat_transfer_coefficient_W_m2K=overall_u,
            dimensions_mm=dimensions_mm,
            hydraulic_diameter_mm=hydraulic_diameter_mm,
        )

    def NTU_from_effectiveness(self, effectiveness: float, Cr: float, flow_arrangement: str) -> float:
        if not (0.0 < effectiveness < 1.0) or not (0.0 <= Cr <= 1.0):
            raise PhysicsViolationError("Effectiveness must be in (0, 1) and Cr in [0, 1]")
        if flow_arrangement != "counterflow":
            raise PhysicsViolationError(f"Unsupported inverse NTU flow arrangement: {flow_arrangement}")
        if abs(1.0 - Cr) < 1.0e-12:
            return effectiveness / (1.0 - effectiveness)
        numerator = effectiveness - 1.0
        denominator = effectiveness * Cr - 1.0
        ratio = numerator / denominator
        if ratio <= 0.0:
            raise PhysicsViolationError("Invalid effectiveness/capacity ratio combination")
        return math.log(ratio) / (Cr - 1.0)

    def fluid_properties(self, fluid: str) -> HeatExchangerFluid:
        if fluid not in self.FLUIDS:
            raise PhysicsViolationError(f"Unsupported heat exchanger fluid: {fluid}")
        return self.FLUIDS[fluid]

    def overall_heat_transfer_coefficient(
        self,
        hot: HeatExchangerFluid,
        cold: HeatExchangerFluid,
        material: str,
        wall_thickness_m: float = 0.0012,
    ) -> float:
        material_k = self.MATERIAL_CONDUCTIVITY_W_MK.get(material, self.MATERIAL_CONDUCTIVITY_W_MK["steel"])
        hot_h = 45.0 + 1600.0 * hot.thermal_conductivity_W_mK
        cold_h = 45.0 + 1600.0 * cold.thermal_conductivity_W_mK
        return 1.0 / (1.0 / hot_h + wall_thickness_m / material_k + 1.0 / cold_h)

    def compact_gyroid_dimensions(self, required_area_m2: float) -> dict[str, float]:
        if required_area_m2 <= 0.0:
            raise PhysicsViolationError("Required area must be positive")
        area_density_m2_m3 = 4200.0
        volume_m3 = required_area_m2 / area_density_m2_m3
        cube_side_mm = max(45.0, min(220.0, volume_m3 ** (1.0 / 3.0) * 1000.0))
        return {
            "width_mm": cube_side_mm,
            "height_mm": cube_side_mm,
            "depth_mm": cube_side_mm * 1.25,
        }

    def pressure_drop_channel(self, geometry: Any, fluid: Any, flow_rate: float) -> float:
        if flow_rate <= 0.0:
            raise PhysicsViolationError("Flow rate must be positive")
        diameter_m = float(getattr(geometry, "hydraulic_diameter_mm", 1.0)) * 1.0e-3
        length_m = float(getattr(geometry, "length_mm", 100.0)) * 1.0e-3
        area_m2 = float(getattr(geometry, "channel_area_mm2", 1.0)) * 1.0e-6
        density = float(getattr(fluid, "density_kg_m3", 997.0))
        viscosity = float(getattr(fluid, "viscosity_Pa_s", 8.9e-4))
        velocity = flow_rate / (density * area_m2)
        reynolds = density * velocity * diameter_m / viscosity
        friction = 64.0 / reynolds if reynolds < 2300.0 else 0.3164 / reynolds**0.25
        return friction * (length_m / diameter_m) * 0.5 * density * velocity**2 / 1.0e5

    def LMTD(
        self,
        T_h_in: float,
        T_h_out: float,
        T_c_in: float,
        T_c_out: float,
        flow_type: str,
    ) -> float:
        if flow_type == "counterflow":
            delta_1 = T_h_in - T_c_out
            delta_2 = T_h_out - T_c_in
        elif flow_type == "parallel":
            delta_1 = T_h_in - T_c_in
            delta_2 = T_h_out - T_c_out
        else:
            raise PhysicsViolationError(f"Unsupported LMTD flow type: {flow_type}")
        if delta_1 <= 0.0 or delta_2 <= 0.0:
            raise PhysicsViolationError("Terminal temperature differences must be positive")
        if abs(delta_1 - delta_2) < 1.0e-12:
            return delta_1
        return (delta_1 - delta_2) / math.log(delta_1 / delta_2)
