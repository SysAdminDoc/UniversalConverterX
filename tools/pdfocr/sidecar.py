"""PDF OCR sidecar -- wraps `ocrmypdf` to add a searchable text layer to
scanned PDFs, with optional rotation correction, deskew, and image cleanup.

Closes the v2.5 OCR sidecar's deferred scanned-PDF item: the standalone
`ocr` sidecar handles individual images via Tesseract, while this one runs
the full ocrmypdf pipeline (Ghostscript + Tesseract + image cleanup +
unpaper) so each PDF page is OCR'd and the text layer is merged back
without changing the rendered appearance.

Frozen-guard: deps are bundled at build time. ocrmypdf at runtime requires
Tesseract + Ghostscript on PATH (typical setup for both); the wrapper
discovers them via PATH and falls back to standard Program Files dirs.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _imports_ok():
    try:
        import ocrmypdf  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_ocrmypdf",
             message=f"ocrmypdf not installed in this build: {ex}")
        return False


def _ensure_tools_on_path():
    """ocrmypdf shells out to tesseract.exe + gswin64c.exe. If they're not on
    PATH, sniff the standard Windows install dirs and prepend them."""
    extras: list[str] = []
    if not shutil.which("tesseract"):
        for c in (
            r"C:\Program Files\Tesseract-OCR",
            r"C:\Program Files (x86)\Tesseract-OCR",
            os.environ.get("TESSERACT_DIR", ""),
        ):
            if c and Path(c, "tesseract.exe").is_file():
                extras.append(c); break
    if not shutil.which("gswin64c") and not shutil.which("gs"):
        # Pick the highest-numbered Ghostscript install dir.
        import glob
        for pattern in (r"C:\Program Files\gs\gs*\bin",
                        r"C:\Program Files (x86)\gs\gs*\bin"):
            hits = sorted(glob.glob(pattern), reverse=True)
            if hits:
                extras.append(hits[0]); break
    if extras:
        os.environ["PATH"] = os.pathsep.join(extras + [os.environ.get("PATH", "")])


def op_probe(_: argparse.Namespace) -> int:
    try:
        import ocrmypdf  # noqa: F401
        package = True
    except ImportError:
        package = False
    _ensure_tools_on_path()
    tesseract = shutil.which("tesseract") or shutil.which("tesseract.exe")
    ghostscript = shutil.which("gswin64c") or shutil.which("gs")
    available = package and tesseract is not None and ghostscript is not None
    emit(
        "backend", available=available, ocrmypdf=package,
        tesseract=tesseract, ghostscript=ghostscript,
    )
    emit("complete", output="", size_bytes=0, available=available)
    return 0 if available else 1


def op_recognize(args: argparse.Namespace) -> int:
    if not _imports_ok():
        return 1
    _ensure_tools_on_path()
    import ocrmypdf

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"PDF(s) not found: {missing}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    emit("log", level="info",
         message=f"OCR pdf x{total} (lang={args.lang}, "
                 f"deskew={args.deskew}, rotate-pages={args.rotate_pages})")
    emit("progress", percent=0, stage="ocr", eta_seconds=None)

    started = time.monotonic()
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "_ocr.pdf")
        try:
            ocrmypdf.ocr(
                input_file=str(src),
                output_file=str(out_path),
                language=args.lang,
                deskew=args.deskew,
                rotate_pages=args.rotate_pages,
                clean=args.clean,
                clean_final=args.clean,
                optimize=int(args.optimize),
                skip_text=args.skip_text,      # pages with text: skip OCR
                redo_ocr=args.redo_ocr,        # rebuild even if text exists
                force_ocr=args.force_ocr,      # OCR everything regardless
                output_type=args.output_type,  # pdf | pdfa | pdfa-1 | pdfa-2 | pdfa-3
                progress_bar=False,
            )
        except ocrmypdf.exceptions.PriorOcrFoundError:
            emit("log", level="warn",
                 message=f"{src.name}: already OCR'd; pass --redo-ocr to rebuild.")
            continue
        except ocrmypdf.exceptions.MissingDependencyError as ex:
            return fail("missing_dependency", f"{src.name}: {ex}")
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("ocrmypdf_failed", f"ocrmypdf failed on {src.name}: {ex}")

        if not out_path.is_file():
            return fail("output_missing",
                        f"ocrmypdf did not produce output for {src.name}")
        emit("pdf_ocr",
             input=str(src),
             output=str(out_path),
             size_bytes=out_path.stat().st_size)

        pct = (i + 1) / total * 100.0
        elapsed = time.monotonic() - started
        local = pct / 100.0
        eta = (elapsed / local - elapsed) if local > 0.01 else None
        emit("progress",
             percent=round(pct, 1),
             stage=f"OCR'd {i + 1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    total_size = sum((out_dir / (Path(p).stem + "_ocr.pdf")).stat().st_size
                     for p in args.input
                     if (out_dir / (Path(p).stem + "_ocr.pdf")).is_file())
    emit("complete", output=str(out_dir), size_bytes=total_size, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdfocr-sidecar",
                                description="Add a searchable text layer to PDFs via ocrmypdf.")
    sub = p.add_subparsers(dest="op", required=True)

    rec = sub.add_parser("recognize", help="OCR scanned PDFs into searchable PDFs.")
    rec.add_argument("--input", nargs="+", required=True)
    rec.add_argument("--output-dir", required=True, dest="output_dir")
    rec.add_argument("--lang", default="eng",
                     help="Tesseract language code(s); '+'-joined for multi-lang.")
    rec.add_argument("--deskew", action="store_true",
                     help="Auto-correct page skew before OCR.")
    rec.add_argument("--rotate-pages", action="store_true", dest="rotate_pages",
                     help="Auto-rotate sideways/upside-down pages.")
    rec.add_argument("--clean", action="store_true",
                     help="Run unpaper to clean noise/specks before OCR.")
    rec.add_argument("--optimize", type=int, default=1,
                     help="0 (off) -- 3 (jbig2-aggressive). Default 1.")
    rec.add_argument("--skip-text", action="store_true", dest="skip_text",
                     help="Skip pages that already have a text layer.")
    rec.add_argument("--redo-ocr", action="store_true", dest="redo_ocr",
                     help="Rebuild text layer even if one exists.")
    rec.add_argument("--force-ocr", action="store_true", dest="force_ocr",
                     help="OCR everything regardless of existing text.")
    rec.add_argument("--output-type", default="pdf", dest="output_type",
                     help="pdf | pdfa | pdfa-1 | pdfa-2 | pdfa-3 (archival).")

    sub.add_parser("probe", help="Check OCRmyPDF, Tesseract, and Ghostscript availability.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "recognize":
            return op_recognize(args)
        if args.op == "probe":
            return op_probe(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
