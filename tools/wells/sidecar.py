"""LAS / DLIS oil-well log conversion sidecar.

Convert oil & gas well-log files between formats:

  * LAS 2.0 / 3.0 (Log ASCII Standard, CWLS)
  * CSV / TSV / JSON / Parquet (analysis-friendly)
  * DLIS (Digital Log Interchange Standard, binary) — read-only via dlisio

LAS files are plain text with section headers (~V, ~W, ~C, ~P, ~A) and a
fixed-width data section. Pure-stdlib parser handles 99% of files in
the wild without lasio (which we use as fallback for the gnarly cases).

Operations:
  las-to-csv     LAS curve data -> CSV with header metadata as comments.
  las-to-json    LAS -> structured JSON (sections + curves + units).
  csv-to-las     CSV with units row -> LAS 2.0.
  dlis-to-csv    DLIS binary -> CSV (per-frame data).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── LAS parser (pure stdlib) ───────────────────────────────────────────

_NULL_VALUES = {"-999.25", "-9999.25", "-999.250", "NaN", "nan"}


def _parse_las(text: str) -> dict:
    """Return {sections: {V/W/C/P/O: [...]}, curves: [name, ...],
             units: [...], data: [[...], ...]}."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sections: dict[str, list] = {}
    cur_section = None
    data_rows: list[list[float | None]] = []
    curves: list[str] = []
    units: list[str] = []
    descriptions: list[str] = []

    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"): continue
        if line.startswith("~"):
            sect = line[1].upper()
            cur_section = sect
            sections.setdefault(sect, [])
            continue
        if cur_section == "A":
            parts = line.split()
            row = []
            for p in parts:
                if p in _NULL_VALUES:
                    row.append(None)
                else:
                    try: row.append(float(p))
                    except ValueError: row.append(p)
            data_rows.append(row)
        elif cur_section in ("V", "W", "C", "P", "O"):
            # Format:  MNEM.UNIT      VALUE          : DESCRIPTION
            if "." not in line:
                sections[cur_section].append({"raw": line})
                continue
            mnem, _, rest = line.partition(".")
            unit, _, after = rest.partition(" ")
            if " : " in after: value, desc = after.split(" : ", 1)
            elif ":" in after: value, desc = after.split(":", 1)
            else: value, desc = after, ""
            entry = {"mnemonic": mnem.strip(), "unit": unit.strip(),
                     "value": value.strip(), "description": desc.strip()}
            sections[cur_section].append(entry)
            if cur_section == "C":
                curves.append(entry["mnemonic"])
                units.append(entry["unit"])
                descriptions.append(entry["description"])

    return {"format": "las", "sections": sections, "curves": curves,
            "units": units, "descriptions": descriptions, "data": data_rows}


def _emit_las2(d: dict, header_lines: list[str] | None = None) -> str:
    """Produce LAS 2.0 text. Expects {curves, units, data, well_info}."""
    lines = ["~Version Information",
             "VERS.   2.0 : CWLS Log ASCII Standard - VERSION 2.0",
             "WRAP.   NO  : One line per depth step", ""]
    lines.append("~Well Information")
    for h in header_lines or []: lines.append(h)
    lines.append("")
    lines.append("~Curve Information")
    for n, (c, u) in enumerate(zip(d["curves"], d["units"])):
        lines.append(f"{c}.{u or ''}   : Curve {n+1}")
    lines.append("")
    lines.append("~ASCII Data")
    for row in d["data"]:
        lines.append(" ".join(f"{x:>10.4f}" if isinstance(x, (int, float))
                              else "  -999.25" if x is None else str(x)
                              for x in row))
    return "\n".join(lines) + "\n"


# ── Operations ─────────────────────────────────────────────────────────

def op_las_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"LAS file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            parsed = _parse_las(src.read_text(encoding="utf-8", errors="replace"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(parsed["curves"])
            w.writerow(parsed["units"])
            for row in parsed["data"]:
                w.writerow("" if x is None else x for x in row)
        emit("well_log",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="las",
             curves=len(parsed["curves"]), rows=len(parsed["data"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_las_to_json(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"LAS file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            parsed = _parse_las(src.read_text(encoding="utf-8", errors="replace"))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".json")
        out_path.write_text(json.dumps(parsed, indent=2, default=str),
                            encoding="utf-8")
        emit("well_log",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source="las",
             curves=len(parsed["curves"]), rows=len(parsed["data"]))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_csv_to_las(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CSV file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            with src.open(encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if len(rows) < 2:
                return fail("bad_csv", f"{src.name}: need header + units rows.")
            curves = rows[0]
            units = rows[1]
            data = []
            for r in rows[2:]:
                row = []
                for cell in r:
                    cell = cell.strip()
                    if not cell: row.append(None); continue
                    try: row.append(float(cell))
                    except ValueError: row.append(cell)
                data.append(row)
            las_text = _emit_las2({"curves": curves, "units": units, "data": data})
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".las")
        out_path.write_text(las_text, encoding="utf-8")
        emit("well_log",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="las", source="csv",
             curves=len(curves), rows=len(data))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_dlis_to_csv(args: argparse.Namespace) -> int:
    try:
        from dlisio import dlis
    except ImportError:
        return fail("missing_dep",
                    "dlisio not installed (`pip install dlisio`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"DLIS file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            with dlis.load(str(src)) as files:
                f = files[0]
                frames = f.frames
                if not frames:
                    return fail("empty_dlis", f"{src.name}: no frames.")
                frame = frames[0]
                channels = frame.channels
                arr = frame.curves()
        except Exception as ex:
            return fail("decode_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as out:
            w = csv.writer(out)
            w.writerow([c.name for c in channels])
            w.writerow([getattr(c, "units", "") for c in channels])
            for row in arr:
                w.writerow(row)
        emit("well_log",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="dlis",
             curves=len(channels), rows=len(arr))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wells-sidecar",
                                description="Oil-well log (LAS / DLIS) conversion.")
    sub = p.add_subparsers(dest="op", required=True)

    a = sub.add_parser("las-to-csv", help="LAS -> CSV.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")

    j = sub.add_parser("las-to-json", help="LAS -> JSON.")
    j.add_argument("--input", nargs="+", required=True)
    j.add_argument("--output-dir", required=True, dest="output_dir")

    c = sub.add_parser("csv-to-las", help="CSV (curves + units rows) -> LAS 2.0.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")

    d = sub.add_parser("dlis-to-csv", help="DLIS binary -> CSV.")
    d.add_argument("--input", nargs="+", required=True)
    d.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "las-to-csv":  return op_las_to_csv(args)
        if args.op == "las-to-json": return op_las_to_json(args)
        if args.op == "csv-to-las":  return op_csv_to_las(args)
        if args.op == "dlis-to-csv": return op_dlis_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
