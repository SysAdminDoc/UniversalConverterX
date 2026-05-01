"""Pandoc sidecar -- thin NDJSON wrapper around the `pandoc` CLI for universal
markup conversion.

Pandoc supports 60+ input formats and 60+ output formats including
markdown / commonmark / gfm / rst / asciidoc / textile / org / docx / odt /
rtf / html / xhtml / epub / fb2 / mediawiki / dokuwiki / man / latex / tex /
beamer / texinfo / context / csljson / bibtex / jats / native / json /
plain / docbook / pdf (via latex/typst).

Frozen-guard: pure-Python wrapper; pandoc.exe must be installed separately.
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


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_pandoc() -> str | None:
    env = os.environ.get("PANDOC_PATH")
    if env and Path(env).is_file():
        return env
    for name in ("pandoc.exe", "pandoc"):
        hit = shutil.which(name)
        if hit:
            return hit
    candidates = [
        r"C:\Program Files\Pandoc\pandoc.exe",
        str(Path(__file__).resolve().parent / "Pandoc" / "pandoc.exe"),
    ]
    if os.name != "nt":
        candidates += ["/usr/bin/pandoc", "/usr/local/bin/pandoc"]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


# Subset of common targets surfaced in the UI; pandoc accepts many more.
KNOWN_OUTPUT_FORMATS = [
    "markdown", "commonmark", "gfm", "rst", "asciidoc", "html", "html5",
    "docx", "odt", "rtf", "epub", "epub3", "fb2", "latex", "tex", "context",
    "man", "mediawiki", "dokuwiki", "org", "textile", "beamer", "json",
    "plain", "docbook", "jats", "csljson", "bibtex", "native", "pdf",
]


def op_convert(args: argparse.Namespace) -> int:
    pandoc = find_pandoc()
    if not pandoc:
        return fail(
            "missing_pandoc",
            "Pandoc not found. Install from https://pandoc.org/installing.html "
            "or set $env:PANDOC_PATH.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Document(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    out_ext = "." + ("md" if target in ("markdown", "gfm", "commonmark")
                     else "tex" if target in ("latex", "context")
                     else "html" if target == "html5"
                     else "epub" if target == "epub3"
                     else target)

    total = len(inputs)
    emit("log", level="info",
         message=f"Pandoc -> .{target} for {total} document(s)")
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    started = time.monotonic()
    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + out_ext)
        cmd = [pandoc, str(src), "-o", str(out_path), "-t", target,
               "--standalone"]
        if args.from_format:
            cmd += ["-f", args.from_format]
        if args.toc:
            cmd.append("--toc")
        if args.template:
            cmd += ["--template", args.template]
        if args.pdf_engine and target == "pdf":
            cmd += ["--pdf-engine", args.pdf_engine]
        if args.metadata:
            for kv in args.metadata.split(","):
                kv = kv.strip()
                if "=" in kv:
                    cmd += ["-M", kv]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
            for ln in tail:
                emit("log", level="error", message=ln)
            return fail("pandoc_failed",
                        f"pandoc exited {proc.returncode} on {src.name}")

        if not out_path.is_file():
            return fail("output_missing",
                        f"Pandoc did not produce output for {src.name}")

        emit("pandoc_doc",
             input=str(src),
             output=str(out_path),
             size_bytes=out_path.stat().st_size)

        pct = (i + 1) / total * 100.0
        elapsed = time.monotonic() - started
        local = pct / 100.0
        eta = (elapsed / local - elapsed) if local > 0.01 else None
        emit("progress",
             percent=round(pct, 1),
             stage=f"converted {i + 1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    total_size = sum((out_dir / (Path(p).stem + out_ext)).stat().st_size
                     for p in args.input
                     if (out_dir / (Path(p).stem + out_ext)).is_file())
    emit("complete", output=str(out_dir), size_bytes=total_size, count=total)
    return 0


def op_formats(args: argparse.Namespace) -> int:
    pandoc = find_pandoc()
    if not pandoc:
        return fail("missing_pandoc", "Pandoc not found.")
    for which in ("input-formats", "output-formats"):
        proc = subprocess.run([pandoc, "--list-" + which],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            continue
        for line in proc.stdout.splitlines():
            name = line.strip()
            if not name:
                continue
            emit("format", direction=which, name=name)
    emit("complete", output="", size_bytes=0)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pandoc-sidecar",
                                description="Universal markup conversion via Pandoc.")
    sub = p.add_subparsers(dest="op", required=True)

    cv = sub.add_parser("convert", help="Convert one or more documents")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True,
                    help="Target format (markdown / docx / epub / latex / html / pdf / ...)")
    cv.add_argument("--from-format", dest="from_format",
                    help="Override source format detection (e.g. 'gfm', 'commonmark+smart').")
    cv.add_argument("--toc", action="store_true",
                    help="Generate table of contents.")
    cv.add_argument("--template",
                    help="Path to a custom Pandoc template.")
    cv.add_argument("--pdf-engine", dest="pdf_engine",
                    help="When --format=pdf: engine to use (xelatex / pdflatex / typst / wkhtmltopdf).")
    cv.add_argument("--metadata",
                    help="Comma-separated key=value pairs (e.g. 'title=My Doc,author=Me').")

    sub.add_parser("formats",
                   help="Enumerate Pandoc's input/output format catalogue.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "formats": return op_formats(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
