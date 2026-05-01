"""Code formatter sidecar -- routes source files to the right OSS formatter
based on extension. Each formatter is a separate CLI; user installs whichever
languages they care about.

  .py / .pyi              -> black
  .js / .jsx / .ts / .tsx -> prettier
  .json / .yaml / .css /
  .scss / .html / .md     -> prettier
  .go                     -> gofmt
  .rs                     -> rustfmt
  .c / .cpp / .h / .hpp   -> clang-format
  .java                   -> google-java-format (auto-discovered)
  .sh / .bash             -> shfmt
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


def _which(*names: str) -> str | None:
    for n in names:
        hit = shutil.which(n) or shutil.which(n + ".exe") or shutil.which(n + ".cmd")
        if hit: return hit
    return None


# ext -> (binary candidates, args-builder function).
ROUTES: dict[str, tuple[tuple[str, ...], list[str]]] = {
    ".py":   (("black",), ["{file}"]),
    ".pyi":  (("black",), ["{file}"]),
    ".js":   (("prettier",), ["--write", "{file}"]),
    ".jsx":  (("prettier",), ["--write", "{file}"]),
    ".ts":   (("prettier",), ["--write", "{file}"]),
    ".tsx":  (("prettier",), ["--write", "{file}"]),
    ".json": (("prettier",), ["--write", "{file}"]),
    ".yaml": (("prettier",), ["--write", "{file}"]),
    ".yml":  (("prettier",), ["--write", "{file}"]),
    ".css":  (("prettier",), ["--write", "{file}"]),
    ".scss": (("prettier",), ["--write", "{file}"]),
    ".html": (("prettier",), ["--write", "{file}"]),
    ".md":   (("prettier",), ["--write", "{file}"]),
    ".go":   (("gofmt",), ["-w", "{file}"]),
    ".rs":   (("rustfmt",), ["{file}"]),
    ".c":    (("clang-format",), ["-i", "{file}"]),
    ".cpp":  (("clang-format",), ["-i", "{file}"]),
    ".cc":   (("clang-format",), ["-i", "{file}"]),
    ".h":    (("clang-format",), ["-i", "{file}"]),
    ".hpp":  (("clang-format",), ["-i", "{file}"]),
    ".java": (("google-java-format", "java-format"), ["-i", "{file}"]),
    ".sh":   (("shfmt",), ["-w", "{file}"]),
    ".bash": (("shfmt",), ["-w", "{file}"]),
}


def op_format(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"Source(s) not found: {missing}")

    # If --output-dir is set, copy each file there first and format the copy.
    out_dir: Path | None = None
    if args.output_dir:
        out_dir = Path(args.output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    skipped: list[str] = []
    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        route = ROUTES.get(ext)
        if route is None:
            skipped.append(str(src))
            emit("log", level="warn", message=f"No formatter for {ext}; skipping {src.name}")
            continue
        candidates, arg_template = route
        binary = _which(*candidates)
        if binary is None:
            skipped.append(str(src))
            emit("log", level="warn",
                 message=f"None of {candidates} found on PATH; skipping {src.name}")
            continue

        target_path = src
        if out_dir is not None:
            target_path = out_dir / src.name
            shutil.copy2(str(src), str(target_path))

        cmd = [binary] + [a.replace("{file}", str(target_path)) for a in arg_template]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            emit("code_format",
                 input=str(src), formatter=Path(binary).stem,
                 success=False, exit_code=proc.returncode)
            continue

        emit("code_format",
             input=str(src), output=str(target_path),
             formatter=Path(binary).stem,
             size_bytes=target_path.stat().st_size if target_path.is_file() else 0,
             success=True)
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)

    emit("complete", output=str(out_dir or ""), size_bytes=0,
         count=total - len(skipped), skipped=len(skipped))
    return 0


def op_check(args: argparse.Namespace) -> int:
    """List which formatters are installed."""
    seen = set()
    for (cands, _) in ROUTES.values():
        for c in cands:
            if c in seen: continue
            seen.add(c)
            hit = _which(c)
            emit("formatter_status", name=c, available=bool(hit), path=hit or "")
    emit("complete", output="", size_bytes=0, count=len(seen))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="codeformat-sidecar",
                                description="Route source files to the right OSS formatter.")
    sub = p.add_subparsers(dest="op", required=True)
    fmt = sub.add_parser("format", help="Format one or more source files in-place (or to --output-dir).")
    fmt.add_argument("--input", nargs="+", required=True)
    fmt.add_argument("--output-dir", dest="output_dir",
                     help="Optional: copy each file here before formatting.")
    sub.add_parser("check", help="Probe which formatters are available on PATH.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "format": return op_format(args)
        if args.op == "check":  return op_check(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
