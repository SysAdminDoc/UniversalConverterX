"""Video post-production timeline sidecar.

Translate professional video editing timelines between formats. Most NLE
projects use proprietary binary formats, but their interchange XMLs are
open and convertible:

  * FCPXML 1.10/1.11 (Final Cut Pro)
  * AAF (Advanced Authoring Format)
  * OpenTimelineIO `.otio` (Pixar / open standard)
  * Premiere Pro `.prproj` (XML inside .gz)
  * DaVinci Resolve `.drp` (binary; metadata-only probe)
  * EDL (Edit Decision List, CMX 3600)
  * XML (Final Cut Pro 7 / "old" XML)

Operations:
  fcpxml-to-otio       FCPXML -> OpenTimelineIO via `otioconvert`.
  otio-to-fcpxml       OTIO -> FCPXML.
  fcpxml-info          FCPXML probe -> JSON.
  prproj-info          Premiere Pro .prproj XML probe.
  edl-to-csv           CMX 3600 EDL -> CSV.
  edl-info             EDL probe.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from xml.etree import ElementTree as ET




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── FCPXML probe ──────────────────────────────────────────────────────

def _parse_fcpxml(path: Path) -> dict:
    tree = ET.parse(str(path))
    root = tree.getroot()
    info: dict = {"version": root.get("version", "")}
    resources = root.find("resources")
    formats = []
    assets = []
    if resources is not None:
        for fmt in resources.findall("format"):
            formats.append({
                "id": fmt.get("id"), "name": fmt.get("name", ""),
                "width": fmt.get("width", ""), "height": fmt.get("height", ""),
                "frameDuration": fmt.get("frameDuration", ""),
            })
        for ast in resources.findall("asset"):
            assets.append({
                "id": ast.get("id"), "name": ast.get("name", ""),
                "src": ast.get("src", ""), "duration": ast.get("duration", ""),
                "format": ast.get("format", ""),
            })
    library = root.find("library")
    events = library.findall("event") if library is not None else []
    sequences = []
    for e in events:
        for proj in e.findall("project"):
            for seq in proj.findall("sequence"):
                clips = sum(1 for _ in seq.iter("clip"))
                sequences.append({
                    "project": proj.get("name", ""),
                    "duration": seq.get("duration", ""),
                    "format": seq.get("format", ""),
                    "clip_count": clips,
                })
    info["formats"] = formats
    info["assets"] = assets[:50]
    info["asset_count"] = len(assets)
    info["sequences"] = sequences
    return info


def op_fcpxml_info(args): return _probe_loop(args, _parse_fcpxml, "fcpxml")


# ── otioconvert ────────────────────────────────────────────────────────

def op_fcpxml_to_otio(args: argparse.Namespace) -> int:
    return _otio_convert(args, "fcpxml", "otio")


def op_otio_to_fcpxml(args: argparse.Namespace) -> int:
    return _otio_convert(args, "otio", "fcpxml")


def _otio_convert(args, from_ext: str, to_ext: str) -> int:
    cli = shutil.which("otioconvert") or shutil.which("otioconvert.exe")
    if not cli: return fail("missing_dep",
                              "otioconvert not on PATH (`pip install OpenTimelineIO`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"timeline file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + to_ext)
        cmd = [cli, "-i", str(src), "-o", str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: otioconvert exit {proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()}")
        emit("vidpost_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=to_ext, source=from_ext)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Premiere .prproj ──────────────────────────────────────────────────

def _parse_prproj(path: Path) -> dict:
    """Premiere Pro projects are gzipped XML. Read just the first 2 MB
    after gunzip — projects can be hundreds of MB, but the structural
    metadata sits early."""
    try:
        with gzip.open(path, "rb") as f:
            buf = f.read(2 * 1024 * 1024)
    except OSError:
        # Some .prproj files are plain XML
        buf = path.read_bytes()[:2 * 1024 * 1024]
    text = buf.decode("utf-8", errors="replace")
    info = {
        "size_bytes": path.stat().st_size,
        "format": "prproj",
    }
    version_m = re.search(r'Version="([^"]+)"', text)
    if version_m: info["version"] = version_m.group(1)
    sequences = re.findall(r"<Sequence\b[^>]*>", text)
    info["sequence_count_estimate"] = len(sequences)
    bins = re.findall(r"<Bin\b[^>]*>", text)
    info["bin_count_estimate"] = len(bins)
    clips = re.findall(r"<ClipProjectItem\b", text)
    info["clip_count_estimate"] = len(clips)
    return info


def op_prproj_info(args): return _probe_loop(args, _parse_prproj, "prproj")


# ── CMX 3600 EDL ──────────────────────────────────────────────────────

_EDL_EVENT_RE = re.compile(
    r"^(?P<num>\d{3})\s+(?P<reel>\S+)\s+(?P<channel>\S+)\s+"
    r"(?P<trans>\S+)\s+(?P<tcin>\d{2}:\d{2}:\d{2}:\d{2})\s+"
    r"(?P<tcout>\d{2}:\d{2}:\d{2}:\d{2})\s+"
    r"(?P<rin>\d{2}:\d{2}:\d{2}:\d{2})\s+"
    r"(?P<rout>\d{2}:\d{2}:\d{2}:\d{2})")


def _parse_edl(text: str) -> list[dict]:
    rows: list[dict] = []
    for line in text.splitlines():
        m = _EDL_EVENT_RE.match(line.strip())
        if m: rows.append(m.groupdict())
    return rows


def op_edl_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".edl file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            rows = _parse_edl(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        keys = ["num", "reel", "channel", "trans", "tcin", "tcout", "rin", "rout"]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("vidpost_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="cmx-3600-edl", events=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_edl_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".edl file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        text = src.read_text(encoding="utf-8", errors="replace")
        rows = _parse_edl(text)
        title_m = re.search(r"^TITLE:\s*(.+)$", text, re.MULTILINE)
        fcm_m = re.search(r"^FCM:\s*(.+)$", text, re.MULTILINE)
        probes.append({
            "file": str(src), "size_bytes": src.stat().st_size,
            "title": title_m.group(1).strip() if title_m else "",
            "fcm": fcm_m.group(1).strip() if fcm_m else "",
            "events": len(rows),
        })
        emit("vidpost_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="cmx-3600-edl",
             events=len(rows))
    out_path = out_dir / "edl-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def _probe_loop(args, parser, source: str) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"timeline file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            info = parser(src)
            info["file"] = str(src)
            info["size_bytes"] = src.stat().st_size
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("vidpost_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source=source)
    out_path = out_dir / f"{source}-info.json"
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vidpost-sidecar",
                                description="Video post-production timeline conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("fcpxml-to-otio",  "FCPXML -> OpenTimelineIO via otioconvert"),
        ("otio-to-fcpxml",  "OpenTimelineIO -> FCPXML"),
        ("fcpxml-info",     "FCPXML probe -> JSON"),
        ("prproj-info",     "Premiere Pro .prproj probe -> JSON"),
        ("edl-to-csv",      "CMX 3600 EDL -> CSV"),
        ("edl-info",        "CMX 3600 EDL probe"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "fcpxml-to-otio": return op_fcpxml_to_otio(args)
        if args.op == "otio-to-fcpxml": return op_otio_to_fcpxml(args)
        if args.op == "fcpxml-info":    return op_fcpxml_info(args)
        if args.op == "prproj-info":    return op_prproj_info(args)
        if args.op == "edl-to-csv":     return op_edl_to_csv(args)
        if args.op == "edl-info":       return op_edl_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
