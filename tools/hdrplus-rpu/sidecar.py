#!/usr/bin/env python3
"""hdrplus-rpu — HDR10+ dynamic metadata pass-through sidecar for UniversalConverterX.

Wraps quietvoid/hdr10plus_tool (Rust binary) to extract, inject, and
manage HDR10+ dynamic tone-mapping metadata (SMPTE ST 2094-40) during
transcodes. Without explicit pass-through, transcoding an HDR10+ source
erases the dynamic curve and reduces the file to static HDR10.

Operations:
  extract     Extract HDR10+ metadata from HEVC → metadata.json
  inject      Inject metadata.json back into encoded HEVC bitstream
  info        Show HDR10+ metadata summary
  probe       Check hdr10plus_tool availability and version

NDJSON contract: progress · log · complete · error · hdrplus_meta
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

def _find_hdr10plus_tool() -> str | None:
    candidates: list[str | None] = [
        os.environ.get("HDR10PLUS_TOOL_PATH"),
        shutil.which("hdr10plus_tool"),
    ]
    here = Path(__file__).resolve().parent
    for name in ("hdr10plus_tool.exe", "hdr10plus_tool"):
        candidates.append(str(here / name))
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
        log("info", line)
    proc.wait()
    return proc.returncode, "\n".join(lines)


# ── Operations ──────────────────────────────────────────────────────

def op_extract(args: argparse.Namespace) -> int:
    binary = _find_hdr10plus_tool()
    if not binary:
        return fail("missing_hdr10plus_tool",
                    "hdr10plus_tool is not installed. Download from "
                    "github.com/quietvoid/hdr10plus_tool/releases and "
                    "place hdr10plus_tool.exe next to this sidecar or on PATH.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {src}")

    out = Path(args.output) if args.output else src.with_suffix(".hdr10plus.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [binary, "extract", "-i", str(src), "-o", str(out)]

    rc, transcript = _run(cmd, "HDR10+ metadata extraction")
    if rc != 0:
        return fail("hdr10plus_tool_failed",
                    f"hdr10plus_tool extract exited {rc}. "
                    + (transcript.splitlines()[-1] if transcript else ""))

    if not out.is_file():
        return fail("output_missing", f"Metadata file not produced: {out}")

    emit("hdrplus_meta", action="extract", metadata_path=str(out),
         metadata_size_bytes=out.stat().st_size)
    emit("complete", output=str(out), size_bytes=out.stat().st_size)
    return 0


def op_inject(args: argparse.Namespace) -> int:
    binary = _find_hdr10plus_tool()
    if not binary:
        return fail("missing_hdr10plus_tool",
                    "hdr10plus_tool is not installed. Download from "
                    "github.com/quietvoid/hdr10plus_tool/releases.")

    src = Path(args.input)
    meta = Path(args.metadata)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {src}")
    if not meta.is_file():
        return fail("missing_metadata", f"Metadata file not found: {meta}")

    out = Path(args.output) if args.output else Path(
        str(src.with_suffix("")) + "_hdr10plus" + src.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [binary, "inject", "-i", str(src), "-j", str(meta), "-o", str(out)]

    rc, transcript = _run(cmd, "HDR10+ metadata injection")
    if rc != 0:
        return fail("hdr10plus_tool_failed",
                    f"hdr10plus_tool inject exited {rc}. "
                    + (transcript.splitlines()[-1] if transcript else ""))

    if not out.is_file():
        return fail("output_missing", f"Output not produced: {out}")

    emit("hdrplus_meta", action="inject", metadata_path=str(meta),
         output_path=str(out), output_size_bytes=out.stat().st_size)
    emit("complete", output=str(out), size_bytes=out.stat().st_size)
    return 0


def op_info(args: argparse.Namespace) -> int:
    binary = _find_hdr10plus_tool()
    if not binary:
        return fail("missing_hdr10plus_tool",
                    "hdr10plus_tool is not installed. Download from "
                    "github.com/quietvoid/hdr10plus_tool/releases.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {src}")

    cmd = [binary, "info", "-i", str(src)]
    if args.summary:
        cmd.append("--summary")

    rc, transcript = _run(cmd, "HDR10+ info")

    scene_count = _extract_field(transcript, r"Scene count:\s*(\d+)")
    max_scl = _extract_field(transcript, r"MaxSCL:\s*(\d+)")

    emit("hdrplus_meta", action="info", scene_count=scene_count,
         max_scl=max_scl, raw_output=transcript)
    emit("complete", output=str(src), size_bytes=src.stat().st_size,
         scene_count=scene_count)
    return 0


def _extract_field(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1) if m else None


def op_probe(args: argparse.Namespace) -> int:
    binary = _find_hdr10plus_tool()
    if not binary:
        log("warn", "hdr10plus_tool is not on PATH and not bundled.")
        emit("complete", output="", size_bytes=0,
             hdr10plus_tool_path=None, hdr10plus_tool_version=None)
        return 0

    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=15)
        version = (result.stdout or result.stderr or "").strip()
    except Exception as ex:
        version = f"probe-failed: {type(ex).__name__}"

    log("info", f"hdr10plus_tool at {binary} ({version})")
    emit("complete", output=binary, size_bytes=0,
         hdr10plus_tool_path=binary, hdr10plus_tool_version=version)
    return 0


def op_presets(_args: argparse.Namespace) -> int:
    presets = [
        {"name": "hdrplus-extract", "description": "Extract HDR10+ metadata from HEVC"},
        {"name": "hdrplus-inject", "description": "Inject HDR10+ metadata into HEVC"},
        {"name": "hdrplus-info", "description": "Show HDR10+ metadata summary"},
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
        prog="hdrplus-rpu",
        description="HDR10+ dynamic metadata pass-through sidecar for UCX")
    sub = p.add_subparsers(dest="op", required=True)

    # extract
    s = sub.add_parser("extract",
                       help="Extract HDR10+ metadata from HEVC")
    s.add_argument("--input", required=True, help="Input HEVC file")
    s.add_argument("--output", help="Output JSON (default: input.hdr10plus.json)")

    # inject
    s = sub.add_parser("inject",
                       help="Inject HDR10+ metadata into HEVC")
    s.add_argument("--input", required=True, help="Input HEVC file")
    s.add_argument("--metadata", required=True,
                   help="HDR10+ metadata JSON file")
    s.add_argument("--output",
                   help="Output HEVC file (default: input_hdr10plus.hevc)")

    # info
    s = sub.add_parser("info",
                       help="Show HDR10+ metadata summary")
    s.add_argument("--input", required=True, help="Input file")
    s.add_argument("--summary", action="store_true",
                   help="Show summary only")

    # probe
    sub.add_parser("probe", help="Check hdr10plus_tool availability")

    # presets
    sub.add_parser("presets", help="List built-in presets")

    ns = p.parse_args()

    ops = {
        "extract": op_extract,
        "inject": op_inject,
        "info": op_info,
        "probe": op_probe,
        "presets": op_presets,
    }
    return ops[ns.op](ns)


if __name__ == "__main__":
    raise SystemExit(main())
