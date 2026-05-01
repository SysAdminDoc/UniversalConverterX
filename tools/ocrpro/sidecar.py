"""Pro OCR sidecar -- Surya 0.6+ layout + text + tables + math.

Surya (datalab.to, Apache-2.0) is the SOTA OSS OCR pipeline: it handles
layout analysis, paragraph reflow, table extraction, and math equation
recognition across 90+ languages. Outperforms Tesseract on photographs of
documents and on multi-column / non-Latin scripts.

Operations:
  text       Recognize text (plain JSON or markdown)
  layout     Detect paragraphs / titles / tables / figures (JSON)
  tables     Extract structured tables to JSON / CSV
  ordering   Reading-order detection
  full       Layout + text + tables in one pass (markdown output)
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


def _check():
    try:
        import surya  # noqa: F401
        return True
    except ImportError as ex:
        emit("error", code="missing_surya",
             message=f"Surya not installed: {ex}. `pip install surya-ocr`.")
        return False


def _load_image(path: Path):
    from PIL import Image
    if path.suffix.lower() == ".pdf":
        from pdf2image import convert_from_path
        return convert_from_path(str(path), dpi=200)
    return [Image.open(str(path)).convert("RGB")]


def op_text(args: argparse.Namespace) -> int:
    if not _check(): return 1
    from surya.recognition import RecognitionPredictor
    from surya.detection import DetectionPredictor

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image/PDF(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rec = RecognitionPredictor()
    det = DetectionPredictor()
    langs = args.languages.split(",") if args.languages else ["en"]

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="ocr", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            pages = _load_image(src)
            results = rec(pages, [langs] * len(pages), det)
        except Exception as ex:
            return fail("ocr_failed", f"{src.name}: {ex}")

        # Collect all detected text lines into a single document.
        markdown_lines: list[str] = []
        json_pages: list[dict] = []
        for page_idx, r in enumerate(results, 1):
            json_pages.append({
                "page": page_idx,
                "lines": [{"text": ln.text,
                           "confidence": float(getattr(ln, "confidence", 0.0)),
                           "bbox": list(map(float, ln.bbox)) if ln.bbox else None}
                          for ln in r.text_lines],
            })
            markdown_lines.append(f"## Page {page_idx}")
            markdown_lines.extend(ln.text for ln in r.text_lines)
            markdown_lines.append("")

        if args.format == "json":
            out_path = out_dir / (src.stem + ".json")
            out_path.write_text(json.dumps(json_pages, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        else:
            out_path = out_dir / (src.stem + ".md")
            out_path.write_text("\n".join(markdown_lines), encoding="utf-8")

        emit("ocr_pro",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             pages=len(results), backend="surya",
             format=args.format)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_layout(args: argparse.Namespace) -> int:
    if not _check(): return 1
    from surya.layout import LayoutPredictor
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Image/PDF(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pred = LayoutPredictor()
    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            pages = _load_image(src)
            results = pred(pages)
        except Exception as ex:
            return fail("layout_failed", f"{src.name}: {ex}")
        out_path = out_dir / (src.stem + "_layout.json")
        payload = []
        for page_idx, r in enumerate(results, 1):
            payload.append({
                "page": page_idx,
                "boxes": [{"label": b.label,
                           "confidence": float(b.confidence),
                           "bbox": list(map(float, b.bbox))}
                          for b in r.bboxes],
            })
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        emit("ocr_pro",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             pages=len(results), backend="surya-layout")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ocrpro-sidecar",
                                description="Surya OCR (text, layout, tables, math).")
    sub = p.add_subparsers(dest="op", required=True)

    t = sub.add_parser("text", help="Recognize text on each page.")
    t.add_argument("--input", nargs="+", required=True)
    t.add_argument("--output-dir", required=True, dest="output_dir")
    t.add_argument("--languages", default="en",
                   help="Comma-separated language codes (en,fr,de,zh,ja,...).")
    t.add_argument("--format", default="markdown",
                   choices=["markdown", "json"])

    l = sub.add_parser("layout", help="Detect layout regions only.")
    l.add_argument("--input", nargs="+", required=True)
    l.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "text":   return op_text(args)
        if args.op == "layout": return op_layout(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
