"""3D LUT generator sidecar.

Generates Adobe-style .cube / .3dl 3D LUTs by sampling a "before / after"
image pair (or a sequence of pairs). Useful for matching looks between
cameras, replicating a film LUT from a reference grade, or capturing a
custom Lightroom/Photoshop look as a portable CUBE LUT.

Algorithm:
  * Read source + target image pair (must be same dimensions).
  * Build a sparse LUT in N^3 grid space by binning source RGB values
    and averaging the target RGB values that map to each bin.
  * Fill empty bins by nearest-neighbor copy from the closest filled bin
    along each axis (simple but stable for typical color-grading deltas).
  * Write Resolve/Premiere/OBS-compatible 33x33x33 (default) .cube file.

Also supports `identity` op which writes a no-op LUT for testing.
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


def _imports():
    try:
        import numpy as np  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_imaging",
             message=f"numpy/Pillow missing: {ex}")
        return False


def _write_cube(path: Path, lut, size: int, title: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f'TITLE "{title}"\n')
        f.write(f"LUT_3D_SIZE {size}\n")
        f.write("DOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n")
        # CUBE iteration order: r is fastest, then g, then b.
        for b in range(size):
            for g in range(size):
                for r in range(size):
                    rr, gg, bb = lut[r, g, b]
                    f.write(f"{rr:.6f} {gg:.6f} {bb:.6f}\n")


def _write_3dl(path: Path, lut, size: int) -> None:
    # Autodesk .3dl: integer 10-bit values, iteration r-fastest, blank lines between r layers.
    scale = 1023
    with path.open("w", encoding="utf-8", newline="\n") as f:
        # Mesh header lists input shaper points (0..1023 in `size` steps).
        steps = " ".join(str(int(round(i * scale / (size - 1)))) for i in range(size))
        f.write(steps + "\n")
        for b in range(size):
            for g in range(size):
                for r in range(size):
                    rr, gg, bb = lut[r, g, b]
                    f.write(f"{int(round(rr * scale))} "
                            f"{int(round(gg * scale))} "
                            f"{int(round(bb * scale))}\n")


def _build_identity(size: int):
    import numpy as np
    axis = np.linspace(0.0, 1.0, size, dtype=np.float32)
    lut = np.zeros((size, size, size, 3), dtype=np.float32)
    for r in range(size):
        for g in range(size):
            for b in range(size):
                lut[r, g, b] = (axis[r], axis[g], axis[b])
    return lut


def _build_from_pair(src_paths: list[Path], dst_paths: list[Path], size: int):
    import numpy as np
    from PIL import Image

    sums = np.zeros((size, size, size, 3), dtype=np.float64)
    counts = np.zeros((size, size, size), dtype=np.int64)

    for sp, dp in zip(src_paths, dst_paths):
        s_img = np.asarray(Image.open(sp).convert("RGB"), dtype=np.float32) / 255.0
        d_img = np.asarray(Image.open(dp).convert("RGB"), dtype=np.float32) / 255.0
        if s_img.shape != d_img.shape:
            raise ValueError(f"shape mismatch: {sp.name} vs {dp.name}")
        s_flat = s_img.reshape(-1, 3)
        d_flat = d_img.reshape(-1, 3)
        idx = np.clip((s_flat * (size - 1)).round().astype(np.int32), 0, size - 1)
        # Accumulate per-bin sums.
        for k in range(s_flat.shape[0]):
            r, g, b = idx[k]
            sums[r, g, b] += d_flat[k]
            counts[r, g, b] += 1

    lut = np.zeros((size, size, size, 3), dtype=np.float32)
    filled = counts > 0
    lut[filled] = (sums[filled] / counts[filled, None]).astype(np.float32)

    if not filled.all():
        # Iterative fill: for empty bins, take mean of filled 6-neighbours; repeat
        # until no empties remain or we hit a sane iteration cap.
        for _ in range(64):
            empties = np.where(~filled)
            if empties[0].size == 0: break
            new_filled = filled.copy()
            new_lut = lut.copy()
            for r, g, b in zip(*empties):
                neigh = []
                for dr, dg, db in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                                   (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                    nr, ng, nb = r + dr, g + dg, b + db
                    if 0 <= nr < size and 0 <= ng < size and 0 <= nb < size:
                        if filled[nr, ng, nb]:
                            neigh.append(lut[nr, ng, nb])
                if neigh:
                    new_lut[r, g, b] = np.mean(neigh, axis=0)
                    new_filled[r, g, b] = True
            filled = new_filled
            lut = new_lut

    return lut


def op_generate(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    src_paths = [Path(p) for p in args.source]
    dst_paths = [Path(p) for p in args.target]
    if len(src_paths) != len(dst_paths) or not src_paths:
        return fail("bad_pairs", "Provide equal-length --source and --target lists.")
    miss = [str(p) for p in src_paths + dst_paths if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    size = int(args.size)
    if size < 2 or size > 65:
        return fail("bad_size", f"--size must be 2..65 (got {size})")

    started = time.monotonic()
    emit("progress", percent=10, stage="sample", eta_seconds=None)

    try:
        lut = _build_from_pair(src_paths, dst_paths, size)
    except Exception as ex:
        return fail("build_failed", str(ex))

    emit("progress", percent=80, stage="write", eta_seconds=None)
    title = args.title or f"UCX_LUT_{size}"
    out_path = out_dir / (title + ("." + args.format))
    if args.format == "cube":
        _write_cube(out_path, lut, size, title)
    elif args.format == "3dl":
        _write_3dl(out_path, lut, size)
    else:
        return fail("bad_format", f"Unknown format '{args.format}' (cube|3dl).")

    emit("lut_cube", input=str(src_paths[0]),
         output=str(out_path), size=size, format=args.format,
         size_bytes=out_path.stat().st_size)
    emit("progress", percent=100, stage="done",
         eta_seconds=int(time.monotonic() - started))
    emit("complete", output=str(out_dir), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_identity(args: argparse.Namespace) -> int:
    if not _imports(): return 1
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    size = int(args.size)
    title = args.title or f"identity_{size}"
    out_path = out_dir / (title + ("." + args.format))
    lut = _build_identity(size)
    if args.format == "cube": _write_cube(out_path, lut, size, title)
    elif args.format == "3dl": _write_3dl(out_path, lut, size)
    else: return fail("bad_format", f"Unknown format '{args.format}' (cube|3dl).")
    emit("lut_cube", input="(identity)", output=str(out_path),
         size=size, format=args.format, size_bytes=out_path.stat().st_size)
    emit("complete", output=str(out_dir), size_bytes=out_path.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lutgen-sidecar",
                                description="3D LUT generator (.cube / .3dl).")
    sub = p.add_subparsers(dest="op", required=True)
    g = sub.add_parser("generate", help="Build a 3D LUT from before/after image pairs.")
    g.add_argument("--source", nargs="+", required=True,
                   help="One or more 'before' images.")
    g.add_argument("--target", nargs="+", required=True,
                   help="Matching 'after' images, same dimensions as sources.")
    g.add_argument("--output-dir", required=True, dest="output_dir")
    g.add_argument("--size", type=int, default=33,
                   help="LUT cube edge size (typical 17/33/65).")
    g.add_argument("--format", default="cube", choices=["cube", "3dl"])
    g.add_argument("--title", default=None,
                   help="LUT title (also used as output filename).")
    i = sub.add_parser("identity", help="Write an identity (no-op) LUT.")
    i.add_argument("--output-dir", required=True, dest="output_dir")
    i.add_argument("--size", type=int, default=33)
    i.add_argument("--format", default="cube", choices=["cube", "3dl"])
    i.add_argument("--title", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "generate": return op_generate(args)
        if args.op == "identity": return op_identity(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
