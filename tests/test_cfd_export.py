from pathlib import Path
from types import SimpleNamespace

from nova.cli.main import build_parser
from nova.core.output import GeometryExporter


def _fake_rocket_design():
    performance = SimpleNamespace(
        chamber_pressure_bar=50.0,
        chamber_temp_K=3500.0,
        mass_flow_rate_kg_s=1.25,
    )
    thermal = SimpleNamespace(max_wall_temperature_K=725.0)
    metadata = {
        "nozzle": {
            "chamber_radius_mm": 28.0,
            "throat_radius_mm": 9.0,
            "exit_radius_mm": 41.0,
            "chamber_length_mm": 38.0,
            "convergence_length_mm": 24.0,
            "total_length_mm": 130.0,
            "coolant_ports": {
                "inlet": {"z_mm": 96.0, "axis": [0.0, 1.0, 0.0]},
                "outlet": {"z_mm": 8.0, "axis": [1.0, 0.0, 0.0]},
            },
        }
    }
    return SimpleNamespace(performance=performance, thermal=thermal, metadata=metadata)


def test_cfd_mesh_export_writes_gmsh_patches_and_boundary_conditions():
    artifact_dir = Path("outputs/test-artifacts/cfd-export")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    mesh = artifact_dir / "engine_internal_flow.msh"
    boundary_conditions = artifact_dir / "boundary_conditions.txt"

    files = GeometryExporter().to_cfd_mesh(
        _fake_rocket_design(),
        str(mesh),
        boundary_conditions_path=str(boundary_conditions),
        axial_segments=8,
        radial_layers=3,
        theta_segments=12,
    )

    mesh_text = mesh.read_text(encoding="ascii")
    bc_text = boundary_conditions.read_text(encoding="ascii")

    assert files == {"cfd_mesh": str(mesh), "boundary_conditions": str(boundary_conditions)}
    assert "$MeshFormat" in mesh_text
    assert "2.2 0 8" in mesh_text
    assert '2 1 "inlet"' in mesh_text
    assert '2 2 "outlet"' in mesh_text
    assert '2 3 "wall"' in mesh_text
    assert '2 4 "cooling_inlet"' in mesh_text
    assert '2 5 "cooling_outlet"' in mesh_text
    assert '3 6 "internal_flow"' in mesh_text
    assert " 3 2 4 4 " in mesh_text
    assert " 3 2 5 5 " in mesh_text
    assert " 6 2 6 6 " in mesh_text
    assert " 5 2 6 6 " in mesh_text
    assert "mesh_units: m" in bc_text
    assert "inlet_pressure_Pa: 5000000.000" in bc_text
    assert "outlet_pressure_Pa: 101325.000" in bc_text
    assert "wall_temperature_K: 725.000" in bc_text


def test_rocket_cli_parser_accepts_export_cfd_flag():
    parser = build_parser()
    args = parser.parse_args(
        [
            "design",
            "rocket-engine",
            "--thrust",
            "5000N",
            "--propellant",
            "kerolox",
            "--export-cfd",
        ]
    )

    assert args.export_cfd is True
