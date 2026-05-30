"""Rocket-engine-specific geometry builders."""

from __future__ import annotations

import math

import numpy as np

from nova.core.geometry_engine.primitives import GeometryBuilder, MeshSolid
from nova.core.knowledge_engine.rules import RocketHeuristics
from nova.core.types import ChannelGeometry, InjectorResult, RocketNozzleResult


class RocketNozzleGeometry:
    def __init__(self, segments: int = 128) -> None:
        self.builder = GeometryBuilder()
        self.segments = segments

    def bell_nozzle(
        self,
        throat_radius_mm: float,
        chamber_radius_mm: float,
        expansion_ratio: float,
        chamber_length_mm: float,
        wall_thickness_mm: float,
        n_cooling_channels: int,
    ) -> RocketNozzleResult:
        if min(throat_radius_mm, chamber_radius_mm, expansion_ratio, chamber_length_mm, wall_thickness_mm) <= 0.0:
            raise ValueError("Rocket nozzle dimensions must be positive")

        convergence_length = max(1.2 * chamber_radius_mm, 3.0 * (chamber_radius_mm - throat_radius_mm))
        chamber_z = np.linspace(0.0, chamber_length_mm, 36)
        chamber_r = np.full_like(chamber_z, chamber_radius_mm)
        conv_x = np.linspace(0.0, 1.0, 40)[1:]
        conv_z = chamber_length_mm + conv_x * convergence_length
        conv_r = throat_radius_mm + (chamber_radius_mm - throat_radius_mm) * 0.5 * (1.0 + np.cos(math.pi * conv_x))
        throat_z = chamber_length_mm + convergence_length
        rao = RocketHeuristics.rao_nozzle_contour(throat_radius_mm, expansion_ratio, n_points=160)
        nozzle_z = throat_z + rao[1:, 0]
        nozzle_r = rao[1:, 1]
        inner_profile = np.column_stack(
            [
                np.concatenate([chamber_z, conv_z, nozzle_z]),
                np.concatenate([chamber_r, conv_r, nozzle_r]),
            ]
        )

        channel_depth_mm = max(0.5, min(0.75, 0.22 * wall_thickness_mm))
        outer_profile = inner_profile.copy()
        outer_profile[:, 1] += wall_thickness_mm + channel_depth_mm
        shell = self.builder.revolved_shell(inner_profile, outer_profile, self.segments, "bell_nozzle_shell")

        total_length = float(inner_profile[-1, 0])
        exit_radius = float(nozzle_r[-1])
        injector_flange = self.builder.cylinder(
            chamber_radius_mm + wall_thickness_mm + 10.0,
            8.0,
            center=(0.0, 0.0, -4.0),
            segments=self.segments,
        )
        exit_flange = self.builder.cylinder(
            exit_radius + wall_thickness_mm + 8.0,
            6.0,
            center=(0.0, 0.0, total_length + 3.0),
            segments=self.segments,
        )
        solid = self.builder.boolean_union(shell, injector_flange, exit_flange)
        channel_width = max(0.8, 0.30 * wall_thickness_mm)
        circumferential_pitch = max(1.0, (2.0 * math.pi * (chamber_radius_mm + wall_thickness_mm)) / max(n_cooling_channels, 1))
        helix_pitch = max(total_length / 1.2, 80.0)
        channel_paths = self._channel_paths(
            radius_profile=outer_profile,
            n_channels=n_cooling_channels,
            pitch_mm=helix_pitch,
            start_z=0.0,
            end_z=total_length,
        )
        channel_length = float(np.mean([np.sum(np.linalg.norm(np.diff(path, axis=0), axis=1)) for path in channel_paths]))
        channels = ChannelGeometry(
            hydraulic_diameter_mm=2.0 * channel_width * channel_depth_mm / (channel_width + channel_depth_mm),
            length_mm=channel_length,
            n_channels=n_cooling_channels,
            channel_area_mm2=channel_width * channel_depth_mm,
            wall_thickness_mm=wall_thickness_mm,
        )

        metadata = {
            "geometry_type": "bell_nozzle",
            "throat_radius_mm": throat_radius_mm,
            "chamber_radius_mm": chamber_radius_mm,
            "exit_radius_mm": exit_radius,
            "expansion_ratio": expansion_ratio,
            "chamber_length_mm": chamber_length_mm,
            "convergence_length_mm": convergence_length,
            "total_length_mm": total_length + 6.0,
            "min_wall_thickness_mm": wall_thickness_mm,
            "min_channel_diameter_mm": min(channel_width, channel_depth_mm),
            "n_cooling_channels": n_cooling_channels,
            "channel_pitch_mm": circumferential_pitch,
            "helix_pitch_mm": helix_pitch,
            "max_overhang_angle_deg": 38.0,
            "feature_trace": [
                "thrust requirement -> throat area -> throat radius",
                "expansion ratio -> exit radius",
                "heat flux heuristic -> cooling channel count and pitch",
            ],
        }
        solid.metadata.update(metadata)
        return RocketNozzleResult(solid=solid, channels=channels, channel_paths=channel_paths, metadata=metadata)

    def aerospike_nozzle(
        self,
        throat_radius_mm: float,
        expansion_ratio: float,
        length_mm: float,
        wall_thickness_mm: float,
    ) -> RocketNozzleResult:
        exit_radius = throat_radius_mm * math.sqrt(expansion_ratio)
        spike = self.builder.cone_frustum(exit_radius + wall_thickness_mm, throat_radius_mm, length_mm, segments=self.segments)
        channels = ChannelGeometry(
            hydraulic_diameter_mm=max(0.5, wall_thickness_mm * 0.25),
            length_mm=length_mm,
            n_channels=24,
            channel_area_mm2=max(0.25, wall_thickness_mm * 0.25) ** 2,
            wall_thickness_mm=wall_thickness_mm,
        )
        spike.metadata.update(
            {
                "geometry_type": "aerospike_nozzle",
                "throat_radius_mm": throat_radius_mm,
                "exit_radius_mm": exit_radius,
                "expansion_ratio": expansion_ratio,
                "min_wall_thickness_mm": wall_thickness_mm,
            }
        )
        return RocketNozzleResult(spike, channels, [], spike.metadata)

    def _channel_paths(
        self,
        radius_profile: np.ndarray,
        n_channels: int,
        pitch_mm: float,
        start_z: float,
        end_z: float,
    ) -> list[np.ndarray]:
        n_channels = max(1, int(n_channels))
        samples = 220
        z = np.linspace(start_z, end_z, samples)
        radius = np.interp(z, radius_profile[:, 0], radius_profile[:, 1])
        turns = max((end_z - start_z) / pitch_mm, 0.2)
        paths: list[np.ndarray] = []
        for channel in range(n_channels):
            phase = 2.0 * math.pi * channel / n_channels
            theta = 2.0 * math.pi * turns * (z - start_z) / max(end_z - start_z, 1.0e-9) + phase
            paths.append(np.column_stack([radius * np.cos(theta), radius * np.sin(theta), z]))
        return paths


class InjectorHeadGeometry:
    def __init__(self, segments: int = 96) -> None:
        self.builder = GeometryBuilder()
        self.segments = segments

    def coaxial_swirler_injector(
        self,
        n_elements: int,
        element_pitch_mm: float,
        oxidizer_post_dia_mm: float,
        fuel_annulus_gap_mm: float,
        manifold_thickness_mm: float,
    ) -> InjectorResult:
        if min(n_elements, element_pitch_mm, oxidizer_post_dia_mm, fuel_annulus_gap_mm, manifold_thickness_mm) <= 0:
            raise ValueError("Injector dimensions must be positive")
        radius = max(oxidizer_post_dia_mm * 3.0, math.sqrt(n_elements) * element_pitch_mm * 0.62)
        disk = self.builder.cylinder(radius, manifold_thickness_mm, center=(0.0, 0.0, -manifold_thickness_mm / 2.0), segments=self.segments)
        element_positions = self._element_positions(n_elements, element_pitch_mm)
        disk.name = "coaxial_swirler_injector"
        disk.metadata.update(
            {
                "n_elements": n_elements,
                "element_pitch_mm": element_pitch_mm,
                "oxidizer_post_dia_mm": oxidizer_post_dia_mm,
                "fuel_annulus_gap_mm": fuel_annulus_gap_mm,
                "manifold_thickness_mm": manifold_thickness_mm,
                "element_positions_mm": element_positions.tolist(),
                "min_wall_thickness_mm": max(0.5, fuel_annulus_gap_mm),
                "min_channel_diameter_mm": min(oxidizer_post_dia_mm, 2.0 * fuel_annulus_gap_mm),
            }
        )
        return InjectorResult(disk, n_elements, disk.metadata)

    def impinging_injector(
        self,
        n_elements: int,
        orifice_dia_mm: float,
        included_angle_deg: float,
        plate_thickness_mm: float,
    ) -> InjectorResult:
        result = self.coaxial_swirler_injector(n_elements, 2.8 * orifice_dia_mm, orifice_dia_mm, 0.5 * orifice_dia_mm, plate_thickness_mm)
        result.solid.metadata["injector_type"] = "impinging"
        result.solid.metadata["included_angle_deg"] = included_angle_deg
        return result

    @staticmethod
    def _element_positions(n_elements: int, pitch: float) -> np.ndarray:
        positions = [[0.0, 0.0]]
        ring = 1
        while len(positions) < n_elements:
            count = 6 * ring
            radius = ring * pitch
            for i in range(count):
                theta = 2.0 * math.pi * i / count
                positions.append([radius * math.cos(theta), radius * math.sin(theta)])
                if len(positions) >= n_elements:
                    break
            ring += 1
        return np.asarray(positions[:n_elements])
