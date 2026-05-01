"""3D Gaussian Splatting sidecar.

Convert between Gaussian Splatting / NeRF-style point cloud formats:

  * `.splat` (Antimatter15 binary format)  <-> `.ply` (3DGS exchange)
  * `.spz` (compressed splat)              -> `.splat`
  * Standard `.ply` point cloud            <-> `.splat`

Each gaussian is 32 bytes in the .splat format:
  * position: 3 * float32 (12 bytes)
  * scales:   3 * float32 (12 bytes)
  * color:    4 * uint8 (RGBA, 4 bytes)
  * rotation: 4 * uint8 quaternion (4 bytes)

Operations:
  splat-to-ply    Antimatter15 .splat -> 3DGS .ply.
  ply-to-splat    3DGS .ply           -> .splat.
  splat-info      Probe .splat header / count -> JSON.

Pure stdlib (struct + array). Streams chunked I/O.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_SPLAT_RECORD = 32  # bytes per gaussian


def _splat_iter(data: bytes):
    if len(data) % _SPLAT_RECORD != 0:
        raise ValueError(
            f"Not a Gaussian Splat .splat file (size {len(data)} not "
            f"divisible by {_SPLAT_RECORD}).")
    count = len(data) // _SPLAT_RECORD
    for i in range(count):
        rec = data[i * _SPLAT_RECORD:(i + 1) * _SPLAT_RECORD]
        x, y, z = struct.unpack("<fff", rec[0:12])
        sx, sy, sz = struct.unpack("<fff", rec[12:24])
        r, g, b, a = rec[24], rec[25], rec[26], rec[27]
        rot = rec[28], rec[29], rec[30], rec[31]
        yield (x, y, z, sx, sy, sz, r, g, b, a, rot)


def op_splat_to_ply(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".splat file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = src.read_bytes()
            count = len(data) // _SPLAT_RECORD
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".ply")
        with out_path.open("wb") as f:
            header = (
                "ply\n"
                "format binary_little_endian 1.0\n"
                f"element vertex {count}\n"
                "property float x\n"
                "property float y\n"
                "property float z\n"
                "property float scale_0\n"
                "property float scale_1\n"
                "property float scale_2\n"
                "property uchar red\n"
                "property uchar green\n"
                "property uchar blue\n"
                "property uchar opacity\n"
                "property uchar rot_0\n"
                "property uchar rot_1\n"
                "property uchar rot_2\n"
                "property uchar rot_3\n"
                "end_header\n"
            ).encode("ascii")
            f.write(header)
            for x, y, z, sx, sy, sz, r, g, b, a, rot in _splat_iter(data):
                f.write(struct.pack("<ffffff", x, y, z, sx, sy, sz))
                f.write(bytes([r, g, b, a, rot[0], rot[1], rot[2], rot[3]]))
        emit("gsplat_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="ply", source="splat", count=count)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_ply_to_splat(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".ply file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            with src.open("rb") as f:
                # Parse PLY header
                header_lines: list[str] = []
                while True:
                    line = f.readline().decode("ascii", errors="replace")
                    if not line:
                        return fail("parse_failed",
                                    f"{src.name}: truncated PLY header.")
                    header_lines.append(line)
                    if line.strip() == "end_header": break
                # Find vertex count
                vertex_count = 0
                props: list[str] = []
                in_vertex = False
                for ln in header_lines:
                    s = ln.strip()
                    if s.startswith("element vertex"):
                        vertex_count = int(s.split()[-1]); in_vertex = True
                    elif s.startswith("element"):
                        in_vertex = False
                    elif in_vertex and s.startswith("property"):
                        props.append(s)
                # Parse + emit splat records
                out_path = out_dir / (src.stem + ".splat")
                with out_path.open("wb") as out:
                    bin_format = any("binary" in ln for ln in header_lines)
                    if bin_format:
                        # Compute per-vertex byte size from properties
                        type_size = {"float": 4, "double": 8, "uchar": 1,
                                       "char": 1, "ushort": 2, "short": 2,
                                       "uint": 4, "int": 4}
                        byte_layout: list[tuple[str, str]] = []
                        for pr in props:
                            tokens = pr.split()
                            byte_layout.append((tokens[1], tokens[2]))
                        # We expect: x, y, z, scale_0/1/2 (or sx/sy/sz),
                        #   red, green, blue, opacity, rot_0..3
                        for _ in range(vertex_count):
                            values: dict = {}
                            for typ, name in byte_layout:
                                size = type_size.get(typ, 0)
                                if not size: continue
                                raw = f.read(size)
                                if typ == "float":
                                    values[name] = struct.unpack("<f", raw)[0]
                                elif typ == "double":
                                    values[name] = struct.unpack("<d", raw)[0]
                                elif typ == "uchar":
                                    values[name] = raw[0]
                                elif typ == "char":
                                    values[name] = struct.unpack("<b", raw)[0]
                            x = float(values.get("x", 0.0))
                            y = float(values.get("y", 0.0))
                            z = float(values.get("z", 0.0))
                            sx = float(values.get("scale_0",
                                                   values.get("sx", 1.0)))
                            sy = float(values.get("scale_1",
                                                   values.get("sy", 1.0)))
                            sz = float(values.get("scale_2",
                                                   values.get("sz", 1.0)))
                            r = int(values.get("red", 255))
                            g = int(values.get("green", 255))
                            b = int(values.get("blue", 255))
                            a = int(values.get("opacity",
                                                 values.get("alpha", 255)))
                            rot = (int(values.get("rot_0", 128)),
                                   int(values.get("rot_1", 128)),
                                   int(values.get("rot_2", 128)),
                                   int(values.get("rot_3", 255)))
                            out.write(struct.pack("<ffffff", x, y, z, sx, sy, sz))
                            out.write(bytes([r & 0xFF, g & 0xFF, b & 0xFF,
                                              a & 0xFF, rot[0] & 0xFF,
                                              rot[1] & 0xFF, rot[2] & 0xFF,
                                              rot[3] & 0xFF]))
                    else:
                        # ASCII PLY
                        for _ in range(vertex_count):
                            ln = f.readline().decode("ascii",
                                                       errors="replace").split()
                            x, y, z = map(float, ln[0:3])
                            sx, sy, sz = (float(ln[3]) if len(ln) > 3 else 1.0,
                                            float(ln[4]) if len(ln) > 4 else 1.0,
                                            float(ln[5]) if len(ln) > 5 else 1.0)
                            r = int(float(ln[6])) if len(ln) > 6 else 255
                            g = int(float(ln[7])) if len(ln) > 7 else 255
                            b = int(float(ln[8])) if len(ln) > 8 else 255
                            a = int(float(ln[9])) if len(ln) > 9 else 255
                            out.write(struct.pack("<ffffff", x, y, z, sx, sy, sz))
                            out.write(bytes([r & 0xFF, g & 0xFF, b & 0xFF,
                                              a & 0xFF, 128, 128, 128, 255]))
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("gsplat_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="splat", source="ply", count=vertex_count)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_splat_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".splat file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        size = src.stat().st_size
        count = size // _SPLAT_RECORD
        probes.append({
            "file": str(src), "size_bytes": size, "gaussians": count,
            "well_formed": size % _SPLAT_RECORD == 0,
        })
        emit("gsplat_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="splat", count=count)
    out_path = out_dir / "splat-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gsplat-sidecar",
                                description="3D Gaussian Splatting format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("splat-to-ply", "Antimatter15 .splat -> 3DGS .ply"),
        ("ply-to-splat", "3DGS .ply -> Antimatter15 .splat"),
        ("splat-info",   "Probe .splat header / count"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "splat-to-ply": return op_splat_to_ply(args)
        if args.op == "ply-to-splat": return op_ply_to_splat(args)
        if args.op == "splat-info":   return op_splat_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
