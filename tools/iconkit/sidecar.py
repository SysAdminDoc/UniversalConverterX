"""Multi-resolution icon sidecar.

Produce platform-native icon containers from one or more PNG / image inputs:

  * .ico  Windows favicon / cursor (multi-resolution, transparent)
  * .icns Apple icon (macOS .app bundles)
  * .iconset  Apple iconset directory (input to `iconutil`)
  * .png  Single resized "app icon" (with optional rounded mask)

Recommended sizes are auto-generated from the largest input image; user can
override with --sizes "16,24,32,48,64,128,256".
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
import struct
import sys
import time
from io import BytesIO
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Default Windows / Apple recommended sizes.
ICO_SIZES_DEFAULT = [16, 24, 32, 48, 64, 128, 256]
ICNS_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def _parse_sizes(spec: str | None, default: list[int]) -> list[int]:
    if not spec: return default
    try:
        return sorted({int(s.strip()) for s in spec.split(",") if s.strip()})
    except Exception:
        return default


def _resize(img, size: int):
    from PIL import Image
    return img.resize((size, size), Image.LANCZOS)


def op_to_ico(args: argparse.Namespace) -> int:
    try:
        from PIL import Image
    except ImportError as ex:
        return fail("missing_pillow", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sizes = _parse_sizes(args.sizes, ICO_SIZES_DEFAULT)
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            img = Image.open(str(src)).convert("RGBA")
            out_path = out_dir / (src.stem + ".ico")
            img.save(str(out_path), format="ICO",
                     sizes=[(s, s) for s in sizes if s <= max(img.size)])
        except Exception as ex:
            return fail("ico_failed", f"{src.name}: {ex}")
        emit("icon_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="ico", sizes=sizes)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ICNS writer -- the format is a header + concatenation of typed blocks.
# Type codes (subset):
ICNS_TYPES = {
    16:   b"icp4",
    32:   b"icp5",
    64:   b"icp6",
    128:  b"ic07",
    256:  b"ic08",
    512:  b"ic09",
    1024: b"ic10",
}


def _icns_block(type_code: bytes, png_bytes: bytes) -> bytes:
    return type_code + struct.pack(">I", 8 + len(png_bytes)) + png_bytes


def op_to_icns(args: argparse.Namespace) -> int:
    try:
        from PIL import Image
    except ImportError as ex:
        return fail("missing_pillow", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            img = Image.open(str(src)).convert("RGBA")
            blocks = b""
            count = 0
            for size, type_code in ICNS_TYPES.items():
                if size > max(img.size): continue
                buf = BytesIO()
                _resize(img, size).save(buf, format="PNG", optimize=True)
                blocks += _icns_block(type_code, buf.getvalue())
                count += 1
            header = b"icns" + struct.pack(">I", 8 + len(blocks))
            out_path = out_dir / (src.stem + ".icns")
            out_path.write_bytes(header + blocks)
        except Exception as ex:
            return fail("icns_failed", f"{src.name}: {ex}")
        emit("icon_blob",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="icns", layers=count)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_iconset(args: argparse.Namespace) -> int:
    """Apple iconset folder layout (input to `iconutil --convert icns`)."""
    try:
        from PIL import Image
    except ImportError as ex:
        return fail("missing_pillow", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        img = Image.open(str(src)).convert("RGBA")
        bundle = out_dir / (src.stem + ".iconset")
        bundle.mkdir(parents=True, exist_ok=True)
        for size in [16, 32, 128, 256, 512]:
            for scale in (1, 2):
                px = size * scale
                if px > max(img.size): continue
                fname = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                _resize(img, px).save(str(bundle / fname), "PNG", optimize=True)
        emit("icon_blob",
             input=str(src), output=str(bundle),
             size_bytes=sum(p.stat().st_size for p in bundle.glob("*")),
             format="iconset")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="iconkit-sidecar",
                                description="Multi-resolution icon container generator.")
    sub = p.add_subparsers(dest="op", required=True)
    a = sub.add_parser("to-ico", help="PNG -> Windows .ico (multi-res).")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")
    a.add_argument("--sizes", default=None,
                   help="Comma-separated pixel sizes (default: 16,24,32,48,64,128,256).")
    b = sub.add_parser("to-icns", help="PNG -> Apple .icns (multi-res).")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")
    c = sub.add_parser("to-iconset", help="PNG -> Apple .iconset folder.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-ico":     return op_to_ico(args)
        if args.op == "to-icns":    return op_to_icns(args)
        if args.op == "to-iconset": return op_to_iconset(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
