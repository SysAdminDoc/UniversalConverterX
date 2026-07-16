"""GifStudio sidecar — NDJSON video→GIF maker for the UCX GIF Maker module.

Two-pass FFmpeg pipeline for high-quality output:
  1. palettegen — analyse the trimmed segment, emit an optimised 256-colour palette
  2. paletteuse — re-encode using the palette (much smaller + cleaner than naive GIF)

Subcommands:
  make           video → GIF
  list-presets   emit a known-presets listing as NDJSON

Standard NDJSON contract: progress / log / complete / error events on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg as shared_find_ffmpeg, run_ffmpeg


# ── NDJSON helpers ───────────────────────────────────────────────────────────



def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── ffmpeg discovery ─────────────────────────────────────────────────────────

def find_ffmpeg() -> str | None:
    """Search PATH, FFMPEG_PATH env, the sidecar dir, and the shared tools/_bin."""
    return shared_find_ffmpeg(Path(__file__).resolve().parent)


def probe_duration(ffmpeg: str, path: Path) -> float:
    """Cheap duration probe via ffmpeg -i (works without ffprobe)."""
    try:
        result = subprocess.run(
            [ffmpeg, "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=15,
        )
        # ffmpeg writes "Duration: HH:MM:SS.MS" on stderr
        m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", result.stderr)
        if m:
            h, mm, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return h * 3600 + mm * 60 + s
    except Exception:
        pass
    return 0.0


# ── ffmpeg progress parser ───────────────────────────────────────────────────

# ── make ─────────────────────────────────────────────────────────────────────

def op_make(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fps = max(1, min(args.fps, 60))
    width = max(64, min(args.width, 4096))
    start = max(0.0, args.start)
    loop = args.loop  # 0 = infinite, -1 = play once, N = N additional loops

    # Resolve segment duration: prefer explicit --duration; otherwise span
    # from --start to end of source.
    if args.duration is not None and args.duration > 0:
        duration = float(args.duration)
    else:
        total = probe_duration(ffmpeg, in_path)
        duration = max(0.1, total - start) if total > 0 else 5.0

    emit("log", level="info",
         message=f"Building GIF: {duration:.1f}s @ {fps} fps, {width}px wide, "
                 f"loop={'infinite' if loop == 0 else 'once' if loop == -1 else f'{loop}x'}")

    palette_dir = tempfile.mkdtemp(prefix="ucx_gifstudio_")
    palette = os.path.join(palette_dir, "palette.png")

    try:
        # ── Pass 1: palettegen ───────────────────────────────────────────────
        emit("progress", percent=0, stage="generating palette", eta_seconds=None)
        gen_cmd = [
            ffmpeg, "-y",
            "-ss", str(start),
            "-t", str(duration),
            "-i", str(in_path),
            "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen",
            palette,
        ]
        rc = run_ffmpeg(gen_cmd, duration, "generating palette")
        if rc != 0:
            return fail("palettegen_failed", f"FFmpeg palettegen exited with code {rc}")
        if not Path(palette).is_file():
            return fail("palettegen_failed", "palette.png was not produced")

        # ── Pass 2: paletteuse ───────────────────────────────────────────────
        emit("progress", percent=50, stage="encoding GIF", eta_seconds=None)
        use_cmd = [
            ffmpeg, "-y",
            "-ss", str(start),
            "-t", str(duration),
            "-i", str(in_path),
            "-i", palette,
            "-lavfi", f"fps={fps},scale={width}:-1:flags=lanczos [x]; [x][1:v] paletteuse",
            "-loop", str(loop),
            str(out_path),
        ]
        rc = run_ffmpeg(use_cmd, duration, "encoding GIF")
        if rc != 0:
            return fail("paletteuse_failed", f"FFmpeg paletteuse exited with code {rc}")

        if not out_path.is_file():
            return fail("output_missing", f"Output GIF not produced: {out_path}")

        emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
        return 0
    finally:
        shutil.rmtree(palette_dir, ignore_errors=True)


# ── presets ──────────────────────────────────────────────────────────────────

_PRESETS = [
    {"id": "social-square",  "label": "Social square",  "width": 480,  "fps": 15, "loop": 0},
    {"id": "social-wide",    "label": "Social wide",    "width": 720,  "fps": 18, "loop": 0},
    {"id": "tiny-thumb",     "label": "Tiny thumbnail", "width": 240,  "fps": 12, "loop": 0},
    {"id": "high-quality",   "label": "High quality",   "width": 1080, "fps": 24, "loop": 0},
    {"id": "play-once",      "label": "Play once",      "width": 480,  "fps": 15, "loop": -1},
]


def op_list_presets(_: argparse.Namespace) -> int:
    for p in _PRESETS:
        emit("preset", **p)
    emit("complete", count=len(_PRESETS))
    return 0


# ── argparse + main ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gifstudio-sidecar",
        description="UCX GifStudio sidecar — video → GIF via two-pass palettegen/paletteuse.",
    )
    sub = parser.add_subparsers(dest="op", required=True)

    make = sub.add_parser("make", help="Convert video to GIF")
    make.add_argument("--input", required=True)
    make.add_argument("--output", required=True)
    make.add_argument("--start", type=float, default=0.0,
                      help="Start time in seconds (default 0)")
    make.add_argument("--duration", type=float, default=None,
                      help="Length in seconds (default: from start to source end)")
    make.add_argument("--fps", type=int, default=15)
    make.add_argument("--width", type=int, default=480,
                      help="Output width in pixels; height keeps aspect ratio")
    make.add_argument("--loop", type=int, default=0,
                      help="GIF loop count: 0 = infinite, -1 = play once, N = N additional loops")

    sub.add_parser("list-presets", help="Emit known render presets")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "make":
            return op_make(args)
        if args.op == "list-presets":
            return op_list_presets(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
