"""Universal media-thumbnail extractor sidecar.

Generate cover-art / thumbnail / preview images from any media file:

  * Video frame extraction at N seconds via FFmpeg.
  * PDF first-page render via Poppler `pdftoppm`.
  * Audio cover-art (ID3 APIC / FLAC / Vorbis) via mutagen.
  * EPUB/CBZ first image via Python zipfile.
  * Office DOCX/XLSX/PPTX first preview image via zipfile.
  * Image format conversion / resize via Pillow.

Operations:
  thumb           Auto-detect input type and emit a JPG thumbnail.
  bulk-thumb      Walk a directory and emit thumbnails into a sidecar dir.

Required: ffmpeg + pdftoppm on PATH for video / PDF; mutagen + Pillow
for audio + image. Pure stdlib for ZIP-based inputs.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".exe")


_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv",
               ".mpg", ".mpeg", ".m4v", ".ts", ".vob", ".3gp"}
_AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".oga", ".m4a", ".aac", ".wav",
               ".opus", ".wma"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp",
               ".heic", ".heif", ".gif", ".avif"}
_ZIP_LIKE = {".cbz", ".cbr", ".epub", ".docx", ".xlsx", ".pptx", ".odt",
             ".ods", ".odp"}


def _save_thumb(img, out_path: Path, max_size: int) -> None:
    img.thumbnail((max_size, max_size))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(out_path, "JPEG", quality=85, optimize=True)


def _video_thumb(src: Path, out_path: Path, ts: float, max_size: int) -> bool:
    cli = _which("ffmpeg")
    if not cli: return False
    cmd = [cli, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", str(ts), "-i", str(src),
           "-frames:v", "1", "-vf", f"scale={max_size}:-2",
           "-q:v", "3", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return proc.returncode == 0 and out_path.is_file()


def _waveform(src: Path, out_path: Path, width: int, height: int,
              color: str) -> bool:
    """Render an audio waveform PNG via FFmpeg's showwavespic filter.

    Accepts any media file that carries an audio stream (audio files and
    videos alike). Downmixes to mono so the trace is a single readable band,
    and writes an RGBA PNG so the preview composites over any page background.
    """
    cli = _which("ffmpeg")
    if not cli:
        return False
    safe_color = color if re.fullmatch(r"[0-9A-Fa-f]{6}", color) else "8AADF4"
    cmd = [cli, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src),
           "-filter_complex",
           (f"aformat=channel_layouts=mono,"
            f"showwavespic=s={width}x{height}:colors=#{safe_color}"),
           "-frames:v", "1", str(out_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        return False
    return proc.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0


def _pdf_thumb(src: Path, out_path: Path, max_size: int) -> bool:
    cli = _which("pdftoppm")
    if not cli: return False
    out_stem = out_path.with_suffix("")
    cmd = [cli, "-jpeg", "-r", "150", "-f", "1", "-l", "1",
           "-singlefile", str(src), str(out_stem)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0: return False
    produced = Path(str(out_stem) + ".jpg")
    if not produced.is_file(): return False
    try:
        from PIL import Image
        with Image.open(produced) as img:
            _save_thumb(img, out_path, max_size)
        if produced != out_path: produced.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _audio_thumb(src: Path, out_path: Path, max_size: int) -> bool:
    try:
        import mutagen
        from PIL import Image
        f = mutagen.File(str(src))
        if not f: return False
        # ID3 APIC
        for tag, val in (f.tags or {}).items():
            if tag.upper().startswith("APIC") or tag == "covr":
                payload = (val.data if hasattr(val, "data") else val[0])
                if hasattr(payload, "imageData"): payload = payload.imageData
                with Image.open(io.BytesIO(payload)) as img:
                    _save_thumb(img, out_path, max_size)
                return True
        # FLAC / Vorbis embedded picture
        for pic in (getattr(f, "pictures", []) or []):
            with Image.open(io.BytesIO(pic.data)) as img:
                _save_thumb(img, out_path, max_size)
            return True
    except Exception:
        return False
    return False


def _zip_thumb(src: Path, out_path: Path, max_size: int) -> bool:
    try:
        from PIL import Image
        with zipfile.ZipFile(src) as z:
            # Look for first image entry by extension
            names = sorted(z.namelist())
            for n in names:
                low = n.lower()
                if any(low.endswith(ext) for ext in _IMAGE_EXTS):
                    with Image.open(io.BytesIO(z.read(n))) as img:
                        _save_thumb(img, out_path, max_size)
                    return True
            # Office formats: ppt/xl/word/media/<image>
            for n in names:
                if "/media/" in n.lower():
                    low = n.lower()
                    if any(low.endswith(ext) for ext in _IMAGE_EXTS):
                        with Image.open(io.BytesIO(z.read(n))) as img:
                            _save_thumb(img, out_path, max_size)
                        return True
    except Exception:
        return False
    return False


def _image_thumb(src: Path, out_path: Path, max_size: int) -> bool:
    try:
        from PIL import Image
        with Image.open(src) as img:
            _save_thumb(img, out_path, max_size)
        return True
    except Exception:
        return False


def _make_thumb(src: Path, out_path: Path, max_size: int, ts: float) -> str:
    ext = src.suffix.lower()
    if ext in _VIDEO_EXTS:
        if _video_thumb(src, out_path, ts, max_size): return "video"
    if ext == ".pdf":
        if _pdf_thumb(src, out_path, max_size): return "pdf"
    if ext in _AUDIO_EXTS:
        if _audio_thumb(src, out_path, max_size): return "audio-coverart"
    if ext in _ZIP_LIKE:
        if _zip_thumb(src, out_path, max_size): return "zip-first-image"
    if ext in _IMAGE_EXTS:
        if _image_thumb(src, out_path, max_size): return "image"
    # Last resort: try image first, then video
    if _image_thumb(src, out_path, max_size): return "image"
    if _video_thumb(src, out_path, ts, max_size): return "video"
    return ""


def op_thumb(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ".jpg")
        kind = _make_thumb(src, out_path, args.size, args.time)
        if not kind:
            return fail("thumb_failed",
                        f"{src.name}: no thumbnail backend produced output.")
        emit("thumb_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="jpg", source=kind)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_bulk_thumb(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if not root.is_dir(): return fail("missing_input", f"Dir not found: {root}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    extensions = _VIDEO_EXTS | _AUDIO_EXTS | _IMAGE_EXTS | _ZIP_LIKE | {".pdf"}
    for cur, _dirs, items in __import__("os").walk(root):
        for fn in items:
            full = Path(cur) / fn
            if full.suffix.lower() in extensions:
                files.append(full)
    total = len(files)
    if not total:
        return fail("empty", "No supported files in tree.")
    written = 0
    for i, src in enumerate(files):
        rel = src.relative_to(root)
        out_path = out_dir / rel.with_suffix(".jpg")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        kind = _make_thumb(src, out_path, args.size, args.time)
        if kind:
            written += 1
            emit("thumb_doc",
                 input=str(src), output=str(out_path),
                 size_bytes=out_path.stat().st_size,
                 format="jpg", source=kind)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=written)
    return 0


def op_waveform(args: argparse.Namespace) -> int:
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"file not found: {src}")
    if not _which("ffmpeg"):
        return fail("ffmpeg_missing",
                    "FFmpeg was not found; waveform previews require FFmpeg.")
    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not _waveform(src, out_path, args.width, args.height, args.color):
        return fail("waveform_failed",
                    f"{src.name}: FFmpeg produced no waveform (no audio stream?).")
    size = out_path.stat().st_size
    emit("waveform_doc", input=str(src), output=str(out_path),
         size_bytes=size, format="png", width=args.width, height=args.height)
    emit("complete", output=str(out_path), size_bytes=size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mediathumb-sidecar",
                                description="Universal media thumbnail extractor.")
    sub = p.add_subparsers(dest="op", required=True)

    th = sub.add_parser("thumb", help="Generate JPG thumbnails for any media")
    th.add_argument("--input", nargs="+", required=True)
    th.add_argument("--output-dir", required=True, dest="output_dir")
    th.add_argument("--size", type=int, default=512,
                    help="Max thumbnail edge in pixels (default 512)")
    th.add_argument("--time", type=float, default=2.0,
                    help="For videos: timestamp (seconds) to grab (default 2.0)")

    bt = sub.add_parser("bulk-thumb", help="Walk a directory, generate thumbs preserving tree")
    bt.add_argument("--root", required=True, help="Directory to walk")
    bt.add_argument("--output-dir", required=True, dest="output_dir")
    bt.add_argument("--size", type=int, default=512)
    bt.add_argument("--time", type=float, default=2.0)

    wf = sub.add_parser("waveform", help="Render an audio waveform PNG via FFmpeg")
    wf.add_argument("--input", required=True, help="Audio or video file to sample")
    wf.add_argument("--output", required=True, help="Destination PNG path")
    wf.add_argument("--width", type=int, default=900, help="Image width (default 900)")
    wf.add_argument("--height", type=int, default=160, help="Image height (default 160)")
    wf.add_argument("--color", default="8AADF4",
                    help="Trace colour as a 6-digit hex RGB (default 8AADF4)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "thumb":      return op_thumb(args)
        if args.op == "bulk-thumb": return op_bulk_thumb(args)
        if args.op == "waveform":   return op_waveform(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
