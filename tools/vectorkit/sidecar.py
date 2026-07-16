"""Vector graphics conversion sidecar -- shells out to Inkscape (CLI mode)
to read/write the vector formats Inkscape supports natively:

  IN:  .ai .eps .ps .emf .wmf .svg .svgz .pdf .cdr (with extension) .vsd
  OUT: .svg .pdf .eps .ps .emf .wmf .png

Inkscape >= 1.0 has a stable headless CLI:
    inkscape <input> --export-type=svg --export-filename=<out>

We don't bundle Inkscape -- user installs it (Windows / macOS / Linux).
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_inkscape() -> str | None:
    env = os.environ.get("INKSCAPE_PATH")
    if env and Path(env).is_file(): return env
    for n in ("inkscape", "inkscape.exe"):
        hit = shutil.which(n)
        if hit: return hit
    for c in (
        r"C:\Program Files\Inkscape\bin\inkscape.exe",
        r"C:\Program Files\Inkscape\inkscape.exe",
        "/Applications/Inkscape.app/Contents/MacOS/inkscape",
        "/usr/bin/inkscape",
        "/usr/local/bin/inkscape",
    ):
        if Path(c).is_file(): return c
    return None


SUPPORTED_OUT = {"svg", "pdf", "eps", "ps", "emf", "wmf", "png"}


def op_convert(args: argparse.Namespace) -> int:
    inkscape = _find_inkscape()
    if not inkscape:
        return fail("missing_inkscape",
                    "Inkscape not found on PATH. Install from https://inkscape.org/ "
                    "or set $env:INKSCAPE_PATH.")

    out_fmt = args.format.lower().lstrip(".")
    if out_fmt not in SUPPORTED_OUT:
        return fail("bad_format",
                    f"Unsupported output '{out_fmt}'. Choose from: {sorted(SUPPORTED_OUT)}")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"Vector file(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + out_fmt)
        cmd = [inkscape, str(src),
               f"--export-type={out_fmt}",
               f"--export-filename={out_path}"]
        if args.dpi and out_fmt == "png":
            cmd.append(f"--export-dpi={int(args.dpi)}")
        if args.area == "page":
            cmd.append("--export-area-page")
        elif args.area == "drawing":
            cmd.append("--export-area-drawing")

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("inkscape_failed",
                        f"{src.name}: rc={proc.returncode}")

        emit("vector_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.is_file() else 0,
             format=out_fmt)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_check(_args: argparse.Namespace) -> int:
    hit = _find_inkscape()
    emit("formatter_status", name="inkscape",
         available=bool(hit), path=hit or "")
    emit("complete", output="", size_bytes=0, count=1 if hit else 0)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vectorkit-sidecar",
                                description="Vector format conversion via Inkscape headless.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert AI/EPS/PS/EMF/WMF/PDF/SVG to another vector format.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help=f"Output format (one of: {sorted(SUPPORTED_OUT)})")
    c.add_argument("--dpi", default=300, help="DPI when output is PNG.")
    c.add_argument("--area", default="page",
                   choices=["page", "drawing", "default"],
                   help="page = export Inkscape page; drawing = export tight bbox of content.")
    sub.add_parser("check", help="Check whether Inkscape is available.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "check":   return op_check(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
