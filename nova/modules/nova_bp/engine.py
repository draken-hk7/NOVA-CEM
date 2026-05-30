"""NOVA-BP scaffold design module."""

from __future__ import annotations

from dataclasses import dataclass

from nova.core.geometry_engine.heatexchanger_geometry import HeatExchangerGeometry
from nova.core.input_schema import BioprintingScaffoldSpec


@dataclass(slots=True)
class BPDesignResult:
    geometry: object
    porosity: float
    pore_size_um: float


class NovaBP:
    def design(self, spec: BioprintingScaffoldSpec) -> BPDesignResult:
        geometry = HeatExchangerGeometry().gyroid_minimal_surface(bounds=spec.bounds_mm, resolution=24, thickness_mm=max(0.05, spec.pore_size_um / 1000.0 * 0.08))
        geometry.name = "bioprinting_scaffold"
        geometry.metadata.update({"porosity": spec.porosity, "pore_size_um": spec.pore_size_um, "material": spec.material})
        return BPDesignResult(geometry, spec.porosity, spec.pore_size_um)

