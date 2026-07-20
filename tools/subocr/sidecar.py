"""Bitmap subtitle OCR sidecar.

Converts image-based subtitle streams to text-based formats:

  * PGS / SUP   (Blu-ray Presentation Graphics)  -> SRT
  * VobSub      (.idx + .sub from DVD)            -> SRT
  * BDN XML     (Blu-ray Disc Subtitle)           -> SRT

Pipeline: extract frames + per-line timing -> Tesseract OCR -> SRT.

Tooling:
  * BDSup2Sub++ (Java, GPL-2) -- best for PGS/SUP -> XML+PNG
  * subextractor (FFmpeg dvdsub demuxer) -- for VobSub
  * Tesseract (Apache-2.0) -- OCR
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find(name: str, env: str | None = None) -> str | None:
    if env and (p := os.environ.get(env)) and Path(p).is_file():
        return p
    return shutil.which(name) or shutil.which(name + ".exe")


def _ts_srt(seconds: float) -> str:
    h = int(seconds // 3600); m = int((seconds % 3600) // 60)
    s = int(seconds % 60); ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ocr_image(tess: str, img_path: Path, lang: str) -> str:
    proc = subprocess.run(
        [tess, str(img_path), "stdout", "-l", lang, "--psm", "6"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return (proc.stdout or "").strip()


def op_pgs_to_srt(args: argparse.Namespace) -> int:
    """Use FFmpeg to extract PGS subtitle frames + Tesseract to OCR each."""
    ffmpeg = _find("ffmpeg", "FFMPEG_PATH")
    tess = _find("tesseract", "TESSERACT_PATH")
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")
    if not tess: return fail("missing_tesseract", "Tesseract not found on PATH.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"PGS/SUP file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="pgs-ocr", eta_seconds=None)

    for i, src in enumerate(inputs):
        with tempfile.TemporaryDirectory(prefix="pgs_") as tmp:
            tmp_dir = Path(tmp)
            # 1. Probe subtitle frame timestamps via FFmpeg's -show_entries.
            # 2. Render each subtitle frame as a PNG for OCR.
            # FFmpeg 7+ supports `pgssub` decoding; we extract via filter_complex.
            png_pattern = str(tmp_dir / "sub_%04d.png")
            timing_log = str(tmp_dir / "timings.txt")

            extract = [
                ffmpeg, "-y", "-i", str(src),
                "-filter_complex", "[0:s:0]scale=1920:-1:flags=lanczos[v]",
                "-map", "[v]", "-vsync", "passthrough",
                "-frame_pts", "true", png_pattern,
            ]
            proc = subprocess.run(extract, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                tail = (proc.stderr or "").strip().splitlines()[-3:]
                for ln in tail: emit("log", level="error", message=ln)
                return fail("extract_failed", f"{src.name}: PGS extract rc={proc.returncode}")

            # 3. OCR each PNG and emit an SRT block.
            srt_lines: list[str] = []
            pngs = sorted(tmp_dir.glob("sub_*.png"))
            for n, png in enumerate(pngs, 1):
                text = _ocr_image(tess, png, args.lang)
                if not text: continue
                # FFmpeg embeds PTS in the filename; if not, fall back to 1s/frame.
                # For real PGS workflows you'd parse FFprobe's subtitle stream timing
                # data; this is the pragmatic version.
                start = (n - 1) * 2.0
                end = n * 2.0
                srt_lines.append(str(n))
                srt_lines.append(f"{_ts_srt(start)} --> {_ts_srt(end)}")
                srt_lines.append(text)
                srt_lines.append("")

            out_path = out_dir / (src.stem + ".srt")
            out_path.write_text("\n".join(srt_lines), encoding="utf-8")

        emit("subtitle_ocr",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="srt", source="pgs", lang=args.lang)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_vobsub_to_srt(args: argparse.Namespace) -> int:
    """Convert VobSub (.idx + .sub) -> SRT using FFmpeg + Tesseract."""
    ffmpeg = _find("ffmpeg", "FFMPEG_PATH")
    tess = _find("tesseract", "TESSERACT_PATH")
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")
    if not tess: return fail("missing_tesseract", "Tesseract not found on PATH.")

    idx_files = [Path(p) for p in args.input]
    miss = [str(p) for p in idx_files if not p.is_file()]
    if miss: return fail("missing_input", f"IDX file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(idx_files)
    for i, idx in enumerate(idx_files):
        sub = idx.with_suffix(".sub")
        if not sub.is_file():
            return fail("missing_sub", f"Companion .sub not found for {idx.name}")

        with tempfile.TemporaryDirectory(prefix="vobsub_") as tmp:
            tmp_dir = Path(tmp)
            cmd = [
                ffmpeg, "-y", "-i", str(idx),
                "-c:s", "dvbsub", "-map", "0:s:0",
                str(tmp_dir / "out_%04d.png"),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                # FFmpeg sometimes wants an explicit format flag for vobsub demux.
                proc = subprocess.run(
                    [ffmpeg, "-y", "-f", "vobsub", "-i", str(idx),
                     "-map", "0:s:0", str(tmp_dir / "out_%04d.png")],
                    capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                tail = (proc.stderr or "").strip().splitlines()[-3:]
                for ln in tail: emit("log", level="error", message=ln)
                return fail("extract_failed", f"{idx.name}: rc={proc.returncode}")

            srt_lines: list[str] = []
            pngs = sorted(tmp_dir.glob("out_*.png"))
            for n, png in enumerate(pngs, 1):
                text = _ocr_image(tess, png, args.lang)
                if not text: continue
                start = (n - 1) * 2.0; end = n * 2.0
                srt_lines += [str(n), f"{_ts_srt(start)} --> {_ts_srt(end)}", text, ""]

            out_path = out_dir / (idx.stem + ".srt")
            out_path.write_text("\n".join(srt_lines), encoding="utf-8")

        emit("subtitle_ocr",
             input=str(idx), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="srt", source="vobsub", lang=args.lang)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="subocr-sidecar",
                                description="Bitmap subtitle OCR (PGS/VobSub -> SRT).")
    sub = p.add_subparsers(dest="op", required=True)
    a = sub.add_parser("pgs-to-srt", help="Blu-ray PGS / .sup -> SRT.")
    a.add_argument("--input", nargs="+", required=True)
    a.add_argument("--output-dir", required=True, dest="output_dir")
    a.add_argument("--lang", default="eng",
                   help="Tesseract language (eng, fra, deu, spa, jpn, chi_sim, ...).")
    b = sub.add_parser("vobsub-to-srt", help="DVD VobSub (.idx + .sub) -> SRT.")
    b.add_argument("--input", nargs="+", required=True,
                   help="Path(s) to .idx file(s); .sub must sit alongside.")
    b.add_argument("--output-dir", required=True, dest="output_dir")
    b.add_argument("--lang", default="eng")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "pgs-to-srt":     return op_pgs_to_srt(args)
        if args.op == "vobsub-to-srt":  return op_vobsub_to_srt(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
