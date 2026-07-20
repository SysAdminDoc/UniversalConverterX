"""Long-tail / specialty video container sidecar.

Targets the formats `videocrush` doesn't normally handle on its own:

  * VOB / EVO        DVD-Video / Blu-ray EVO containers
  * MTS / M2TS / TS  Blu-ray AVCHD + MPEG-TS broadcast
  * DV / DIF         DV / DVCPRO camcorder tape capture
  * 3GP / 3G2        Mobile MPEG-4 container
  * F4V / SWF        Adobe Flash containers
  * H.264 / H.265 / AV1 elementary streams (.h264, .264, .h265, .hevc, .ivf)
  * Y4M              Raw uncompressed YUV4MPEG2
  * AVS / AVS2       Chinese AVS

Backed by FFmpeg shellouts. We intentionally keep this separate from
videocrush so users get a dedicated tile + preset library for these niche
sources.
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
from ucx_sidecar import emit, find_ffmpeg as shared_find_ffmpeg




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_ffmpeg() -> str | None:
    return shared_find_ffmpeg(Path(__file__).resolve().parent)


# Container -> FFmpeg muxer + recommended audio/video codec pair.
TARGETS = {
    "mp4":   ("mp4",  "libx264", "aac"),
    "mkv":   ("matroska", "libx264", "aac"),
    "mov":   ("mov",  "libx264", "aac"),
    "webm":  ("webm", "libvpx-vp9", "libopus"),
    "avi":   ("avi",  "mpeg4", "mp3"),
    "ts":    ("mpegts", "libx264", "aac"),
    "ivf":   ("ivf",  "libsvtav1", "copy"),
    "h264":  ("h264",  "copy", None),    # raw bitstream extract
    "h265":  ("hevc",  "copy", None),
    "y4m":   ("yuv4mpegpipe", "rawvideo", None),
}


def _convert(ffmpeg: str, src: Path, out_dir: Path,
              target: str, copy: bool) -> Path | None:
    fmt = TARGETS.get(target)
    if not fmt: return None
    muxer, vcodec, acodec = fmt
    out_path = out_dir / (src.stem + "." + target)
    cmd = [ffmpeg, "-y", "-i", str(src)]
    if copy:
        cmd += ["-c:v", "copy"]
        if acodec: cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:v", vcodec]
        if acodec: cmd += ["-c:a", acodec]
    cmd += ["-f", muxer, str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        for ln in tail: emit("log", level="error", message=ln)
        return None
    return out_path


def op_convert(args: argparse.Namespace) -> int:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Video file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in TARGETS:
        return fail("bad_format", f"Choose: {sorted(TARGETS)}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="videopro", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = _convert(ffmpeg, src, out_dir, target, args.copy)
        if out_path is None:
            return fail("convert_failed", f"{src.name}: FFmpeg failed.")
        emit("video_specialty",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, copy=args.copy,
             source_ext=src.suffix.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_extract_bitstream(args: argparse.Namespace) -> int:
    """Extract raw H.264 / HEVC / AV1 elementary stream from any container."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Video file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    codec = args.codec.lower()
    ext_map = {"h264": "h264", "h265": "hevc", "hevc": "hevc",
               "av1": "ivf", "vp9": "ivf"}
    if codec not in ext_map:
        return fail("bad_codec", "Choose h264 | h265 | av1 | vp9.")

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + ext_map[codec])
        cmd = [ffmpeg, "-y", "-i", str(src),
               "-an", "-c:v", "copy", "-bsf:v", f"{codec}_mp4toannexb",
               "-f", codec, str(out_path)]
        # AV1/VP9 use IVF, not annex-B.
        if codec in ("av1", "vp9"):
            cmd = [ffmpeg, "-y", "-i", str(src),
                   "-an", "-c:v", "copy", "-f", "ivf", str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("extract_failed", f"{src.name}: rc={proc.returncode}")
        emit("video_specialty",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=ext_map[codec], codec=codec, role="bitstream")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="videopro-sidecar",
                                description="Specialty video container conversion (VOB/MTS/DV/3GP/F4V/elementary streams).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Container conversion via FFmpeg.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="mp4 | mkv | mov | webm | avi | ts | ivf | h264 | h265 | y4m")
    c.add_argument("--copy", action="store_true",
                   help="Stream-copy (no re-encode) when source codec is compatible.")
    e = sub.add_parser("extract-bitstream", help="Extract raw video elementary stream.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    e.add_argument("--codec", required=True, help="h264 | h265 | hevc | av1 | vp9")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":            return op_convert(args)
        if args.op == "extract-bitstream":  return op_extract_bitstream(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
