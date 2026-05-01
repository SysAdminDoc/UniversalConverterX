"""PDF -> Markdown sidecar.

Two backends, both Apache/MIT-licensed:

  * pymupdf4llm  -- fast layout-aware extraction built on PyMuPDF.
                    Single shot per file; preserves headings/tables.
  * marker       -- LLM-grade conversion via the `marker-pdf` package
                    (uses a transformer pipeline; slower but better on
                    multi-column journal articles and scans).

Default backend = pymupdf4llm (no GPU dependency, ~1s/page).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _convert_pymupdf4llm(src: Path, out_path: Path, page_chunks: bool) -> int:
    try:
        import pymupdf4llm
    except ImportError as ex:
        return fail("missing_pymupdf4llm",
                    f"pymupdf4llm not installed: {ex}. `pip install pymupdf4llm`.")
    try:
        if page_chunks:
            chunks = pymupdf4llm.to_markdown(str(src), page_chunks=True)
            out_path.write_text(
                "\n\n---\n\n".join(c.get("text", "") if isinstance(c, dict) else str(c)
                                   for c in chunks),
                encoding="utf-8")
        else:
            md = pymupdf4llm.to_markdown(str(src))
            out_path.write_text(md, encoding="utf-8")
    except Exception as ex:
        return fail("convert_failed", f"{src.name}: {ex}")
    return 0


def _convert_marker(src: Path, out_path: Path) -> int:
    try:
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict
        from marker.output import text_from_rendered
    except ImportError as ex:
        return fail("missing_marker",
                    f"marker-pdf not installed: {ex}. `pip install marker-pdf`.")
    try:
        converter = PdfConverter(artifact_dict=create_model_dict())
        rendered = converter(str(src))
        text, _, _ = text_from_rendered(rendered)
        out_path.write_text(text, encoding="utf-8")
    except Exception as ex:
        return fail("convert_failed", f"{src.name}: {ex}")
    return 0


def op_to_md(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"PDF(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="to-md", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".md")
        if args.backend == "marker":
            rc = _convert_marker(src, out_path)
        else:
            rc = _convert_pymupdf4llm(src, out_path, page_chunks=bool(args.page_chunks))
        if rc != 0: return rc

        emit("pdf_md",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             backend=args.backend)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdfmarkdown-sidecar",
                                description="Convert PDFs to Markdown.")
    sub = p.add_subparsers(dest="op", required=True)
    m = sub.add_parser("to-md", help="Convert PDF -> Markdown.")
    m.add_argument("--input", nargs="+", required=True)
    m.add_argument("--output-dir", required=True, dest="output_dir")
    m.add_argument("--backend", default="pymupdf4llm",
                   choices=["pymupdf4llm", "marker"])
    m.add_argument("--page-chunks", action="store_true",
                   help="(pymupdf4llm) emit one chunk per page separated by '---'.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "to-md": return op_to_md(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
