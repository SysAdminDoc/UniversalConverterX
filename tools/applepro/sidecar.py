"""Apple iWork sidecar.

Convert Apple Pages / Numbers / Keynote (.pages, .numbers, .key) to
universal formats. iWork files are technically zip bundles containing a
mix of XML (older) and Apple-proprietary IWA / Snappy compression
(modern -- since 2013). We try LibreOffice first (it can crack older
iWork up to ~2009), then fall back to bundle extraction so the user at
least gets the embedded preview PDF / images that every iWork file
carries.

Outputs:
  pdf | docx | odt | rtf | html | txt | preview-only
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
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
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/libreoffice", "/usr/bin/soffice",
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
    "xlsx": "xlsx:Calc Office Open XML",
    "ods":  "ods:calc8",
    "csv":  "csv:Text - txt - csv (StarCalc)",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "odp":  "odp:impress8",
}


def _convert_via_soffice(soffice: str, src: Path, out_dir: Path,
                          target: str) -> Path | None:
    out_filter = SOFFICE_OUTPUT.get(target)
    if not out_filter: return None
    cmd = [soffice, "--headless", "--norestore",
           "--convert-to", out_filter,
           "--outdir", str(out_dir), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0: return None
    expected = out_dir / (src.stem + "." + target)
    return expected if expected.is_file() else None


def _extract_preview(src: Path, out_dir: Path) -> Path | None:
    """Every iWork bundle ships a `QuickLook/Preview.pdf` (or .jpg). Pull it."""
    try:
        with zipfile.ZipFile(str(src)) as zf:
            for name in zf.namelist():
                lower = name.lower()
                if lower.endswith(("quicklook/preview.pdf", "preview.pdf",
                                   "preview-web.pdf")):
                    out_path = out_dir / (src.stem + "_preview.pdf")
                    out_path.write_bytes(zf.read(name))
                    return out_path
            for name in zf.namelist():
                lower = name.lower()
                if "preview" in lower and lower.endswith((".jpg", ".jpeg", ".png")):
                    out_path = out_dir / (src.stem + "_preview" + Path(lower).suffix)
                    out_path.write_bytes(zf.read(name))
                    return out_path
    except zipfile.BadZipFile:
        return None
    return None


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"iWork file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")

    soffice = _find_soffice()
    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="iwork", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path: Path | None = None
        method = ""
        if target != "preview-only" and soffice:
            out_path = _convert_via_soffice(soffice, src, out_dir, target)
            if out_path is not None: method = "libreoffice"
        if out_path is None:
            # Fall back to embedded preview extraction (always works for
            # modern iWork, since every bundle ships a Preview.pdf).
            out_path = _extract_preview(src, out_dir)
            if out_path is not None: method = "preview-bundle"
        if out_path is None:
            return fail("convert_failed",
                        f"{src.name}: LibreOffice could not convert and no embedded "
                        "preview was found. Modern iWork (post-2013) often needs "
                        "Apple's own Pages/Numbers/Keynote on macOS.")

        emit("iwork_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=out_path.suffix.lstrip("."),
             method=method, source_ext=src.suffix.lstrip("."))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="applepro-sidecar",
                                description="Apple iWork (Pages / Numbers / Keynote) conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert .pages / .numbers / .key files.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="pdf | docx | odt | rtf | html | txt | xlsx | ods | csv | "
                        "pptx | odp | preview-only")
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
