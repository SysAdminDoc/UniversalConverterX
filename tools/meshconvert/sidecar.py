"""3D model converter sidecar -- wraps `trimesh` (which uses pyassimp / pyglet
under the hood) for every common 3D format.

Read formats: STL / OBJ / PLY / GLB / GLTF / FBX / DAE / 3DS / OFF / XYZ /
              X3D / DXF / WRL / STEP (via OCC if available)

Write formats: STL (binary or ASCII) / OBJ / PLY / GLB / GLTF / DAE / OFF /
               STEP

Frozen-guard: deps bundled at PyInstaller build time, no runtime pip.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


KNOWN_OUTPUT_FORMATS = {
    "stl", "obj", "ply", "glb", "gltf", "dae", "off", "step", "x3d",
}


def op_convert(args: argparse.Namespace) -> int:
    try:
        import trimesh  # noqa: F401
    except ImportError:
        return fail("missing_trimesh", "trimesh is not installed in this build.")
    import trimesh

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"3D file(s) not found: {missing}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    if target not in KNOWN_OUTPUT_FORMATS:
        emit("log", level="warn",
             message=f"Format '{target}' not in the curated list; trimesh may "
                     "still accept it.")

    total = len(inputs)
    emit("log", level="info",
         message=f"Convert {total} mesh(es) -> .{target}")
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    started = time.monotonic()
    for i, src in enumerate(inputs):
        try:
            mesh = trimesh.load(str(src), force="scene" if target in ("glb", "gltf", "dae") else "mesh")
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("load_failed", f"Could not load {src.name}: {ex}")

        out_path = out_dir / (src.stem + "." + target)
        try:
            # Scene vs Mesh export -- trimesh handles both transparently.
            if hasattr(mesh, "export"):
                mesh.export(str(out_path))
            else:
                trimesh.exchange.export.export_mesh(mesh, str(out_path), file_type=target)
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("export_failed", f"Could not write {out_path.name}: {ex}")

        # Compute basic stats so the UI can show them.
        try:
            face_count = len(getattr(mesh, "faces", [])) if hasattr(mesh, "faces") else 0
            vertex_count = len(getattr(mesh, "vertices", [])) if hasattr(mesh, "vertices") else 0
        except Exception:
            face_count = vertex_count = 0

        emit("mesh",
             input=str(src),
             output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             faces=face_count,
             vertices=vertex_count)

        pct = (i + 1) / total * 100.0
        elapsed = time.monotonic() - started
        local = pct / 100.0
        eta = (elapsed / local - elapsed) if local > 0.01 else None
        emit("progress",
             percent=round(pct, 1),
             stage=f"converted {i + 1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    total_size = sum((out_dir / (Path(p).stem + "." + target)).stat().st_size
                     for p in args.input
                     if (out_dir / (Path(p).stem + "." + target)).is_file())
    emit("complete", output=str(out_dir), size_bytes=total_size, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    try:
        import trimesh  # noqa: F401
    except ImportError:
        return fail("missing_trimesh", "trimesh is not installed in this build.")
    import trimesh

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"3D file not found: {args.input}")
    try:
        mesh = trimesh.load(str(src), force="mesh")
    except Exception as ex:
        return fail("load_failed", f"Could not parse {src.name}: {ex}")

    bounds = getattr(mesh, "bounds", None)
    extents = getattr(mesh, "extents", None)
    emit("mesh_info",
         path=str(src),
         faces=len(getattr(mesh, "faces", [])) if hasattr(mesh, "faces") else 0,
         vertices=len(getattr(mesh, "vertices", [])) if hasattr(mesh, "vertices") else 0,
         is_watertight=bool(getattr(mesh, "is_watertight", False)),
         volume=float(getattr(mesh, "volume", 0)) if hasattr(mesh, "volume") else 0.0,
         area=float(getattr(mesh, "area", 0)) if hasattr(mesh, "area") else 0.0,
         extents=list(extents) if extents is not None else None,
         bounds_min=list(bounds[0]) if bounds is not None else None,
         bounds_max=list(bounds[1]) if bounds is not None else None)
    emit("complete", output=str(src), size_bytes=src.stat().st_size)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meshconvert-sidecar",
                                description="3D model conversion via trimesh.")
    sub = p.add_subparsers(dest="op", required=True)

    cv = sub.add_parser("convert", help="Convert 3D model files to another format")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True,
                    help="Target: " + " | ".join(sorted(KNOWN_OUTPUT_FORMATS)))

    info = sub.add_parser("info", help="Probe a mesh for face/vertex/volume stats")
    info.add_argument("--input", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "info":    return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
