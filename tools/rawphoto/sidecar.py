"""RAW photo sidecar -- decodes camera RAW files via `rawpy` (LibRaw bindings)
and writes JPEG / TIFF / PNG / 16-bit TIFF output through Pillow.

Read formats: every camera RAW LibRaw recognises -- CR2, CR3, NEF, ARW, RAF,
RW2, ORF, DNG, PEF, SRW, SRF, X3F, KDC, DCR, DCS, MOS, MEF, MRW, NRW, ERF,
ARQ, BAY, BMQ, CINE, CS1, EIP, FFF, IIQ, K25, MDC, MFW, NXR, PXN, R3D, RAW,
RWL, RWZ, etc.

Write formats: jpg / jpeg / png / tiff / tif / tiff16 (16-bit linear).

Frozen-guard: deps bundled at build time, no runtime pip.
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
        import rawpy  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_deps",
             message=f"rawpy/Pillow not installed in this build: {ex}")
        return False


# rawpy demosaic algorithms surfaced to the UI.
DEMOSAIC = {
    "linear":   0,   # rawpy.DemosaicAlgorithm.LINEAR
    "vng":      1,   # VNG
    "ppg":      2,   # Patterned Pixel Grouping
    "ahd":      3,   # Adaptive Homogeneity-Directed (default)
    "dcb":      4,
    "dht":      11,
    "modified_ahd": 12,
}


def op_convert(args: argparse.Namespace) -> int:
    if not _imports():
        return 1
    import rawpy
    from PIL import Image

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"RAW file(s) not found: {missing}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    if target not in ("jpg", "jpeg", "png", "tiff", "tif", "tiff16"):
        return fail("bad_format",
                    f"Unknown target '{target}'. Use jpg/jpeg/png/tiff/tif/tiff16.")
    out_ext = ".tiff" if target.startswith("tiff") else ("." + target)

    demosaic_id = DEMOSAIC.get(args.demosaic.lower(), 3)
    use_camera_wb = args.white_balance.lower() in ("camera", "as_shot")
    use_auto_wb = args.white_balance.lower() == "auto"

    total = len(inputs)
    emit("log", level="info",
         message=(f"RAW develop {total} -> .{target} "
                  f"(demosaic={args.demosaic}, wb={args.white_balance}, "
                  f"bright={args.brightness:.2f}, gamma={args.gamma})"))
    emit("progress", percent=0, stage="develop", eta_seconds=None)

    started = time.monotonic()
    for i, src in enumerate(inputs):
        try:
            with rawpy.imread(str(src)) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=use_camera_wb,
                    use_auto_wb=use_auto_wb,
                    no_auto_bright=not args.auto_brightness,
                    bright=float(args.brightness),
                    gamma=(float(args.gamma), float(args.gamma_toe)),
                    output_bps=16 if target == "tiff16" else 8,
                    demosaic_algorithm=rawpy.DemosaicAlgorithm(demosaic_id),
                    user_flip=int(args.orientation),
                )
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("decode_failed", f"Could not develop {src.name}: {ex}")

        out_path = out_dir / (src.stem + out_ext)
        try:
            if target == "tiff16":
                Image.fromarray(rgb, mode="RGB").save(
                    str(out_path), format="TIFF", compression="tiff_lzw")
            elif target in ("tiff", "tif"):
                Image.fromarray(rgb, mode="RGB").save(
                    str(out_path), format="TIFF", compression="tiff_lzw")
            elif target == "png":
                Image.fromarray(rgb, mode="RGB").save(
                    str(out_path), format="PNG", optimize=True)
            else:
                Image.fromarray(rgb, mode="RGB").save(
                    str(out_path), format="JPEG",
                    quality=int(args.quality), optimize=True)
        except Exception as ex:
            return fail("write_failed", f"Could not write {out_path.name}: {ex}")

        emit("raw_photo",
             input=str(src),
             output=str(out_path),
             size_bytes=out_path.stat().st_size,
             width=int(rgb.shape[1]),
             height=int(rgb.shape[0]))

        pct = (i + 1) / total * 100.0
        elapsed = time.monotonic() - started
        local = pct / 100.0
        eta = (elapsed / local - elapsed) if local > 0.01 else None
        emit("progress",
             percent=round(pct, 1),
             stage=f"developed {i + 1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    total_size = sum((out_dir / (Path(p).stem + out_ext)).stat().st_size
                     for p in args.input
                     if (out_dir / (Path(p).stem + out_ext)).is_file())
    emit("complete", output=str(out_dir), size_bytes=total_size, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rawphoto-sidecar",
                                description="Camera RAW developer via rawpy/LibRaw.")
    sub = p.add_subparsers(dest="op", required=True)

    cv = sub.add_parser("convert",
                        help="Develop one or more RAW files to JPEG / PNG / TIFF.")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True,
                    help="jpg | jpeg | png | tiff | tif | tiff16")
    cv.add_argument("--quality", type=int, default=92,
                    help="JPEG quality 1-100 (default 92).")
    cv.add_argument("--white-balance", default="camera", dest="white_balance",
                    help="camera (as-shot) | auto | daylight")
    cv.add_argument("--demosaic", default="ahd",
                    help=" | ".join(DEMOSAIC.keys()))
    cv.add_argument("--brightness", type=float, default=1.0,
                    help="Brightness multiplier (1.0 = neutral).")
    cv.add_argument("--auto-brightness", action="store_true",
                    dest="auto_brightness",
                    help="Let LibRaw auto-stretch the histogram.")
    cv.add_argument("--gamma", type=float, default=2.222,
                    help="Output gamma (default 2.222 ~ sRGB).")
    cv.add_argument("--gamma-toe", type=float, default=4.5,
                    dest="gamma_toe",
                    help="Toe slope of the gamma curve (default 4.5).")
    cv.add_argument("--orientation", type=int, default=-1,
                    help="0 keep, 3 = 180, 5 = 90 CCW, 6 = 90 CW, -1 = use camera flag (default).")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":
            return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
