"""RecordCast sidecar - NDJSON screen recorder for the UCX Recorder module.

Initial scope is intentionally narrow: Windows desktop capture via FFmpeg
gdigrab with fixed-duration sessions. Webcam and audio capture require device
enumeration and consent flows and are kept out of this shim until the UI can
surface those choices safely.
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


def run_ffmpeg(cmd: list[str], duration_sec: int) -> int:
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
                        stage="recording screen",
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


def op_record(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    duration = max(1, min(args.duration, 21_600))
    framerate = max(5, min(args.framerate, 120))
    crf = max(0, min(args.crf, 51))

    emit("log", level="info", message=f"Recording desktop for {duration}s at {framerate} fps")
    emit("progress", percent=0, stage="starting capture", eta_seconds=duration)

    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "gdigrab",
        "-framerate",
        str(framerate),
        "-i",
        "desktop",
        "-t",
        str(duration),
        "-c:v",
        "libx264",
        "-preset",
        args.preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]

    rc = run_ffmpeg(cmd, duration)
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not output.is_file():
        return fail("output_missing", f"Output not produced: {output}")

    emit("complete", output=str(output), size_bytes=output.stat().st_size)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recordcast-sidecar",
        description="UCX RecordCast sidecar - fixed-duration Windows screen capture.",
    )
    sub = parser.add_subparsers(dest="op", required=True)

    record = sub.add_parser("record", help="Record the Windows desktop")
    record.add_argument("--output", required=True)
    record.add_argument("--duration", type=int, required=True, help="Duration in seconds")
    record.add_argument("--framerate", type=int, default=30)
    record.add_argument("--crf", type=int, default=20)
    record.add_argument("--preset", default="veryfast")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "record":
            return op_record(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
