"""Slicer integration boundary."""

from __future__ import annotations

import math
from pathlib import Path

from nova.core.types import GCodeResult, ProcessParams


class SlicerInterface:
    """Generate deterministic placeholder G-code for direct print handoff tests."""

    def slice_stl(self, stl_path: str, process_params: ProcessParams) -> GCodeResult:
        path = Path(stl_path)
        if not path.exists():
            raise FileNotFoundError(stl_path)
        gcode_path = path.with_suffix(".gcode")
        estimated_layers = max(1, int(math.ceil(100.0 / process_params.layer_height_mm)))
        with gcode_path.open("w", encoding="ascii") as handle:
            handle.write("; NOVA generated deterministic slice handoff\n")
            handle.write(f"; source={path.name}\n")
            handle.write(f"; layer_height_mm={process_params.layer_height_mm}\n")
            handle.write(f"; estimated_layers={estimated_layers}\n")
        return GCodeResult(str(gcode_path), estimated_layers, estimated_layers * 0.015)

