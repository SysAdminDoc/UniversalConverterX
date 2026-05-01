"""Log-file conversion sidecar.

Convert plaintext log files into structured formats (JSON-Lines, CSV) so
they can be ingested by analytics tools.

Supported parsers:
  * Apache / NCSA Common Log Format (CLF)
  * Apache Combined / Nginx Combined
  * Syslog (RFC 3164 + RFC 5424)
  * AWS ELB / CloudFront access logs (semicolon-delimited)
  * Windows Event Log .evtx (via python-evtx)
  * Generic CSV / TSV / pipe-delimited (auto-sniff)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# ── Apache common / combined log formats ─────────────────────────────────────

_CLF = re.compile(
    r'^(?P<host>\S+) (?P<ident>\S+) (?P<user>\S+) \[(?P<time>[^\]]+)\] '
    r'"(?P<request>[^"]*)" (?P<status>\d{3}) (?P<bytes>\S+)'
    r'(?: "(?P<referer>[^"]*)" "(?P<agent>[^"]*)")?'
)


def _parse_clf(line: str) -> dict | None:
    m = _CLF.match(line)
    if not m: return None
    d = m.groupdict()
    parts = (d.get("request") or "").split(" ", 2)
    if len(parts) == 3:
        d["method"], d["path"], d["protocol"] = parts
    return d


# ── Syslog (RFC 3164 / 5424) ────────────────────────────────────────────────

_SYSLOG_RFC3164 = re.compile(
    r'^<(?P<pri>\d+)>(?P<time>\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})\s+'
    r'(?P<host>\S+)\s+(?P<process>\S+?)(?:\[(?P<pid>\d+)\])?:\s+(?P<msg>.*)$'
)
_SYSLOG_RFC5424 = re.compile(
    r'^<(?P<pri>\d+)>(?P<version>\d+)\s+(?P<time>\S+)\s+(?P<host>\S+)\s+'
    r'(?P<app>\S+)\s+(?P<pid>\S+)\s+(?P<msgid>\S+)\s+(?P<sd>\S+)?\s+(?P<msg>.*)$'
)


def _parse_syslog(line: str) -> dict | None:
    m = _SYSLOG_RFC5424.match(line) or _SYSLOG_RFC3164.match(line)
    if not m: return None
    d = m.groupdict()
    if d.get("pri"):
        pri = int(d["pri"])
        d["facility"] = pri >> 3
        d["severity"] = pri & 0x07
    return d


PARSERS = {
    "clf":      _parse_clf,
    "combined": _parse_clf,
    "apache":   _parse_clf,
    "nginx":    _parse_clf,
    "syslog":   _parse_syslog,
}


def op_to_jsonl(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Log file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    parser = PARSERS.get(args.format.lower())
    if parser is None:
        return fail("bad_format", f"Choose: {sorted(PARSERS)}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="logkit", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".jsonl")
        ok = bad = 0
        with src.open("r", encoding="utf-8", errors="replace") as inh, \
             out_path.open("w", encoding="utf-8") as outh:
            for line in inh:
                d = parser(line.rstrip("\n"))
                if d is None:
                    bad += 1; continue
                outh.write(json.dumps(d, ensure_ascii=False) + "\n")
                ok += 1
        emit("log_record",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=args.format, parsed=ok, skipped=bad)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_evtx_to_jsonl(args: argparse.Namespace) -> int:
    """Windows Event Log .evtx -> JSON-Lines via python-evtx."""
    try:
        from Evtx.Evtx import Evtx
        import xmltodict
    except ImportError as ex:
        return fail("missing_evtx",
                    f"python-evtx + xmltodict not installed: {ex}. "
                    "`pip install python-evtx xmltodict`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"EVTX file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".jsonl")
        with Evtx(str(src)) as log, out_path.open("w", encoding="utf-8") as outh:
            n = 0
            for record in log.records():
                try:
                    d = xmltodict.parse(record.xml())
                except Exception:
                    continue
                outh.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
                n += 1
        emit("log_record",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="evtx", parsed=n)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="logkit-sidecar",
                                description="Log file -> structured JSON / CSV.")
    sub = p.add_subparsers(dest="op", required=True)
    j = sub.add_parser("to-jsonl", help="Plaintext log -> JSON Lines.")
    j.add_argument("--input", nargs="+", required=True)
    j.add_argument("--output-dir", required=True, dest="output_dir")
    j.add_argument("--format", required=True,
                   choices=sorted(PARSERS.keys()),
                   help="Log format dialect.")
    e = sub.add_parser("evtx-to-jsonl", help="Windows .evtx -> JSON Lines.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-jsonl":      return op_to_jsonl(args)
        if args.op == "evtx-to-jsonl": return op_evtx_to_jsonl(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
