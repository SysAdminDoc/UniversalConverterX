"""Adaptive streaming manifest sidecar.

Convert between adaptive bitrate streaming packagings:

  * DASH        .mpd manifest + segments
  * HLS         .m3u8 master + variant playlists + segments
  * CMAF        Common Media Application Format (fragmented MP4)
  * MSS / SS    Microsoft Smooth Streaming (.ism / .ismv)

We shell out to:
  * shaka-packager (Apache-2.0)  -- canonical DASH / HLS packager from Google
  * FFmpeg                       -- fallback for HLS-from-source remux

Operations:
  hls-from-mp4    MP4 -> HLS (.m3u8 + .ts segments).
  dash-from-mp4   MP4 -> DASH (.mpd + .m4s segments).
  hls-to-mp4      HLS .m3u8 -> single MP4 (FFmpeg concat).
  dash-to-mp4     DASH .mpd -> single MP4.
  hls-to-dash     Repackage HLS to DASH without re-encoding.
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
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find(name: str, env: str | None = None) -> str | None:
    if env and (p := os.environ.get(env)) and Path(p).is_file(): return p
    return shutil.which(name) or shutil.which(name + ".exe")


def op_hls_from_mp4(args: argparse.Namespace) -> int:
    ffmpeg = _find("ffmpeg", "FFMPEG_PATH")
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MP4(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        sub = out_dir / src.stem
        sub.mkdir(parents=True, exist_ok=True)
        m3u8 = sub / "playlist.m3u8"
        cmd = [
            ffmpeg, "-y", "-i", str(src),
            "-c:v", "copy", "-c:a", "copy",
            "-hls_time", str(args.segment_seconds),
            "-hls_list_size", "0",
            "-hls_segment_filename", str(sub / "seg_%03d.ts"),
            "-f", "hls", str(m3u8),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("hls_failed", f"{src.name}: rc={proc.returncode}")
        size = sum(p.stat().st_size for p in sub.rglob("*") if p.is_file())
        emit("stream_manifest",
             input=str(src), output=str(m3u8),
             size_bytes=size,
             format="hls", segment_seconds=int(args.segment_seconds))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_dash_from_mp4(args: argparse.Namespace) -> int:
    """Use shaka-packager when available; FFmpeg as fallback."""
    pkg = _find("packager", "SHAKA_PACKAGER_PATH") or _find("shaka-packager")
    ffmpeg = _find("ffmpeg", "FFMPEG_PATH")
    if not pkg and not ffmpeg:
        return fail("missing_packager",
                    "Neither shaka-packager nor FFmpeg available. "
                    "Install one to package DASH.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MP4(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        sub = out_dir / src.stem
        sub.mkdir(parents=True, exist_ok=True)
        mpd = sub / "manifest.mpd"
        if pkg:
            video = sub / "video.m4s"
            audio = sub / "audio.m4s"
            cmd = [
                pkg,
                f"in={src},stream=video,output={video}",
                f"in={src},stream=audio,output={audio}",
                f"--mpd_output={mpd}",
                "--segment_duration", str(args.segment_seconds),
            ]
        else:
            cmd = [
                ffmpeg, "-y", "-i", str(src),
                "-c:v", "copy", "-c:a", "copy",
                "-seg_duration", str(args.segment_seconds),
                "-use_template", "1", "-use_timeline", "1",
                "-init_seg_name", "init_$RepresentationID$.m4s",
                "-media_seg_name", "chunk_$RepresentationID$_$Number%05d$.m4s",
                "-f", "dash", str(mpd),
            ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("dash_failed", f"{src.name}: rc={proc.returncode}")
        size = sum(p.stat().st_size for p in sub.rglob("*") if p.is_file())
        emit("stream_manifest",
             input=str(src), output=str(mpd),
             size_bytes=size, format="dash",
             segment_seconds=int(args.segment_seconds),
             tool="shaka-packager" if pkg else "ffmpeg")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_mp4(args: argparse.Namespace) -> int:
    """HLS / DASH manifest -> single MP4 via FFmpeg concat-protocol."""
    ffmpeg = _find("ffmpeg", "FFMPEG_PATH")
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Manifest(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".mp4")
        cmd = [ffmpeg, "-y", "-i", str(src),
               "-c", "copy", "-bsf:a", "aac_adtstoasc",
               str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("mp4_failed", f"{src.name}: rc={proc.returncode}")
        emit("stream_manifest",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="mp4")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="streaming-sidecar",
                                description="Adaptive streaming manifest conversion (HLS / DASH / CMAF).")
    sub = p.add_subparsers(dest="op", required=True)

    h = sub.add_parser("hls-from-mp4", help="MP4 -> HLS .m3u8 + .ts segments.")
    h.add_argument("--input", nargs="+", required=True)
    h.add_argument("--output-dir", required=True, dest="output_dir")
    h.add_argument("--segment-seconds", type=int, default=6, dest="segment_seconds")

    d = sub.add_parser("dash-from-mp4", help="MP4 -> DASH .mpd + .m4s segments.")
    d.add_argument("--input", nargs="+", required=True)
    d.add_argument("--output-dir", required=True, dest="output_dir")
    d.add_argument("--segment-seconds", type=int, default=6, dest="segment_seconds")

    m = sub.add_parser("to-mp4", help="HLS .m3u8 / DASH .mpd -> single MP4.")
    m.add_argument("--input", nargs="+", required=True)
    m.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "hls-from-mp4":  return op_hls_from_mp4(args)
        if args.op == "dash-from-mp4": return op_dash_from_mp4(args)
        if args.op == "to-mp4":         return op_to_mp4(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
