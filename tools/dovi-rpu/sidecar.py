#!/usr/bin/env python3
"""dovi-rpu — Dolby Vision RPU pass-through sidecar for UniversalConverterX.

Wraps quietvoid/dovi_tool (Rust binary) to extract, inject, and manage
Dolby Vision RPU metadata during transcodes. Without explicit RPU
pass-through, transcoding a Dolby Vision source flattens it to HDR10
and silently destroys per-shot grading.

Operations:
  extract-rpu   Extract RPU data from HEVC bitstream → RPU.bin
  inject-rpu    Inject RPU.bin back into an encoded HEVC bitstream
  demux         Demux Dolby Vision BL+EL+RPU layers
  info          Show RPU info for a video (profile, levels, trims)
  probe         Check dovi_tool availability and version

NDJSON contract: progress · log · complete · error · dovi_rpu
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
import re
import shutil
import subprocess
import sys
from pathlib import Path


# ── NDJSON helpers ──────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


# ── Binary discovery ────────────────────────────────────────────────

def _find_dovi_tool() -> str | None:
    candidates: list[str | None] = [
        os.environ.get("DOVI_TOOL_PATH"),
        shutil.which("dovi_tool"),
    ]
    here = Path(__file__).resolve().parent
    for name in ("dovi_tool.exe", "dovi_tool"):
        candidates.append(str(here / name))
        candidates.append(str(here.parent / "_bin" / name))
    for c in candidates:
        if c and Path(c).is_file():
            return c
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


_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%%")


def _parse_progress(line: str) -> float | None:
    m = _PCT_RE.search(line)
    return float(m.group(1)) if m else None


# ── Operations ──────────────────────────────────────────────────────

def op_extract_rpu(args: argparse.Namespace) -> int:
    binary = _find_dovi_tool()
    if not binary:
        return fail("missing_dovi_tool",
                    "dovi_tool is not installed. Download from "
                    "github.com/quietvoid/dovi_tool/releases and place "
                    "dovi_tool.exe next to this sidecar or on PATH.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {src}")

    out = Path(args.output) if args.output else src.with_suffix(".rpu.bin")
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [binary, "extract-rpu", "-i", str(src), "-o", str(out)]
    if args.mode:
        cmd += ["--mode", str(args.mode)]

    rc, transcript = _run(cmd, "RPU extraction")
    if rc != 0:
        return fail("dovi_tool_failed",
                    f"dovi_tool extract-rpu exited {rc}. "
                    + (transcript.splitlines()[-1] if transcript else ""))

    if not out.is_file():
        return fail("output_missing", f"RPU file not produced: {out}")

    emit("dovi_rpu", action="extract", rpu_path=str(out),
         rpu_size_bytes=out.stat().st_size)
    emit("complete", output=str(out), size_bytes=out.stat().st_size)
    return 0


def op_inject_rpu(args: argparse.Namespace) -> int:
    binary = _find_dovi_tool()
    if not binary:
        return fail("missing_dovi_tool",
                    "dovi_tool is not installed. Download from "
                    "github.com/quietvoid/dovi_tool/releases.")

    src = Path(args.input)
    rpu = Path(args.rpu)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {src}")
    if not rpu.is_file():
        return fail("missing_rpu", f"RPU file not found: {rpu}")

    out = Path(args.output) if args.output else Path(
        str(src.with_suffix("")) + "_dv" + src.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [binary, "inject-rpu", "-i", str(src), "--rpu-in", str(rpu),
           "-o", str(out)]
    if args.no_eos:
        cmd.append("--no-add-aud-nal")

    rc, transcript = _run(cmd, "RPU injection")
    if rc != 0:
        return fail("dovi_tool_failed",
                    f"dovi_tool inject-rpu exited {rc}. "
                    + (transcript.splitlines()[-1] if transcript else ""))

    if not out.is_file():
        return fail("output_missing", f"Output not produced: {out}")

    emit("dovi_rpu", action="inject", rpu_path=str(rpu),
         output_path=str(out), output_size_bytes=out.stat().st_size)
    emit("complete", output=str(out), size_bytes=out.stat().st_size)
    return 0


def op_demux(args: argparse.Namespace) -> int:
    binary = _find_dovi_tool()
    if not binary:
        return fail("missing_dovi_tool",
                    "dovi_tool is not installed. Download from "
                    "github.com/quietvoid/dovi_tool/releases.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {src}")

    out_dir = Path(args.output_dir) if args.output_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem

    cmd = [binary, "demux", "-i", str(src)]
    bl_out = out_dir / f"{stem}_BL.hevc"
    el_out = out_dir / f"{stem}_EL.hevc"
    rpu_out = out_dir / f"{stem}_RPU.bin"
    cmd += ["--bl-out", str(bl_out), "--el-out", str(el_out),
            "--rpu-out", str(rpu_out)]

    rc, transcript = _run(cmd, "Dolby Vision demux")
    if rc != 0:
        return fail("dovi_tool_failed",
                    f"dovi_tool demux exited {rc}. "
                    + (transcript.splitlines()[-1] if transcript else ""))

    produced: list[str] = []
    for p in (bl_out, el_out, rpu_out):
        if p.is_file():
            produced.append(str(p))
            emit("dovi_rpu", action="demux", layer=p.stem.split("_")[-1],
                 path=str(p), size_bytes=p.stat().st_size)

    if not produced:
        return fail("output_missing", "No demuxed layers produced.")

    emit("complete", output=produced[0], size_bytes=sum(
        Path(p).stat().st_size for p in produced),
        layers=produced)
    return 0


def op_info(args: argparse.Namespace) -> int:
    binary = _find_dovi_tool()
    if not binary:
        return fail("missing_dovi_tool",
                    "dovi_tool is not installed. Download from "
                    "github.com/quietvoid/dovi_tool/releases.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {src}")

    cmd = [binary, "info", "-i", str(src)]
    if args.summary:
        cmd.append("--summary")

    rc, transcript = _run(cmd, "RPU info")

    profile = _extract_field(transcript, r"Profile:\s*(\d+)")
    max_cll = _extract_field(transcript, r"MaxCLL:\s*(\d+)")
    max_fall = _extract_field(transcript, r"MaxFALL:\s*(\d+)")
    rpu_count = _extract_field(transcript, r"RPU count:\s*(\d+)")

    emit("dovi_rpu", action="info", profile=profile, max_cll=max_cll,
         max_fall=max_fall, rpu_count=rpu_count, raw_output=transcript)
    emit("complete", output=str(src), size_bytes=src.stat().st_size,
         profile=profile, rpu_count=rpu_count)
    return 0


def _extract_field(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1) if m else None


def op_probe(args: argparse.Namespace) -> int:
    binary = _find_dovi_tool()
    if not binary:
        log("warn", "dovi_tool is not on PATH and not bundled.")
        emit("complete", output="", size_bytes=0,
             dovi_tool_path=None, dovi_tool_version=None)
        return 0

    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=15)
        version = (result.stdout or result.stderr or "").strip()
    except Exception as ex:
        version = f"probe-failed: {type(ex).__name__}"

    ffmpeg = _find_ffmpeg()
    log("info", f"dovi_tool at {binary} ({version})")
    emit("complete", output=binary, size_bytes=0,
         dovi_tool_path=binary, dovi_tool_version=version,
         ffmpeg_path=ffmpeg)
    return 0


# ── Argparse ────────────────────────────────────────────────────────

def main() -> int:
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()

    p = argparse.ArgumentParser(
        prog="dovi-rpu",
        description="Dolby Vision RPU pass-through sidecar for UCX")
    sub = p.add_subparsers(dest="op", required=True)

    # extract-rpu
    s = sub.add_parser("extract-rpu",
                       help="Extract RPU from HEVC bitstream")
    s.add_argument("--input", required=True, help="Input HEVC file")
    s.add_argument("--output", help="Output RPU.bin (default: input.rpu.bin)")
    s.add_argument("--mode", type=int, choices=[0, 1, 2],
                   help="Extraction mode (0=MEL, 1=profile 8.1, 2=profile 8.4)")

    # inject-rpu
    s = sub.add_parser("inject-rpu",
                       help="Inject RPU into HEVC bitstream")
    s.add_argument("--input", required=True, help="Input HEVC file")
    s.add_argument("--rpu", required=True, help="RPU.bin file to inject")
    s.add_argument("--output", help="Output HEVC file (default: input_dv.hevc)")
    s.add_argument("--no-eos", action="store_true",
                   help="Do not add AUD NAL units")

    # demux
    s = sub.add_parser("demux",
                       help="Demux Dolby Vision BL+EL+RPU layers")
    s.add_argument("--input", required=True, help="Input DV HEVC file")
    s.add_argument("--output-dir",
                   help="Output directory (default: same as input)")

    # info
    s = sub.add_parser("info",
                       help="Show RPU info for a video")
    s.add_argument("--input", required=True, help="Input file")
    s.add_argument("--summary", action="store_true",
                   help="Show summary only")

    # probe
    sub.add_parser("probe", help="Check dovi_tool availability")

    # presets
    s = sub.add_parser("presets",
                       help="List built-in presets")

    ns = p.parse_args()

    ops = {
        "extract-rpu": op_extract_rpu,
        "inject-rpu": op_inject_rpu,
        "demux": op_demux,
        "info": op_info,
        "probe": op_probe,
        "presets": op_presets,
    }
    return ops[ns.op](ns)


def op_presets(_args: argparse.Namespace) -> int:
    presets = [
        {"name": "dovi-extract-rpu", "description": "Extract Dolby Vision RPU from HEVC"},
        {"name": "dovi-inject-rpu", "description": "Inject Dolby Vision RPU into HEVC"},
        {"name": "dovi-demux", "description": "Demux Dolby Vision BL+EL+RPU layers"},
        {"name": "dovi-info", "description": "Show Dolby Vision RPU info"},
    ]
    for preset in presets:
        emit("log", level="info", message=json.dumps(preset))
    emit("complete", output="", size_bytes=0, presets=presets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
