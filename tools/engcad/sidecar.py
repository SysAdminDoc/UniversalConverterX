"""Engineering CAD format sidecar.

The `cadkit` sidecar handles 2D CAD (DXF / DWG); this one covers the BREP
solid modeling formats used in mechanical engineering / CAM:

  * STEP (.step, .stp)        ISO 10303 (most common)
  * IGES (.iges, .igs)        IGES 5.3 legacy interchange
  * BREP (.brep, .brp)        Open CASCADE native
  * STL  (.stl)               binary or ASCII triangle mesh
  * VRML (.wrl)               legacy 3D scene
  * OBJ  (.obj)               Wavefront mesh
  * X3D  (.x3d, .x3dv)        Web3D successor to VRML

Backed by `pythonocc-core` (LGPL) which wraps Open CASCADE Technology.
The library is heavy (~250 MB) but is the only OSS BREP option that round-
trips STEP/IGES with confidence. Falls back to mesh-only conversion via
`trimesh` if pythonocc isn't installed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _via_pythonocc(src: Path, out_path: Path) -> int:
    try:
        from OCC.Core.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
        from OCC.Core.IGESControl import IGESControl_Reader, IGESControl_Writer
        from OCC.Core.BRepTools import breptools_Read, breptools_Write
        from OCC.Core.StlAPI import StlAPI_Reader, StlAPI_Writer
        from OCC.Core.IFSelect import IFSelect_RetDone
        from OCC.Core.TopoDS import TopoDS_Shape
        from OCC.Core.BRep import BRep_Builder
    except ImportError as ex:
        return fail("missing_pythonocc",
                    f"pythonocc-core not installed: {ex}. "
                    "`pip install pythonocc-core` (or use conda).")

    src_ext = src.suffix.lower()
    out_ext = out_path.suffix.lower()
    shape = TopoDS_Shape()

    # ---- read ----
    if src_ext in (".step", ".stp"):
        reader = STEPControl_Reader()
        if reader.ReadFile(str(src)) != IFSelect_RetDone:
            return fail("read_failed", f"{src.name}: STEP read failed.")
        reader.TransferRoots()
        shape = reader.OneShape()
    elif src_ext in (".iges", ".igs"):
        reader = IGESControl_Reader()
        if reader.ReadFile(str(src)) != IFSelect_RetDone:
            return fail("read_failed", f"{src.name}: IGES read failed.")
        reader.TransferRoots()
        shape = reader.OneShape()
    elif src_ext in (".brep", ".brp"):
        builder = BRep_Builder()
        if not breptools_Read(shape, str(src), builder):
            return fail("read_failed", f"{src.name}: BREP read failed.")
    elif src_ext == ".stl":
        reader = StlAPI_Reader()
        reader.Read(shape, str(src))
    else:
        return fail("bad_format", f"pythonocc cannot read {src_ext}.")

    # ---- write ----
    if out_ext in (".step", ".stp"):
        w = STEPControl_Writer()
        w.Transfer(shape, STEPControl_AsIs)
        w.Write(str(out_path))
    elif out_ext in (".iges", ".igs"):
        w = IGESControl_Writer()
        w.AddShape(shape)
        w.Write(str(out_path))
    elif out_ext in (".brep", ".brp"):
        breptools_Write(shape, str(out_path))
    elif out_ext == ".stl":
        # Need a mesh -- triangulate first.
        from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
        BRepMesh_IncrementalMesh(shape, 0.5).Perform()
        w = StlAPI_Writer()
        w.SetASCIIMode(False)
        w.Write(shape, str(out_path))
    else:
        return fail("bad_target", f"pythonocc cannot write {out_ext}.")
    return 0


def _via_trimesh(src: Path, out_path: Path) -> int:
    try:
        import trimesh
    except ImportError as ex:
        return fail("missing_trimesh",
                    f"trimesh not installed: {ex}. `pip install trimesh`.")
    try:
        mesh = trimesh.load(str(src), force="mesh")
        mesh.export(str(out_path))
    except Exception as ex:
        return fail("convert_failed", f"{src.name}: {ex}")
    return 0


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CAD file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()
    backend = args.backend.lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="engcad", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + target_ext)
        if backend == "pythonocc":
            rc = _via_pythonocc(src, out_path)
        else:
            rc = _via_trimesh(src, out_path)
        if rc != 0: return rc

        emit("eng_cad",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target_ext.lstrip("."), backend=backend)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="engcad-sidecar",
                                description="Engineering CAD (STEP / IGES / BREP / STL) conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert STEP / IGES / BREP / STL / OBJ.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="step | stp | iges | igs | brep | stl | obj")
    c.add_argument("--backend", default="pythonocc",
                   choices=["pythonocc", "trimesh"],
                   help="pythonocc handles BREP solids; trimesh handles meshes only.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
