"""HDR / scientific-imaging sidecar.

Convert between high-dynamic-range and floating-point image formats:

  * Radiance HDR (.hdr / .pic / .rgbe)
  * OpenEXR  (.exr)  -- both half-float and 32-bit float
  * Portable Float Map (.pfm)
  * 16-bit PNG / 16-bit TIFF
  * Tone-mapped 8-bit PNG / JPEG (Reinhard / Drago / Mantiuk via OpenCV)

Operations:
  convert       Decode any of the above and re-encode as another HDR format.
  tonemap       HDR -> 8-bit LDR via a chosen tone-map operator.
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
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _imread(path: Path):
    """Read an HDR image as a float32 numpy array (H, W, C) in linear light."""
    import numpy as np
    ext = path.suffix.lower()
    if ext == ".hdr" or ext == ".pic" or ext == ".rgbe":
        try:
            import imageio.v3 as iio
            arr = iio.imread(str(path))
            return arr.astype("float32")
        except Exception:
            import cv2
            arr = cv2.imread(str(path), cv2.IMREAD_ANYDEPTH | cv2.IMREAD_COLOR)
            return arr[..., ::-1].astype("float32")  # BGR -> RGB
    if ext == ".exr":
        import OpenEXR, Imath
        f = OpenEXR.InputFile(str(path))
        dw = f.header()["dataWindow"]
        w = dw.max.x - dw.min.x + 1
        h = dw.max.y - dw.min.y + 1
        pt = Imath.PixelType(Imath.PixelType.FLOAT)
        chans = [c for c in ("R", "G", "B") if c in f.header()["channels"]]
        if not chans: chans = list(f.header()["channels"].keys())[:3]
        bands = [np.frombuffer(f.channel(c, pt), dtype="float32").reshape(h, w)
                 for c in chans]
        f.close()
        return np.stack(bands, axis=-1)
    if ext == ".pfm":
        return _read_pfm(path)
    if ext in (".png", ".tif", ".tiff"):
        import imageio.v3 as iio
        arr = iio.imread(str(path))
        if arr.dtype == np.uint16:
            return (arr.astype("float32") / 65535.0)
        if arr.dtype == np.uint8:
            return (arr.astype("float32") / 255.0)
        return arr.astype("float32")
    raise ValueError(f"Unsupported HDR extension: {ext}")


def _read_pfm(path: Path):
    import numpy as np
    with path.open("rb") as f:
        header = f.readline().decode("ascii").strip()
        if header not in ("PF", "Pf"):
            raise ValueError(f"Not a PFM file: {path}")
        channels = 3 if header == "PF" else 1
        size_line = f.readline().decode("ascii")
        while size_line.startswith("#"):
            size_line = f.readline().decode("ascii")
        w, h = (int(x) for x in size_line.split())
        scale = float(f.readline().decode("ascii").strip())
        endian = "<" if scale < 0 else ">"
        data = np.frombuffer(f.read(), dtype=endian + "f4")
        if channels == 3:
            data = data.reshape(h, w, 3)
        else:
            data = data.reshape(h, w)
        # PFM stores rows bottom-up.
        return np.flipud(data) * abs(scale)


def _imwrite(arr, path: Path) -> None:
    import numpy as np
    ext = path.suffix.lower()
    if ext in (".hdr", ".pic", ".rgbe"):
        import cv2
        cv2.imwrite(str(path), arr[..., ::-1])  # RGB -> BGR
        return
    if ext == ".exr":
        import OpenEXR, Imath
        h, w = arr.shape[:2]
        header = OpenEXR.Header(w, h)
        pt = Imath.PixelType(Imath.PixelType.FLOAT)
        header["channels"] = {"R": Imath.Channel(pt),
                              "G": Imath.Channel(pt),
                              "B": Imath.Channel(pt)}
        f = OpenEXR.OutputFile(str(path), header)
        bands = {c: arr[..., i].astype("float32").tobytes()
                 for i, c in enumerate("RGB") if i < arr.shape[-1]}
        f.writePixels(bands); f.close()
        return
    if ext == ".pfm":
        h, w = arr.shape[:2]
        channels = arr.shape[2] if arr.ndim == 3 else 1
        magic = b"PF\n" if channels == 3 else b"Pf\n"
        with path.open("wb") as f:
            f.write(magic)
            f.write(f"{w} {h}\n".encode("ascii"))
            f.write(b"-1.0\n")  # little-endian
            np.flipud(arr).astype("<f4").tofile(f)
        return
    if ext in (".png", ".tif", ".tiff"):
        import imageio.v3 as iio
        if arr.max() <= 1.0:
            iio.imwrite(str(path), (arr * 65535).clip(0, 65535).astype("uint16"))
        else:
            iio.imwrite(str(path), arr.astype("float32"))
        return
    raise ValueError(f"Unsupported output ext: {ext}")


def op_convert(args: argparse.Namespace) -> int:
    try:
        import numpy as np  # noqa: F401
    except ImportError as ex:
        return fail("missing_numpy", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"HDR file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="hdr", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            arr = _imread(src)
            out_path = out_dir / (src.stem + target_ext)
            _imwrite(arr, out_path)
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("hdr_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target_ext.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_tonemap(args: argparse.Namespace) -> int:
    try:
        import cv2
        import numpy as np
    except ImportError as ex:
        return fail("missing_opencv", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"HDR file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    operator_factories = {
        "reinhard": lambda: cv2.createTonemapReinhard(args.gamma, 0, 0, 0),
        "drago":    lambda: cv2.createTonemapDrago(args.gamma, 1.0, 0.85),
        "mantiuk":  lambda: cv2.createTonemapMantiuk(args.gamma, 0.85, 1.2),
        "linear":   lambda: cv2.createTonemap(args.gamma),
    }
    if args.operator not in operator_factories:
        return fail("bad_operator", f"Choose: {sorted(operator_factories)}")
    op = operator_factories[args.operator]()

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            arr = _imread(src).astype("float32")
            ldr = op.process(arr[..., ::-1])  # BGR
            ldr = (np.clip(ldr, 0, 1) * 255).astype("uint8")
            out_path = out_dir / (src.stem + "_ldr." + args.format)
            cv2.imwrite(str(out_path), ldr)
        except Exception as ex:
            return fail("tonemap_failed", f"{src.name}: {ex}")
        emit("hdr_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=args.format, operator=args.operator)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hdrkit-sidecar",
                                description="HDR image conversion (Radiance / EXR / PFM / 16-bit PNG-TIFF).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert between HDR formats.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="hdr | exr | pfm | png | tif")
    t = sub.add_parser("tonemap", help="Convert HDR -> 8-bit LDR via a tone-map operator.")
    t.add_argument("--input", nargs="+", required=True)
    t.add_argument("--output-dir", required=True, dest="output_dir")
    t.add_argument("--operator", default="reinhard",
                   choices=["reinhard", "drago", "mantiuk", "linear"])
    t.add_argument("--gamma", type=float, default=2.2)
    t.add_argument("--format", default="png", choices=["png", "jpg", "jpeg", "tif", "tiff"])
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "tonemap": return op_tonemap(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
