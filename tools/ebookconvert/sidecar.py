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
import os
import re
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


def build_calibre_environment(job_dir: Path) -> dict[str, str]:
    """Return an isolated Calibre environment with no user-installed plugins."""
    env = os.environ.copy()
    for unsafe_name in ("CALIBRE_DEVELOP_FROM", "PYTHONHOME", "PYTHONPATH"):
        env.pop(unsafe_name, None)

    directories = {
        "CALIBRE_CONFIG_DIRECTORY": job_dir / "config",
        "CALIBRE_CACHE_DIRECTORY": job_dir / "cache",
        "CALIBRE_TEMP_DIR": job_dir / "temp",
    }
    for name, directory in directories.items():
        directory.mkdir(parents=True, exist_ok=True)
        env[name] = str(directory)

    # An empty per-job config directory prevents discovery of user-installed
    # plugins. ebook-convert has no supported global --ignore-plugins switch.
    env["CALIBRE_ALLOW_PYTHON_TEMPLATES"] = "0"
    return env


def promote_output(staged_path: Path, destination: Path) -> None:
    """Validate a staged output before atomically replacing the destination."""
    if staged_path.is_symlink() or not staged_path.is_file():
        raise RuntimeError("Calibre did not produce a regular output file")
    if staged_path.stat().st_size == 0:
        raise RuntimeError("Calibre produced an empty output file")
    os.replace(staged_path, destination)


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
    if not re.fullmatch(r"[a-z0-9]{1,16}", target):
        return fail("invalid_format", "Target format must be a simple extension token")
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
        with tempfile.TemporaryDirectory(prefix="ucx-ebook-") as job_dir_raw:
            job_dir = Path(job_dir_raw)
            input_dir = job_dir / "input"
            output_dir = job_dir / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            # Copy the source into the job root so HTML and archive parsers cannot
            # traverse sibling files beside the user's original document.
            staged_input = input_dir / src.name
            staged_output = output_dir / (src.stem + "." + target)
            shutil.copyfile(src.resolve(), staged_input)

            cmd = [calibre, str(staged_input), str(staged_output)]
            if args.title:    cmd += ["--title", args.title]
            if args.authors:  cmd += ["--authors", args.authors]
            if args.language: cmd += ["--language", args.language]

            proc = subprocess.Popen(
                cmd,
                cwd=job_dir,
                env=build_calibre_environment(job_dir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = raw.rstrip()
                    if not line:
                        continue
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
            try:
                promote_output(staged_output, out_path)
            except RuntimeError as ex:
                return fail("output_invalid", f"{ex} for {src.name}")

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
