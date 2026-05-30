"""Domain-specific NOVA exceptions."""

from __future__ import annotations


class PhysicsViolationError(ValueError):
    """Raised when a requested design violates a physical constraint."""

    def __init__(
        self,
        message: str,
        *,
        requirement: str | None = None,
        actual: float | None = None,
        limit: float | None = None,
        unit: str | None = None,
    ) -> None:
        details: list[str] = []
        if requirement:
            details.append(f"requirement={requirement}")
        if actual is not None:
            details.append(f"actual={actual:g}{unit or ''}")
        if limit is not None:
            details.append(f"limit={limit:g}{unit or ''}")
        suffix = f" ({', '.join(details)})" if details else ""
        super().__init__(f"{message}{suffix}")
        self.requirement = requirement
        self.actual = actual
        self.limit = limit
        self.unit = unit


class ManufacturingViolationError(ValueError):
    """Raised when a design cannot be made compatible with a process."""


class GeometryValidationError(ValueError):
    """Raised when generated geometry fails mesh or manufacturability checks."""

