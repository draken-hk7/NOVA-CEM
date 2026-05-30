"""Technical documentation generators."""

from __future__ import annotations

from typing import Any

import pandas as pd

from nova.core.types import CEMRunResult


class TechnicalDocGenerator:
    def assembly_instructions(self, result: CEMRunResult) -> str:
        design = result.design
        return (
            f"NOVA Assembly Instructions for {result.job_id}\n"
            "1. Inspect printed geometry for blocked channels and flange flatness.\n"
            "2. Clean all flow passages using qualified solvent and dry nitrogen.\n"
            "3. Install injector head using the specified bolt circle and torque pattern.\n"
            "4. Pressure test cooling circuit before hot-fire installation.\n"
            f"Predicted dry mass: {getattr(design, 'mass_kg', 0.0):.3f} kg.\n"
        )

    def bill_of_materials(self, result: CEMRunResult) -> pd.DataFrame:
        design: Any = result.design
        material = getattr(getattr(design, "manufacturing", None), "material", "unknown")
        mass = getattr(design, "mass_kg", 0.0)
        return pd.DataFrame(
            [
                {"item": "printed_engine_body", "material": material, "quantity": 1, "mass_kg": mass},
                {"item": "injector_fastener_set", "material": "steel", "quantity": 1, "mass_kg": 0.0},
            ]
        )

    def dimensional_drawing_svg(self, result: CEMRunResult) -> str:
        geometry = result.design.geometry
        lo, hi = geometry.bounds_mm
        width = max(hi[0] - lo[0], hi[1] - lo[1])
        length = hi[2] - lo[2]
        return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 220">
  <rect x="40" y="80" width="560" height="60" fill="none" stroke="black"/>
  <line x1="40" y1="160" x2="600" y2="160" stroke="black"/>
  <text x="250" y="190" font-size="14">Length {length:.1f} mm</text>
  <text x="44" y="70" font-size="14">Max dia {width:.1f} mm</text>
</svg>"""

    def test_procedure(self, result: CEMRunResult) -> str:
        return (
            f"NOVA Acceptance Test Procedure for {result.job_id}\n"
            "A. Visual and dimensional inspection.\n"
            "B. Hydrostatic proof to 1.5x chamber design pressure.\n"
            "C. Cooling circuit pressure drop and leak test.\n"
            "D. Instrumented low-duration hot-fire with automatic abort limits.\n"
        )

