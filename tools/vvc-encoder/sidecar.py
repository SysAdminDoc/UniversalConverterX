#!/usr/bin/env python3
"""vvc-encoder — VVC / H.266 encoding sidecar for UniversalConverterX.

Wraps Fraunhofer HHI's vvencapp / vvencFFapp (VVC encoder) for H.266
encoding with capped constant-quality (CQF) mode and film-grain
analysis. VVC achieves ~30-50%% bitrate savings vs H.265 at equal
quality per Fraunhofer benchmarks.

Operations:
  encode    Encode video to VVC/H.266 via vvencapp
  probe     Check vvencapp availability and version
  presets   List built-in encode presets

NDJSON contract: progress · log · complete · error · vvc_encode
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# ── NDJSON helpers ──────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


# ── Binary discovery ────────────────────────────────────────────────

def _find_vvenc() -> str | None:
    for env_var in ("VVENC_PATH", "VVENCFFAPP_PATH"):
        v = os.environ.get(env_var)
        if v and Path(v).is_file():
            return v
    for name in ("vvencapp", "vvencFFapp"):
        found = shutil.which(name)
        if found:
            return found
    here = Path(__file__).resolve().parent
    for name in ("vvencapp.exe", "vvencapp", "vvencFFapp.exe", "vvencFFapp"):
        for base in (here, here.parent / "_bin"):
            p = base / name
            if p.is_file():
                return str(p)
    return None


def _find_ffmpeg() -> str | None:
    candidates: list[str | None] = [
        os.environ.get("FFMPEG_PATH"),
        shutil.which("ffmpeg"),
    ]
    here = Path(__file__).resolve().parent
    for name in ("ffmpeg.exe", "ffmpeg"):
        candidates.append(str(here.parent / "ffmpeg" / name))
        candidates.append(str(here.parent / "_bin" / name))
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


# ── Process runner ──────────────────────────────────────────────────

_FRAME_RE = re.compile(r"POC\s+(\d+)")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%%")


def _stream(cmd: list[str], stage: str, total_frames: int | None = None
            ) -> tuple[int, str]:
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
        m = _FRAME_RE.search(line)
        if m and total_frames and total_frames > 0:
            pct = min(100.0, int(m.group(1)) / total_frames * 100)
            emit("progress", percent=round(pct, 1), stage=stage, eta_seconds=None)
        else:
            mp = _PCT_RE.search(line)
            if mp:
                emit("progress", percent=float(mp.group(1)), stage=stage, eta_seconds=None)
            else:
                log("info", line)
    proc.wait()
    return proc.returncode, "\n".join(lines)


# ── Operations ──────────────────────────────────────────────────────

PRESETS = ["faster", "fast", "medium", "slow", "slower"]


def op_encode(args: argparse.Namespace) -> int:
    binary = _find_vvenc()
    if not binary:
        return fail("missing_vvenc",
                    "vvencapp is not installed. Download from "
                    "github.com/fraunhoferhhi/vvenc/releases and place "
                    "vvencapp.exe next to this sidecar or on PATH.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {src}")

    out = Path(args.output) if args.output else Path(
        str(src.with_suffix("")) + "_vvc.266")
    out.parent.mkdir(parents=True, exist_ok=True)

    preset = args.preset if args.preset in PRESETS else "medium"
    qp = args.qp if args.qp is not None else 32

    cmd = [binary, "-i", str(src), "-o", str(out),
           "--preset", preset, "--qp", str(qp)]

    if args.threads:
        cmd += ["--threads", str(args.threads)]
    if args.width:
        cmd += ["-s", f"{args.width}x{args.height or args.width}"]
    if args.fps:
        cmd += ["-r", str(args.fps)]
    if args.bitrate:
        cmd += ["--bitrate", str(args.bitrate)]
    if args.film_grain:
        cmd += ["--film-grain-analysis"]

    log("info", f"Encoding {src.name} → VVC ({preset}, QP {qp})")
    rc, transcript = _stream(cmd, "VVC encoding")

    if rc != 0:
        return fail("vvenc_failed",
                    f"vvencapp exited {rc}. "
                    + (transcript.splitlines()[-1] if transcript else ""))

    if not out.is_file():
        return fail("output_missing", f"VVC output not produced: {out}")

    emit("vvc_encode", preset=preset, qp=qp,
         output_path=str(out), output_size_bytes=out.stat().st_size)
    emit("complete", output=str(out), size_bytes=out.stat().st_size,
         preset=preset, qp=qp)
    return 0


def op_probe(args: argparse.Namespace) -> int:
    binary = _find_vvenc()
    if not binary:
        log("warn", "vvencapp is not on PATH and not bundled.")
        emit("complete", output="", size_bytes=0,
             vvenc_path=None, vvenc_version=None)
        return 0

    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=15)
        version = (result.stdout or result.stderr or "").strip().split("\n")[0]
    except Exception as ex:
        version = f"probe-failed: {type(ex).__name__}"

    ffmpeg = _find_ffmpeg()
    log("info", f"vvencapp at {binary} ({version})")
    emit("complete", output=binary, size_bytes=0,
         vvenc_path=binary, vvenc_version=version, ffmpeg_path=ffmpeg)
    return 0


def op_presets(_args: argparse.Namespace) -> int:
    presets = [
        {"name": "vvc-medium", "description": "VVC/H.266 medium preset (balanced)"},
        {"name": "vvc-slow", "description": "VVC/H.266 slow preset (best quality)"},
        {"name": "vvc-fast", "description": "VVC/H.266 fast preset (speed)"},
    ]
    for p in presets:
        emit("log", level="info", message=json.dumps(p))
    emit("complete", output="", size_bytes=0, presets=presets)
    return 0


# ── Argparse ────────────────────────────────────────────────────────

def main() -> int:
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()

    p = argparse.ArgumentParser(
        prog="vvc-encoder",
        description="VVC / H.266 encoding sidecar for UCX (vvencapp wrapper)")
    sub = p.add_subparsers(dest="op", required=True)

    s = sub.add_parser("encode", help="Encode video to VVC/H.266")
    s.add_argument("--input", required=True, help="Input Y4M or raw YUV file")
    s.add_argument("--output", help="Output .266 file (default: input_vvc.266)")
    s.add_argument("--preset", choices=PRESETS, default="medium",
                   help="Encode preset (default: medium)")
    s.add_argument("--qp", type=int, default=32,
                   help="Quantization parameter (default: 32)")
    s.add_argument("--bitrate", type=int,
                   help="Target bitrate in kbps (enables rate control)")
    s.add_argument("--threads", type=int,
                   help="Number of encoding threads")
    s.add_argument("--width", type=int, help="Input width")
    s.add_argument("--height", type=int, help="Input height")
    s.add_argument("--fps", type=float, help="Input framerate")
    s.add_argument("--film-grain", action="store_true",
                   help="Enable film grain analysis (vvenc 1.14+)")

    sub.add_parser("probe", help="Check vvencapp availability")
    sub.add_parser("presets", help="List built-in presets")

    ns = p.parse_args()
    ops = {
        "encode": op_encode,
        "probe": op_probe,
        "presets": op_presets,
    }
    return ops[ns.op](ns)


if __name__ == "__main__":
    raise SystemExit(main())
