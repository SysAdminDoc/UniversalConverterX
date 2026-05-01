"""Document converter sidecar -- thin NDJSON wrapper over `libreoffice
--headless --convert-to`.

Supported targets (anything LibreOffice can write): pdf, docx, doc, odt, rtf,
txt, html, epub, xlsx, ods, csv, pptx, odp, png, svg.

Frozen-guard: this sidecar does not call pip at runtime; it's a pure-Python
shim that shells out to soffice.exe. The PyInstaller-frozen build still passes
the contract test even though the body never touches pip.
"""
from __future__ import annotations

import argparse
import json
import os
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


def find_soffice() -> str | None:
    """Locate LibreOffice's `soffice.exe` (Windows) or `soffice` (POSIX)."""
    # Honour explicit override first.
    env = os.environ.get("LIBREOFFICE_PATH")
    if env and Path(env).is_file():
        return env

    # PATH lookup.
    for name in ("soffice.exe", "soffice", "libreoffice"):
        hit = shutil.which(name)
        if hit:
            return hit

    # Standard Windows install dirs.
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        # Portable bundle co-located with the sidecar.
        str(Path(__file__).resolve().parent / "libreoffice" / "program" / "soffice.exe"),
    ]
    # Standard POSIX install dirs.
    if os.name != "nt":
        candidates += [
            "/usr/bin/soffice",
            "/usr/lib/libreoffice/program/soffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


# Common output extensions LibreOffice accepts via --convert-to.
KNOWN_FORMATS = {
    # Text documents
    "pdf", "docx", "doc", "odt", "rtf", "txt", "html", "epub", "fodt",
    # Spreadsheets
    "xlsx", "xls", "ods", "csv", "tsv", "fods",
    # Presentations
    "pptx", "ppt", "odp", "fodp",
    # Drawings
    "odg", "fodg",
    # Image exports
    "png", "jpg", "jpeg", "svg",
}


def op_convert(args: argparse.Namespace) -> int:
    soffice = find_soffice()
    if not soffice:
        return fail(
            "missing_libreoffice",
            "LibreOffice not found. Install LibreOffice "
            "(https://www.libreoffice.org/download/) or set $env:LIBREOFFICE_PATH.")

    target = args.format.lower().lstrip(".")
    if target not in KNOWN_FORMATS:
        emit("log", level="warn",
             message=f"Format '{target}' is not in the known list; LibreOffice "
                     "may still accept it.")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Input(s) not found: {missing}")

    total = len(inputs)
    emit("log", level="info",
         message=f"Convert {total} file(s) -> .{target} via LibreOffice")
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    started = time.monotonic()
    output_paths: list[str] = []
    for i, src in enumerate(inputs):
        # LibreOffice's --headless mode takes a single source per invocation
        # reliably; batch-from-CLI forks fight over the user profile lock.
        cmd = [soffice, "--headless",
               "--convert-to", target,
               "--outdir", str(out_dir),
               str(src.resolve())]
        emit("log", level="debug", message=" ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
            for ln in tail:
                emit("log", level="error", message=ln)
            return fail("libreoffice_failed",
                        f"LibreOffice exited {proc.returncode} on {src.name}")

        # LibreOffice names the output by replacing the extension.
        out_path = out_dir / (src.stem + "." + target)
        if not out_path.is_file():
            # Some converters drop alternate extensions (e.g. txt for tsv);
            # fall back to anything matching the stem.
            cand = list(out_dir.glob(src.stem + ".*"))
            if cand:
                out_path = cand[0]
            else:
                return fail("output_missing",
                            f"LibreOffice didn't produce an output for {src.name}")
        output_paths.append(str(out_path))
        emit("doc",
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

    total_size = sum(Path(p).stat().st_size for p in output_paths if Path(p).is_file())
    emit("complete",
         output=str(out_dir),
         size_bytes=total_size,
         count=len(output_paths))
    return 0


def op_formats(args: argparse.Namespace) -> int:
    """Emit the known-good target formats so the UI can populate a combo box
    without hard-coding the list."""
    for fmt in sorted(KNOWN_FORMATS):
        emit("format", extension=fmt)
    emit("complete", output="", size_bytes=0, count=len(KNOWN_FORMATS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docconvert-sidecar",
                                description="Document conversion via LibreOffice headless.")
    sub = p.add_subparsers(dest="op", required=True)

    cv = sub.add_parser("convert", help="Convert one or more documents to a target format")
    cv.add_argument("--input", nargs="+", required=True,
                    help="One or more source documents (DOCX, ODT, XLSX, ...).")
    cv.add_argument("--output-dir", required=True, dest="output_dir",
                    help="Destination directory for the converted files.")
    cv.add_argument("--format", required=True,
                    help="Target extension (e.g. pdf, docx, odt).")

    sub.add_parser("formats", help="Enumerate the known target formats.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert":
            return op_convert(args)
        if args.op == "formats":
            return op_formats(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
