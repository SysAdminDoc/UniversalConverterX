"""Subtitle / closed-caption edge cases sidecar.

Extends `subkit` (SAMI/TTML/SCC/STL/MicroDVD/LRC/SBV) with the broadcast +
streaming-platform niches:

  * CEA-608 / CEA-708 closed captions    via ccextractor (CLI shellout)
  * iTT (iTunes Timed Text)              XML, similar to TTML
  * SMIL (SMIL 3.0)                      XML scaffold for media
  * Karaoke ASS w/ time-aligned tags    -> LRC

Operations:
  cea-to-srt    Extract CEA-608/708 captions from MP4/TS via ccextractor.
  itt-to-srt    iTunes Timed Text -> SRT.
  itt-to-vtt    iTT -> WebVTT.
  ass-to-lrc    Time-aligned ASS karaoke -> LRC karaoke.
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
from xml.etree import ElementTree as ET


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".exe")


# ── CEA-608 / CEA-708 via ccextractor ─────────────────────────────────

def op_cea_to_srt(args: argparse.Namespace) -> int:
    cce = _find("ccextractor") or _find("ccextractorwin")
    if not cce:
        return fail("missing_ccextractor",
                    "ccextractor not found. Install from https://ccextractor.org "
                    "or via `apt install ccextractor` / `choco install ccextractor`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Video file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".srt")
        cmd = [cce, str(src), "-o", str(out_path), "-out=srt"]
        if args.line == "708": cmd.append("-svc=1")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("ccextractor_failed", f"{src.name}: rc={proc.returncode}")

        emit("subtitle_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             format="srt", source=f"cea-{args.line}")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── iTT (iTunes Timed Text) ───────────────────────────────────────────

def _ts_to_srt(ts: str) -> str:
    """Accept HH:MM:SS.fff or HH:MM:SS,fff or seconds-as-decimal."""
    if "," in ts: ts = ts.replace(",", ".")
    if ":" in ts:
        parts = ts.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return f"{int(h):02d}:{int(m):02d}:{int(float(s)):02d},{int(round((float(s) % 1) * 1000)):03d}"
    secs = float(ts)
    h = int(secs // 3600); m = int((secs % 3600) // 60)
    s = int(secs % 60); ms = int((secs % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _itt_to_srt(text: str) -> str:
    tree = ET.fromstring(text)
    cues = []
    for n, p in enumerate(tree.iter(), 1):
        if not p.tag.endswith("p"): continue
        begin = p.attrib.get("begin"); end = p.attrib.get("end")
        if not begin or not end: continue
        body = "".join(p.itertext()).strip()
        if not body: continue
        cues.append(f"{n}\n{_ts_to_srt(begin)} --> {_ts_to_srt(end)}\n{body}\n")
    return "\n".join(cues)


def _itt_to_vtt(text: str) -> str:
    srt = _itt_to_srt(text)
    return "WEBVTT\n\n" + srt.replace(",", ".")


def op_itt_to_srt(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"iTT file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target_ext = ".vtt" if args.vtt else ".srt"

    total = len(inputs)
    for i, src in enumerate(inputs):
        text = src.read_text(encoding="utf-8", errors="replace")
        try:
            converted = _itt_to_vtt(text) if args.vtt else _itt_to_srt(text)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + target_ext)
        out_path.write_text(converted, encoding="utf-8")
        emit("subtitle_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="vtt" if args.vtt else "srt", source="itt")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── ASS karaoke -> LRC ────────────────────────────────────────────────

_K_TAG = re.compile(r"\\k(\d+)", re.IGNORECASE)


def op_ass_to_lrc(args: argparse.Namespace) -> int:
    try:
        import pysubs2
    except ImportError as ex:
        return fail("missing_pysubs2",
                    f"pysubs2 not installed: {ex}. `pip install pysubs2`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"ASS file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        subs = pysubs2.load(str(src))
        lines: list[str] = []
        for ev in subs:
            ms = ev.start
            mins = ms // 60000
            secs = (ms % 60000) // 1000
            cs = (ms % 1000) // 10
            text = ev.plaintext or ev.text or ""
            text = _K_TAG.sub("", text).strip()
            if not text: continue
            lines.append(f"[{int(mins):02d}:{int(secs):02d}.{int(cs):02d}]{text}")
        out_path = out_dir / (src.stem + ".lrc")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        emit("subtitle_extra",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="lrc", source="ass-karaoke")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="subextra-sidecar",
                                description="Subtitle edge cases (CEA-608/708, iTT, ASS karaoke).")
    sub = p.add_subparsers(dest="op", required=True)
    a = sub.add_parser("cea-to-srt", help="Extract CEA-608/708 captions from MP4/TS.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")
    a.add_argument("--line", default="608", choices=["608", "708"])

    b = sub.add_parser("itt-to-srt", help="iTunes Timed Text -> SRT (or VTT).")
    b.add_argument("--input", nargs="+", required=True)
    b.add_argument("--output-dir", required=True, dest="output_dir")
    b.add_argument("--vtt", action="store_true",
                   help="Emit WebVTT instead of SRT.")

    c = sub.add_parser("ass-to-lrc", help="Karaoke ASS -> LRC.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "cea-to-srt":  return op_cea_to_srt(args)
        if args.op == "itt-to-srt":  return op_itt_to_srt(args)
        if args.op == "ass-to-lrc":  return op_ass_to_lrc(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
