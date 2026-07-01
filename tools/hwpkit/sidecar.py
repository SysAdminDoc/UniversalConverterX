"""Korean Hangul (HWP / HWPX) document sidecar.

Convert .hwp (HWP 5.x binary OLE2-style format) and .hwpx (HWPX, the
modern OOXML-style zip container) to PDF / DOCX / ODT / HTML / TXT.

Two backends:
  * pyhwp        Pure-Python HWP 5 reader (text + structure extraction).
  * LibreOffice  Has a "Hangul Word Processor" import filter. Prefer it
                 for fidelity-preserving conversion to PDF / DOCX.

We try LibreOffice first, fall back to pyhwp text extraction.
"""
from __future__ import annotations

import argparse
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_soffice() -> str | None:
    env = os.environ.get("SOFFICE_PATH") or os.environ.get("LIBREOFFICE_PATH")
    if env and Path(env).is_file(): return env
    for n in ("soffice", "soffice.exe", "libreoffice", "libreoffice.exe"):
        h = shutil.which(n)
        if h: return h
    for c in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/libreoffice",
    ):
        if Path(c).is_file(): return c
    return None


SOFFICE_OUTPUT = {
    "pdf":  "pdf:writer_pdf_Export",
    "docx": "docx:MS Word 2007 XML",
    "odt":  "odt:writer8",
    "rtf":  "rtf:Rich Text Format",
    "html": "html:HTML (StarWriter)",
    "txt":  "txt:Text (encoded):UTF8",
}


def _via_soffice(soffice: str, src: Path, out_dir: Path, target: str) -> Path | None:
    flt = SOFFICE_OUTPUT.get(target)
    if not flt: return None
    cmd = [soffice, "--headless", "--norestore",
           "--convert-to", flt, "--outdir", str(out_dir), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0: return None
    expected = out_dir / (src.stem + "." + target)
    return expected if expected.is_file() else None


def _via_pyhwp(src: Path, out_path: Path, target: str) -> int:
    """Text / HTML extraction fallback when LibreOffice isn't available."""
    try:
        from hwp5 import xmlmodel
        from hwp5.hwp5html import HTMLTransform
        from hwp5.hwp5txt import TextTransform
        from hwp5.xmlmodel import Hwp5File
    except ImportError as ex:
        return fail("missing_pyhwp",
                    f"pyhwp not installed: {ex}. `pip install pyhwp`. "
                    "Or install LibreOffice for fidelity-preserving conversion.")
    try:
        with Hwp5File(str(src)) as f:
            if target == "html":
                with out_path.open("wb") as outh:
                    HTMLTransform().transform_hwp5_to_html(f, outh)
            else:  # txt
                with out_path.open("wb") as outh:
                    TextTransform().transform_hwp5_to_text(f, outh)
    except Exception as ex:
        return fail("hwp_failed", f"{src.name}: {ex}")
    return 0


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"HWP file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")

    soffice = _find_soffice()
    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="hwp", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path: Path | None = None
        method = ""
        if soffice:
            out_path = _via_soffice(soffice, src, out_dir, target)
            if out_path is not None: method = "libreoffice"
        if out_path is None:
            if target not in ("html", "txt"):
                return fail("missing_soffice",
                            f"{src.name}: LibreOffice not available; pyhwp fallback "
                            "only supports html and txt targets.")
            out_path = out_dir / (src.stem + "." + target)
            rc = _via_pyhwp(src, out_path, target)
            if rc != 0: return rc
            method = "pyhwp"

        emit("hwp_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, method=method)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hwpkit-sidecar",
                                description="Korean Hangul (HWP / HWPX) document conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert .hwp / .hwpx -> PDF / DOCX / ODT / HTML / TXT.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="pdf | docx | odt | rtf | html | txt")
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
