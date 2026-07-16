"""Niche raster image sidecar.

Heicshift handles the modern image set; this sidecar covers the legacy /
specialty raster formats that shipped Pillow / imageio / OpenCV plugins
can read and write but which fall outside the typical "image converter"
scope:

  * PCX                                ZSoft Paintbrush
  * Truevision TGA (.tga)              gaming / 3D textures
  * Cineon (.cin) + DPX (.dpx)         motion picture exchange (10-bit log)
  * SGI / RGB (.sgi, .rgb, .bw, .rgba) Silicon Graphics
  * Sun Raster (.ras, .rast)           Sun Microsystems
  * Wireless Bitmap (.wbmp)            mobile WAP
  * Photo CD (.pcd)                    Kodak (read-only)
  * Netpbm (.pbm/.pgm/.ppm/.pnm)       portable any-map
  * APNG (.apng)                       animated PNG
  * MNG (.mng)                         multi-image network graphics (read)
  * FLI / FLC (.fli/.flc)              Autodesk Animator (read)
  * X PixMap (.xpm), XBM (.xbm)        X Window text-based bitmaps
  * Palm Pixmap (.palm)                Palm OS image
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


# Many of these formats are handled by Pillow with format hints.
PIL_FORMAT = {
    "pcx": "PCX", "tga": "TGA",
    "dpx": "DPX",
    "sgi": "SGI", "rgb": "SGI", "bw": "SGI", "rgba": "SGI",
    "ras": "RAS", "rast": "RAS", "sun": "RAS",
    "wbmp": "WBMP",
    "ppm": "PPM", "pgm": "PPM", "pbm": "PPM", "pnm": "PPM",
    "apng": "PNG",  # APNG via Pillow's PNG plugin (with `save_all`).
    "mng": "MNG",
    "fli": "FLI", "flc": "FLI",
    "xpm": "XPM", "xbm": "XBM",
    "palm": "PALM",
    "pcd": "PCD",
}


def _convert_pillow(src: Path, out_path: Path) -> int:
    from PIL import Image
    try:
        img = Image.open(str(src))
    except Exception as ex:
        return fail("read_failed", f"{src.name}: {ex}")

    out_ext = out_path.suffix.lower().lstrip(".")
    save_kwargs = {}
    fmt_hint = PIL_FORMAT.get(out_ext)
    if fmt_hint == "PNG" and out_ext == "apng":
        save_kwargs["save_all"] = True

    # Some formats require RGB (no alpha) -- drop alpha gracefully.
    if out_ext in ("pcx", "fli", "flc", "wbmp", "xpm", "xbm"):
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "L" and out_ext == "wbmp":
            img = img.convert("1")
    try:
        if fmt_hint:
            img.save(str(out_path), format=fmt_hint, **save_kwargs)
        else:
            img.save(str(out_path), **save_kwargs)
    except Exception as ex:
        return fail("write_failed", f"{src.name}: {ex}")
    return 0


def op_convert(args: argparse.Namespace) -> int:
    try:
        from PIL import Image  # noqa: F401
    except ImportError as ex:
        return fail("missing_pillow", str(ex))

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="rasterimg", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + target_ext)
        rc = _convert_pillow(src, out_path)
        if rc != 0: return rc
        emit("raster_image",
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rasterimg-sidecar",
                                description="Niche raster image conversion (PCX/TGA/DPX/SGI/Sun/PCD/Netpbm/APNG/MNG/FLI/XPM).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert between niche raster formats.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="png | jpg | tif | pcx | tga | dpx | sgi | ras | wbmp | "
                        "ppm | pgm | pbm | apng | xpm | xbm | palm")
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
