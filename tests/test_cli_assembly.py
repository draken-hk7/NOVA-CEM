import json
from pathlib import Path

from nova.cli.main import _read_stl_triangles, main


def _write_triangle_stl(path: Path, solid_name: str, vertices: tuple[tuple[float, float, float], ...]) -> None:
    path.write_text(
        "\n".join(
            [
                f"solid {solid_name}",
                "  facet normal 0 0 1",
                "    outer loop",
                f"      vertex {vertices[0][0]} {vertices[0][1]} {vertices[0][2]}",
                f"      vertex {vertices[1][0]} {vertices[1][1]} {vertices[1][2]}",
                f"      vertex {vertices[2][0]} {vertices[2][1]} {vertices[2][2]}",
                "    endloop",
                "  endfacet",
                f"endsolid {solid_name}",
                "",
            ]
        ),
        encoding="ascii",
    )


def test_cli_assemble_exports_offset_multi_body_stl_and_pdf_report():
    base = Path("outputs/test-artifacts/assembly-cli")
    engine_dir = base / "engine-job"
    hx_dir = base / "hx-job"
    engine_dir.mkdir(parents=True, exist_ok=True)
    hx_dir.mkdir(parents=True, exist_ok=True)

    _write_triangle_stl(
        engine_dir / "engine.stl",
        "engine",
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 10.0, 0.0)),
    )
    _write_triangle_stl(
        hx_dir / "heat_exchanger.stl",
        "hx",
        ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (0.0, 5.0, 0.0)),
    )
    (engine_dir / "report.pdf").write_bytes(b"%PDF-1.4\nengine report\n")
    (hx_dir / "report.pdf").write_bytes(b"%PDF-1.4\nhx report\n")
    (engine_dir / "data.json").write_text(
        json.dumps({"design": {"performance": {"thrust_N": 5000.0, "specific_impulse_s": 302.0}}}),
        encoding="utf-8",
    )
    (hx_dir / "data.json").write_text(
        json.dumps({"design": {"performance": {"effectiveness": 0.78, "required_area_m2": 0.12}}}),
        encoding="utf-8",
    )

    output = base / "assembly.stl"
    assert main(["assemble", "--engine", str(engine_dir), "--hx", str(hx_dir), "--output", str(output)]) == 0

    report = output.with_suffix(".pdf")
    assembly_text = output.read_text(encoding="ascii")
    triangles = _read_stl_triangles(output)
    x_values = [vertex[0] for triangle in triangles for vertex in triangle.vertices]

    assert output.exists()
    assert "solid nova_engine" in assembly_text
    assert "solid nova_heat_exchanger" in assembly_text
    assert len(triangles) == 2
    assert max(x_values) == 155.0
    assert report.exists() and report.stat().st_size > 0
    assert b"NOVA Assembly Report" in report.read_bytes()
    assert b"Heat exchanger offset: +150.0 mm X" in report.read_bytes()
