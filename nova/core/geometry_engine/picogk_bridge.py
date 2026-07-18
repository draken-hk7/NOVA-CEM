"""Optional PicoGK geometry-backend bridge.

PicoGK is optional and is never imported by NOVA's normal CadQuery deployment.
When a compatible Python wrapper exposes ``build_rocket_nozzle`` or
``create_rocket_nozzle``, the bridge delegates to it.  Otherwise it quietly
uses the supplied CadQuery builder so calculations and artifacts remain
available in every supported NOVA environment.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class GeometryBackendStatus:
    requested_backend: str
    active_backend: str
    picogk_available: bool


class PicoGKBridge:
    """Select a guarded optional PicoGK integration with a CadQuery fallback."""

    def __init__(self, backend: str | None = None) -> None:
        requested = (backend or os.getenv("NOVA_GEOMETRY_BACKEND", "cadquery")).strip().lower()
        self.requested_backend = requested if requested in {"cadquery", "picogk"} else "cadquery"
        self._picogk = self._load_picogk() if self.requested_backend == "picogk" else None
        self.active_backend = "picogk" if self._supports_rocket_builder(self._picogk) else "cadquery"

    @property
    def status(self) -> GeometryBackendStatus:
        return GeometryBackendStatus(
            requested_backend=self.requested_backend,
            active_backend=self.active_backend,
            picogk_available=self._picogk is not None,
        )

    def build_rocket_nozzle(self, fallback: Callable[[], Any], **parameters: Any) -> Any:
        """Use a compatible optional wrapper; otherwise call CadQuery fallback."""

        if self.active_backend != "picogk" or self._picogk is None:
            return fallback()
        try:
            builder = getattr(self._picogk, "build_rocket_nozzle", None) or getattr(self._picogk, "create_rocket_nozzle", None)
            result = builder(**parameters) if callable(builder) else None
            if result is not None and hasattr(result, "solid") and hasattr(result, "metadata"):
                result.metadata.setdefault("geometry_backend", "picogk")
                return result
        except Exception:
            pass
        self.active_backend = "cadquery"
        return fallback()

    @staticmethod
    def _load_picogk() -> Any | None:
        try:
            return importlib.import_module("picogk")
        except Exception:
            return None

    @staticmethod
    def _supports_rocket_builder(module: Any | None) -> bool:
        return bool(module and (callable(getattr(module, "build_rocket_nozzle", None)) or callable(getattr(module, "create_rocket_nozzle", None))))
