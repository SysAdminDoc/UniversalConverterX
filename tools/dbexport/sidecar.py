"""Database vendor-export format sidecar.

Convert vendor database unload / export formats to portable CSV. These
are formats DBAs hit when migrating between platforms or when tools
don't read each other's output:

  * IBM DB2 IXF (Integrated eXchange Format)
  * Teradata FastExport / TPT
  * Vertica COPY OUT delimited
  * Snowflake CSV unload (ZSTD-compressed CSV with header)
  * SQL Server BCP native + character formats
  * Oracle SQL*Loader DAT
  * MySQL .sql dump -> CSV (table-by-table)

Operations:
  ixf-to-csv      DB2 IXF binary -> CSV.
  bcp-to-csv      SQL Server BCP character format -> CSV.
  mysql-dump-csv  Extract INSERT INTO statements from a .sql dump -> CSV per table.
  sqlloader-info  Probe Oracle SQL*Loader DAT/CTL pair.

Pure stdlib. Vendor-specific binary formats (BCP native) require schema
metadata which the user must provide in the .fmt control file.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import struct
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── DB2 IXF ───────────────────────────────────────────────────────────

def _parse_ixf(data: bytes) -> tuple[list[str], list[list[str]]]:
    """IXF: stream of records each prefixed by a 6-byte length-padded
    counter and a 1-byte type identifier. Types: H=header, T=table,
    C=column, D=data row, A=app, X=external."""
    p = 0
    columns: list[str] = []
    column_widths: list[int] = []
    column_types: list[int] = []
    rows: list[list[str]] = []
    while p + 8 < len(data):
        rec_len = int(data[p:p + 6].decode("ascii", errors="replace") or "0")
        rec_type = chr(data[p + 6])
        p += 8
        if rec_len <= 0: break
        body = data[p - 1:p - 1 + rec_len]
        p += rec_len - 1
        if rec_type == "C":
            name = body[1:32].decode("ascii", errors="replace").strip()
            type_code = int(body[32:35].decode("ascii", errors="replace") or "0")
            type_len = int(body[42:48].decode("ascii", errors="replace") or "0")
            columns.append(name)
            column_widths.append(type_len)
            column_types.append(type_code)
        elif rec_type == "D":
            cur_row: list[str] = []
            row_p = 8
            for ti, ty in enumerate(column_types):
                width = column_widths[ti] if ti < len(column_widths) else 0
                if width <= 0: continue
                if row_p + 2 > len(body): break
                null_ind = struct.unpack("<H", body[row_p:row_p + 2])[0]
                row_p += 2
                if null_ind == 0xFFFF:
                    cur_row.append("")
                    row_p += width
                    continue
                raw = body[row_p:row_p + width]
                row_p += width
                if ty in (384, 388):  # CHAR / VARCHAR
                    cur_row.append(raw.decode("utf-8", errors="replace").rstrip())
                elif ty in (496, 500):  # INT / SMALLINT
                    if width == 2:
                        cur_row.append(str(struct.unpack(">h", raw[:2])[0]))
                    elif width == 4:
                        cur_row.append(str(struct.unpack(">i", raw[:4])[0]))
                    else:
                        cur_row.append(raw.hex())
                else:
                    cur_row.append(raw.decode("utf-8", errors="replace").rstrip())
            rows.append(cur_row)
    return columns, rows


def op_ixf_to_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"IXF file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            cols, rows = _parse_ixf(src.read_bytes())
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if cols: w.writerow(cols)
            for r in rows: w.writerow(r)
        emit("dbexport_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="db2-ixf",
             rows=len(rows), columns=len(cols))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── BCP character ─────────────────────────────────────────────────────

def op_bcp_to_csv(args: argparse.Namespace) -> int:
    """BCP character format: TAB-delimited rows, CR/LF line terminators.
    Convert to standard CSV (comma-delimited, RFC 4180 quoting)."""
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"BCP file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding=args.encoding, errors="replace")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".csv")
        rows = [line.split("\t") for line in text.splitlines() if line]
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            for r in rows: w.writerow(r)
        emit("dbexport_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="csv", source="sqlserver-bcp", rows=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── MySQL dump → per-table CSV ─────────────────────────────────────────

_INSERT_RE = re.compile(
    r"INSERT INTO `(?P<table>[^`]+)`\s*(?:\([^)]*\))?\s*VALUES\s*(?P<vals>.+?);",
    re.IGNORECASE | re.DOTALL)
_TUPLE_RE = re.compile(r"\(((?:[^()'\\]|'(?:[^'\\]|\\.)*')*)\)")
_LITERAL_RE = re.compile(
    r"(?:'((?:[^'\\]|\\.)*)'|(NULL)|(-?\d+(?:\.\d+)?(?:e-?\d+)?))",
    re.IGNORECASE)


def op_mysql_dump_csv(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"MySQL dump(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        per_table: dict[str, list[list[str]]] = {}
        for m in _INSERT_RE.finditer(text):
            table = m.group("table")
            vals = m.group("vals")
            for tup in _TUPLE_RE.finditer(vals):
                inner = tup.group(1)
                row: list[str] = []
                for lit in _LITERAL_RE.finditer(inner):
                    if lit.group(1) is not None:
                        row.append(lit.group(1).replace("\\'", "'")
                                                 .replace('\\"', '"')
                                                 .replace("\\\\", "\\")
                                                 .replace("\\n", "\n"))
                    elif lit.group(2):
                        row.append("")
                    else:
                        row.append(lit.group(3))
                per_table.setdefault(table, []).append(row)
        for table, rows in per_table.items():
            out_path = out_dir / (src.stem + "__" + table + ".csv")
            with out_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                for r in rows: w.writerow(r)
            emit("dbexport_doc",
                 input=str(src), output=str(out_path),
                 size_bytes=out_path.stat().st_size,
                 format="csv", source="mysql-dump",
                 table=table, rows=len(rows))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── SQL*Loader probe ───────────────────────────────────────────────────

def op_sqlloader_info(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f".ctl file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    probes: list[dict] = []
    for src in inputs:
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        load = re.search(r"LOAD\s+DATA", text, re.IGNORECASE)
        infile = re.search(r"INFILE\s+'([^']+)'", text, re.IGNORECASE)
        table = re.search(r"INTO\s+TABLE\s+(\w+)", text, re.IGNORECASE)
        delim = re.search(r"FIELDS\s+TERMINATED\s+BY\s+'([^']+)'",
                           text, re.IGNORECASE)
        cols = re.findall(r"^\s*(\w+)\s+(?:CHAR|INTEGER|DECIMAL|DATE|TIMESTAMP|FLOAT)",
                            text, re.IGNORECASE | re.MULTILINE)
        probes.append({
            "file": str(src), "has_load_data": bool(load),
            "infile": infile.group(1) if infile else "",
            "table": table.group(1) if table else "",
            "delimiter": delim.group(1) if delim else ",",
            "column_count": len(cols),
            "columns": cols[:50],
        })
    out_path = out_dir / "sqlloader-info.json"
    out_path.write_text(json.dumps(probes, indent=2), encoding="utf-8")
    for p in probes:
        emit("dbexport_doc",
             input=p["file"], output="",
             size_bytes=0, format="probe",
             source="oracle-sqlloader", table=p.get("table", ""))
    emit("complete", output=str(out_path),
         size_bytes=out_path.stat().st_size, count=len(probes))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dbexport-sidecar",
                                description="Database vendor-export format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("ixf-to-csv",     "DB2 IXF binary -> CSV"),
        ("mysql-dump-csv", "MySQL dump -> CSV per table"),
        ("sqlloader-info", "Oracle SQL*Loader .ctl probe -> JSON"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    bcp = sub.add_parser("bcp-to-csv", help="SQL Server BCP character -> CSV")
    bcp.add_argument("--input", nargs="+", required=True)
    bcp.add_argument("--output-dir", required=True, dest="output_dir")
    bcp.add_argument("--encoding", default="utf-8",
                     help="Source encoding (utf-8 / cp1252 / latin-1).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "ixf-to-csv":     return op_ixf_to_csv(args)
        if args.op == "bcp-to-csv":     return op_bcp_to_csv(args)
        if args.op == "mysql-dump-csv": return op_mysql_dump_csv(args)
        if args.op == "sqlloader-info": return op_sqlloader_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
