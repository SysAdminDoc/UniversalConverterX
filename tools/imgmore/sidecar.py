"""Niche image format sidecar (extends `rasterimg`).

Adds the truly long-tail image formats: legal-archive bitmaps, FAX,
Atari/Amiga heritage, and JBIG2.

  * JBIG2 (.jb2)         legal/medical archive bitmap (jbig2dec)
  * FAX TIFF G3 / G4    libtiff via Pillow + LZW/CCITT
  * Mac PICT (.pict)     ImageMagick CLI shellout
  * Amiga IFF / ILBM     ImageMagick CLI shellout
  * Atari Degas / Neo    ImageMagick CLI shellout
  * Adobe layered TIFF   tifffile preserves layers
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find(*names: str) -> str | None:
    for n in names:
        h = shutil.which(n) or shutil.which(n + ".exe")
        if h: return h
    return None


def _via_imagemagick(src: Path, out_path: Path) -> int:
    magick = _find("magick", "convert")
    if not magick:
        return fail("missing_imagemagick",
                    "ImageMagick not found. `apt install imagemagick` / "
                    "`choco install imagemagick`.")
    cmd = [magick, str(src), str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("imagemagick_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def _via_jbig2dec(src: Path, out_path: Path) -> int:
    jbig2dec = _find("jbig2dec")
    if not jbig2dec:
        return fail("missing_jbig2dec",
                    "jbig2dec not found. `apt install jbig2dec`.")
    cmd = [jbig2dec, "-o", str(out_path), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("jbig2dec_failed", f"{src.name}: rc={proc.returncode}")
    return 0


def _via_tifffile(src: Path, out_path: Path) -> int:
    """Adobe layered TIFF read; emit frame N as PNG."""
    try:
        import tifffile
        from PIL import Image
        import numpy as np
    except ImportError as ex:
        return fail("missing_tifffile",
                    f"tifffile not installed: {ex}.")
    try:
        with tifffile.TiffFile(str(src)) as tif:
            for n, page in enumerate(tif.pages):
                arr = page.asarray()
                if arr.ndim == 2:
                    img = Image.fromarray(arr)
                elif arr.ndim == 3:
                    img = Image.fromarray(arr.astype("uint8"))
                else:
                    continue
                p = out_path.with_name(f"{out_path.stem}_layer{n:02d}{out_path.suffix}")
                img.save(p)
    except Exception as ex:
        return fail("tifffile_failed", f"{src.name}: {ex}")
    return 0


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = "." + args.format.lstrip(".").lower()

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="imgmore", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        out_path = out_dir / (src.stem + target_ext)
        rc = 0
        if ext == ".jb2":
            rc = _via_jbig2dec(src, out_path)
        elif ext in (".tif", ".tiff") and args.split_layers:
            rc = _via_tifffile(src, out_path)
        else:
            rc = _via_imagemagick(src, out_path)
        if rc != 0: return rc

        emit("imgmore",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             format=target_ext.lstrip("."),
             source_ext=ext.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="imgmore-sidecar",
                                description="Niche image conversion: JBIG2 / FAX TIFF / PICT / IFF / Atari / layered TIFF.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert niche image -> PNG/JPG/TIFF/etc.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="png | jpg | tif | bmp | webp")
    c.add_argument("--split-layers", action="store_true", dest="split_layers",
                   help="(layered TIFF) emit one PNG per IFD page.")
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
