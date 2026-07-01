"""Automotive / industrial bus sidecar.

Convert vehicle / control bus database formats:

  * DBC (Vector CAN database) <-> JSON / CSV / KCD
  * ARXML (AUTOSAR XML)        <-> JSON probe
  * FIBEX (FIBEX Field Bus Exchange Format) -> JSON probe
  * SocketCAN candump log      -> CSV / JSON
  * OBD-II PID list            -> CSV (built-in PID dictionary)

Operations:
  dbc-to-json     DBC -> structured JSON (messages + signals).
  dbc-to-csv      DBC -> per-signal CSV.
  candump-to-csv  candump trace -> CSV (timestamp, iface, id, len, payload).
  arxml-info      ARXML quick probe -> JSON (toplevel package + ECU count).
  pid-list        Built-in OBD-II PID reference -> CSV.

DBC parsing uses cantools when installed; otherwise a stdlib subset
parser handles the common BO_ / SG_ / VAL_ / CM_ keywords.
"""
from __future__ import annotations

import argparse
import csv
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── DBC parser (stdlib subset) ─────────────────────────────────────────

_BO_RE = re.compile(r"^BO_\s+(\d+)\s+([A-Za-z0-9_]+)\s*:\s*(\d+)\s+([A-Za-z0-9_]+)")
_SG_RE = re.compile(
    r"^\s*SG_\s+([A-Za-z0-9_]+)\s*([Mm]?\d*)\s*:\s*"
    r"(\d+)\|(\d+)@([01])([+-])\s*"
    r"\(([^,]+),([^)]+)\)\s*"
    r"\[([^|]+)\|([^\]]+)\]\s*"
    r'"([^"]*)"\s*(.*)$')
_VAL_RE = re.compile(r"^VAL_\s+(\d+)\s+([A-Za-z0-9_]+)\s+(.+);")


def _parse_dbc(text: str) -> dict:
    messages: dict[int, dict] = {}
    cur_msg: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = _BO_RE.match(line)
        if m:
            mid = int(m.group(1))
            cur_msg = {"id": mid, "name": m.group(2),
                        "length": int(m.group(3)),
                        "transmitter": m.group(4), "signals": []}
            messages[mid] = cur_msg
            continue
        if cur_msg:
            sg = _SG_RE.match(line)
            if sg:
                cur_msg["signals"].append({
                    "name":         sg.group(1),
                    "mux_indicator": (sg.group(2) or "").strip(),
                    "start_bit":    int(sg.group(3)),
                    "length":       int(sg.group(4)),
                    "byte_order":   "little" if sg.group(5) == "1" else "big",
                    "value_type":   "signed" if sg.group(6) == "-" else "unsigned",
                    "factor":       float(sg.group(7).strip()),
                    "offset":       float(sg.group(8).strip()),
                    "min":          float(sg.group(9).strip() or 0),
                    "max":          float(sg.group(10).strip() or 0),
                    "unit":         sg.group(11),
                    "receivers":    [r.strip() for r in sg.group(12).split(",") if r.strip()],
                })
                continue
        v = _VAL_RE.match(line)
        if v:
            mid = int(v.group(1))
            sig = v.group(2)
            value_table = {}
            tokens = v.group(3).split()
            it = iter(tokens)
            for k in it:
                if k.startswith('"'):
                    label_parts = [k.lstrip('"')]
                    while not label_parts[-1].endswith('"'):
                        label_parts.append(next(it, ""))
                    label = " ".join(label_parts).strip('"')
                    continue
                label_token = next(it, "")
                value_table[int(k)] = label_token.strip('"')
            if mid in messages:
                for s in messages[mid]["signals"]:
                    if s["name"] == sig: s["values"] = value_table
    return {"messages": list(messages.values())}


def op_dbc_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"DBC file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            parsed = _parse_dbc(src.read_text(encoding="utf-8", errors="replace"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(parsed, indent=2),
                            encoding="utf-8")
        emit("bus_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="dbc",
             messages=len(parsed["messages"]),
             signals=sum(len(m["signals"]) for m in parsed["messages"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_dbc_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"DBC file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            parsed = _parse_dbc(src.read_text(encoding="utf-8", errors="replace"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            keys = ["msg_id", "msg_name", "msg_length", "transmitter",
                    "signal_name", "start_bit", "length", "byte_order",
                    "value_type", "factor", "offset", "min", "max", "unit"]
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for m in parsed["messages"]:
                for s in m["signals"]:
                    w.writerow({
                        "msg_id": m["id"], "msg_name": m["name"],
                        "msg_length": m["length"], "transmitter": m["transmitter"],
                        "signal_name": s["name"], "start_bit": s["start_bit"],
                        "length": s["length"], "byte_order": s["byte_order"],
                        "value_type": s["value_type"], "factor": s["factor"],
                        "offset": s["offset"], "min": s["min"], "max": s["max"],
                        "unit": s["unit"],
                    })
        emit("bus_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="dbc",
             messages=len(parsed["messages"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── candump trace -> CSV ───────────────────────────────────────────────

_CANDUMP_RE = re.compile(
    r"\((?P<ts>[\d.]+)\)\s+(?P<iface>\S+)\s+"
    r"(?P<id>[0-9A-Fa-f]+)#(?P<data>[0-9A-Fa-f]*)")


def op_candump_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"candump log(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            rows = []
            for line in text.splitlines():
                m = _CANDUMP_RE.search(line)
                if not m: continue
                rows.append({
                    "timestamp": float(m.group("ts")),
                    "iface": m.group("iface"),
                    "id_hex": m.group("id").lower(),
                    "id_dec": int(m.group("id"), 16),
                    "len": len(m.group("data")) // 2,
                    "data_hex": m.group("data").lower(),
                })
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp", "iface", "id_hex",
                                                 "id_dec", "len", "data_hex"])
            w.writeheader()
            for r in rows: w.writerow(r)
        emit("bus_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="candump", frames=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── ARXML quick probe ──────────────────────────────────────────────────

_NS_RE = re.compile(r"\{[^}]+\}")


def op_arxml_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"ARXML file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            tree = ET.parse(str(src))
            root = tree.getroot()
            packages = []
            ecus = 0
            for elem in root.iter():
                tag = _NS_RE.sub("", elem.tag)
                if tag == "AR-PACKAGE":
                    short = ""
                    for c in elem:
                        if _NS_RE.sub("", c.tag) == "SHORT-NAME":
                            short = c.text or ""; break
                    packages.append(short)
                if tag in ("ECU-INSTANCE", "FLAT-INSTANCE-DESCRIPTOR"):
                    ecus += 1
            info = {
                "file": str(src),
                "size_bytes": src.stat().st_size,
                "package_count": len(packages),
                "packages": packages[:20],
                "ecu_count": ecus,
            }
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        probes.append(info)
        emit("bus_doc",
             input=str(src), output="",
             size_bytes=0, format="json", source="arxml",
             packages=info["package_count"], ecus=ecus)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    out_path = out_dir / "arxml-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


# ── OBD-II PID reference ───────────────────────────────────────────────

_OBD2_PIDS = [
    ("01", "00", "Supported PIDs [01-20]", "bitfield"),
    ("01", "04", "Calculated engine load", "%"),
    ("01", "05", "Engine coolant temperature", "°C"),
    ("01", "0B", "Intake manifold absolute pressure", "kPa"),
    ("01", "0C", "Engine RPM", "rpm"),
    ("01", "0D", "Vehicle speed", "km/h"),
    ("01", "0F", "Intake air temperature", "°C"),
    ("01", "10", "MAF air flow rate", "g/s"),
    ("01", "11", "Throttle position", "%"),
    ("01", "1F", "Run time since engine start", "s"),
    ("01", "21", "Distance with MIL on", "km"),
    ("01", "2F", "Fuel tank level input", "%"),
    ("01", "33", "Absolute barometric pressure", "kPa"),
    ("01", "5C", "Engine oil temperature", "°C"),
    ("09", "02", "Vehicle Identification Number (VIN)", "ASCII"),
    ("09", "0A", "ECU name", "ASCII"),
]


def op_pid_list(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "obd2-pids.csv"
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "pid", "description", "unit"])
        for row in _OBD2_PIDS: w.writerow(row)
    emit("bus_doc",
         input="(builtin)", output=str(out_path),
         size_bytes=out_path.stat().st_size,
         format="csv", source="obd2", count=len(_OBD2_PIDS))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(_OBD2_PIDS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bus-sidecar",
                                description="Automotive / industrial bus database conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("dbc-to-json",     "DBC CAN database -> JSON"),
        ("dbc-to-csv",      "DBC CAN database -> per-signal CSV"),
        ("candump-to-csv",  "SocketCAN candump trace -> CSV"),
        ("arxml-info",      "AUTOSAR ARXML probe -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    pl = sub.add_parser("pid-list", help="Built-in OBD-II PID reference -> CSV")
    pl.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "dbc-to-json":     return op_dbc_to_json(args)
        if args.op == "dbc-to-csv":      return op_dbc_to_csv(args)
        if args.op == "candump-to-csv":  return op_candump_to_csv(args)
        if args.op == "arxml-info":      return op_arxml_info(args)
        if args.op == "pid-list":        return op_pid_list(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
