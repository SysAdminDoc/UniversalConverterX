"""Industrial IoT bus sidecar.

Probe / convert industrial automation protocols and configurations:

  * OPC UA NodeSet XML (.xml) -> JSON node graph
  * Modbus TCP / RTU register map JSON -> CSV
  * BACnet device export (.bdp, .bv) -> JSON probe
  * KNX ETS project (.knxproj, ZIP-based) -> JSON probe
  * EDS (Electronic Data Sheet) for DeviceNet / EtherNet-IP -> JSON

Operations:
  opcua-nodeset-info  OPC UA NodeSet XML -> JSON node summary.
  modbus-map-to-csv   Modbus register map JSON -> CSV.
  knxproj-info        KNX ETS .knxproj ZIP -> JSON probe.
  eds-to-json         EDS file -> JSON sections.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


_NS_RE = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str: return _NS_RE.sub("", tag)


# ── OPC UA NodeSet ─────────────────────────────────────────────────────

def op_opcua_nodeset_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"NodeSet file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            counts: dict[str, int] = {}
            sample: list[dict] = []
            for elem in root:
                tag = _strip_ns(elem.tag)
                if not tag.startswith("UA"): continue
                counts[tag] = counts.get(tag, 0) + 1
                if len(sample) < 50:
                    sample.append({
                        "kind": tag,
                        "node_id": elem.get("NodeId", ""),
                        "browse_name": elem.get("BrowseName", ""),
                        "display_name": "".join(
                            d.text or "" for d in elem
                            if _strip_ns(d.tag) == "DisplayName"),
                    })
            namespace_uris = []
            for ns in root.iter():
                if _strip_ns(ns.tag) == "Uri":
                    namespace_uris.append((ns.text or "").strip())
            info = {
                "file": str(src), "size_bytes": src.stat().st_size,
                "namespaces": namespace_uris[:20],
                "counts": counts,
                "sample": sample,
            }
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".opcua.json")
        out_path.write_text(json.dumps(info, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("iot_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="opcua-nodeset",
             nodes=sum(counts.values()))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Modbus register map -> CSV ────────────────────────────────────────

def op_modbus_map_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Modbus map(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        registers = data.get("registers", []) if isinstance(data, dict) else data
        rows: list[dict] = []
        for r in registers:
            rows.append({
                "name": r.get("name", ""),
                "function_code": r.get("function_code", r.get("fc", "")),
                "address": r.get("address", r.get("addr", "")),
                "type": r.get("type", r.get("dataType", "")),
                "scale": r.get("scale", ""),
                "unit": r.get("unit", ""),
                "description": r.get("description", r.get("desc", "")),
            })
        out_path = out_dir / (src.stem + ".modbus.csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["name", "function_code",
                                                 "address", "type", "scale",
                                                 "unit", "description"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("iot_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="modbus-map", registers=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── KNX ETS .knxproj ──────────────────────────────────────────────────

def op_knxproj_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".knxproj file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            with zipfile.ZipFile(src) as z:
                names = z.namelist()
                # Find first project XML
                proj_xml_name = next((n for n in names
                                       if n.lower().endswith("project.xml")
                                       or n.lower().endswith("0.xml")), None)
                proj_info: dict = {}
                if proj_xml_name:
                    try:
                        text = z.read(proj_xml_name).decode("utf-8",
                                                              errors="replace")
                        root = ET.fromstring(text)
                        proj_info["addresses"] = sum(
                            1 for e in root.iter()
                            if _strip_ns(e.tag) == "GroupAddress")
                        proj_info["devices"] = sum(
                            1 for e in root.iter()
                            if _strip_ns(e.tag) == "DeviceInstance")
                    except Exception as ex:
                        proj_info["parse_error"] = str(ex)
                probes.append({
                    "file": str(src), "size_bytes": src.stat().st_size,
                    "entry_count": len(names),
                    "project": proj_info,
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("iot_doc",
             input=str(src), output="",
             size_bytes=0, format="probe", source="knxproj")
    out_path = out_dir / "knxproj-info.json"
    out_path.write_text(json.dumps(probes, indent=2, default=str),
                        encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── EDS (DeviceNet / EtherNet-IP) ─────────────────────────────────────

_EDS_SECTION_RE = re.compile(r"^\[([^\]]+)\]\s*$", re.MULTILINE)
_EDS_KV_RE = re.compile(
    r"^([A-Za-z][\w\s]*?)\s*=\s*(.+?)(?:;[^;]*)?$",
    re.MULTILINE)


def op_eds_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"EDS file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        sections: dict[str, dict] = {}
        cur_section: str | None = None
        for line in text.splitlines():
            sm = _EDS_SECTION_RE.match(line)
            if sm:
                cur_section = sm.group(1).strip()
                sections[cur_section] = {}
                continue
            if not cur_section: continue
            kv = _EDS_KV_RE.match(line)
            if kv:
                sections[cur_section][kv.group(1).strip()] = kv.group(2).strip().strip('"')
        out_path = out_dir / (src.stem + ".eds.json")
        out_path.write_text(json.dumps(sections, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        emit("iot_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="eds", sections=len(sections))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="iotbus-sidecar",
                                description="Industrial IoT bus protocol probes.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("opcua-nodeset-info",  "OPC UA NodeSet XML -> JSON"),
        ("modbus-map-to-csv",   "Modbus register map JSON -> CSV"),
        ("knxproj-info",        "KNX ETS .knxproj probe"),
        ("eds-to-json",         "EDS DeviceNet / EtherNet-IP -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "opcua-nodeset-info":  return op_opcua_nodeset_info(args)
        if args.op == "modbus-map-to-csv":   return op_modbus_map_to_csv(args)
        if args.op == "knxproj-info":        return op_knxproj_info(args)
        if args.op == "eds-to-json":         return op_eds_to_json(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
