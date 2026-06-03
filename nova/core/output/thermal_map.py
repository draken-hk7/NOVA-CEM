"""Rocket engine thermal map SVG generation."""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from nova.core.physics_solver import CoolingChannelSolver


@dataclass(slots=True)
class ThermalMapPoint:
    z_mm: float
    wall_temperature_K: float
    heat_flux_W_m2: float
    color: str


@dataclass(slots=True)
class ThermalMapData:
    points: list[ThermalMapPoint]
    length_mm: float
    throat_z_mm: float
    cooling_inlet_z_mm: float | None
    cooling_outlet_z_mm: float | None
    peak_heat_flux_z_mm: float
    min_wall_temperature_K: float
    max_wall_temperature_K: float
    peak_heat_flux_W_m2: float


class ThermalMapGenerator:
    """Generate a nozzle-axis wall-temperature map from NOVA rocket results."""

    def generate_svg(self, run_result: Any, path: str | Path, *, n_points: int = 160) -> ThermalMapData | None:
        data = self.from_run_result(run_result, n_points=n_points)
        if data is None:
            return None
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_svg(data), encoding="utf-8")
        return data

    def from_run_result(self, run_result: Any, *, n_points: int = 160) -> ThermalMapData | None:
        if getattr(run_result, "module", "") != "rocket-engine":
            return None
        design = getattr(run_result, "design", None)
        if design is None:
            return None
        metadata = getattr(design, "metadata", {}) or {}
        nozzle = metadata.get("nozzle", {})
        performance = getattr(design, "performance", None)
        if performance is None or not nozzle:
            return None

        throat_radius = _float(nozzle.get("throat_radius_mm"))
        chamber_temp = _float(getattr(performance, "chamber_temp_K", None))
        chamber_pressure = _float(getattr(performance, "chamber_pressure_bar", None))
        if throat_radius is None or chamber_temp is None or chamber_pressure is None:
            return None

        heat_flux = CoolingChannelSolver.bartz_heat_flux(
            chamber_temperature_K=chamber_temp,
            wall_temperature_K=650.0,
            chamber_pressure_bar=chamber_pressure,
            throat_radius_mm=throat_radius,
            n_points=n_points,
        )
        wall_temperature = self._wall_temperature(design, heat_flux, n_points)
        length = max(_float(nozzle.get("total_length_mm")) or float(n_points - 1), 1.0)
        throat_z = _float(nozzle.get("throat_z_mm"))
        if throat_z is None:
            throat_z = (_float(nozzle.get("chamber_length_mm")) or length * 0.42) + (_float(nozzle.get("convergence_length_mm")) or length * 0.08)
        throat_z = min(max(throat_z, 0.0), length)
        z_values = _axis_positions(length, throat_z, n_points)
        colors = [_temperature_color(value, float(np.min(wall_temperature)), float(np.max(wall_temperature))) for value in wall_temperature]
        peak_index = int(np.argmax(heat_flux))
        points = [
            ThermalMapPoint(float(z), float(temp), float(q), color)
            for z, temp, q, color in zip(z_values, wall_temperature, heat_flux, colors)
        ]
        ports = nozzle.get("coolant_ports", {})
        return ThermalMapData(
            points=points,
            length_mm=length,
            throat_z_mm=throat_z,
            cooling_inlet_z_mm=_port_z(ports, "inlet"),
            cooling_outlet_z_mm=_port_z(ports, "outlet"),
            peak_heat_flux_z_mm=float(z_values[peak_index]),
            min_wall_temperature_K=float(np.min(wall_temperature)),
            max_wall_temperature_K=float(np.max(wall_temperature)),
            peak_heat_flux_W_m2=float(np.max(heat_flux)),
        )

    @staticmethod
    def _wall_temperature(design: Any, heat_flux: np.ndarray, n_points: int) -> np.ndarray:
        thermal = getattr(design, "thermal", None)
        wall = getattr(thermal, "wall_temperature_K", None)
        if wall is not None:
            values = np.asarray(wall, dtype=float)
            if values.size == n_points:
                return values
            if values.size > 1:
                source = np.linspace(0.0, 1.0, values.size)
                target = np.linspace(0.0, 1.0, n_points)
                return np.interp(target, source, values)
        return 650.0 + np.asarray(heat_flux, dtype=float) / 6500.0

    def to_svg(self, data: ThermalMapData) -> str:
        width = 900
        height = 330
        margin_left = 74
        margin_right = 54
        plot_width = width - margin_left - margin_right
        strip_y = 135
        strip_h = 72
        axis_y = strip_y + strip_h + 32

        segments = []
        for index, point in enumerate(data.points[:-1]):
            next_point = data.points[index + 1]
            x = margin_left + plot_width * point.z_mm / data.length_mm
            x_next = margin_left + plot_width * next_point.z_mm / data.length_mm
            segments.append(f'<rect x="{x:.2f}" y="{strip_y}" width="{max(x_next - x, 1.0):.2f}" height="{strip_h}" fill="{point.color}"/>')

        markers = [
            _marker("Throat", data.throat_z_mm, data.length_mm, margin_left, plot_width, strip_y - 28, strip_y + strip_h + 8, "#111827"),
            _marker("Peak heat flux", data.peak_heat_flux_z_mm, data.length_mm, margin_left, plot_width, strip_y - 52, strip_y + strip_h + 20, "#d62828"),
        ]
        if data.cooling_inlet_z_mm is not None:
            markers.append(_marker("Cooling inlet", data.cooling_inlet_z_mm, data.length_mm, margin_left, plot_width, axis_y + 12, strip_y + strip_h + 8, "#1769ff"))
        if data.cooling_outlet_z_mm is not None:
            markers.append(_marker("Cooling outlet", data.cooling_outlet_z_mm, data.length_mm, margin_left, plot_width, axis_y + 34, strip_y + strip_h + 8, "#16706a"))

        legend = []
        for i in range(80):
            color = _temperature_color(float(i), 0.0, 79.0)
            legend.append(f'<rect x="{margin_left + i * 2.4:.2f}" y="78" width="2.6" height="14" fill="{color}"/>')

        return "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="330" viewBox="0 0 900 330" role="img" aria-label="NOVA rocket thermal map">',
                "<metadata>Generated by NOVA ThermalMapGenerator using CoolingChannelSolver.bartz_heat_flux.</metadata>",
                '<rect width="900" height="330" fill="#ffffff"/>',
                '<text x="34" y="38" font-family="Arial, Helvetica, sans-serif" font-size="22" font-weight="700" fill="#17202a">Rocket Engine Thermal Map</text>',
                '<text x="34" y="62" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#66727c">Wall temperature distribution from injector to nozzle exit; Bartz heat flux peak is at the throat.</text>',
                *legend,
                f'<text x="{margin_left}" y="70" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="#66727c">Coolest {data.min_wall_temperature_K:.0f} K</text>',
                f'<text x="{margin_left + 208}" y="70" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="#66727c">Hottest {data.max_wall_temperature_K:.0f} K</text>',
                f'<rect x="{margin_left}" y="{strip_y}" width="{plot_width}" height="{strip_h}" fill="#eef2f7" stroke="#d9dfdc" stroke-width="1"/>',
                *segments,
                f'<path d="M {margin_left:.1f} {axis_y:.1f} H {margin_left + plot_width:.1f}" stroke="#66727c" stroke-width="1"/>',
                f'<text x="{margin_left}" y="{axis_y + 18}" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#66727c">Injector</text>',
                f'<text x="{margin_left + plot_width - 68}" y="{axis_y + 18}" font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#66727c">Nozzle exit</text>',
                *markers,
                f'<text x="34" y="310" font-family="Arial, Helvetica, sans-serif" font-size="11" fill="#66727c">Peak heat flux: {data.peak_heat_flux_W_m2 / 1.0e6:.2f} MW/m2</text>',
                "</svg>",
            ]
        )


def _axis_positions(length_mm: float, throat_z_mm: float, n_points: int) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n_points)
    z = np.empty_like(t)
    before = t <= 0.5
    z[before] = np.interp(t[before], [0.0, 0.5], [0.0, throat_z_mm])
    z[~before] = np.interp(t[~before], [0.5, 1.0], [throat_z_mm, length_mm])
    return z


def _temperature_color(value: float, min_value: float, max_value: float) -> str:
    if not math.isfinite(value) or max_value <= min_value:
        ratio = 0.0
    else:
        ratio = (value - min_value) / (max_value - min_value)
    ratio = min(max(ratio, 0.0), 1.0)
    if ratio <= 0.5:
        local = ratio * 2.0
        return _blend((23, 105, 255), (255, 210, 63), local)
    return _blend((255, 210, 63), (214, 40, 40), (ratio - 0.5) * 2.0)


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], ratio: float) -> str:
    values = [round(a[i] + (b[i] - a[i]) * ratio) for i in range(3)]
    return f"#{values[0]:02x}{values[1]:02x}{values[2]:02x}"


def _marker(
    label: str,
    z_mm: float,
    length_mm: float,
    margin_left: float,
    plot_width: float,
    text_y: float,
    line_bottom: float,
    color: str,
) -> str:
    x = margin_left + plot_width * z_mm / max(length_mm, 1.0)
    return "\n".join(
        [
            f'<path d="M {x:.2f} 112 L {x:.2f} {line_bottom:.2f}" stroke="{color}" stroke-width="2" stroke-dasharray="4 3"/>',
            f'<circle cx="{x:.2f}" cy="112" r="4" fill="{color}"/>',
            f'<text x="{x + 6:.2f}" y="{text_y:.2f}" font-family="Arial, Helvetica, sans-serif" font-size="11" font-weight="700" fill="{color}">{html.escape(label)}</text>',
        ]
    )


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _port_z(ports: dict, name: str) -> float | None:
    port = ports.get(name, {}) if isinstance(ports, dict) else {}
    if not isinstance(port, dict):
        return None
    return _float(port.get("z_mm"))
