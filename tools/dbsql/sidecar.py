"""SQL dialect translation sidecar.

Translate SQL between dialects (MySQL <-> PostgreSQL <-> SQL Server <->
Oracle <-> SQLite <-> BigQuery <-> Snowflake <-> DuckDB <-> ClickHouse
<-> Spark <-> Hive <-> Redshift <-> Databricks) using `sqlglot`.

Operations:
  translate   Convert SQL from source dialect to target dialect.
  format      Pretty-print SQL in a target dialect.
  parse       SQL -> AST as JSON (debugging / tooling).

Requires: pip install sqlglot
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


VALID_DIALECTS = (
    "mysql", "postgres", "sqlite", "tsql", "oracle", "bigquery",
    "snowflake", "duckdb", "clickhouse", "spark", "hive", "redshift",
    "databricks", "presto", "trino", "athena", "drill", "starrocks",
)


def op_translate(args: argparse.Namespace) -> int:
    try:
        import sqlglot
    except ImportError:
        return fail("missing_dep", "sqlglot not installed (`pip install sqlglot`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SQL file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    src_d = args.from_dialect.lower()
    dst_d = args.to_dialect.lower()
    if src_d not in VALID_DIALECTS:
        return fail("bad_dialect", f"Unknown source dialect: {src_d}")
    if dst_d not in VALID_DIALECTS:
        return fail("bad_dialect", f"Unknown target dialect: {dst_d}")

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            sql = src.read_text(encoding="utf-8")
            statements = sqlglot.transpile(sql, read=src_d, write=dst_d, pretty=True)
            translated = ";\n\n".join(statements) + ";\n"
        except Exception as ex:
            return fail("translate_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + f".{dst_d}.sql")
        out_path.write_text(translated, encoding="utf-8")
        emit("sql_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="sql", source_dialect=src_d, target_dialect=dst_d,
             statements=len(statements))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_format(args: argparse.Namespace) -> int:
    try:
        import sqlglot
    except ImportError:
        return fail("missing_dep", "sqlglot not installed (`pip install sqlglot`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SQL file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    dialect = args.dialect.lower()
    if dialect not in VALID_DIALECTS:
        return fail("bad_dialect", f"Unknown dialect: {dialect}")

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            sql = src.read_text(encoding="utf-8")
            statements = sqlglot.transpile(sql, read=dialect, write=dialect,
                                           pretty=True)
            formatted = ";\n\n".join(statements) + ";\n"
        except Exception as ex:
            return fail("format_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".formatted.sql")
        out_path.write_text(formatted, encoding="utf-8")
        emit("sql_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="sql", source_dialect=dialect, target_dialect=dialect,
             statements=len(statements))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_parse(args: argparse.Namespace) -> int:
    try:
        import sqlglot
    except ImportError:
        return fail("missing_dep", "sqlglot not installed (`pip install sqlglot`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"SQL file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    dialect = args.dialect.lower()

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            sql = src.read_text(encoding="utf-8")
            trees = sqlglot.parse(sql, read=dialect)
            ast = [t.dump() if t else None for t in trees]
        except Exception as ex:
            return fail("parse_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + ".ast.json")
        out_path.write_text(json.dumps(ast, indent=2, default=str),
                            encoding="utf-8")
        emit("sql_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="json", source_dialect=dialect, target_dialect="ast",
             statements=len(ast))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dbsql-sidecar",
                                description="SQL dialect translator (sqlglot-backed).")
    sub = p.add_subparsers(dest="op", required=True)

    t = sub.add_parser("translate", help="Translate SQL between dialects.")
    t.add_argument("--input", nargs="+", required=True)
    t.add_argument("--output-dir", required=True, dest="output_dir")
    t.add_argument("--from", required=True, dest="from_dialect",
                   help="Source dialect: " + " | ".join(VALID_DIALECTS))
    t.add_argument("--to", required=True, dest="to_dialect",
                   help="Target dialect.")

    f = sub.add_parser("format", help="Pretty-print SQL in a dialect.")
    f.add_argument("--input", nargs="+", required=True)
    f.add_argument("--output-dir", required=True, dest="output_dir")
    f.add_argument("--dialect", required=True)

    pa = sub.add_parser("parse", help="SQL -> AST JSON.")
    pa.add_argument("--input", nargs="+", required=True)
    pa.add_argument("--output-dir", required=True, dest="output_dir")
    pa.add_argument("--dialect", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "translate": return op_translate(args)
        if args.op == "format":    return op_format(args)
        if args.op == "parse":     return op_parse(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
