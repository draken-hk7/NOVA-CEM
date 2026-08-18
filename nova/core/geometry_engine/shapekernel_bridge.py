"""Optional bridge to LEAP71 ShapeKernel's .NET/PicoGK geometry runner.

ShapeKernel is a C# source library rather than a Python package.  This bridge
keeps the integration deliberately process-isolated: NOVA sends a JSON rocket
description to the runner and accepts a native STL only when the runner reports
success.  A missing SDK, source checkout, runner, or runner failure always
falls back to the existing CadQuery geometry path.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_GEOMETRY_BACKENDS = frozenset({"cadquery", "picogk", "shapekernel"})
NOVA_CEM_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class ShapeKernelBackendStatus:
    """Availability and selection state for the external ShapeKernel runner."""

    requested_backend: str
    active_backend: str
    dotnet_available: bool
    runner_available: bool
    runner_command: tuple[str, ...] | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ShapeKernelRunResult:
    """A native STL emitted by the isolated ShapeKernel runner process."""

    stl_path: Path
    runner_message: str


class ShapeKernelBridge:
    """Run the optional ShapeKernel STL generator with a CadQuery fallback."""

    RUNNER_TIMEOUT_SECONDS = 180

    def __init__(self, backend: str | None = None) -> None:
        requested = (backend or os.getenv("NOVA_GEOMETRY_BACKEND", "cadquery")).strip().lower()
        self.requested_backend = requested if requested in SUPPORTED_GEOMETRY_BACKENDS else "cadquery"
        self._runner_dir = NOVA_CEM_ROOT / "nova" / "shapekernel_runner"
        self._work_root = NOVA_CEM_ROOT / "outputs" / "shapekernel_work"
        self._searched_runner_paths: list[Path] = []
        self._source_dir = Path(
            os.getenv(
                "NOVA_SHAPEKERNEL_SOURCE",
                str(self._runner_dir / "vendor" / "LEAP71_ShapeKernel"),
            )
        ).expanduser()
        self._dotnet = self._find_dotnet() if self.requested_backend == "shapekernel" else None
        self._command = self._resolve_runner_command() if self._dotnet else None
        self.active_backend = "shapekernel" if self.requested_backend == "shapekernel" and self._command else "cadquery"
        self.reason = self._initial_reason()
        if self.requested_backend == "shapekernel" and self.active_backend != "shapekernel":
            self._debug(f"Falling back to CadQuery: {self.reason}")

    @property
    def status(self) -> ShapeKernelBackendStatus:
        return ShapeKernelBackendStatus(
            requested_backend=self.requested_backend,
            active_backend=self.active_backend,
            dotnet_available=self._dotnet is not None,
            runner_available=self._command is not None,
            runner_command=tuple(self._command) if self._command else None,
            reason=self.reason,
        )

    def build_rocket_stl(self, **parameters: Any) -> ShapeKernelRunResult | None:
        """Ask the C# runner for a bell-engine STL, returning ``None`` on fallback."""

        if self.active_backend != "shapekernel" or not self._command:
            return None
        if str(parameters.get("nozzle_type", "bell")).lower() != "bell":
            self._fallback("ShapeKernel runner currently supports bell-nozzle STL export only")
            return None

        try:
            output_dir = self._create_working_directory()
            atexit.register(shutil.rmtree, output_dir, ignore_errors=True)
            output_path = output_dir / "engine.stl"
            payload = {key: value for key, value in parameters.items() if value is not None}
            payload["output_stl"] = str(output_path)
            completed = subprocess.run(
                self._command,
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                cwd=self._runner_dir,
                timeout=self.RUNNER_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception:
            self._fallback_with_traceback("ShapeKernel runner could not start")
            return None

        try:
            response = self._response_from_stdout(completed.stdout)
            if completed.returncode != 0 or not response.get("success"):
                detail = str(response.get("error") or completed.stderr or completed.stdout).strip()
                self._fallback(f"ShapeKernel runner failed: {detail or 'no diagnostic returned'}")
                return None
            reported_path = response.get("stl_path")
            if reported_path and Path(str(reported_path)).resolve() != output_path.resolve():
                self._fallback("ShapeKernel runner returned an unexpected STL output path")
                return None
            if not output_path.is_file() or output_path.stat().st_size == 0:
                self._fallback("ShapeKernel runner reported success but did not create an STL")
                return None
        except Exception:
            self._fallback_with_traceback("ShapeKernel runner output validation failed")
            return None

        self.reason = None
        return ShapeKernelRunResult(
            stl_path=output_path,
            runner_message=str(response.get("message", "ShapeKernel STL generated")),
        )

    def _find_dotnet(self) -> str | None:
        executable = shutil.which("dotnet")
        if not executable:
            return None
        try:
            completed = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except OSError:
            return None
        return executable if completed.returncode == 0 and completed.stdout.strip() else None

    def _resolve_runner_command(self) -> list[str] | None:
        assert self._dotnet is not None
        configured_runner = os.getenv("NOVA_SHAPEKERNEL_RUNNER")
        if configured_runner:
            configured_path = Path(configured_runner).expanduser()
            command = self._command_for_runner_path(configured_path)
            if command:
                return command

        for configuration in ("Release", "Debug"):
            runner_dll = self._runner_dir / "bin" / configuration / "net9.0" / "nova_runner.dll"
            self._searched_runner_paths.append(runner_dll)
            try:
                exists = runner_dll.is_file()
            except OSError as exc:
                self._debug(f"Runner search failed at {runner_dll}: {exc}")
                continue
            self._debug(f"Searching for compiled runner at {runner_dll}: exists={exists}")
            if exists:
                self._debug(f"Using ShapeKernel runner command: {self._dotnet} {runner_dll}")
                return [self._dotnet, str(runner_dll)]

        project = self._runner_dir / "nova_runner.csproj"
        if project.is_file() and (self._source_dir / "ShapeKernel").is_dir():
            return [
                self._dotnet,
                "run",
                "--project",
                str(project),
                "--configuration",
                "Release",
                f"-p:ShapeKernelSourceDir={self._source_dir}",
                "--",
            ]
        self._debug(f"No ShapeKernel runner was found. Searched: {self._runner_search_summary()}")
        return None

    def _command_for_runner_path(self, runner_path: Path) -> list[str] | None:
        self._searched_runner_paths.append(runner_path)
        try:
            exists = runner_path.is_file()
        except OSError as exc:
            self._debug(f"Configured ShapeKernel runner path could not be inspected ({runner_path}): {exc}")
            return None
        self._debug(f"Searching configured ShapeKernel runner at {runner_path}: exists={exists}")
        if not exists:
            return None
        if runner_path.suffix.lower() == ".dll":
            assert self._dotnet is not None
            self._debug(f"Using configured ShapeKernel runner command: {self._dotnet} {runner_path}")
            return [self._dotnet, str(runner_path)]
        return [str(runner_path)]

    def _initial_reason(self) -> str | None:
        if self.requested_backend != "shapekernel":
            return None
        if not self._dotnet:
            return "dotnet runtime is not available"
        if not self._command:
            return f"ShapeKernel runner was not found. Searched: {self._runner_search_summary()}"
        return None

    def _fallback(self, reason: str) -> None:
        self.active_backend = "cadquery"
        self.reason = reason
        self._debug(f"Falling back to CadQuery: {reason}. Searched: {self._runner_search_summary()}")

    def _create_working_directory(self) -> Path:
        self._work_root.mkdir(parents=True, exist_ok=True)
        output_dir = self._work_root / f"run-{uuid.uuid4().hex}"
        output_dir.mkdir()
        self._debug(f"Using ShapeKernel working directory: {output_dir}")
        return output_dir

    def _fallback_with_traceback(self, context: str) -> None:
        self._fallback(f"{context}:\n{traceback.format_exc()}")

    def _runner_search_summary(self) -> str:
        if not self._searched_runner_paths:
            return "no runner path was inspected"
        return "; ".join(str(path) for path in self._searched_runner_paths)

    @staticmethod
    def _debug(message: str) -> None:
        print(f"[NOVA ShapeKernel] {message}", file=sys.stderr)

    @staticmethod
    def _response_from_stdout(stdout: str) -> dict[str, Any]:
        for line in reversed(stdout.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                return candidate
        return {}
