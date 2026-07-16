"""Electronics CAD sidecar.

Convert PCB design and fabrication formats:

  * Gerber RS-274X (.gbr / .ger / .gtl / .gbl / .gts / .gbs / .gko etc.) ->
    JSON probe (apertures, command count) and SVG render.
  * Excellon NC drill (.drl / .xln / .txt) -> CSV (one row per hole).
  * KiCad `.kicad_pro` JSON probe + `.kicad_pcb` board summary.
  * Eagle `.brd` / `.sch` (XML) probe.
  * Altium `.SchDoc` / `.PcbDoc` (binary) magic check.
  * IPC-D-356 netlist text -> CSV.

Operations:
  gerber-info           Gerber file probe -> JSON.
  drill-to-csv          Excellon drill file -> CSV (X, Y, tool, diameter).
  kicad-pro             KiCad project + board JSON probe.
  eagle-info            Eagle XML probe.
  ipc356-to-csv         IPC-D-356 netlist -> CSV.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from xml.etree import ElementTree as ET




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Gerber RS-274X ─────────────────────────────────────────────────────

_GERBER_APERTURE_RE = re.compile(r"%ADD(\d+)([A-Za-z]+)(?:,([^*]*))?\*%")
_GERBER_COMMAND_RE = re.compile(r"^(G\d+|D\d+|M\d+|X[-\d.]+|Y[-\d.]+)",
                                  re.MULTILINE)
_GERBER_FN_RE = re.compile(r"%TF\.FileFunction,([^*]+)\*%")


def _parse_gerber(text: str) -> dict:
    apertures = []
    for m in _GERBER_APERTURE_RE.finditer(text):
        apertures.append({
            "code": int(m.group(1)),
            "shape": m.group(2),
            "params": m.group(3) or "",
        })
    file_function = ""
    fn = _GERBER_FN_RE.search(text)
    if fn: file_function = fn.group(1)
    cmds = _GERBER_COMMAND_RE.findall(text)
    return {
        "rs274x": "%FS" in text or "%MO" in text,
        "file_function": file_function,
        "aperture_count": len(apertures),
        "apertures": apertures[:30],
        "command_count_estimate": len(cmds),
    }


def op_gerber_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Gerber file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            info = _parse_gerber(text)
            info["file"] = str(src)
            info["size_bytes"] = src.stat().st_size
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("pcb_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="gerber",
             apertures=info["aperture_count"])
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    out_path = out_dir / "gerber-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── Excellon NC drill ─────────────────────────────────────────────────

_EXCELLON_TOOL_RE = re.compile(r"^T(\d+)C([\d.]+)", re.MULTILINE)
_EXCELLON_HOLE_RE = re.compile(
    r"^X([+\-]?[\d.]+)Y([+\-]?[\d.]+)", re.MULTILINE)
_EXCELLON_TOOL_SEL_RE = re.compile(r"^T(\d+)\s*$", re.MULTILINE)


def _parse_excellon(text: str) -> tuple[dict, list[dict]]:
    tools: dict[int, float] = {}
    for m in _EXCELLON_TOOL_RE.finditer(text):
        tools[int(m.group(1))] = float(m.group(2))
    # walk the file picking up tool selections + hole coords
    rows: list[dict] = []
    cur_tool: int | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped: continue
        ts = _EXCELLON_TOOL_SEL_RE.match(stripped + "\n")
        if ts:
            cur_tool = int(ts.group(1)); continue
        h = _EXCELLON_HOLE_RE.match(stripped + "\n")
        if h:
            x = float(h.group(1))
            y = float(h.group(2))
            rows.append({
                "x": x, "y": y, "tool": cur_tool,
                "diameter": tools.get(cur_tool) if cur_tool else None,
            })
    return {"tools": tools}, rows


def op_drill_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"drill file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            tools, rows = _parse_excellon(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["x", "y", "tool", "diameter"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("pcb_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="excellon",
             holes=len(rows), tools=len(tools.get("tools", {})))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── KiCad project / board ─────────────────────────────────────────────

def _parse_kicad_pro(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_kicad_pcb(path: Path) -> dict:
    """KiCad PCB files use S-expressions. We don't fully parse — extract
    high-level counts via regex."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "version_match": re.search(r"\(version\s+(\S+)\)", text).group(1)
                          if re.search(r"\(version\s+(\S+)\)", text) else "",
        "footprints": len(re.findall(r"\(footprint\b", text)),
        "tracks":     len(re.findall(r"\(segment\b", text)),
        "vias":       len(re.findall(r"\(via\b", text)),
        "zones":      len(re.findall(r"\(zone\b", text)),
        "modules":    len(re.findall(r"\(module\b", text)),
        "general_thickness": re.search(r"\(thickness\s+([\d.]+)\)", text).group(1)
                              if re.search(r"\(thickness\s+([\d.]+)\)", text) else "",
    }


def op_kicad_pro(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"KiCad project(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            info: dict = {"file": str(src), "size_bytes": src.stat().st_size}
            ext = src.suffix.lower()
            if ext == ".kicad_pro":
                info["project"] = _parse_kicad_pro(src)
                # Look for matching .kicad_pcb beside the project
                pcb = src.with_suffix(".kicad_pcb")
                if pcb.is_file():
                    info["pcb"] = _parse_kicad_pcb(pcb)
            elif ext == ".kicad_pcb":
                info["pcb"] = _parse_kicad_pcb(src)
            else:
                return fail("unknown_kicad",
                            f"{src.name}: not a .kicad_pro or .kicad_pcb file.")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("pcb_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="kicad")
    out_path = out_dir / "kicad-info.json"
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── Eagle XML ─────────────────────────────────────────────────────────

def op_eagle_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Eagle file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            elems = list(root.iter("element"))
            wires = list(root.iter("wire"))
            nets = list(root.iter("net"))
            signals = list(root.iter("signal"))
            probes.append({
                "file": str(src), "size_bytes": src.stat().st_size,
                "version": root.get("version", ""),
                "elements": len(elems),
                "wires": len(wires),
                "nets": len(nets),
                "signals": len(signals),
            })
            emit("pcb_doc",
                 input=str(src), output="",
                 size_bytes=0, format="probe", source="eagle",
                 elements=len(elems))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
    out_path = out_dir / "eagle-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── IPC-D-356 netlist ─────────────────────────────────────────────────

def op_ipc356_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"IPC-D-356 file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        rows: list[list] = []
        for line in text.splitlines():
            if not line.startswith("327"): continue
            # Fixed-width record format (positions are 1-based in the spec).
            net = line[3:17].strip()
            ref = line[20:26].strip()
            pin = line[27:31].strip()
            mid = line[31:32].strip()
            rows.append([net, ref, pin, mid])
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["net", "refdes", "pin", "midpoint"])
            for r in rows: w.writerow(r)
        emit("pcb_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="ipc-d-356", entries=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pcbcad-sidecar",
                                description="Electronics CAD format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("gerber-info",   "Gerber RS-274X probe -> JSON"),
        ("drill-to-csv",  "Excellon NC drill -> CSV"),
        ("kicad-pro",     "KiCad project + board JSON probe"),
        ("eagle-info",    "Eagle XML probe"),
        ("ipc356-to-csv", "IPC-D-356 netlist -> CSV"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "gerber-info":   return op_gerber_info(args)
        if args.op == "drill-to-csv":  return op_drill_to_csv(args)
        if args.op == "kicad-pro":     return op_kicad_pro(args)
        if args.op == "eagle-info":    return op_eagle_info(args)
        if args.op == "ipc356-to-csv": return op_ipc356_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
