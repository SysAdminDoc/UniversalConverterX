"""Legacy / niche spreadsheet converter sidecar.

Convert legacy spreadsheets (Lotus 1-2-3 .wk1/.wk3/.wk4/.123, Quattro
Pro .wq1/.wq2/.qpw, Gnumeric .gnumeric, StarOffice .sxc, AppleWorks
.cwk) to modern formats (XLSX, ODS, CSV) via LibreOffice's headless
soffice CLI. LibreOffice imports all of the above out of the box.

Operations:
  to-xlsx   Legacy spreadsheet -> .xlsx.
  to-ods    Legacy spreadsheet -> .ods.
  to-csv    Legacy spreadsheet -> .csv (first sheet).

Requires: `soffice` on PATH (LibreOffice 7.x or newer).
"""
from __future__ import annotations

import argparse
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


def _soffice() -> str | None:
    return (shutil.which("soffice") or shutil.which("soffice.exe")
            or shutil.which("libreoffice"))


def _convert(src: Path, fmt: str, out_dir: Path) -> Path:
    so = _soffice()
    if not so:
        raise RuntimeError("soffice (LibreOffice) not on PATH.")
    # `--convert-to xlsx --outdir <out>` writes <stem>.<fmt> next to nothing,
    # but to <out>.
    cmd = [so, "--headless", "--norestore", "--nologo", "--nofirststartwizard",
           "--convert-to", fmt, "--outdir", str(out_dir), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"soffice exit {proc.returncode}: "
                           f"{proc.stderr or proc.stdout}")
    out_path = out_dir / (src.stem + "." + fmt.split(":")[0])
    if not out_path.is_file():
        raise RuntimeError(f"Expected output not produced: {out_path}")
    return out_path


def _run(args: argparse.Namespace, fmt: str, ext_label: str) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Spreadsheet(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            out_path = _convert(src, fmt, out_dir)
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        emit("spreadsheet_legacy",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=ext_label)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_xlsx(args): return _run(args, "xlsx", "xlsx")
def op_to_ods(args):  return _run(args, "ods",  "ods")
def op_to_csv(args):  return _run(args, "csv",  "csv")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spreadsheet-sidecar",
                                description="Lotus 1-2-3 / Quattro Pro / Gnumeric / etc. -> modern.")
    sub = p.add_subparsers(dest="op", required=True)
    for op in ("to-xlsx", "to-ods", "to-csv"):
        sp = sub.add_parser(op, help=f"Convert legacy spreadsheet -> {op[3:]}.")
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-xlsx": return op_to_xlsx(args)
        if args.op == "to-ods":  return op_to_ods(args)
        if args.op == "to-csv":  return op_to_csv(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
