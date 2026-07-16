"""FrameSnap NDJSON sidecar — batch video frame extraction.

The legacy `framesnap.py` is a GUI tool. This sidecar gives the engine a
headless CLI surface so the C# host can drive it as a batch operation:

  * Extract frames at fixed intervals
  * Extract a single thumbnail at timestamp T
  * Extract every Nth frame
  * Extract scene-change frames (delegates to FFmpeg `select=gt(scene,...)`)

Operations:
  every-n-seconds   One frame every N seconds.
  every-n-frames    One frame every N frames.
  at-time           Single frame at a specific timestamp.
  scene-cuts        Frames at scene-change boundaries.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def _run(args: argparse.Namespace, ffmpeg_args: list[str], suffix: str) -> int:
    cli = _ffmpeg()
    if not cli: return fail("missing_dep", "ffmpeg not on PATH.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"video file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        target_dir = out_dir / src.stem
        target_dir.mkdir(parents=True, exist_ok=True)
        pattern = str(target_dir / (src.stem + "_%05d." + args.format))
        cmd = [cli, "-y", "-hide_banner", "-loglevel", "warning",
               "-i", str(src)] + ffmpeg_args + [
               "-q:v", str(args.quality), pattern]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=3600)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: ffmpeg exit {proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()}")
        produced = sorted(target_dir.glob(f"{src.stem}_*.{args.format}"))
        for f in produced:
            emit("frame",
                 input=str(src), output=str(f),
                 size_bytes=f.stat().st_size,
                 format=args.format, source=suffix)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_every_n_seconds(args: argparse.Namespace) -> int:
    return _run(args, ["-vf", f"fps=1/{args.seconds}"], "every-n-seconds")


def op_every_n_frames(args: argparse.Namespace) -> int:
    return _run(args, ["-vf", f"select=not(mod(n\\,{args.frames}))",
                        "-vsync", "vfr"], "every-n-frames")


def op_at_time(args: argparse.Namespace) -> int:
    return _run(args, ["-ss", str(args.time), "-frames:v", "1"],
                  "at-time")


def op_scene_cuts(args: argparse.Namespace) -> int:
    return _run(args, ["-vf", f"select=gt(scene\\,{args.threshold})",
                        "-vsync", "vfr"], "scene-cuts")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="framesnap-sidecar",
                                description="Batch video frame extraction.")
    sub = p.add_subparsers(dest="op", required=True)

    s = sub.add_parser("every-n-seconds", help="One frame every N seconds")
    s.add_argument("--input", nargs="+", required=True)
    s.add_argument("--output-dir", required=True, dest="output_dir")
    s.add_argument("--seconds", type=float, default=10.0)
    s.add_argument("--format", default="jpg",
                   choices=["jpg", "png", "webp", "tiff"])
    s.add_argument("--quality", type=int, default=3,
                   help="JPEG quality 1-31 (low number = high quality).")

    f = sub.add_parser("every-n-frames", help="One frame every N frames")
    f.add_argument("--input", nargs="+", required=True)
    f.add_argument("--output-dir", required=True, dest="output_dir")
    f.add_argument("--frames", type=int, default=30)
    f.add_argument("--format", default="jpg",
                   choices=["jpg", "png", "webp", "tiff"])
    f.add_argument("--quality", type=int, default=3)

    t = sub.add_parser("at-time", help="Single frame at timestamp")
    t.add_argument("--input", nargs="+", required=True)
    t.add_argument("--output-dir", required=True, dest="output_dir")
    t.add_argument("--time", required=True,
                   help="Timestamp (seconds or HH:MM:SS).")
    t.add_argument("--format", default="jpg",
                   choices=["jpg", "png", "webp", "tiff"])
    t.add_argument("--quality", type=int, default=3)

    sc = sub.add_parser("scene-cuts", help="Frames at scene changes")
    sc.add_argument("--input", nargs="+", required=True)
    sc.add_argument("--output-dir", required=True, dest="output_dir")
    sc.add_argument("--threshold", type=float, default=0.4)
    sc.add_argument("--format", default="jpg",
                    choices=["jpg", "png", "webp", "tiff"])
    sc.add_argument("--quality", type=int, default=3)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "every-n-seconds":  return op_every_n_seconds(args)
        if args.op == "every-n-frames":   return op_every_n_frames(args)
        if args.op == "at-time":          return op_at_time(args)
        if args.op == "scene-cuts":       return op_scene_cuts(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
