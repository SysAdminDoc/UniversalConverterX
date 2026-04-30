"""RecordCast sidecar - NDJSON screen/webcam recorder for the UCX Recorder module.

Supports:
  - Screen capture (gdigrab) with optional microphone audio (dshow)
  - Webcam-only capture (dshow video + audio)
  - Device enumeration via 'list-devices' subcommand
"""
from __future__ import annotations

import argparse
import json
import os
import re
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


def find_ffmpeg() -> str | None:
    here = Path(__file__).resolve().parent
    for candidate in [
        os.environ.get("FFMPEG_PATH"),
        shutil.which("ffmpeg"),
        str(here / "ffmpeg.exe"),
        str(here.parent / "_bin" / "ffmpeg.exe"),
    ]:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


_TIME_RE = re.compile(r"out_time_ms=(\d+)")
_DSHOW_DEVICE_RE = re.compile(r'^\[dshow[^\]]*\]\s+"(.+)"')
_DSHOW_TYPE_RE = re.compile(r"DirectShow (video|audio) devices")


def run_ffmpeg(cmd: list[str], duration_sec: int, stage: str = "recording") -> int:
    proc = subprocess.Popen(
        cmd + ["-progress", "pipe:1", "-nostats"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    started = time.monotonic()
    last_pct = -1.0
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            match = _TIME_RE.search(line)
            if match and duration_sec > 0:
                current = int(match.group(1)) / 1_000_000
                pct = max(0.0, min(100.0, current / duration_sec * 100.0))
                if pct - last_pct >= 0.5:
                    last_pct = pct
                    elapsed = time.monotonic() - started
                    local = pct / 100.0
                    eta = (elapsed / local - elapsed) if local > 0.01 else None
                    emit(
                        "progress",
                        percent=round(pct, 1),
                        stage=stage,
                        eta_seconds=int(eta) if eta and eta < 86400 else None,
                    )
            elif line.startswith("progress=end"):
                emit("progress", percent=100, stage="finalizing", eta_seconds=0)
    finally:
        proc.wait()
        if proc.returncode != 0 and proc.stderr is not None:
            for ln in proc.stderr.read().splitlines()[-20:]:
                emit("log", level="error", message=ln)
    return proc.returncode


def op_list_devices(args: argparse.Namespace) -> int:
    """Enumerate DirectShow video and audio devices via FFmpeg and emit them as NDJSON."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")

    proc = subprocess.run(
        [ffmpeg, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
        capture_output=True,
        text=True,
    )

    # FFmpeg prints device list on stderr
    output = proc.stderr + proc.stdout
    current_type: str | None = None
    found = 0
    for line in output.splitlines():
        type_match = _DSHOW_TYPE_RE.search(line)
        if type_match:
            current_type = type_match.group(1)
            continue
        if current_type:
            device_match = _DSHOW_DEVICE_RE.search(line)
            if device_match:
                name = device_match.group(1)
                emit("device", type=current_type, name=name)
                found += 1

    emit("complete", device_count=found)
    return 0


def op_record(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    duration = max(1, min(args.duration, 21_600))
    framerate = max(5, min(args.framerate, 120))
    crf = max(0, min(args.crf, 51))
    source = (args.source or "screen").lower()
    webcam = args.webcam or None
    audio = args.audio or None

    if source == "webcam" and not webcam:
        return fail("missing_webcam", "--webcam <device name> is required when --source webcam")

    emit("log", level="info",
         message=f"Recording ({source}) for {duration}s at {framerate} fps")
    emit("progress", percent=0, stage="starting capture", eta_seconds=duration)

    cmd: list[str] = [ffmpeg, "-y"]

    if source == "screen":
        # gdigrab desktop + optional dshow microphone
        cmd += ["-f", "gdigrab", "-framerate", str(framerate), "-i", "desktop"]
        if audio:
            cmd += ["-f", "dshow", "-i", f"audio={audio}"]
        cmd += [
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", args.preset,
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ]
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        stage = "recording screen"

    elif source == "webcam":
        # dshow webcam video + optional dshow microphone
        cmd += ["-f", "dshow", "-framerate", str(framerate), "-i", f"video={webcam}"]
        if audio:
            cmd += ["-f", "dshow", "-i", f"audio={audio}"]
        cmd += [
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", args.preset,
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
        ]
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        stage = "recording webcam"

    else:
        return fail("invalid_source", f"Unknown source: {source}. Use screen or webcam.")

    cmd.append(str(output))

    rc = run_ffmpeg(cmd, duration, stage=stage)
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not output.is_file():
        return fail("output_missing", f"Output not produced: {output}")

    emit("complete", output=str(output), size_bytes=output.stat().st_size)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recordcast-sidecar",
        description="UCX RecordCast sidecar — Windows screen/webcam capture.",
    )
    sub = parser.add_subparsers(dest="op", required=True)

    # list-devices
    sub.add_parser("list-devices", help="Enumerate DirectShow video and audio devices")

    # record
    record = sub.add_parser("record", help="Record screen or webcam")
    record.add_argument("--output", required=True)
    record.add_argument("--duration", type=int, required=True, help="Duration in seconds")
    record.add_argument("--framerate", type=int, default=30)
    record.add_argument("--crf", type=int, default=20)
    record.add_argument("--preset", default="veryfast")
    record.add_argument("--source", default="screen", choices=["screen", "webcam"],
                        help="Capture source: screen (gdigrab) or webcam (dshow)")
    record.add_argument("--webcam", default=None, metavar="DEVICE",
                        help="DirectShow webcam device name (required when --source webcam)")
    record.add_argument("--audio", default=None, metavar="DEVICE",
                        help="DirectShow audio device name for microphone capture")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "record":
            return op_record(args)
        if args.op == "list-devices":
            return op_list_devices(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
