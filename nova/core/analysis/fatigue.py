"""Conservative thermal-fatigue design-screening calculation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from nova.core.knowledge_engine.rules import get_material_properties, normalize_material


THERMAL_FATIGUE_PROPERTIES = {
    "copper": {"cte_per_K": 16.5e-6, "youngs_modulus_GPa": 117.0, "poisson": 0.34, "ductility_strain": 0.10},
    "inconel718": {"cte_per_K": 13.0e-6, "youngs_modulus_GPa": 200.0, "poisson": 0.29, "ductility_strain": 0.08},
    "titanium": {"cte_per_K": 8.6e-6, "youngs_modulus_GPa": 114.0, "poisson": 0.34, "ductility_strain": 0.06},
    "steel": {"cte_per_K": 12.0e-6, "youngs_modulus_GPa": 200.0, "poisson": 0.30, "ductility_strain": 0.05},
}


@dataclass(slots=True)
class ThermalFatigueResult:
    material: str
    temperature_delta_K: float
    thermal_strain: float
    thermal_stress_MPa: float
    estimated_cycles: int
    recommended_firings: int
    model_note: str


def estimate_thermal_fatigue_life(*, material: str, peak_wall_temperature_K: float, coolant_temperature_K: float) -> ThermalFatigueResult:
    """Estimate low-cycle thermal fatigue life using a conservative strain screen."""

    key = normalize_material(material)
    data = THERMAL_FATIGUE_PROPERTIES.get(key, THERMAL_FATIGUE_PROPERTIES["steel"])
    properties = get_material_properties(key)
    delta = max(float(peak_wall_temperature_K) - float(coolant_temperature_K), 1.0)
    cte = float(data["cte_per_K"])
    modulus_mpa = float(data["youngs_modulus_GPa"]) * 1000.0
    poisson = float(data["poisson"])
    strain = cte * delta
    stress = modulus_mpa * strain / max(1.0 - poisson, 0.1)
    yield_strain = float(properties["yield_strength_mpa"]) / modulus_mpa
    allowable_strain = max(min(yield_strain * 0.45, float(data["ductility_strain"]) * 0.12), 1.0e-5)
    strain_ratio = max(strain / allowable_strain, 1.0e-9)
    cycles = int(max(1.0, min(1_000_000.0, 15_000.0 / strain_ratio**2.15)))
    firings = max(1, int(cycles * 0.65))
    return ThermalFatigueResult(
        material=key,
        temperature_delta_K=delta,
        thermal_strain=strain,
        thermal_stress_MPa=stress,
        estimated_cycles=cycles,
        recommended_firings=firings,
        model_note="Screening estimate based on restrained thermal strain; establish life with material coupons and duty-cycle testing.",
    )
