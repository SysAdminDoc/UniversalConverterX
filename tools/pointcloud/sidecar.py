"""Point cloud / 3D scan sidecar.

Mutually convert the formats LiDAR / photogrammetry pipelines produce:

  .ply / .pcd / .xyz / .pts / .obj  (open3d / generic)
  .las / .laz                       (laspy + lazrs)
  .e57                              (pye57 — optional)

Operations:
  convert   <list of inputs> -> <target ext>
  info      print point count + extent + dtype
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


OPEN3D_EXTS = {".ply", ".pcd", ".xyz", ".xyzn", ".xyzrgb", ".pts", ".obj"}
LAS_EXTS = {".las", ".laz"}
E57_EXTS = {".e57"}


def _read_points(path: Path):
    """Return numpy ndarray (N,3) plus optional ndarray (N,3) of colors."""
    import numpy as np
    ext = path.suffix.lower()
    if ext in OPEN3D_EXTS:
        import open3d as o3d
        pcd = o3d.io.read_point_cloud(str(path))
        pts = np.asarray(pcd.points)
        cols = np.asarray(pcd.colors) if pcd.has_colors() else None
        return pts, cols
    if ext in LAS_EXTS:
        import laspy
        f = laspy.read(str(path))
        pts = np.vstack([f.x, f.y, f.z]).T
        try:
            cols = np.vstack([f.red / 65535, f.green / 65535, f.blue / 65535]).T
        except Exception:
            cols = None
        return pts, cols
    if ext in E57_EXTS:
        import pye57, numpy as np
        e = pye57.E57(str(path))
        d = e.read_scan(0, intensity=False, colors=True, ignore_missing_fields=True)
        pts = np.vstack([d["cartesianX"], d["cartesianY"], d["cartesianZ"]]).T
        cols = None
        if all(k in d for k in ("colorRed", "colorGreen", "colorBlue")):
            cols = np.vstack([d["colorRed"] / 255, d["colorGreen"] / 255,
                              d["colorBlue"] / 255]).T
        return pts, cols
    raise ValueError(f"Unsupported input ext: {ext}")


def _write_points(pts, cols, path: Path) -> None:
    import numpy as np
    ext = path.suffix.lower()
    if ext in OPEN3D_EXTS:
        import open3d as o3d
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        if cols is not None:
            pcd.colors = o3d.utility.Vector3dVector(cols)
        if not o3d.io.write_point_cloud(str(path), pcd):
            raise RuntimeError(f"open3d failed to write {path}")
        return
    if ext in LAS_EXTS:
        import laspy
        header = laspy.LasHeader(point_format=3, version="1.4")
        header.offsets = pts.min(axis=0)
        header.scales = (0.001, 0.001, 0.001)
        las = laspy.LasData(header)
        las.x = pts[:, 0]; las.y = pts[:, 1]; las.z = pts[:, 2]
        if cols is not None:
            las.red = (cols[:, 0] * 65535).astype(np.uint16)
            las.green = (cols[:, 1] * 65535).astype(np.uint16)
            las.blue = (cols[:, 2] * 65535).astype(np.uint16)
        las.write(str(path))
        return
    if ext in E57_EXTS:
        import pye57
        scan = {"cartesianX": pts[:, 0],
                "cartesianY": pts[:, 1],
                "cartesianZ": pts[:, 2]}
        if cols is not None:
            scan["colorRed"]   = (cols[:, 0] * 255).astype("u1")
            scan["colorGreen"] = (cols[:, 1] * 255).astype("u1")
            scan["colorBlue"]  = (cols[:, 2] * 255).astype("u1")
        e = pye57.E57(str(path), mode="w")
        e.write_scan_raw(scan)
        return
    raise ValueError(f"Unsupported output ext: {ext}")


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Cloud file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = "." + args.format.lower().lstrip(".")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + target)
        try:
            pts, cols = _read_points(src)
            _write_points(pts, cols, out_path)
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("point_cloud",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target.lstrip("."),
             point_count=int(pts.shape[0]))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_info(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"File not found: {src}")
    try:
        pts, cols = _read_points(src)
    except Exception as ex:
        return fail("read_failed", f"{src.name}: {ex}")
    mins = pts.min(axis=0).tolist()
    maxs = pts.max(axis=0).tolist()
    emit("point_cloud_info",
         path=str(src), point_count=int(pts.shape[0]),
         bounds_min=mins, bounds_max=maxs,
         has_colors=cols is not None)
    emit("complete", output=str(src), size_bytes=src.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pointcloud-sidecar",
                                description="Point cloud / 3D scan conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert PLY/PCD/XYZ/PTS/OBJ/LAS/LAZ/E57.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True, help="ply|pcd|xyz|pts|obj|las|laz|e57")
    info = sub.add_parser("info", help="Probe a point cloud file.")
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
