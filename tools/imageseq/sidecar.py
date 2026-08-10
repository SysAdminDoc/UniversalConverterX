"""Image-sequence <-> video sidecar.

Visual-effects and color-grading workflows commonly bounce between video
files and frame-by-frame image sequences (DPX / Cineon / OpenEXR / TIFF /
PNG / JPEG). This sidecar handles both directions via FFmpeg's image2
demuxer / muxer.

Operations:
  encode    Image sequence  -> video (MP4 / MOV / MKV / ProRes / DNxHD)
  decode    Video           -> image sequence (any format Pillow / FFmpeg
                              can write, including DPX / EXR for HDR work)

Frame-rate, color-space, and codec are configurable.
"""
from __future__ import annotations

import argparse
from functools import partial
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg as shared_find_ffmpeg




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_find_ffmpeg = partial(shared_find_ffmpeg, Path(__file__).resolve().parent)


_FRAME_RE = re.compile(r"(\d+)(?=\.[A-Za-z0-9]+$)")


def _autoderive_pattern(first: Path) -> tuple[str, int] | None:
    """Given the first frame, derive an FFmpeg-style pattern + start index."""
    m = _FRAME_RE.search(first.name)
    if not m: return None
    digits = m.group(1)
    pattern = first.name[:m.start()] + f"%0{len(digits)}d" + first.name[m.end():]
    return str(first.parent / pattern), int(digits)


VIDEO_PROFILES = {
    "h264": ("libx264", "yuv420p", ["-preset", "slow", "-crf", "18"]),
    "h265": ("libx265", "yuv420p", ["-preset", "slow", "-crf", "20"]),
    "prores-422":    ("prores_ks", "yuv422p10le", ["-profile:v", "2"]),
    "prores-422-hq": ("prores_ks", "yuv422p10le", ["-profile:v", "3"]),
    "prores-4444":   ("prores_ks", "yuv444p10le", ["-profile:v", "4"]),
    "dnxhr-hq":  ("dnxhd", "yuv422p10le", ["-profile:v", "dnxhr_hq"]),
    "dnxhr-sq":  ("dnxhd", "yuv422p10le", ["-profile:v", "dnxhr_sq"]),
    "av1":       ("libsvtav1", "yuv420p", ["-preset", "8", "-crf", "30"]),
    "ffv1":      ("ffv1", "yuv420p", []),
    "rawvideo":  ("rawvideo", "yuv420p", []),
}


def op_encode(args: argparse.Namespace) -> int:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")

    if args.pattern:
        pattern = args.pattern
        start = int(args.start_index)
    else:
        if not args.input:
            return fail("bad_args",
                        "Pass --pattern '<dir>/frame_%04d.exr' or --input <first frame>.")
        first = Path(args.input[0])
        if not first.is_file():
            return fail("missing_input", f"First frame not found: {first}")
        derived = _autoderive_pattern(first)
        if not derived:
            return fail("bad_pattern",
                        f"Could not derive pattern from {first.name}; pass --pattern.")
        pattern, start = derived

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = args.name or "sequence"
    profile = args.profile.lower()
    if profile not in VIDEO_PROFILES:
        return fail("bad_profile", f"Choose: {sorted(VIDEO_PROFILES)}")
    vcodec, pix_fmt, extra = VIDEO_PROFILES[profile]

    out_path = out_dir / f"{out_name}.{args.container}"
    cmd = [ffmpeg, "-y",
           "-framerate", str(args.fps),
           "-start_number", str(start),
           "-i", pattern,
           "-c:v", vcodec, "-pix_fmt", pix_fmt,
           *extra, str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        for ln in tail: emit("log", level="error", message=ln)
        return fail("encode_failed", f"rc={proc.returncode}")

    emit("image_seq",
         pattern=pattern, output=str(out_path),
         size_bytes=out_path.stat().st_size,
         profile=profile, fps=float(args.fps),
         container=args.container)
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_decode(args: argparse.Namespace) -> int:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Video file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.format.lower().lstrip(".")

    total = len(inputs)
    for i, src in enumerate(inputs):
        sub = out_dir / src.stem
        sub.mkdir(parents=True, exist_ok=True)
        pattern = sub / f"frame_%0{args.digits}d.{fmt}"
        cmd = [ffmpeg, "-y", "-i", str(src)]
        if args.fps:
            cmd += ["-vf", f"fps={args.fps}"]
        cmd += [str(pattern)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("decode_failed", f"{src.name}: rc={proc.returncode}")
        frames = sorted(sub.glob(f"frame_*.{fmt}"))
        emit("image_seq",
             input=str(src), output=str(sub),
             size_bytes=sum(f.stat().st_size for f in frames),
             format=fmt, frame_count=len(frames))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="imageseq-sidecar",
                                description="Image sequence <-> video.")
    sub = p.add_subparsers(dest="op", required=True)
    e = sub.add_parser("encode", help="Image sequence -> video.")
    e.add_argument("--input", nargs="*", default=None,
                   help="First frame (auto-derives the pattern + start index).")
    e.add_argument("--pattern", default=None,
                   help="Explicit FFmpeg-style pattern, e.g. 'shot/frame_%%04d.exr'.")
    e.add_argument("--start-index", default=0, dest="start_index")
    e.add_argument("--output-dir", required=True, dest="output_dir")
    e.add_argument("--name", default="sequence")
    e.add_argument("--fps", default=24)
    e.add_argument("--container", default="mov",
                   help="Output extension/container (mov | mp4 | mkv | webm | mxf).")
    e.add_argument("--profile", default="prores-422-hq",
                   help=f"Codec profile: {sorted(VIDEO_PROFILES)}")

    d = sub.add_parser("decode", help="Video -> image sequence.")
    d.add_argument("--input", nargs="+", required=True)
    d.add_argument("--output-dir", required=True, dest="output_dir")
    d.add_argument("--format", default="png",
                   help="Frame format: png | jpg | tif | exr | dpx | bmp")
    d.add_argument("--fps", default=None)
    d.add_argument("--digits", type=int, default=6)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "encode": return op_encode(args)
        if args.op == "decode": return op_decode(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
