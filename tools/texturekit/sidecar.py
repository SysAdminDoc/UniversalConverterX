"""Texture format converter -- game / GPU texture formats.

Read:  PNG / JPEG / WebP / TIFF / BMP / EXR / HDR / DDS / KTX / KTX2 / TGA
Write: PNG / JPEG / WebP / TIFF / BMP / EXR / DDS / KTX / KTX2 / TGA / ASTC

Uses Pillow for the lossless image set, imageio for KTX/KTX2/EXR, and shells
out to astcenc.exe for ASTC compression (user installs separately).
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_astcenc() -> str | None:
    for n in ("astcenc-avx2.exe", "astcenc-sse4.1.exe", "astcenc.exe", "astcenc"):
        hit = shutil.which(n)
        if hit: return hit
    here = Path(__file__).resolve().parent
    for c in (here / "astcenc.exe", here.parent / "_bin" / "astcenc.exe"):
        if c.is_file(): return str(c)
    return None


PILLOW_FORMATS = {"png", "jpg", "jpeg", "webp", "tiff", "tif", "bmp", "tga", "dds"}
IMAGEIO_FORMATS = {"ktx", "ktx2", "exr", "hdr"}


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"Texture(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    if target == "astc":
        astc = _find_astcenc()
        if astc is None:
            return fail("missing_astcenc",
                        "astcenc not found. Install ARM's ASTC encoder "
                        "(github.com/ARM-software/astc-encoder) or set PATH.")
    use_pil = target in PILLOW_FORMATS
    use_iio = target in IMAGEIO_FORMATS

    if not use_pil and not use_iio and target != "astc":
        return fail("bad_format",
                    f"Unknown texture format '{target}'. Use png/jpg/webp/tiff/bmp/tga/dds/ktx/ktx2/exr/astc.")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + target)
        try:
            if target == "astc":
                # astcenc-cli quality_preset src.png out.astc <block_size>
                blk = args.astc_block or "6x6"
                quality = args.astc_quality or "medium"
                cmd = [astc, "-cl", str(src), str(out_path), blk, "-" + quality]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    return fail("astcenc_failed",
                                (proc.stderr or proc.stdout)[-400:])
            elif use_pil:
                from PIL import Image
                img = Image.open(str(src))
                img.save(str(out_path))
            else:
                import imageio.v3 as iio
                arr = iio.imread(str(src))
                iio.imwrite(str(out_path), arr)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")

        emit("texture",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             format=target)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="texturekit-sidecar",
                                description="GPU / game texture conversion (DDS / KTX / ASTC / EXR).")
    sub = p.add_subparsers(dest="op", required=True)
    cv = sub.add_parser("convert", help="Convert textures between formats.")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True,
                    help="png | jpg | webp | tiff | bmp | tga | dds | ktx | ktx2 | exr | astc")
    cv.add_argument("--astc-block", dest="astc_block",
                    help="ASTC block size (4x4 / 5x5 / 6x6 / 8x8 / 10x10 / 12x12). Default 6x6.")
    cv.add_argument("--astc-quality", dest="astc_quality",
                    help="ASTC speed/quality preset: fastest / fast / medium / thorough / verythorough / exhaustive.")
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
