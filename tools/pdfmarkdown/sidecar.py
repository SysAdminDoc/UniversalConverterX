"""PDF -> Markdown sidecar.

Four backends, all OSS:

  * pymupdf4llm  -- fast layout-aware extraction built on PyMuPDF (default).
                    No GPU; ~1 s/page; preserves headings + tables.
  * marker       -- LLM-grade conversion via the `marker-pdf` package
                    (transformer pipeline; slower but stronger on
                    multi-column journal articles and scans).
  * docling      -- IBM's docling pipeline (Apache-2.0, 2024). Preserves
                    tables / math / figure refs / formulas. Best on
                    structured documents (research, technical PDFs).
  * mineru       -- magic-pdf / MinerU (Shanghai AI Lab, 2024). Strong on
                    LaTeX math, tables, and OCR'd image-only PDFs.

Default backend = pymupdf4llm. Pick docling for technical PDFs with tables /
math, marker for messy scans, mineru for math-heavy academic content.
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


def _convert_docling(src: Path, out_path: Path) -> int:
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as ex:
        return fail("missing_docling",
                    f"docling not installed: {ex}. `pip install docling`.")
    try:
        converter = DocumentConverter()
        result = converter.convert(str(src))
        text = result.document.export_to_markdown()
        out_path.write_text(text, encoding="utf-8")
    except Exception as ex:
        return fail("convert_failed", f"{src.name}: {ex}")
    return 0


def _convert_mineru(src: Path, out_path: Path) -> int:
    try:
        from magic_pdf.pipe.UNIPipe import UNIPipe
        from magic_pdf.rw.DiskReaderWriter import DiskReaderWriter
        import magic_pdf.model as model_config
        model_config.__use_inside_model__ = True
    except ImportError as ex:
        return fail("missing_mineru",
                    f"magic-pdf (MinerU) not installed: {ex}. `pip install magic-pdf`.")
    try:
        with src.open("rb") as f:
            pdf_bytes = f.read()
        rw = DiskReaderWriter(out_path.parent.as_posix())
        pipe = UNIPipe(pdf_bytes, {"_pdf_type": "", "model_list": []}, rw)
        pipe.pipe_classify()
        pipe.pipe_analyze()
        pipe.pipe_parse()
        md = pipe.pipe_mk_markdown(out_path.parent.as_posix(), drop_mode="none")
        out_path.write_text(md if isinstance(md, str) else "\n".join(md or []),
                            encoding="utf-8")
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
        elif args.backend == "docling":
            rc = _convert_docling(src, out_path)
        elif args.backend == "mineru":
            rc = _convert_mineru(src, out_path)
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
                   choices=["pymupdf4llm", "marker", "docling", "mineru"])
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
