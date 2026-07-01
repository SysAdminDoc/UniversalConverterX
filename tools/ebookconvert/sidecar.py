"""eBook converter sidecar -- thin NDJSON wrapper around Calibre's
`ebook-convert` CLI.

Supported formats (Calibre handles dozens; common ones surfaced in UI):
  EPUB, MOBI, AZW3, PDF, FB2, LIT, LRF, PDB, RTF, TXT, HTML, HTMLZ, DOCX, ODT,
  CBZ, CBR (read-only), KFX (with plugin).

Frozen-guard: pure Python shim, no third-party deps.
"""
from __future__ import annotations

import argparse
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_calibre() -> str | None:
    env = os.environ.get("CALIBRE_PATH")
    if env and Path(env).is_file():
        return env
    for name in ("ebook-convert.exe", "ebook-convert"):
        hit = shutil.which(name)
        if hit:
            return hit
    candidates = [
        r"C:\Program Files\Calibre2\ebook-convert.exe",
        r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",
        r"C:\Program Files\Calibre\ebook-convert.exe",
        # Co-located portable bundle
        str(Path(__file__).resolve().parent / "Calibre" / "ebook-convert.exe"),
    ]
    if os.name != "nt":
        candidates += [
            "/usr/bin/ebook-convert",
            "/usr/local/bin/ebook-convert",
            "/Applications/calibre.app/Contents/MacOS/ebook-convert",
        ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


KNOWN_FORMATS = [
    "epub", "mobi", "azw3", "pdf", "fb2", "lit", "lrf", "pdb",
    "rtf", "txt", "html", "htmlz", "docx", "odt", "cbz",
]


# Calibre prints lines like "10% Initial output" -- catch the leading percent.
_PCT_RE = re.compile(r"^\s*(\d{1,3})%")


def op_convert(args: argparse.Namespace) -> int:
    calibre = find_calibre()
    if not calibre:
        return fail(
            "missing_calibre",
            "Calibre's ebook-convert.exe not found. Install Calibre "
            "(https://calibre-ebook.com/download) or set $env:CALIBRE_PATH.")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    if target not in KNOWN_FORMATS:
        emit("log", level="warn",
             message=f"Format '{target}' is not in the curated list; Calibre "
                     "may still accept it.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"eBook(s) not found: {missing}")

    total = len(inputs)
    emit("log", level="info",
         message=f"Convert {total} eBook(s) -> .{target} via Calibre")
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    started = time.monotonic()
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + target)
        cmd = [calibre, str(src), str(out_path)]
        if args.title:    cmd += ["--title", args.title]
        if args.authors:  cmd += ["--authors", args.authors]
        if args.language: cmd += ["--language", args.language]

        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True, bufsize=1)
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line: continue
                m = _PCT_RE.match(line)
                if m:
                    inner = float(m.group(1))
                    # Combine inner-file progress with batch progress so the UI
                    # bar moves smoothly across the whole queue.
                    overall = (i + inner / 100.0) / total * 100.0
                    elapsed = time.monotonic() - started
                    local = overall / 100.0
                    eta = (elapsed / local - elapsed) if local > 0.01 else None
                    emit("progress",
                         percent=round(overall, 1),
                         stage=f"{i + 1}/{total}: {line}",
                         eta_seconds=int(eta) if eta and eta < 86400 else None)
                else:
                    emit("log", level="info", message=line)
        finally:
            proc.wait()

        if proc.returncode != 0:
            return fail("calibre_failed",
                        f"ebook-convert exited {proc.returncode} on {src.name}")
        if not out_path.is_file():
            return fail("output_missing",
                        f"Calibre didn't produce output for {src.name}")

        emit("ebook",
             input=str(src),
             output=str(out_path),
             size_bytes=out_path.stat().st_size)

    total_size = sum((out_dir / (Path(p).stem + "." + target)).stat().st_size
                     for p in args.input
                     if (out_dir / (Path(p).stem + "." + target)).is_file())
    emit("complete", output=str(out_dir), size_bytes=total_size, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ebookconvert-sidecar",
                                description="eBook conversion via Calibre.")
    sub = p.add_subparsers(dest="op", required=True)

    cv = sub.add_parser("convert", help="Convert one or more eBooks")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True,
                    help="Target: " + " | ".join(KNOWN_FORMATS))
    cv.add_argument("--title", help="Override book title metadata")
    cv.add_argument("--authors", help='Override author(s) metadata (e.g. "Asimov, Isaac")')
    cv.add_argument("--language", help="Override language metadata (e.g. en, fr)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":
            return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
