"""Cooling and flow-channel routing geometry."""

from __future__ import annotations

import math

import numpy as np

from nova.core.geometry_engine.primitives import GeometryBuilder, MeshSolid


class ChannelRouter:
    def helical_channels(
        self,
        host_cylinder: MeshSolid,
        n_channels: int,
        channel_width_mm: float,
        channel_depth_mm: float,
        pitch_mm: float,
        start_z: float,
        end_z: float,
    ) -> MeshSolid:
        """Attach helical cooling-channel path metadata to a cylindrical host."""

        if n_channels <= 0 or channel_width_mm <= 0.0 or channel_depth_mm <= 0.0 or pitch_mm <= 0.0:
            raise ValueError("Channel count and dimensions must be positive")
        result = host_cylinder.copy(name=f"{host_cylinder.name}_helical_channels")
        radius = float(result.metadata.get("max_radius_mm", result.metadata.get("radius_mm", 1.0)))
        length = abs(end_z - start_z)
        turns = max(length / pitch_mm, 0.25)
        samples = max(64, int(48 * turns))
        paths = []
        z = np.linspace(start_z, end_z, samples)
        for channel in range(n_channels):
            phase = 2.0 * math.pi * channel / n_channels
            theta = 2.0 * math.pi * turns * (z - start_z) / max(end_z - start_z, 1.0e-9) + phase
            paths.append(np.column_stack([radius * np.cos(theta), radius * np.sin(theta), z]))
        result.metadata["channel_paths"] = [path.tolist() for path in paths]
        result.metadata["n_cooling_channels"] = n_channels
        result.metadata["min_channel_diameter_mm"] = min(channel_width_mm, channel_depth_mm)
        result.metadata["channel_width_mm"] = channel_width_mm
        result.metadata["channel_depth_mm"] = channel_depth_mm
        result.metadata["channel_pitch_mm"] = pitch_mm
        return result

    def conformal_channels(self, host_surface: MeshSolid, n_channels: int, cross_section: tuple[float, float]) -> MeshSolid:
        if n_channels <= 0 or cross_section[0] <= 0.0 or cross_section[1] <= 0.0:
            raise ValueError("Conformal channel inputs must be positive")
        result = host_surface.copy(name=f"{host_surface.name}_conformal_channels")
        result.metadata["n_conformal_channels"] = n_channels
        result.metadata["min_channel_diameter_mm"] = min(cross_section)
        return result

    def branching_manifold(self, inlet_dia: float, n_outlets: int, outlet_dia: float) -> MeshSolid:
        if inlet_dia <= 0.0 or n_outlets <= 0 or outlet_dia <= 0.0:
            raise ValueError("Manifold diameters and outlet count must be positive")
        builder = GeometryBuilder()
        base = builder.cylinder(inlet_dia / 2.0, inlet_dia * 1.8, segments=48)
        outlets = []
        radius = inlet_dia
        for i in range(n_outlets):
            angle = 2.0 * math.pi * i / n_outlets
            outlet = builder.cylinder(
                outlet_dia / 2.0,
                inlet_dia * 1.2,
                center=(radius * math.cos(angle), radius * math.sin(angle), inlet_dia * 0.45),
                segments=24,
            )
            outlets.append(outlet)
        result = builder.boolean_union(base, *outlets)
        result.name = "branching_manifold"
        result.metadata.update({"inlet_dia_mm": inlet_dia, "outlet_dia_mm": outlet_dia, "n_outlets": n_outlets})
        return result

