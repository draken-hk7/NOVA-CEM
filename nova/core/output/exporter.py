"""Geometry and performance artifact exporters."""

from __future__ import annotations

import textwrap
import zipfile
from pathlib import Path
from typing import Any

from nova.core.geometry_engine.primitives import MeshSolid
from nova.core.types import CEMRunResult, to_jsonable


class GeometryExporter:
    def to_stl(
        self,
        solid: MeshSolid,
        path: str,
        binary: bool = True,
        *,
        tolerance: float | None = None,
        angular_tolerance: float | None = None,
    ) -> None:
        del binary
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs = {}
        if tolerance is not None:
            kwargs["tolerance"] = tolerance
        if angular_tolerance is not None:
            kwargs["angular_tolerance"] = angular_tolerance
        solid.export_stl(path, **kwargs)

    def to_step(self, solid: MeshSolid, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        solid.export_step(path)

    def to_obj(self, solid: MeshSolid, path: str, *, tolerance: float | None = None) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs = {}
        if tolerance is not None:
            kwargs["tolerance"] = tolerance
        solid.export_obj(path, **kwargs)

    def to_3mf(self, solid: MeshSolid, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        vertices = "\n".join(f'<vertex x="{x:.9g}" y="{y:.9g}" z="{z:.9g}"/>' for x, y, z in solid.vertices)
        triangles = "\n".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in solid.faces)
        model = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model">
      <mesh><vertices>{vertices}</vertices><triangles>{triangles}</triangles></mesh>
    </object>
  </resources>
  <build><item objectid="1"/></build>
</model>
"""
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
            archive.writestr("3D/3dmodel.model", model)


class PerformanceReporter:
    def generate_pdf_report(self, run_result: CEMRunResult, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        payload = self.generate_json_data(run_result)
        lines = [
            "NOVA Computational Engineering Model Report",
            f"Job ID: {run_result.job_id}",
            f"Module: {run_result.module}",
            "",
            "Performance Summary:",
        ]
        performance = payload.get("design", {}).get("performance", {})
        for key, value in performance.items():
            lines.append(f"  {key}: {value}")
        lines.extend(["", "Manufacturing Summary:"])
        manufacturing = payload.get("design", {}).get("manufacturing", {})
        for key, value in manufacturing.items():
            if key != "warnings":
                lines.append(f"  {key}: {value}")
        self._write_minimal_pdf(path, "\n".join(lines))

    def generate_json_data(self, run_result: CEMRunResult) -> dict:
        return to_jsonable(run_result)

    def generate_cfd_mesh(self, solid: MeshSolid, path: str) -> None:
        GeometryExporter().to_obj(solid, path)

    def _write_minimal_pdf(self, path: str, text: str) -> None:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        wrapped = []
        for line in escaped.splitlines():
            wrapped.extend(textwrap.wrap(line, width=92) or [""])
        content_lines = ["BT", "/F1 10 Tf", "50 780 Td"]
        for i, line in enumerate(wrapped[:68]):
            if i:
                content_lines.append("0 -12 Td")
            content_lines.append(f"({line}) Tj")
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("latin-1", errors="replace")
        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
            b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
            f"5 0 obj << /Length {len(stream)} >> stream\n".encode("ascii") + stream + b"\nendstream endobj\n",
        ]
        offsets = []
        output = bytearray(b"%PDF-1.4\n")
        for obj in objects:
            offsets.append(len(output))
            output.extend(obj)
        xref = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
        Path(path).write_bytes(output)
