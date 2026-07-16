"""Comic-book archive sidecar.

Convert between the four comic-book container formats (CBZ / CBR / CBT /
CB7) and to readable distribution formats (PDF / EPUB).

  CBZ = ZIP of images          stdlib zipfile
  CBR = RAR of images          rarfile (needs unrar binary on PATH)
  CBT = TAR of images          stdlib tarfile
  CB7 = 7z of images           7z CLI shellout

Operations:
  convert   Re-pack into another comic container (CBZ default).
  to-pdf    Stitch images into a single PDF (img2pdf).
  to-epub   Wrap images in a minimal EPUB (ebooklib).
  info      List entries + dimensions of the cover image.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def _extract(src: Path, dest: Path) -> int:
    """Extract any of CBZ / CBR / CBT / CB7 to a directory."""
    ext = src.suffix.lower()
    try:
        if ext == ".cbz":
            with zipfile.ZipFile(str(src)) as zf:
                zf.extractall(str(dest))
        elif ext == ".cbt":
            with tarfile.open(str(src)) as tf:
                tf.extractall(str(dest))
        elif ext == ".cbr":
            try:
                import rarfile
            except ImportError as ex:
                return fail("missing_rarfile",
                            f"rarfile not installed: {ex}. `pip install rarfile`. "
                            "Also requires `unrar` on PATH.")
            with rarfile.RarFile(str(src)) as rf:
                rf.extractall(str(dest))
        elif ext == ".cb7":
            sz = shutil.which("7z") or shutil.which("7za")
            if not sz: return fail("missing_7zip", "7z not found on PATH.")
            proc = subprocess.run([sz, "x", "-y", f"-o{dest}", str(src)],
                                   capture_output=True, text=True)
            if proc.returncode != 0:
                return fail("7zip_failed", f"{src.name}: rc={proc.returncode}")
        else:
            return fail("bad_format", f"Unknown comic ext: {ext}")
    except Exception as ex:
        return fail("extract_failed", f"{src.name}: {ex}")
    return 0


def _gather_images(folder: Path) -> list[Path]:
    return sorted([p for p in folder.rglob("*")
                   if p.is_file() and p.suffix.lower() in IMAGE_EXTS],
                  key=lambda p: p.as_posix().lower())


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Comic file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")
    if target not in ("cbz", "cbt", "cb7"):
        return fail("bad_target", "Re-pack supports cbz | cbt | cb7. (Writing CBR is not supported by OSS tools.)")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="comic", eta_seconds=None)

    for i, src in enumerate(inputs):
        with tempfile.TemporaryDirectory(prefix="comic_") as tmp:
            tmp_dir = Path(tmp)
            rc = _extract(src, tmp_dir)
            if rc != 0: return rc
            images = _gather_images(tmp_dir)
            if not images:
                return fail("empty", f"{src.name}: no image entries.")

            out_path = out_dir / (src.stem + "." + target)
            try:
                if target == "cbz":
                    with zipfile.ZipFile(str(out_path), "w",
                                          compression=zipfile.ZIP_DEFLATED) as zf:
                        for img in images:
                            zf.write(str(img), arcname=img.name)
                elif target == "cbt":
                    with tarfile.open(str(out_path), "w") as tf:
                        for img in images:
                            tf.add(str(img), arcname=img.name)
                elif target == "cb7":
                    sz = shutil.which("7z") or shutil.which("7za")
                    if not sz: return fail("missing_7zip", "7z not found.")
                    cmd = [sz, "a", "-tzip", str(out_path)] + [str(p) for p in images]
                    cmd[2] = "-t7z"
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    if proc.returncode != 0:
                        return fail("7zip_failed", f"{src.name}: rc={proc.returncode}")
            except Exception as ex:
                return fail("write_failed", f"{src.name}: {ex}")

        emit("comic_book",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, pages=len(images))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_pdf(args: argparse.Namespace) -> int:
    try:
        import img2pdf
    except ImportError as ex:
        return fail("missing_img2pdf",
                    f"img2pdf not installed: {ex}. `pip install img2pdf`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Comic file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="to-pdf", eta_seconds=None)

    for i, src in enumerate(inputs):
        with tempfile.TemporaryDirectory(prefix="comic_") as tmp:
            tmp_dir = Path(tmp)
            rc = _extract(src, tmp_dir)
            if rc != 0: return rc
            images = _gather_images(tmp_dir)
            if not images:
                return fail("empty", f"{src.name}: no images.")
            out_path = out_dir / (src.stem + ".pdf")
            try:
                with out_path.open("wb") as f:
                    f.write(img2pdf.convert([str(p) for p in images]))
            except Exception as ex:
                return fail("pdf_failed", f"{src.name}: {ex}")
        emit("comic_book",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="pdf", pages=len(images))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_epub(args: argparse.Namespace) -> int:
    try:
        from ebooklib import epub
    except ImportError as ex:
        return fail("missing_ebooklib",
                    f"ebooklib not installed: {ex}. `pip install EbookLib`.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Comic file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        with tempfile.TemporaryDirectory(prefix="comic_") as tmp:
            tmp_dir = Path(tmp)
            rc = _extract(src, tmp_dir)
            if rc != 0: return rc
            images = _gather_images(tmp_dir)
            if not images:
                return fail("empty", f"{src.name}: no images.")

            book = epub.EpubBook()
            book.set_identifier(src.stem)
            book.set_title(src.stem)
            book.set_language("en")
            chapters = []
            for n, img in enumerate(images):
                ext = img.suffix.lstrip(".").lower()
                with img.open("rb") as f:
                    data = f.read()
                ei = epub.EpubItem(uid=f"img_{n:03d}",
                                    file_name=f"images/{n:03d}.{ext}",
                                    media_type=f"image/{ext}",
                                    content=data)
                book.add_item(ei)
                ch = epub.EpubHtml(title=f"Page {n+1}",
                                    file_name=f"page_{n:03d}.xhtml")
                ch.content = (f'<html><body><img src="images/{n:03d}.{ext}" '
                              f'alt="Page {n+1}"/></body></html>')
                book.add_item(ch); chapters.append(ch)
            book.toc = tuple(chapters)
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            book.spine = ["nav"] + chapters

            out_path = out_dir / (src.stem + ".epub")
            try:
                epub.write_epub(str(out_path), book)
            except Exception as ex:
                return fail("epub_failed", f"{src.name}: {ex}")

        emit("comic_book",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="epub", pages=len(images))
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="comic-sidecar",
                                description="Comic book archive conversion (CBZ / CBR / CBT / CB7 + PDF + EPUB).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Re-pack comic archive (cbz/cbt/cb7).")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", default="cbz", choices=["cbz", "cbt", "cb7"])

    pdf = sub.add_parser("to-pdf", help="Stitch comic images into PDF.")
    pdf.add_argument("--input", nargs="+", required=True)
    pdf.add_argument("--output-dir", required=True, dest="output_dir")

    ep = sub.add_parser("to-epub", help="Wrap comic in EPUB.")
    ep.add_argument("--input", nargs="+", required=True)
    ep.add_argument("--output-dir", required=True, dest="output_dir")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "to-pdf":  return op_to_pdf(args)
        if args.op == "to-epub": return op_to_epub(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
