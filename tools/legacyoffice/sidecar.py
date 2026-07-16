"""Legacy office-document sidecar.

Convert formats from the pre-OOXML era. Most paths shell out to LibreOffice
headless, which is the most comprehensive OSS importer. A few specialty
paths (Publisher, WordStar) use dedicated libraries.

Inputs:
  * WordPerfect       (.wpd, .wpt, .wpg)
  * WordStar          (.ws, .wsd)
  * AmiPro            (.sam, .smm)
  * Microsoft Works   (.wps, .wpt)
  * Microsoft Publisher (.pub)         read-only via libmspub
  * StarOffice 1-5    (.sxw, .sxc, .sxi, .sxd)
  * KOffice           (.kwd, .ksp, .kpr)
  * AbiWord           (.abw)
  * AppleWorks        (.cwk)
  * MacWrite          (.mw)

Outputs: pdf | docx | odt | rtf | html | txt
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




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
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/libreoffice", "/usr/bin/soffice",
        "/usr/local/bin/libreoffice", "/snap/bin/libreoffice",
    ):
        if Path(c).is_file(): return c
    return None


# LibreOffice -> filter mapping for the formats it can read.
SOFFICE_INPUT_EXTS = {
    ".wpd", ".wpt", ".wpg",          # WordPerfect
    ".sam", ".smm",                  # AmiPro / Lotus Word Pro
    ".wps", ".wpt",                  # Works
    ".sxw", ".sxc", ".sxi", ".sxd",  # StarOffice 1-5
    ".kwd", ".ksp", ".kpr",          # KOffice
    ".abw",                          # AbiWord
    ".cwk",                          # AppleWorks
    ".mw",                           # MacWrite
}

# Outputs supported via the `--convert-to` flag.
SOFFICE_OUTPUT = {
    "pdf":  "pdf:writer_pdf_Export",
    "docx": "docx:MS Word 2007 XML",
    "odt":  "odt:writer8",
    "rtf":  "rtf:Rich Text Format",
    "html": "html:HTML (StarWriter)",
    "txt":  "txt:Text (encoded):UTF8",
}


def _convert_via_soffice(soffice: str, src: Path, out_dir: Path,
                          target: str) -> Path | None:
    out_filter = SOFFICE_OUTPUT.get(target)
    if not out_filter: return None
    cmd = [soffice, "--headless", "--norestore",
           "--convert-to", out_filter,
           "--outdir", str(out_dir), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return None
    expected = out_dir / (src.stem + "." + target)
    return expected if expected.is_file() else None


def _convert_publisher(src: Path, out_dir: Path, target: str) -> int:
    """libmspub for .pub -> ODT/PDF round-trip via LibreOffice."""
    # libmspub is pulled in by LibreOffice; if soffice can't open .pub,
    # it isn't installed. We treat .pub the same as anything else.
    soffice = _find_soffice()
    if not soffice:
        return fail("missing_soffice",
                    "LibreOffice not found. Install LibreOffice to convert Publisher files.")
    out_path = _convert_via_soffice(soffice, src, out_dir, target)
    if out_path is None:
        return fail("convert_failed", f"{src.name}: LibreOffice could not convert .pub.")
    return 0


def op_convert(args: argparse.Namespace) -> int:
    soffice = _find_soffice()
    if not soffice:
        return fail("missing_soffice",
                    "LibreOffice not found. Install LibreOffice "
                    "(`choco install libreoffice-fresh` / `brew install --cask libreoffice` / "
                    "`apt install libreoffice`).")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Document(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in SOFFICE_OUTPUT:
        return fail("bad_format", f"Choose: {sorted(SOFFICE_OUTPUT)}")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="legacy", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = _convert_via_soffice(soffice, src, out_dir, target)
        if out_path is None:
            return fail("convert_failed", f"{src.name}: LibreOffice could not convert.")
        emit("legacy_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, source_ext=src.suffix.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="legacyoffice-sidecar",
                                description="Legacy office document conversion via LibreOffice.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert WordPerfect / AmiPro / Works / Publisher / StarOffice / KOffice / AbiWord / AppleWorks.")
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
