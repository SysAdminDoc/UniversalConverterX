"""Lottie animation sidecar -- .json (Lottie / Bodymovin) / .tgs (Telegram
sticker) / .lottie (dotLottie zip) -> GIF / MP4 / APNG / WEBP / PNG-sequence.

Implementation strategy:
  1. python-lottie can render to GIF / HTML / SVG / WebP directly.
  2. For MP4/APNG, render a PNG sequence and composite via ffmpeg.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg as shared_find_ffmpeg




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_ffmpeg() -> str | None:
    return shared_find_ffmpeg(Path(__file__).resolve().parent)


def _load_lottie(path: Path):
    """Return parsed Lottie dict; handle .json / .tgs (gzip) / .lottie (zip)."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix == ".tgs":
        import gzip
        return json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
    if suffix == ".lottie":
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith(".json") and "manifest" not in name.lower():
                    return json.loads(zf.read(name).decode("utf-8"))
        raise RuntimeError("dotLottie zip missing animation JSON")
    raise RuntimeError(f"Unsupported Lottie source: {suffix}")


def op_convert(args: argparse.Namespace) -> int:
    try:
        from lottie.parsers.tgs import parse_tgs  # noqa: F401
        from lottie.parsers.baseporter import importer as _imp  # noqa: F401
        from lottie.exporters.cairo import export_png as _exp_png
        from lottie import objects  # noqa: F401
    except ImportError as ex:
        return fail("missing_lottie",
                    f"python-lottie + cairosvg not installed: {ex}")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"Lottie file(s) not found: {missing}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in ("gif", "mp4", "webp", "apng", "png", "webm", "svg"):
        return fail("bad_format", f"Use gif | mp4 | webm | webp | apng | png | svg.")

    ffmpeg = _find_ffmpeg() if target in ("mp4", "webm", "apng") else None
    if target in ("mp4", "webm", "apng") and ffmpeg is None:
        return fail("missing_ffmpeg",
                    f"{target.upper()} output requires ffmpeg on PATH.")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            from lottie.parsers.tgs import parse_tgs as _parse_tgs
            from lottie.utils import script as _scripts  # noqa: F401
            # Simplest cross-format path: parse the JSON and emit through python-lottie's
            # exporter selector.
            from lottie import exporters
            anim = _parse_tgs(str(src)) if src.suffix.lower() == ".tgs" else exporters.exporters.from_filename(str(src))
        except Exception:
            # Fallback: load JSON manually, build animation via lottie.objects.Animation.load.
            try:
                from lottie.objects import Animation
                anim = Animation.load(_load_lottie(src))
            except Exception as ex:
                return fail("parse_failed", f"{src.name}: {ex}")

        try:
            if target in ("gif", "webp", "svg"):
                from lottie import exporters
                out_path = out_dir / (src.stem + "." + target)
                exporters.exporters.get_from_extension(target).process(anim, str(out_path))
            elif target == "png":
                # PNG sequence -> per-frame files.
                seq_dir = out_dir / src.stem
                seq_dir.mkdir(parents=True, exist_ok=True)
                from lottie.exporters import cairo as _cairo
                if hasattr(_cairo, "export_png"):
                    _cairo.export_png(anim, str(seq_dir / "frame_%05d.png"))
                out_path = seq_dir
            else:
                # mp4 / webm / apng via ffmpeg over a temp PNG sequence.
                with tempfile.TemporaryDirectory() as tmp:
                    seq = Path(tmp)
                    from lottie.exporters import cairo as _cairo
                    _cairo.export_png(anim, str(seq / "frame_%05d.png"))
                    fps = float(getattr(anim, "frame_rate", None) or 30)
                    out_path = out_dir / (src.stem + "." + target)
                    cmd = [ffmpeg, "-y", "-framerate", str(fps),
                           "-i", str(seq / "frame_%05d.png")]
                    if target == "mp4":
                        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
                    elif target == "webm":
                        cmd += ["-c:v", "libvpx-vp9", "-b:v", "1M"]
                    elif target == "apng":
                        cmd += ["-plays", "0"]   # loop forever
                    cmd.append(str(out_path))
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    if proc.returncode != 0:
                        tail = (proc.stderr or proc.stdout).splitlines()[-5:]
                        for ln in tail: emit("log", level="error", message=ln)
                        return fail("ffmpeg_failed", f"{src.name}: rc={proc.returncode}")
        except Exception as ex:
            return fail("export_failed", f"{src.name}: {ex}")

        emit("lottie_render",
             input=str(src), output=str(out_path), format=target,
             size_bytes=out_path.stat().st_size if Path(out_path).is_file() else 0)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lottiekit-sidecar",
                                description="Lottie / Bodymovin / TGS / dotLottie -> GIF / MP4 / WEBP / APNG / SVG / PNG.")
    sub = p.add_subparsers(dest="op", required=True)
    cv = sub.add_parser("convert", help="Render Lottie animations to other formats.")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True,
                    help="gif | mp4 | webm | webp | apng | svg | png (sequence)")
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
