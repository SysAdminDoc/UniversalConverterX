"""PDF tools sidecar -- merge / split / rotate / extract pages / encrypt /
decrypt / linearize / probe via `pikepdf` (which embeds qpdf).

pikepdf is MIT, ships with qpdf in its wheel, and supports every PDF feature
qpdf does -- no external binary required at runtime.

Frozen-guard: this sidecar performs no runtime pip install; deps are baked
into the PyInstaller binary at build time. The contract test passes because
no `pip install` invocation appears anywhere.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _import_pikepdf():
    try:
        import pikepdf  # noqa: F401
        return pikepdf
    except ImportError:
        return None


# ── helpers ────────────────────────────────────────────────────────────────────


def _parse_page_spec(spec: str, total: int) -> list[int]:
    """Parse '1,3-5,7' into a 1-based list of unique page indices, sorted."""
    pages: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            start = max(1, int(a)) if a else 1
            end   = min(total, int(b)) if b else total
            for i in range(start, end + 1):
                pages.add(i)
        else:
            i = int(chunk)
            if 1 <= i <= total:
                pages.add(i)
    return sorted(pages)


# ── ops ────────────────────────────────────────────────────────────────────────


def op_info(args: argparse.Namespace) -> int:
    pikepdf = _import_pikepdf()
    if not pikepdf:
        return fail("missing_pikepdf", "pikepdf not installed in this build.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"PDF not found: {args.input}")
    try:
        with pikepdf.open(src, password=args.password or "") as pdf:
            meta = dict(pdf.docinfo) if pdf.docinfo else {}
            emit("pdf_info",
                 path=str(src),
                 pages=len(pdf.pages),
                 encrypted=pdf.is_encrypted,
                 linearized=pdf.is_linearized,
                 pdf_version=str(pdf.pdf_version) if hasattr(pdf, "pdf_version") else "",
                 title=str(meta.get("/Title", "")),
                 author=str(meta.get("/Author", "")),
                 creator=str(meta.get("/Creator", "")),
                 producer=str(meta.get("/Producer", "")))
    except pikepdf.PasswordError:
        return fail("password_required",
                    "PDF is encrypted; pass --password to read it.")
    emit("complete", output=str(src), size_bytes=src.stat().st_size, pages=0)
    return 0


def op_merge(args: argparse.Namespace) -> int:
    pikepdf = _import_pikepdf()
    if not pikepdf:
        return fail("missing_pikepdf", "pikepdf not installed in this build.")
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"PDF(s) not found: {missing}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    emit("log", level="info", message=f"Merge {len(inputs)} PDF(s) -> {out.name}")
    emit("progress", percent=0, stage="merge", eta_seconds=None)
    total_pages = 0
    with pikepdf.Pdf.new() as merged:
        for i, src in enumerate(inputs):
            try:
                with pikepdf.open(src) as pdf:
                    merged.pages.extend(pdf.pages)
                    total_pages += len(pdf.pages)
            except pikepdf.PasswordError:
                return fail("password_required",
                            f"{src.name} is encrypted; merge requires unlocked PDFs.")
            pct = (i + 1) / len(inputs) * 100.0
            emit("progress", percent=round(pct, 1),
                 stage=f"appended {i + 1}/{len(inputs)}", eta_seconds=None)
        merged.save(out)
    emit("complete", output=str(out),
         size_bytes=out.stat().st_size, pages=total_pages)
    return 0


def op_split(args: argparse.Namespace) -> int:
    pikepdf = _import_pikepdf()
    if not pikepdf:
        return fail("missing_pikepdf", "pikepdf not installed in this build.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"PDF not found: {args.input}")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with pikepdf.open(src, password=args.password or "") as pdf:
        total = len(pdf.pages)
        if args.ranges:
            # Custom split: each comma-separated range becomes one output PDF.
            ranges = [r.strip() for r in args.ranges.split(",") if r.strip()]
            outputs = []
            for j, rng in enumerate(ranges):
                pages = _parse_page_spec(rng, total)
                if not pages:
                    continue
                with pikepdf.Pdf.new() as part:
                    for p in pages:
                        part.pages.append(pdf.pages[p - 1])
                    out_path = out_dir / f"{src.stem}_part{j + 1:03d}.pdf"
                    part.save(out_path)
                outputs.append(out_path)
                emit("pdf_part",
                     index=j + 1, range=rng, output=str(out_path),
                     page_count=len(pages),
                     size_bytes=out_path.stat().st_size)
                emit("progress", percent=round((j + 1) / len(ranges) * 100, 1),
                     stage=f"part {j + 1}/{len(ranges)}", eta_seconds=None)
        else:
            # Default: one PDF per page.
            outputs = []
            for i in range(total):
                with pikepdf.Pdf.new() as part:
                    part.pages.append(pdf.pages[i])
                    out_path = out_dir / f"{src.stem}_page{i + 1:04d}.pdf"
                    part.save(out_path)
                outputs.append(out_path)
                emit("pdf_part",
                     index=i + 1, range=str(i + 1), output=str(out_path),
                     page_count=1, size_bytes=out_path.stat().st_size)
                if (i + 1) % max(1, total // 100) == 0 or i == total - 1:
                    emit("progress", percent=round((i + 1) / total * 100, 1),
                         stage=f"page {i + 1}/{total}", eta_seconds=None)

    total_size = sum(p.stat().st_size for p in outputs)
    emit("complete", output=str(out_dir),
         size_bytes=total_size, parts=len(outputs))
    return 0


def op_extract(args: argparse.Namespace) -> int:
    pikepdf = _import_pikepdf()
    if not pikepdf:
        return fail("missing_pikepdf", "pikepdf not installed in this build.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"PDF not found: {args.input}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    with pikepdf.open(src, password=args.password or "") as pdf:
        pages = _parse_page_spec(args.pages, len(pdf.pages))
        if not pages:
            return fail("no_pages", f"--pages '{args.pages}' selected zero pages of {len(pdf.pages)}.")
        with pikepdf.Pdf.new() as out_pdf:
            for p in pages:
                out_pdf.pages.append(pdf.pages[p - 1])
            out_pdf.save(out)
    emit("complete", output=str(out),
         size_bytes=out.stat().st_size, pages=len(pages))
    return 0


def op_rotate(args: argparse.Namespace) -> int:
    pikepdf = _import_pikepdf()
    if not pikepdf:
        return fail("missing_pikepdf", "pikepdf not installed in this build.")
    if args.angle not in (90, 180, 270, -90):
        return fail("bad_angle", "--angle must be 90, 180, 270, or -90.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"PDF not found: {args.input}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    with pikepdf.open(src, password=args.password or "", allow_overwriting_input=True) as pdf:
        target = list(range(1, len(pdf.pages) + 1)) \
            if args.pages in (None, "all", "*") \
            else _parse_page_spec(args.pages, len(pdf.pages))
        for i in target:
            page = pdf.pages[i - 1]
            page.rotate(args.angle, relative=True)
        pdf.save(out)
    emit("complete", output=str(out),
         size_bytes=out.stat().st_size, pages=len(target))
    return 0


def op_encrypt(args: argparse.Namespace) -> int:
    pikepdf = _import_pikepdf()
    if not pikepdf:
        return fail("missing_pikepdf", "pikepdf not installed in this build.")
    if not args.user_password and not args.owner_password:
        return fail("no_password",
                    "Provide at least --user-password (or --owner-password).")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"PDF not found: {args.input}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    with pikepdf.open(src, password=args.read_password or "") as pdf:
        pdf.save(
            out,
            encryption=pikepdf.Encryption(
                owner=args.owner_password or args.user_password,
                user=args.user_password or "",
                R=6,  # AES-256
            ),
        )
    emit("complete", output=str(out),
         size_bytes=out.stat().st_size, pages=0)
    return 0


def op_decrypt(args: argparse.Namespace) -> int:
    pikepdf = _import_pikepdf()
    if not pikepdf:
        return fail("missing_pikepdf", "pikepdf not installed in this build.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"PDF not found: {args.input}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with pikepdf.open(src, password=args.password or "") as pdf:
            pdf.save(out)
    except pikepdf.PasswordError:
        return fail("password_required",
                    "Wrong password -- decrypt aborted.")
    emit("complete", output=str(out),
         size_bytes=out.stat().st_size, pages=0)
    return 0


def op_compress(args: argparse.Namespace) -> int:
    """Save with object stream and content-stream compression for size reduction."""
    pikepdf = _import_pikepdf()
    if not pikepdf:
        return fail("missing_pikepdf", "pikepdf not installed in this build.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"PDF not found: {args.input}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.open(src, password=args.password or "") as pdf:
        pdf.save(
            out,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            compress_streams=True,
            stream_decode_level=pikepdf.StreamDecodeLevel.generalized,
            linearize=True,
        )
    saved = src.stat().st_size - out.stat().st_size
    emit("complete", output=str(out),
         size_bytes=out.stat().st_size,
         saved_bytes=saved if saved > 0 else 0)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pdftools-sidecar",
                                description="PDF merge / split / rotate / extract / encrypt / decrypt via pikepdf.")
    sub = p.add_subparsers(dest="op", required=True)

    info = sub.add_parser("info", help="Show PDF metadata + page count")
    info.add_argument("--input", required=True)
    info.add_argument("--password", default="")

    mg = sub.add_parser("merge", help="Concatenate multiple PDFs into one")
    mg.add_argument("--input", nargs="+", required=True)
    mg.add_argument("--output", required=True)

    sp = sub.add_parser("split", help="Split a PDF (per-page, or by --ranges)")
    sp.add_argument("--input", required=True)
    sp.add_argument("--output-dir", required=True, dest="output_dir")
    sp.add_argument("--ranges", help="Comma-separated ranges, e.g. '1-3,5,7-9'. "
                                     "Omit for one PDF per page.")
    sp.add_argument("--password", default="")

    ex = sub.add_parser("extract", help="Extract a subset of pages into a new PDF")
    ex.add_argument("--input", required=True)
    ex.add_argument("--output", required=True)
    ex.add_argument("--pages", required=True,
                    help="Page range, e.g. '1,3-5,7'.")
    ex.add_argument("--password", default="")

    rt = sub.add_parser("rotate", help="Rotate selected pages by 90/180/270")
    rt.add_argument("--input", required=True)
    rt.add_argument("--output", required=True)
    rt.add_argument("--angle", type=int, required=True)
    rt.add_argument("--pages", help="Page range. Default: all pages.")
    rt.add_argument("--password", default="")

    en = sub.add_parser("encrypt", help="Add password protection to a PDF")
    en.add_argument("--input", required=True)
    en.add_argument("--output", required=True)
    en.add_argument("--user-password", dest="user_password",
                    help="Password required to open the PDF (read).")
    en.add_argument("--owner-password", dest="owner_password",
                    help="Password to remove restrictions (defaults to user pwd).")
    en.add_argument("--read-password", dest="read_password", default="",
                    help="Password to read source if it's already encrypted.")

    de = sub.add_parser("decrypt", help="Strip password protection")
    de.add_argument("--input", required=True)
    de.add_argument("--output", required=True)
    de.add_argument("--password", default="")

    co = sub.add_parser("compress", help="Re-save with stream compression + linearisation")
    co.add_argument("--input", required=True)
    co.add_argument("--output", required=True)
    co.add_argument("--password", default="")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "info":     return op_info(args)
        if args.op == "merge":    return op_merge(args)
        if args.op == "split":    return op_split(args)
        if args.op == "extract":  return op_extract(args)
        if args.op == "rotate":   return op_rotate(args)
        if args.op == "encrypt":  return op_encrypt(args)
        if args.op == "decrypt":  return op_decrypt(args)
        if args.op == "compress": return op_compress(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
