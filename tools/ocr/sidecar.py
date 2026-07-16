"""OCR sidecar -- thin NDJSON wrapper around Tesseract OCR.

Output formats: txt (plain text), hocr (HTML with bbox), pdf (searchable PDF
with invisible OCR layer), tsv (per-word coords), alto (ALTO XML).

Frozen-guard: pure-Python shim, no third-party deps; just shells out to
tesseract.exe (which the user installs separately).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_tesseract() -> str | None:
    env = os.environ.get("TESSERACT_PATH")
    if env and Path(env).is_file():
        return env
    for name in ("tesseract.exe", "tesseract"):
        hit = shutil.which(name)
        if hit:
            return hit
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Tools\Tesseract-OCR\tesseract.exe",
        # Co-located portable
        str(Path(__file__).resolve().parent / "Tesseract-OCR" / "tesseract.exe"),
    ]
    if os.name != "nt":
        candidates += [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/opt/homebrew/bin/tesseract",
        ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


def find_tessdata(tesseract_exe: str) -> str | None:
    """Find tessdata dir alongside the tesseract executable, or via env."""
    env = os.environ.get("TESSDATA_PREFIX")
    if env and Path(env).is_dir():
        return env
    base = Path(tesseract_exe).parent
    for cand in (base / "tessdata", base.parent / "tessdata", base.parent / "share" / "tessdata"):
        if cand.is_dir():
            return str(cand)
    # UCX shared model cache
    shared = os.environ.get("UCX_MODEL_DIR")
    if shared:
        td = Path(shared) / "tessdata"
        if td.is_dir():
            return str(td)
    return None


# Tesseract emits to stderr lines like:
#   "Detected x dpi"
#   "Page 1"
#   "Estimating resolution as ..."
# It doesn't print true % progress; we approximate by counting "Page N" lines
# against the total file count.

def op_languages(args: argparse.Namespace) -> int:
    tess = find_tesseract()
    if not tess:
        return fail("missing_tesseract",
                    "Tesseract not found. Install from "
                    "https://github.com/UB-Mannheim/tesseract/wiki or set $env:TESSERACT_PATH.")
    proc = subprocess.run([tess, "--list-langs"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("tesseract_failed",
                    f"tesseract --list-langs exited {proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()}")
    # First line is "List of available languages...", rest are codes.
    langs = [l.strip() for l in proc.stdout.splitlines()[1:] if l.strip()]
    for lang in langs:
        emit("ocr_language", code=lang)
    emit("complete", output="", size_bytes=0, count=len(langs))
    return 0


def op_recognize(args: argparse.Namespace) -> int:
    tess = find_tesseract()
    if not tess:
        return fail("missing_tesseract",
                    "Tesseract not found. Install from "
                    "https://github.com/UB-Mannheim/tesseract/wiki or set $env:TESSERACT_PATH.")
    tessdata = find_tessdata(tess)

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Image(s) not found: {missing}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = args.format.lower()
    # Tesseract uses "configfile" tokens for output formats. txt is implied.
    config_token = {
        "txt":   None,        # default
        "hocr":  "hocr",
        "pdf":   "pdf",
        "tsv":   "tsv",
        "alto":  "alto",
    }.get(fmt)
    if config_token is None and fmt != "txt":
        return fail("bad_format",
                    f"Unknown output format '{fmt}'. Use: txt | hocr | pdf | tsv | alto")

    out_ext = {"txt": ".txt", "hocr": ".hocr", "pdf": ".pdf",
               "tsv": ".tsv", "alto": ".xml"}[fmt]

    total = len(inputs)
    emit("log", level="info",
         message=f"OCR {total} image(s) -> .{fmt} (lang={args.lang}, psm={args.psm})")
    emit("progress", percent=0, stage="ocr", eta_seconds=None)

    started = time.monotonic()
    for i, src in enumerate(inputs):
        # Tesseract's output arg is the BASENAME (no extension). It picks the
        # extension from the configfile token (or .txt for default).
        out_base = out_dir / src.stem
        cmd = [tess, str(src), str(out_base),
               "-l", args.lang,
               "--psm", str(args.psm),
               "--oem", str(args.oem)]
        if tessdata:
            cmd += ["--tessdata-dir", tessdata]
        if config_token:
            cmd.append(config_token)

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).splitlines()[-5:]
            for ln in tail:
                emit("log", level="error", message=ln)
            return fail("tesseract_failed",
                        f"tesseract exited {proc.returncode} on {src.name}")

        out_path = out_base.with_suffix(out_ext)
        if not out_path.is_file():
            # PDF mode adds .pdf; txt adds .txt; etc. -- usually it's correct,
            # but a stale or path-truncation case might land elsewhere.
            cands = list(out_dir.glob(src.stem + ".*"))
            if cands:
                out_path = cands[0]

        emit("ocr_result",
             input=str(src),
             output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0)

        pct = (i + 1) / total * 100.0
        elapsed = time.monotonic() - started
        local = pct / 100.0
        eta = (elapsed / local - elapsed) if local > 0.01 else None
        emit("progress",
             percent=round(pct, 1),
             stage=f"OCR'd {i + 1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    total_size = sum(p.stat().st_size for p in out_dir.glob(f"*{out_ext}") if p.is_file())
    emit("complete", output=str(out_dir), size_bytes=total_size, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ocr-sidecar",
                                description="Image OCR via Tesseract.")
    sub = p.add_subparsers(dest="op", required=True)

    rec = sub.add_parser("recognize", help="Run OCR on one or more images")
    rec.add_argument("--input", nargs="+", required=True)
    rec.add_argument("--output-dir", required=True, dest="output_dir")
    rec.add_argument("--format", default="txt",
                     help="Output: txt | hocr | pdf | tsv | alto. Default txt.")
    rec.add_argument("--lang", default="eng",
                     help="Language code(s), '+' joined for multi-lang (e.g. 'eng+fra'). Default eng.")
    rec.add_argument("--psm", type=int, default=3,
                     help="Page segmentation mode 0-13 (Tesseract). Default 3 = auto.")
    rec.add_argument("--oem", type=int, default=1,
                     help="OCR engine mode (0=legacy, 1=LSTM, 2=both, 3=default). Default 1.")

    sub.add_parser("languages",
                   help="List installed Tesseract language packs.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "recognize":  return op_recognize(args)
        if args.op == "languages":  return op_languages(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
