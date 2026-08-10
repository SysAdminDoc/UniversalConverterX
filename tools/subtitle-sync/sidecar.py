#!/usr/bin/env python3
"""subtitle-sync — Audio-fingerprint subtitle synchronization sidecar for UCX.

Wraps smacke/subsync (Python, pip-installable) to correct subtitle timing
drift by comparing FFT audio fingerprints of speech segments against
subtitle timestamps. No video re-encode; outputs a re-timed .srt file.

Also supports ffsubsync (an older maintained fork) as a fallback.

Operations:
  sync      Synchronize subtitles to a reference video/audio
  probe     Check subsync/ffsubsync availability

NDJSON contract: progress · log · complete · error · subtitle_synced
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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg as shared_find_ffmpeg


# ── NDJSON helpers ──────────────────────────────────────────────────



def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


# ── Binary/module discovery ────────────────────────────────────────

def _find_subsync() -> tuple[str | None, str]:
    """Find subsync or ffsubsync. Returns (command, tool_name)."""
    for tool in ("subsync", "ffsubsync"):
        path = shutil.which(tool)
        if path:
            return path, tool
    env = os.environ.get("SUBSYNC_PATH")
    if env and Path(env).is_file():
        return env, "subsync"
    here = Path(__file__).resolve().parent
    for name in ("subsync.exe", "subsync", "ffsubsync.exe", "ffsubsync"):
        p = here / name
        if p.is_file():
            return str(p), name.replace(".exe", "")
        p = here.parent / "_bin" / name
        if p.is_file():
            return str(p), name.replace(".exe", "")
    return None, "subsync"


_find_ffmpeg = partial(shared_find_ffmpeg, Path(__file__).resolve().parent)


# ── Process runner ──────────────────────────────────────────────────

def _run(cmd: list[str], stage: str) -> tuple[int, str]:
    log("info", f"[{stage}] {' '.join(cmd)}")
    emit("progress", percent=0, stage=stage, eta_seconds=None)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        lines.append(line)
        pct = _parse_progress(line)
        if pct is not None:
            emit("progress", percent=pct, stage=stage, eta_seconds=None)
        else:
            log("info", line)
    proc.wait()
    return proc.returncode, "\n".join(lines)


_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _parse_progress(line: str) -> float | None:
    m = _PCT_RE.search(line)
    if m:
        val = float(m.group(1))
        if 0 <= val <= 100:
            return val
    return None


# ── Operations ──────────────────────────────────────────────────────

def op_sync(args: argparse.Namespace) -> int:
    binary, tool_name = _find_subsync()
    if not binary:
        return fail("missing_subsync",
                    "Neither subsync nor ffsubsync is installed. Install via "
                    "'pip install subsync' or 'pip install ffsubsync', or place "
                    "the binary next to this sidecar.")

    ref = Path(args.reference)
    sub = Path(args.input)
    if not ref.is_file():
        return fail("missing_reference", f"Reference video/audio not found: {ref}")
    if not sub.is_file():
        return fail("missing_input", f"Subtitle file not found: {sub}")

    out = Path(args.output) if args.output else Path(
        str(sub.with_suffix("")) + "_synced" + sub.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)

    if tool_name == "ffsubsync":
        cmd = [binary, str(ref), "-i", str(sub), "-o", str(out)]
    else:
        cmd = [binary, str(ref), "-i", str(sub), "-o", str(out)]

    if args.max_offset:
        cmd += ["--max-offset-seconds", str(args.max_offset)]

    rc, transcript = _run(cmd, "subtitle synchronization")
    if rc != 0:
        return fail("subsync_failed",
                    f"{tool_name} exited {rc}. "
                    + (transcript.splitlines()[-1] if transcript else ""))

    if not out.is_file():
        return fail("output_missing", f"Synced subtitle not produced: {out}")

    offset = _extract_offset(transcript)

    emit("subtitle_synced", reference=str(ref), original=str(sub),
         synced=str(out), tool=tool_name, offset_seconds=offset)
    emit("complete", output=str(out), size_bytes=out.stat().st_size,
         tool=tool_name, offset_seconds=offset)
    return 0


def _extract_offset(text: str) -> float | None:
    m = re.search(r"offset[:\s]+([-+]?\d+(?:\.\d+)?)\s*s", text, re.IGNORECASE)
    return float(m.group(1)) if m else None


def op_probe(args: argparse.Namespace) -> int:
    binary, tool_name = _find_subsync()
    if not binary:
        log("warn", "Neither subsync nor ffsubsync is on PATH or bundled.")
        emit("complete", output="", size_bytes=0,
             subsync_path=None, subsync_version=None, tool=None)
        return 0

    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=15)
        version = (result.stdout or result.stderr or "").strip()
    except Exception as ex:
        version = f"probe-failed: {type(ex).__name__}"

    ffmpeg = _find_ffmpeg()
    log("info", f"{tool_name} at {binary} ({version})")
    emit("complete", output=binary, size_bytes=0,
         subsync_path=binary, subsync_version=version,
         tool=tool_name, ffmpeg_path=ffmpeg)
    return 0


def op_presets(_args: argparse.Namespace) -> int:
    presets = [
        {"name": "subtitle-sync", "description": "Sync subtitles to video via audio fingerprint"},
    ]
    for preset in presets:
        emit("log", level="info", message=json.dumps(preset))
    emit("complete", output="", size_bytes=0, presets=presets)
    return 0


# ── Argparse ────────────────────────────────────────────────────────

def main() -> int:
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()

    p = argparse.ArgumentParser(
        prog="subtitle-sync",
        description="Audio-fingerprint subtitle synchronization sidecar for UCX")
    sub = p.add_subparsers(dest="op", required=True)

    # sync
    s = sub.add_parser("sync",
                       help="Synchronize subtitles to reference video/audio")
    s.add_argument("--input", required=True,
                   help="Input subtitle file (.srt/.vtt/.ass)")
    s.add_argument("--reference", required=True,
                   help="Reference video or audio file")
    s.add_argument("--output",
                   help="Output synced subtitle (default: input_synced.srt)")
    s.add_argument("--max-offset", type=float,
                   help="Maximum allowed offset in seconds")

    # probe
    sub.add_parser("probe", help="Check subsync/ffsubsync availability")

    # presets
    sub.add_parser("presets", help="List built-in presets")

    ns = p.parse_args()

    ops = {
        "sync": op_sync,
        "probe": op_probe,
        "presets": op_presets,
    }
    return ops[ns.op](ns)


if __name__ == "__main__":
    raise SystemExit(main())
