"""Jupyter / R Markdown notebook sidecar.

Convert Jupyter notebooks (.ipynb) and R Markdown (.Rmd) between every
useful representation:

  ipynb (Jupyter)   -> md, html, py, rst, tex, pdf (via Pandoc), slides
  py / md / Rmd     -> ipynb (round-trip via jupytext)
  Quarto (.qmd)     -> ipynb / md / html (Quarto CLI shellout)

Backed by `nbconvert` (BSD-3) and `jupytext` (MIT). Both are pure-Python
when called via their CLIs; we shell out for cleanliness.
"""
from __future__ import annotations

import argparse
import json
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


def _have(name: str) -> bool:
    return shutil.which(name) is not None or shutil.which(name + ".exe") is not None


def _via_nbconvert(src: Path, out_dir: Path, target: str) -> int:
    cmd = [sys.executable, "-m", "nbconvert", "--to", target,
           "--output-dir", str(out_dir), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("nbconvert_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def _via_jupytext(src: Path, out_dir: Path, target: str) -> int:
    """Round-trip ipynb <-> py/md/Rmd via jupytext."""
    out_path = out_dir / (src.stem + "." + target)
    cmd = [sys.executable, "-m", "jupytext", "--to", target,
           "--output", str(out_path), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("jupytext_failed",
                    f"{src.name}: rc={proc.returncode}: "
                    f"{(proc.stderr or proc.stdout).strip()[:240]}")
    return 0


def _via_quarto(src: Path, out_dir: Path, target: str) -> int:
    quarto = shutil.which("quarto") or shutil.which("quarto.cmd")
    if not quarto:
        return fail("missing_quarto",
                    "Quarto CLI not found. Install from https://quarto.org/.")
    cmd = [quarto, "render", str(src), "--to", target,
           "--output-dir", str(out_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return fail("quarto_failed",
                    f"{src.name}: rc={proc.returncode}")
    return 0


# Targets nbconvert handles natively.
NBCONVERT_TARGETS = {"html", "latex", "tex", "pdf", "rst", "markdown",
                     "asciidoc", "script", "slides"}
JUPYTEXT_TARGETS = {"py", "md", "Rmd", "qmd", "ipynb"}


def op_convert(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Notebook file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")

    # Map convenience aliases.
    nb_target = {"md": "markdown", "py": "script", "tex": "latex"}.get(target, target)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="notebooks", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        rc = 0
        if ext == ".qmd" or target == "qmd":
            rc = _via_quarto(src, out_dir, target)
        elif (ext == ".ipynb" and target in JUPYTEXT_TARGETS) or \
             (target == "ipynb"):
            rc = _via_jupytext(src, out_dir, target)
        else:
            rc = _via_nbconvert(src, out_dir, nb_target)
        if rc != 0: return rc

        # nbconvert names the output the input stem with the target's typical ext.
        # Find what was produced.
        guessed = out_dir / (src.stem + "." + target)
        if not guessed.is_file():
            for cand in out_dir.glob(src.stem + ".*"):
                if cand.is_file() and cand != src:
                    guessed = cand; break
        emit("notebook_doc",
             input=str(src), output=str(guessed) if guessed.is_file() else str(out_dir),
             size_bytes=guessed.stat().st_size if guessed.is_file() else 0,
             format=target)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_execute(args: argparse.Namespace) -> int:
    """Run a notebook in-place, writing executed outputs back to .ipynb."""
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Notebook(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for src in inputs:
        out_path = out_dir / (src.stem + "_executed.ipynb")
        cmd = [sys.executable, "-m", "nbconvert", "--to", "notebook",
               "--execute", "--output", str(out_path), str(src)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return fail("execute_failed",
                        f"{src.name}: rc={proc.returncode}: "
                        f"{(proc.stderr or proc.stdout).strip()[:240]}")
        emit("notebook_doc",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="ipynb", executed=True)
    emit("complete", output=str(out_dir), size_bytes=0, count=len(inputs))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="notebooks-sidecar",
                                description="Jupyter / R Markdown / Quarto notebook conversion.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert ipynb / py / md / Rmd / qmd / html / pdf / slides.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help="ipynb | py | md | Rmd | qmd | html | pdf | tex | rst | slides")
    e = sub.add_parser("execute", help="Run notebook + save outputs.")
    e.add_argument("--input", nargs="+", required=True)
    e.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "execute": return op_execute(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
