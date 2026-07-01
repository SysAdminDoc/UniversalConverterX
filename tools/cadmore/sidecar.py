"""Modern 3D-printing / additive-manufacturing CAD sidecar.

The `cadkit` (DXF/DWG) and `engcad` (STEP/IGES BREP) sidecars cover legacy
2D and engineering CAD; this one is for 3D-printing pipelines:

  * 3MF (3D Manufacturing Format)         .3mf
  * AMF (Additive Manufacturing Format)   .amf
  * G-code (3D printer)                   .gcode, .nc, .gco
  * STL <-> 3MF round-trip
  * OBJ / PLY -> 3MF / AMF

Backed by `lib3mf` Python bindings + `numpy-stl` for STL <-> 3MF, and a
custom AMF emitter (XML-based).
"""
from __future__ import annotations

import argparse
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import re
import sys
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def emit(event: str, **fields_) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields_}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── STL <-> 3MF / AMF (mesh-only path) ─────────────────────────────────

def _load_mesh_with_trimesh(path: Path):
    import trimesh
    return trimesh.load(str(path), force="mesh")


def _write_3mf(mesh, path: Path) -> None:
    """Emit a minimal 3MF file (zip + 3D/3dmodel.model)."""
    import numpy as np
    vertices = mesh.vertices
    faces = mesh.faces
    model = ET.Element("model", unit="millimeter",
                       xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02")
    resources = ET.SubElement(model, "resources")
    obj_el = ET.SubElement(resources, "object", id="1", type="model")
    mesh_el = ET.SubElement(obj_el, "mesh")
    verts_el = ET.SubElement(mesh_el, "vertices")
    for v in vertices:
        ET.SubElement(verts_el, "vertex",
                      x=f"{v[0]:.6f}", y=f"{v[1]:.6f}", z=f"{v[2]:.6f}")
    tris_el = ET.SubElement(mesh_el, "triangles")
    for tri in faces:
        ET.SubElement(tris_el, "triangle",
                      v1=str(int(tri[0])), v2=str(int(tri[1])), v3=str(int(tri[2])))
    build = ET.SubElement(model, "build")
    ET.SubElement(build, "item", objectid="1")

    body = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        ct = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
            "</Types>"
        )
        rels = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rel0" Target="/3D/3dmodel.model" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            "</Relationships>"
        )
        zf.writestr("[Content_Types].xml", ct)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", body)


def _write_amf(mesh, path: Path) -> None:
    """Emit AMF (XML)."""
    root = ET.Element("amf", unit="millimeter")
    metadata = ET.SubElement(root, "metadata", type="cad")
    metadata.text = "UCX"
    obj_el = ET.SubElement(root, "object", id="0")
    mesh_el = ET.SubElement(obj_el, "mesh")
    verts_el = ET.SubElement(mesh_el, "vertices")
    for v in mesh.vertices:
        vertex = ET.SubElement(verts_el, "vertex")
        coords = ET.SubElement(vertex, "coordinates")
        ET.SubElement(coords, "x").text = f"{v[0]:.6f}"
        ET.SubElement(coords, "y").text = f"{v[1]:.6f}"
        ET.SubElement(coords, "z").text = f"{v[2]:.6f}"
    volume = ET.SubElement(mesh_el, "volume")
    for tri in mesh.faces:
        triangle = ET.SubElement(volume, "triangle")
        ET.SubElement(triangle, "v1").text = str(int(tri[0]))
        ET.SubElement(triangle, "v2").text = str(int(tri[1]))
        ET.SubElement(triangle, "v3").text = str(int(tri[2]))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def op_mesh_convert(args: argparse.Namespace) -> int:
    try:
        import trimesh
    except ImportError as ex:
        return fail("missing_trimesh",
                    f"trimesh not installed: {ex}. `pip install trimesh`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Mesh file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            mesh = _load_mesh_with_trimesh(src)
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")

        out_path = out_dir / (src.stem + "." + target)
        try:
            if target == "3mf":
                _write_3mf(mesh, out_path)
            elif target == "amf":
                _write_amf(mesh, out_path)
            elif target in ("stl", "obj", "ply", "glb", "gltf", "dae", "off"):
                mesh.export(str(out_path))
            else:
                return fail("bad_target",
                            "Choose 3mf | amf | stl | obj | ply | glb | gltf | dae | off.")
        except Exception as ex:
            return fail("write_failed", f"{src.name}: {ex}")

        emit("cad_more",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, faces=int(mesh.faces.shape[0]),
             vertices=int(mesh.vertices.shape[0]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── G-code analysis ────────────────────────────────────────────────────

_GCODE_LINE = re.compile(r"^([GMT]\d+)(.*)$", re.IGNORECASE)


def op_gcode_info(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"G-code not found: {src}")
    text = src.read_text(encoding="utf-8", errors="replace")
    line_count = layer_count = 0
    extrusion = 0.0
    travel = 0.0
    last_x = last_y = last_z = 0.0
    last_e = 0.0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            line_count += 1
            if "LAYER:" in line.upper() or ";LAYER" in line.upper():
                layer_count += 1
            continue
        line_count += 1
        if line.upper().startswith(("G0 ", "G1 ", "G2 ", "G3 ")):
            x = _gcode_axis(line, "X", last_x)
            y = _gcode_axis(line, "Y", last_y)
            z = _gcode_axis(line, "Z", last_z)
            e = _gcode_axis(line, "E", last_e)
            dist = ((x - last_x) ** 2 + (y - last_y) ** 2 + (z - last_z) ** 2) ** 0.5
            if e > last_e: extrusion += (e - last_e)
            else: travel += dist
            last_x, last_y, last_z, last_e = x, y, z, e

    emit("cad_more_info",
         path=str(src), size_bytes=src.stat().st_size,
         line_count=line_count,
         layer_count=layer_count,
         extrusion_mm=round(extrusion, 2),
         travel_mm=round(travel, 2),
         max_z=round(last_z, 2))
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def _gcode_axis(line: str, axis: str, default: float) -> float:
    m = re.search(rf"{axis}(-?\d+(?:\.\d+)?)", line, re.IGNORECASE)
    return float(m.group(1)) if m else default


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cadmore-sidecar",
                                description="Modern 3D-printing CAD: 3MF / AMF / G-code.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Mesh format conversion (STL/OBJ/PLY -> 3MF/AMF + reverse).")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="3mf | amf | stl | obj | ply | glb | gltf | dae | off")
    g = sub.add_parser("gcode-info", help="Probe G-code: line count, layer count, extrusion / travel mm.")
    g.add_argument("--input", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":    return op_mesh_convert(args)
        if args.op == "gcode-info": return op_gcode_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
