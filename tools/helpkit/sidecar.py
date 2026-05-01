"""Compiled Help (CHM / HLP) sidecar.

Operations:
  extract   Crack open .chm and dump the contained HTML / images / TOC.
  to-pdf    Stitch the extracted HTML into a single PDF (chm2pdf-style).
  to-epub   Wrap the HTML pages into a navigable EPUB.

Backend: chmlib via the Python `pychm` (Linux/macOS) OR the cross-platform
`extract_chmLib` binary from the `archmage` project. We fall back to 7z
which has a `chm` extractor compiled in.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _extract_via_7zip(src: Path, dest: Path) -> int:
    sz = shutil.which("7z") or shutil.which("7za")
    if not sz:
        return fail("missing_7zip",
                    "7z not found on PATH. Install p7zip / 7-Zip.")
    cmd = [sz, "x", "-y", f"-o{dest}", str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("7zip_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def _gather_html(folder: Path) -> list[Path]:
    return sorted([p for p in folder.rglob("*")
                   if p.is_file() and p.suffix.lower() in {".html", ".htm"}],
                  key=lambda p: p.as_posix().lower())


def op_extract(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CHM file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="extract", eta_seconds=None)

    for i, src in enumerate(inputs):
        target = out_dir / src.stem
        target.mkdir(parents=True, exist_ok=True)
        rc = _extract_via_7zip(src, target)
        if rc != 0: return rc
        size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
        html_files = _gather_html(target)
        emit("help_doc",
             input=str(src), output=str(target),
             size_bytes=size, format="chm-extracted",
             html_count=len(html_files))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_pdf(args: argparse.Namespace) -> int:
    """CHM -> single PDF via pdfkit (wkhtmltopdf) or weasyprint."""
    try:
        from weasyprint import HTML
    except ImportError as ex:
        return fail("missing_weasyprint",
                    f"weasyprint not installed: {ex}. `pip install weasyprint`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CHM(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        with tempfile.TemporaryDirectory(prefix="chm_") as tmp:
            tmp_dir = Path(tmp)
            rc = _extract_via_7zip(src, tmp_dir)
            if rc != 0: return rc
            html_files = _gather_html(tmp_dir)
            if not html_files:
                return fail("empty", f"{src.name}: no HTML files extracted.")
            # Concatenate HTML into a synthetic doc, then PDF it.
            combined = "\n<hr/>\n".join(p.read_text(encoding="utf-8", errors="replace")
                                          for p in html_files)
            wrapper = f"<html><body>{combined}</body></html>"
            out_path = out_dir / (src.stem + ".pdf")
            try:
                HTML(string=wrapper, base_url=str(tmp_dir)).write_pdf(str(out_path))
            except Exception as ex:
                return fail("pdf_failed", f"{src.name}: {ex}")
        emit("help_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="pdf", html_count=len(html_files))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="helpkit-sidecar",
                                description="Compiled Help (CHM) extraction + PDF.")
    sub = p.add_subparsers(dest="op", required=True)
    e = sub.add_parser("extract", help="Extract .chm to a directory of HTML.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    pdf = sub.add_parser("to-pdf", help="CHM -> single PDF.")
    pdf.add_argument("--input", nargs="+", required=True)
    pdf.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "extract": return op_extract(args)
        if args.op == "to-pdf":  return op_to_pdf(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
