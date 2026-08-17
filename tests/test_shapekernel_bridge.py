import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from nova.cli.main import build_parser
from nova.core.geometry_engine import shapekernel_bridge
from nova.core.geometry_engine.shapekernel_bridge import ShapeKernelBridge
from nova.core.output import GeometryExporter


def _artifact_dir(name: str) -> Path:
    directory = Path("outputs/test-artifacts") / name
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def test_shapekernel_bridge_falls_back_when_dotnet_is_unavailable(monkeypatch):
    monkeypatch.setattr(shapekernel_bridge.shutil, "which", lambda _name: None)

    bridge = ShapeKernelBridge(backend="shapekernel")

    assert bridge.status.requested_backend == "shapekernel"
    assert bridge.status.active_backend == "cadquery"
    assert not bridge.status.dotnet_available
    assert bridge.status.reason == "dotnet runtime is not available"


def test_shapekernel_bridge_sends_json_and_accepts_native_stl(monkeypatch):
    artifact_dir = _artifact_dir("shapekernel-bridge")
    runner = artifact_dir / "nova_runner.dll"
    runner.write_bytes(b"runner")
    runner_output_dir = artifact_dir / "runner-output"
    runner_output_dir.mkdir(parents=True, exist_ok=True)
    seen_payload = {}

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "9.0.100\n", "")
        payload = json.loads(kwargs["input"])
        seen_payload.update(payload)
        output = Path(payload["output_stl"])
        output.write_text("solid shapekernel\nendsolid shapekernel\n", encoding="ascii")
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"success": True, "stl_path": str(output), "message": "generated"}) + "\n",
            "",
        )

    monkeypatch.setenv("NOVA_SHAPEKERNEL_RUNNER", str(runner))
    monkeypatch.setattr(shapekernel_bridge.shutil, "which", lambda _name: "dotnet")
    monkeypatch.setattr(shapekernel_bridge.subprocess, "run", fake_run)
    monkeypatch.setattr(shapekernel_bridge.tempfile, "mkdtemp", lambda prefix: str(runner_output_dir))
    bridge = ShapeKernelBridge(backend="shapekernel")

    result = bridge.build_rocket_stl(
        nozzle_type="bell",
        throat_radius_mm=8.0,
        chamber_radius_mm=20.0,
        expansion_ratio=20.0,
        chamber_length_mm=70.0,
        wall_thickness_mm=1.5,
        n_cooling_channels=8,
    )

    assert result is not None
    assert result.stl_path.exists()
    assert bridge.status.active_backend == "shapekernel"
    assert seen_payload["nozzle_type"] == "bell"
    assert seen_payload["output_stl"] == str(result.stl_path)


def test_native_shapekernel_stl_is_copied_after_validation(monkeypatch):
    artifact_dir = _artifact_dir("shapekernel-native-export")
    native_stl = artifact_dir / "native.stl"
    native_stl.write_bytes(b"shape-kernel-native-stl")
    destination = artifact_dir / "exported.stl"
    solid = SimpleNamespace(metadata={"native_stl_path": str(native_stl)})

    monkeypatch.setattr("nova.core.output.exporter.validate_for_stl_export", lambda _solid: None)
    GeometryExporter().to_stl(solid, str(destination))

    assert destination.read_bytes() == native_stl.read_bytes()


def test_cli_accepts_shapekernel_geometry_backend():
    args = build_parser().parse_args(
        [
            "design",
            "rocket-engine",
            "--thrust",
            "5000N",
            "--propellant",
            "kerolox",
            "--geometry-backend",
            "shapekernel",
        ]
    )

    assert args.geometry_backend == "shapekernel"


def test_runner_project_uses_picogk_and_shapekernel_base_shapes():
    root = Path(__file__).resolve().parents[1] / "nova" / "shapekernel_runner"
    project = (root / "nova_runner.csproj").read_text(encoding="utf-8")
    program = (root / "Program.cs").read_text(encoding="utf-8")

    assert 'PackageReference Include="PicoGK"' in project
    assert "ShapeKernel\\**\\*.cs" in project
    assert all(name in program for name in ("BaseCylinder", "BaseCone", "BasePipe", "Sh.ExportVoxelsToSTLFile"))
