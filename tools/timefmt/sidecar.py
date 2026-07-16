"""Timestamp / time-format conversion sidecar.

Convert dates and timestamps between every common representation:

  ISO 8601 / RFC 3339           "2026-05-01T13:00:00Z"
  Unix epoch seconds            1746104400
  Unix epoch milliseconds       1746104400000
  Excel serial date             46117.5416666667
  Apple Cocoa epoch             778431600  (seconds since 2001-01-01)
  Microsoft FILETIME            132857328000000000 (100-ns since 1601)
  HFS+ timestamp                3826209600
  RFC 822 / 2822 / 5322         "Thu, 01 May 2026 13:00:00 +0000"
  Mainframe Julian              2026.121
  PowerShell DateTime ticks     638828064000000000
  Java Date.getTime()           1746104400000  (same as ms but explicit)

Operations:
  convert       Treat each input string as a timestamp; emit JSON with all
                representations.
  cron-explain  Render `next-N-runs` for a cron expression.
  cron-when     Translate cron -> human readable.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Constants ────────────────────────────────────────────────────────────

EPOCH_UNIX = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
EPOCH_COCOA = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
EPOCH_HFS = dt.datetime(1904, 1, 1, tzinfo=dt.timezone.utc)
EPOCH_FILETIME = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc)
EPOCH_TICKS = dt.datetime(1, 1, 1, tzinfo=dt.timezone.utc)
EPOCH_EXCEL = dt.datetime(1899, 12, 30, tzinfo=dt.timezone.utc)


def _parse(value: str) -> dt.datetime:
    """Best-effort parser for any of the supported representations."""
    s = value.strip()
    # Pure number -> guess unit by magnitude.
    if s.replace(".", "").replace("-", "").isdigit() or _is_number(s):
        n = float(s)
        if abs(n) > 1e16:           # ticks (100-ns since year 1)
            ms100 = int(n)
            return EPOCH_TICKS + dt.timedelta(microseconds=ms100 // 10)
        if abs(n) > 1e13:           # FILETIME 100-ns since 1601
            return EPOCH_FILETIME + dt.timedelta(microseconds=int(n) // 10)
        if abs(n) > 1e11:           # ms epoch
            return EPOCH_UNIX + dt.timedelta(milliseconds=n)
        if abs(n) > 1e9:            # s epoch
            return EPOCH_UNIX + dt.timedelta(seconds=n)
        if 0 < n < 60000:           # likely Excel serial
            return EPOCH_EXCEL + dt.timedelta(days=n)
    # Try ISO / RFC.
    try:
        if s.endswith("Z"):
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.datetime.fromisoformat(s)
    except Exception:
        pass
    # Try email / RFC 822.
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s)
    except Exception:
        pass
    raise ValueError(f"Could not parse timestamp: {value!r}")


def _is_number(s: str) -> bool:
    try: float(s); return True
    except Exception: return False


def _all_repr(d: dt.datetime) -> dict:
    if d.tzinfo is None: d = d.replace(tzinfo=dt.timezone.utc)
    delta = d - EPOCH_UNIX
    secs = delta.total_seconds()
    ms = int(secs * 1000)
    excel = (d - EPOCH_EXCEL).total_seconds() / 86400.0
    cocoa = (d - EPOCH_COCOA).total_seconds()
    hfs = (d - EPOCH_HFS).total_seconds()
    ft = int((d - EPOCH_FILETIME).total_seconds() * 1e7)
    ticks = int((d - EPOCH_TICKS).total_seconds() * 1e7)
    julian_doy = d.timetuple().tm_yday
    return {
        "iso8601": d.isoformat().replace("+00:00", "Z"),
        "rfc822": d.strftime("%a, %d %b %Y %H:%M:%S %z"),
        "epoch_seconds": int(secs),
        "epoch_ms": ms,
        "excel_serial": round(excel, 8),
        "cocoa_seconds": int(cocoa),
        "hfs_seconds": int(hfs),
        "filetime_100ns": ft,
        "ticks_100ns": ticks,
        "year_doy": f"{d.year}.{julian_doy:03d}",
    }


def op_convert(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir).resolve() if args.output_dir else None
    if out_dir: out_dir.mkdir(parents=True, exist_ok=True)

    values: list[str] = []
    if args.input:
        values.extend(args.input)
    if args.input_file:
        text = Path(args.input_file).read_text(encoding="utf-8")
        values.extend(line.strip() for line in text.splitlines() if line.strip())
    if not values:
        return fail("no_input", "Pass --input <ts> [<ts>...] or --input-file <path>.")

    rows: list[dict] = []
    for value in values:
        try:
            d = _parse(value)
            row = {"source": value, **_all_repr(d)}
        except Exception as ex:
            row = {"source": value, "error": str(ex)}
        rows.append(row)
        emit("time_value", **row)

    if out_dir is not None:
        out_path = out_dir / "timestamps.json"
        out_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        emit("complete", output=str(out_path),
             size_bytes=out_path.stat().st_size, count=len(rows))
    else:
        emit("complete", output="(stdout)", size_bytes=0, count=len(rows))
    return 0


def op_cron_explain(args: argparse.Namespace) -> int:
    try:
        from croniter import croniter
        from cron_descriptor import get_description
    except ImportError as ex:
        return fail("missing_dep",
                    f"croniter / cron_descriptor missing: {ex}. "
                    "`pip install croniter cron-descriptor`.")
    base = dt.datetime.now(dt.timezone.utc)
    runs = []
    try:
        it = croniter(args.expression, base)
        for _ in range(int(args.count)):
            runs.append(it.get_next(dt.datetime).isoformat())
        human = get_description(args.expression)
    except Exception as ex:
        return fail("cron_failed", str(ex))
    emit("cron_explain",
         expression=args.expression,
         human=human,
         next_runs=runs)
    emit("complete", output="(stdout)", size_bytes=0, count=len(runs))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="timefmt-sidecar",
                                description="Timestamp / cron format conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Translate a timestamp into every common representation.")
    c.add_argument("--input", nargs="*", default=None,
                   help="Timestamp values to convert (any supported encoding).")
    c.add_argument("--input-file", default=None, dest="input_file",
                   help="One timestamp per line.")
    c.add_argument("--output-dir", default=None, dest="output_dir",
                   help="If set, also write timestamps.json into it.")

    cr = sub.add_parser("cron-explain", help="Show next N runs + human description of a cron expression.")
    cr.add_argument("--expression", required=True)
    cr.add_argument("--count", type=int, default=5)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":      return op_convert(args)
        if args.op == "cron-explain": return op_cron_explain(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
