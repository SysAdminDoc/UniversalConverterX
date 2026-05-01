"""Database / statistical-format conversion sidecar.

Reads legacy / proprietary database and statistical formats and writes them
out as CSV, JSON-Lines, Parquet, or SQLite tables.

Supported inputs:
  * SQLite (.db, .sqlite, .sqlite3)
  * MS Access (.mdb, .accdb)              via mdbtools (mdb-export shellout)
  * dBase (.dbf)                          via dbfread
  * SAS XPORT / 7BDAT (.xpt, .sas7bdat)   via pandas.read_sas
  * SPSS (.sav, .zsav)                    via pyreadstat
  * Stata (.dta)                          via pandas.read_stata
  * R Data (.rda, .rdata, .rds)           via pyreadr

Supported outputs: csv | tsv | jsonl | parquet | sqlite
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _read_sqlite(path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        cur.execute(f'SELECT * FROM "{t}"')
        out[t] = [dict(r) for r in cur.fetchall()]
    con.close()
    return out


def _read_mdb(path: Path) -> dict[str, list[dict]]:
    """MS Access via the mdbtools `mdb-tables` + `mdb-export` CLIs."""
    mdb_tables = shutil.which("mdb-tables") or shutil.which("mdb-tables.exe")
    mdb_export = shutil.which("mdb-export") or shutil.which("mdb-export.exe")
    if not mdb_tables or not mdb_export:
        raise RuntimeError(
            "mdbtools (mdb-tables, mdb-export) not found on PATH. "
            "Install via Chocolatey (`choco install mdbtools`), Homebrew, or apt.")
    listing = subprocess.run([mdb_tables, "-1", str(path)],
                              capture_output=True, text=True).stdout.strip()
    out: dict[str, list[dict]] = {}
    for tbl in (t for t in listing.splitlines() if t.strip()):
        proc = subprocess.run([mdb_export, str(path), tbl],
                               capture_output=True, text=True, encoding="utf-8")
        rows = list(csv.DictReader(proc.stdout.splitlines()))
        out[tbl] = rows
    return out


def _read_dbf(path: Path) -> dict[str, list[dict]]:
    from dbfread import DBF
    return {path.stem: [dict(r) for r in DBF(str(path), load=True)]}


def _read_sas(path: Path) -> dict[str, list[dict]]:
    import pandas as pd
    df = pd.read_sas(str(path))
    return {path.stem: df.to_dict(orient="records")}


def _read_spss(path: Path) -> dict[str, list[dict]]:
    import pyreadstat
    df, _meta = pyreadstat.read_sav(str(path))
    return {path.stem: df.to_dict(orient="records")}


def _read_stata(path: Path) -> dict[str, list[dict]]:
    import pandas as pd
    df = pd.read_stata(str(path))
    return {path.stem: df.to_dict(orient="records")}


def _read_r(path: Path) -> dict[str, list[dict]]:
    import pyreadr
    result = pyreadr.read_r(str(path))
    out: dict[str, list[dict]] = {}
    for name, df in result.items():
        out[name or path.stem] = df.to_dict(orient="records")
    return out


READERS = {
    ".db": _read_sqlite, ".sqlite": _read_sqlite, ".sqlite3": _read_sqlite,
    ".mdb": _read_mdb, ".accdb": _read_mdb,
    ".dbf": _read_dbf,
    ".xpt": _read_sas, ".sas7bdat": _read_sas,
    ".sav": _read_spss, ".zsav": _read_spss,
    ".dta": _read_stata,
    ".rda": _read_r, ".rdata": _read_r, ".rds": _read_r,
}


def _write_csv(rows: list[dict], path: Path, sep: str = ",") -> None:
    if not rows:
        path.write_text("", encoding="utf-8"); return
    cols = list({k for r in rows for k in r.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=sep, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _write_jsonl(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str, ensure_ascii=False) + "\n")


def _write_parquet(rows: list[dict], path: Path) -> None:
    import pandas as pd
    pd.DataFrame(rows).to_parquet(str(path), index=False)


def _write_sqlite(tables: dict[str, list[dict]], path: Path) -> None:
    con = sqlite3.connect(str(path))
    cur = con.cursor()
    for name, rows in tables.items():
        if not rows: continue
        cols = list({k for r in rows for k in r.keys()})
        safe_name = "".join(c for c in name if c.isalnum() or c == "_") or "table"
        cur.execute(f'CREATE TABLE IF NOT EXISTS "{safe_name}" '
                    f'({", ".join(f""""{c}" TEXT""" for c in cols)})')
        placeholders = ",".join("?" for _ in cols)
        cur.executemany(
            f'INSERT INTO "{safe_name}" ({", ".join(f""""{c}" """ for c in cols)}) '
            f'VALUES ({placeholders})',
            [[(str(r.get(c)) if r.get(c) is not None else None) for c in cols] for r in rows])
    con.commit(); con.close()


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Database file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="dbconvert", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        reader = READERS.get(ext)
        if not reader:
            return fail("bad_format", f"Unsupported input ext '{ext}'.")
        try:
            tables = reader(src)
        except ImportError as ex:
            return fail("missing_dep", str(ex))
        except Exception as ex:
            return fail("read_failed", f"{src.name}: {ex}")

        if target == "sqlite":
            out_path = out_dir / (src.stem + ".sqlite")
            _write_sqlite(tables, out_path)
            emit("dbtable",
                 input=str(src), output=str(out_path),
                 size_bytes=out_path.stat().st_size,
                 tables=len(tables), rows=sum(len(v) for v in tables.values()),
                 format="sqlite")
        else:
            for name, rows in tables.items():
                safe = "".join(c for c in name if c.isalnum() or c in "._-") or "table"
                if target in ("csv", "tsv"):
                    out_path = out_dir / f"{src.stem}__{safe}.{target}"
                    _write_csv(rows, out_path, sep="\t" if target == "tsv" else ",")
                elif target == "jsonl":
                    out_path = out_dir / f"{src.stem}__{safe}.jsonl"
                    _write_jsonl(rows, out_path)
                elif target == "parquet":
                    out_path = out_dir / f"{src.stem}__{safe}.parquet"
                    _write_parquet(rows, out_path)
                else:
                    return fail("bad_format",
                                f"Target '{target}' not supported. "
                                "Choose csv | tsv | jsonl | parquet | sqlite.")
                emit("dbtable",
                     input=str(src), output=str(out_path),
                     size_bytes=out_path.stat().st_size,
                     table=safe, rows=len(rows), format=target)

        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dbtools-sidecar",
                                description="Database/statistical -> CSV/JSON/Parquet/SQLite.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert SQLite/MDB/DBF/SAS/SPSS/Stata/R.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="csv | tsv | jsonl | parquet | sqlite")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
