"""Comic-book archive sidecar.

Convert between the four comic-book container formats (CBZ / CBR / CBT /
CB7) and to readable, device-profiled distribution formats (PDF / EPUB /
MOBI).

  CBZ = ZIP of images          stdlib zipfile
  CBR = RAR of images          rarfile, with 7z fallback when unrar is absent
  CBT = TAR of images          stdlib tarfile
  CB7 = 7z of images           7z CLI shellout

Operations:
  convert   Re-pack into another comic container (CBZ default).
  to-pdf    Stitch images into a single PDF (img2pdf).
  to-epub   Wrap images in a generic EPUB (ebooklib).
  to-device Build a KCC-compatible, device-profiled EPUB or MOBI.
  info      List entries + dimensions of the cover image.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, safe_extract_path, safe_tar_extractall




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

DEVICE_PROFILES = {
    "generic": {"max_width": 1600, "max_height": 2400,
                 "jpeg_quality": 92, "calibre_profile": "tablet"},
    "kobo": {"max_width": 1404, "max_height": 1872,
             "jpeg_quality": 88, "calibre_profile": "tablet"},
    "kindle": {"max_width": 1264, "max_height": 1680,
                "jpeg_quality": 85, "calibre_profile": "kindle_pw3"},
}


def _safe_zip_extractall(archive: zipfile.ZipFile, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for info in archive.infolist():
        target = safe_extract_path(dest, info.filename)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        # ZIP symlinks are represented in the Unix mode bits. Never materialise
        # one while staging an untrusted comic archive.
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f"unsafe ZIP symlink rejected: {info.filename!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as output:
            output.write(archive.read(info))


def _extract_rar_with_7zip(src: Path, dest: Path, reason: str) -> int:
    seven_zip = shutil.which("7z") or shutil.which("7za")
    if not seven_zip:
        return fail("missing_rarfile", reason + " Also requires unrar or 7z on PATH.")
    proc = subprocess.run(
        [seven_zip, "x", "-y", f"-o{dest}", str(src)],
        capture_output=True,
        text=True,
        timeout=600,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
        return fail("rar_extract_failed",
                    f"{src.name}: 7z exit {proc.returncode}"
                    + (f": {detail[0]}" if detail else ""))
    return 0


def _extract(src: Path, dest: Path) -> int:
    """Extract any of CBZ / CBR / CBT / CB7 to a directory."""
    ext = src.suffix.lower()
    try:
        if ext == ".cbz":
            with zipfile.ZipFile(str(src)) as zf:
                _safe_zip_extractall(zf, dest)
        elif ext == ".cbt":
            with tarfile.open(str(src)) as tf:
                safe_tar_extractall(tf, dest)
        elif ext == ".cbr":
            # A few libraries use the .cbr label for a ZIP-compatible archive.
            # Accept that form without weakening the real RAR path below.
            if zipfile.is_zipfile(str(src)):
                with zipfile.ZipFile(str(src)) as zf:
                    _safe_zip_extractall(zf, dest)
                return 0
            try:
                import rarfile
                with rarfile.RarFile(str(src)) as rf:
                    for info in rf.infolist():
                        safe_extract_path(dest, info.filename)
                    rf.extractall(str(dest))
            except ImportError as ex:
                return _extract_rar_with_7zip(
                    src, dest,
                    f"rarfile not installed: {ex}. `pip install rarfile`.")
            except ValueError as ex:
                return fail("unsafe_archive", f"{src.name}: {ex}")
            except Exception as ex:
                return _extract_rar_with_7zip(
                    src, dest,
                    f"rarfile could not extract {src.name}: {ex}.")
        elif ext == ".cb7":
            sz = shutil.which("7z") or shutil.which("7za")
            if not sz: return fail("missing_7zip", "7z not found on PATH.")
            proc = subprocess.run([sz, "x", "-y", f"-o{dest}", str(src)],
                                   capture_output=True, text=True, timeout=600)
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


def _comic_metadata(folder: Path, fallback: str) -> tuple[str, list[str], str]:
    metadata_path = next((path for path in folder.rglob("*")
                          if path.is_file() and path.name.lower() == "comicinfo.xml"), None)
    if metadata_path is None:
        return fallback, [], "en"
    try:
        root = ET.parse(str(metadata_path)).getroot()
        values = {
            child.tag.rsplit("}", 1)[-1].lower(): (child.text or "").strip()
            for child in root
        }
        title = values.get("title") or fallback
        authors = [value for key in ("writer", "author")
                   if (value := values.get(key))]
        language = values.get("language") or "en"
        return title, authors, language
    except (OSError, ET.ParseError):
        return fallback, [], "en"


def _prepare_device_image(source: Path, destination: Path, profile: dict) -> tuple[int, int]:
    from PIL import Image, ImageOps

    with Image.open(str(source)) as original:
        image = ImageOps.exif_transpose(original)
        image.thumbnail((profile["max_width"], profile["max_height"]), Image.Resampling.LANCZOS)
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(destination), format="JPEG", quality=profile["jpeg_quality"],
                   optimize=True, progressive=True)
        return image.width, image.height


def _write_epub(
    image_data: list[tuple[Path, int, int]],
    destination: Path,
    title: str,
    authors: list[str],
    language: str,
    profile_name: str,
) -> None:
    from ebooklib import epub

    profile = DEVICE_PROFILES[profile_name]
    book = epub.EpubBook()
    book.set_identifier("ucx-" + re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80])
    book.set_title(title)
    book.set_language(language)
    for author in authors:
        book.add_author(author)
    css = epub.EpubItem(
        uid="device-style",
        file_name="styles/device.css",
        media_type="text/css",
        content=(
            "html, body { margin: 0; padding: 0; background: #fff; }\n"
            "body { text-align: center; }\n"
            "img.page { display: block; width: 100%; height: auto; "
            "max-height: 100vh; object-fit: contain; }\n"
            f"/* UCX device profile: {profile_name}; max {profile['max_width']}x"
            f"{profile['max_height']} */\n"
        ).encode("utf-8"),
    )
    book.add_item(css)

    chapters = []
    for index, (image, width, height) in enumerate(image_data):
        image_item = epub.EpubItem(
            uid=f"img_{index:04d}",
            file_name=f"images/{index:04d}.jpg",
            media_type="image/jpeg",
            content=image.read_bytes(),
        )
        book.add_item(image_item)
        chapter = epub.EpubHtml(
            title=f"Page {index + 1}",
            file_name=f"page_{index:04d}.xhtml",
            lang=language,
        )
        chapter.add_link(href="styles/device.css", rel="stylesheet", type="text/css")
        chapter.content = (
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            f"<head><title>Page {index + 1}</title></head><body>"
            f'<img class="page" src="images/{index:04d}.jpg" '
            f'alt="Page {index + 1}" width="{width}" height="{height}"/>'
            "</body></html>"
        )
        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters
    epub.write_epub(str(destination), book)


def _find_calibre() -> str | None:
    env_path = os.environ.get("CALIBRE_PATH")
    if env_path and Path(env_path).is_file():
        return env_path
    for name in ("ebook-convert.exe", "ebook-convert"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files\Calibre2\ebook-convert.exe",
        r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",
        r"C:\Program Files\Calibre\ebook-convert.exe",
        str(Path(__file__).resolve().parent / "Calibre" / "ebook-convert.exe"),
    ]
    if os.name != "nt":
        candidates.extend([
            "/usr/bin/ebook-convert",
            "/usr/local/bin/ebook-convert",
            "/Applications/calibre.app/Contents/MacOS/ebook-convert",
        ])
    return next((candidate for candidate in candidates if Path(candidate).is_file()), None)


def _calibre_environment(job_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("CALIBRE_DEVELOP_FROM", "PYTHONHOME", "PYTHONPATH"):
        env.pop(name, None)
    for name, child in {
        "CALIBRE_CONFIG_DIRECTORY": job_dir / "config",
        "CALIBRE_CACHE_DIRECTORY": job_dir / "cache",
        "CALIBRE_TEMP_DIR": job_dir / "temp",
    }.items():
        child.mkdir(parents=True, exist_ok=True)
        env[name] = str(child)
    env["CALIBRE_ALLOW_PYTHON_TEMPLATES"] = "0"
    return env


def _device_output_path(src: Path, out_dir: Path, target: str,
                        profile_name: str, legacy_name: bool) -> Path:
    suffix = "" if legacy_name or profile_name == "generic" else "." + profile_name
    return out_dir / f"{src.stem}{suffix}.{target}"


def _convert_epub_to_mobi(
    calibre: str,
    source: Path,
    destination: Path,
    profile_name: str,
    job_dir: Path,
) -> None:
    staged = job_dir / "device-output.mobi"
    command = [calibre, str(source), str(staged),
               "--output-profile", DEVICE_PROFILES[profile_name]["calibre_profile"]]
    completed = subprocess.run(
        command,
        cwd=str(job_dir),
        env=_calibre_environment(job_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=900,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        detail = (completed.stdout or "").strip().splitlines()[-1:]
        raise RuntimeError(
            f"ebook-convert exited {completed.returncode}"
            + (f": {detail[0]}" if detail else ""))
    if not staged.is_file() or staged.stat().st_size == 0:
        raise RuntimeError("Calibre did not produce a non-empty MOBI output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, destination)


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
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
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


def op_to_device(args: argparse.Namespace) -> int:
    try:
        import ebooklib  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as ex:
        package = "EbookLib" if "ebooklib" in str(ex).lower() else "Pillow"
        return fail("missing_device_dependency",
                    f"{package} is required for device comic output: {ex}")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss:
        return fail("missing_input", f"Comic file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = str(getattr(args, "format", "epub")).lower()
    profile_name = str(getattr(args, "profile", "generic")).lower()
    if target not in ("epub", "mobi"):
        return fail("bad_target", "Device comic output supports epub | mobi.")
    if profile_name not in DEVICE_PROFILES:
        return fail("bad_profile", "Device profile must be generic | kobo | kindle.")

    calibre = _find_calibre() if target == "mobi" else None
    if target == "mobi" and calibre is None:
        return fail(
            "missing_calibre",
            "Calibre is required for device-profiled MOBI output. Install Calibre "
            "or set $env:CALIBRE_PATH.")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage=f"to-{profile_name}-{target}", eta_seconds=None)
    for index, src in enumerate(inputs):
        with tempfile.TemporaryDirectory(prefix="comic-device-") as tmp:
            tmp_dir = Path(tmp)
            rc = _extract(src, tmp_dir)
            if rc != 0:
                return rc
            images = _gather_images(tmp_dir)
            if not images:
                return fail("empty", f"{src.name}: no images.")

            profile = DEVICE_PROFILES[profile_name]
            prepared_dir = tmp_dir / "prepared"
            prepared: list[tuple[Path, int, int]] = []
            try:
                for page, image in enumerate(images):
                    prepared_path = prepared_dir / f"{page:04d}.jpg"
                    width, height = _prepare_device_image(image, prepared_path, profile)
                    prepared.append((prepared_path, width, height))
                title, authors, language = _comic_metadata(tmp_dir, src.stem)
                epub_path = tmp_dir / "comic.epub"
                _write_epub(prepared, epub_path, title, authors, language, profile_name)
            except Exception as ex:
                return fail("epub_failed", f"{src.name}: {ex}")

            out_path = _device_output_path(
                src, out_dir, target, profile_name,
                bool(getattr(args, "legacy_name", False)),
            )
            try:
                if target == "epub":
                    if not epub_path.is_file() or epub_path.stat().st_size == 0:
                        raise RuntimeError("EPUB writer produced an empty output")
                    os.replace(epub_path, out_path)
                else:
                    assert calibre is not None
                    _convert_epub_to_mobi(calibre, epub_path, out_path, profile_name, tmp_dir)
            except (OSError, RuntimeError) as ex:
                return fail("device_convert_failed", f"{src.name}: {ex}")

        emit("comic_book",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, profile=profile_name, pages=len(images),
             source="kcc-compatible")
        percent = (index + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (percent / 100) - elapsed) if percent > 1 else None
        emit("progress", percent=round(percent, 1),
             stage=f"{index + 1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_to_epub(args: argparse.Namespace) -> int:
    args.format = "epub"
    args.profile = getattr(args, "profile", "generic")
    args.legacy_name = True
    return op_to_device(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="comic-sidecar",
                                description="Comic archive conversion (CBZ / CBR / CBT / CB7 + PDF + device EPUB/MOBI).")
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
    ep.add_argument("--profile", choices=sorted(DEVICE_PROFILES), default="generic")

    device = sub.add_parser(
        "to-device",
        help="Build a KCC-compatible device-profiled EPUB or MOBI.",
    )
    device.add_argument("--input", nargs="+", required=True)
    device.add_argument("--output-dir", required=True, dest="output_dir")
    device.add_argument("--format", choices=["epub", "mobi"], required=True)
    device.add_argument("--profile", choices=sorted(DEVICE_PROFILES), default="generic")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "to-pdf":  return op_to_pdf(args)
        if args.op == "to-epub": return op_to_epub(args)
        if args.op == "to-device": return op_to_device(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
