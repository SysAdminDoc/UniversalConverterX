"""Lab / measurement / Windows-trace data sidecar.

Convert binary measurement and trace data formats into CSV / JSON for
analysis pipelines:

  * LabVIEW .lvm (text Measurement file) -> CSV
  * LabVIEW .tdms (binary, hierarchical) -> CSV / parquet via npTDMS
  * Sysinternals Process Monitor .pml    -> CSV via Procmon /OpenLog
  * Windows ETW .etl Event Tracing       -> CSV / JSON via tracerpt
  * Windows perfmon .blg counter logs    -> CSV via relog
  * National Instruments .csv-with-header normalization

Operations:
  lvm-to-csv         LabVIEW Measurement file -> CSV (strip text header).
  tdms-to-csv        LabVIEW TDMS binary -> CSV.
  pml-to-csv         Sysinternals Process Monitor -> CSV via procmon.exe.
  etl-to-csv         ETW .etl -> CSV via tracerpt.exe.
  blg-to-csv         Performance Monitor .blg -> CSV via relog.exe.

LabVIEW .lvm is a text format with a `***End_of_Header***` sentinel; we
parse without external libraries. .tdms requires `npTDMS` (in
requirements.txt). The Windows tracing formats shell out to bundled OS
tools (procmon / tracerpt / relog) which are part of every Windows
install.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── LabVIEW .lvm (text) ────────────────────────────────────────────────

def _parse_lvm(text: str) -> tuple[list[str], list[list]]:
    """Return (header_columns, rows). LVM files use tab separators and a
    *** End_of_Header *** sentinel between every channel block."""
    lines = text.splitlines()
    columns: list[str] = []
    rows: list[list] = []
    in_data = False
    for line in lines:
        if line.startswith("***End_of_Header***"):
            in_data = True; continue
        if in_data:
            parts = line.split("\t")
            if not parts or not parts[0].strip(): continue
            if not columns and any(p and not p.replace(".", "").replace("-", "").replace("E", "").replace("+", "").isdigit()
                                    for p in parts):
                columns = [p.strip() for p in parts]
                continue
            rows.append([p.strip() for p in parts])
    if not columns and rows:
        columns = [f"Col{i}" for i in range(len(rows[0]))]
    return columns, rows


def op_lvm_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"LVM file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
            cols, rows = _parse_lvm(text)
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if cols: w.writerow(cols)
            for r in rows: w.writerow(r)
        emit("lab_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="lvm",
             rows=len(rows), columns=len(cols))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── LabVIEW .tdms (binary) ────────────────────────────────────────────

def op_tdms_to_csv(args: argparse.Namespace) -> int:
    try:
        from nptdms import TdmsFile
    except ImportError:
        return fail("missing_dep", "npTDMS not installed (`pip install npTDMS`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"TDMS file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            with TdmsFile.open(str(src)) as tdms:
                # write one CSV per group
                for group in tdms.groups():
                    channels = group.channels()
                    if not channels: continue
                    name = group.name.replace("/", "_").replace("\\", "_")
                    out_path = out_dir / (src.stem + "_" + name + ".csv")
                    cols = [ch.name for ch in channels]
                    data = [ch[:] for ch in channels]
                    n_rows = max(len(d) for d in data) if data else 0
                    with out_path.open("w", encoding="utf-8", newline="") as f:
                        w = csv.writer(f)
                        w.writerow(cols)
                        for r in range(n_rows):
                            w.writerow(d[r] if r < len(d) else ""
                                        for d in data)
                    emit("lab_doc",
                         input=str(src), output=str(out_path),
                         size_bytes=out_path.stat().st_size,
                         format="csv", source="tdms",
                         group=group.name, rows=n_rows, columns=len(cols))
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Windows trace tools ───────────────────────────────────────────────

def _run_windows_tool(args: argparse.Namespace, cli_name: str,
                      cli_args_fn, source: str, ext: str) -> int:
    cli = shutil.which(cli_name) or shutil.which(cli_name + ".exe")
    if not cli: return fail("missing_dep", f"{cli_name} not on PATH (Windows-only).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"trace file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + ext)
        cmd = [cli] + cli_args_fn(src, out_path)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: {cli_name} exit {proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()}")
        if not out_path.is_file():
            return fail("convert_failed",
                        f"{src.name}: {cli_name} produced no output.")
        emit("lab_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=ext, source=source)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_pml_to_csv(args):
    return _run_windows_tool(
        args, "Procmon",
        lambda s, o: ["/OpenLog", str(s), "/SaveAs", str(o), "/Quiet",
                       "/Minimized"],
        "procmon-pml", "csv")


def op_etl_to_csv(args):
    return _run_windows_tool(
        args, "tracerpt",
        lambda s, o: [str(s), "-o", str(o), "-of", "CSV", "-y"],
        "etw-etl", "csv")


def op_blg_to_csv(args):
    return _run_windows_tool(
        args, "relog",
        lambda s, o: [str(s), "-f", "CSV", "-o", str(o), "-y"],
        "perfmon-blg", "csv")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="labkit-sidecar",
                                description="Lab / measurement / Windows-trace decoders.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("lvm-to-csv",  "LabVIEW .lvm -> CSV"),
        ("tdms-to-csv", "LabVIEW TDMS binary -> CSV"),
        ("pml-to-csv",  "Sysinternals Procmon -> CSV"),
        ("etl-to-csv",  "Windows ETW .etl -> CSV via tracerpt"),
        ("blg-to-csv",  "Windows perfmon .blg -> CSV via relog"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "lvm-to-csv":  return op_lvm_to_csv(args)
        if args.op == "tdms-to-csv": return op_tdms_to_csv(args)
        if args.op == "pml-to-csv":  return op_pml_to_csv(args)
        if args.op == "etl-to-csv":  return op_etl_to_csv(args)
        if args.op == "blg-to-csv":  return op_blg_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
