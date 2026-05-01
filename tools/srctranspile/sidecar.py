"""Source-code transpilation sidecar.

Cross-language and cross-version source migrations:

  * Python 2 -> Python 3 via stdlib `lib2to3`.
  * CoffeeScript -> JavaScript via the `coffee` CLI.
  * Vue 2 -> Vue 3 SFC migration via `vue-codemod` (npm).
  * JavaScript -> TypeScript bootstrap via `tsc --allowJs --declaration`.
  * Flow type annotations -> TypeScript via `flow-to-ts`.

Operations:
  py2-to-py3        Python 2 source -> Python 3 source.
  coffee-to-js      CoffeeScript -> JavaScript.
  vue2-to-vue3      Vue 2 SFC -> Vue 3 (Composition API).
  js-to-ts          JS source + tsc -> TS source + .d.ts emit.
  flow-to-ts        Flow-annotated JS -> TypeScript.

Each operation reports clearly when its required CLI / npm tool is missing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name + ".cmd") or shutil.which(name + ".exe")


# ── Python 2 -> 3 (uses bundled lib2to3) ──────────────────────────────

def op_py2_to_py3(args: argparse.Namespace) -> int:
    try:
        from lib2to3.refactor import RefactoringTool, get_fixers_from_package
    except ImportError:
        return fail("missing_dep",
                    "lib2to3 unavailable (Python 3.13 dropped it; "
                    "try Python 3.11/3.12 host or install `2to3` package).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Python file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fixers = get_fixers_from_package("lib2to3.fixes")
    rt = RefactoringTool(fixers)

    total = len(inputs)
    for i, src in enumerate(inputs):
        try:
            text = src.read_text(encoding="utf-8")
            tree = rt.refactor_string(text + ("\n" if not text.endswith("\n") else ""),
                                       str(src))
            out_text = str(tree) if tree else text
        except Exception as ex:
            return fail("convert_failed", f"{src.name}: {ex}")
        out_path = out_dir / src.name
        out_path.write_text(out_text, encoding="utf-8")
        emit("source_xform",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="python3", source="python2")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── CoffeeScript -> JS via `coffee` CLI ────────────────────────────────

def op_coffee_to_js(args: argparse.Namespace) -> int:
    cli = _which("coffee")
    if not cli: return fail("missing_dep", "coffee CLI not on PATH (`npm install -g coffeescript`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"CoffeeScript file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        proc = subprocess.run([cli, "--compile", "--output", str(out_dir),
                                str(src)],
                               capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: coffee exit {proc.returncode}: "
                        f"{proc.stderr or proc.stdout}")
        out_path = out_dir / (src.stem + ".js")
        emit("source_xform",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size if out_path.exists() else 0,
             format="javascript", source="coffeescript")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Vue 2 -> Vue 3 via vue-codemod ─────────────────────────────────────

def op_vue2_to_vue3(args: argparse.Namespace) -> int:
    cli = _which("vue-codemod")
    if not cli:
        return fail("missing_dep",
                    "vue-codemod not on PATH (`npm install -g vue-codemod`). "
                    "Manual cleanup is typically required after auto-migration.")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Vue file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        # vue-codemod transforms in-place; copy to out_dir first then run.
        target = out_dir / src.name
        shutil.copy2(src, target)
        proc = subprocess.run([cli, "-t", "vue-2-to-3", str(target)],
                               capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: vue-codemod exit {proc.returncode}: "
                        f"{proc.stderr or proc.stdout}")
        emit("source_xform",
             input=str(src), output=str(target),
             size_bytes=target.stat().st_size,
             format="vue3", source="vue2")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── JS -> TS bootstrap via tsc ─────────────────────────────────────────

def op_js_to_ts(args: argparse.Namespace) -> int:
    cli = _which("tsc")
    if not cli: return fail("missing_dep", "tsc not on PATH (`npm install -g typescript`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"JS file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        # produce .d.ts beside renamed .ts copy
        ts_path = out_dir / (src.stem + ".ts")
        shutil.copyfile(src, ts_path)
        proc = subprocess.run(
            [cli, "--allowJs", "--declaration", "--emitDeclarationOnly",
             "--outDir", str(out_dir), str(src)],
            capture_output=True, text=True, timeout=120)
        # tsc may print "Found N errors" but still emit useful output.
        if proc.returncode not in (0, 2):
            return fail("convert_failed",
                        f"{src.name}: tsc exit {proc.returncode}: "
                        f"{proc.stderr or proc.stdout}")
        emit("source_xform",
             input=str(src), output=str(ts_path),
             size_bytes=ts_path.stat().st_size,
             format="typescript", source="javascript")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


# ── Flow -> TypeScript via flow-to-ts ──────────────────────────────────

def op_flow_to_ts(args: argparse.Namespace) -> int:
    cli = _which("flow-to-ts")
    if not cli: return fail("missing_dep", "flow-to-ts not on PATH (`npm install -g flow-to-ts`).")
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Flow file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    for i, src in enumerate(inputs):
        proc = subprocess.run([cli, "--write", "--out-dir", str(out_dir),
                                str(src)],
                               capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return fail("convert_failed",
                        f"{src.name}: flow-to-ts exit {proc.returncode}: "
                        f"{proc.stderr or proc.stdout}")
        ts_path = out_dir / (src.stem + ".ts")
        if not ts_path.is_file():
            ts_path = out_dir / (src.stem + ".tsx")
        emit("source_xform",
             input=str(src), output=str(ts_path),
             size_bytes=ts_path.stat().st_size if ts_path.exists() else 0,
             format="typescript", source="flow")
        emit("progress", percent=round((i + 1) / total * 100, 1),
             stage=f"{i+1}/{total}", eta_seconds=None)
    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="srctranspile-sidecar",
                                description="Cross-language / cross-version source transpilation.")
    sub = p.add_subparsers(dest="op", required=True)
    for op, helpstr in [
        ("py2-to-py3",   "Python 2 source -> Python 3"),
        ("coffee-to-js", "CoffeeScript -> JavaScript"),
        ("vue2-to-vue3", "Vue 2 SFC -> Vue 3"),
        ("js-to-ts",     "JS -> TS + .d.ts"),
        ("flow-to-ts",   "Flow-annotated JS -> TypeScript"),
    ]:
        sp = sub.add_parser(op, help=helpstr)
        sp.add_argument("--input", nargs="+", required=True)
        sp.add_argument("--output-dir", required=True, dest="output_dir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "py2-to-py3":   return op_py2_to_py3(args)
        if args.op == "coffee-to-js": return op_coffee_to_js(args)
        if args.op == "vue2-to-vue3": return op_vue2_to_vue3(args)
        if args.op == "js-to-ts":     return op_js_to_ts(args)
        if args.op == "flow-to-ts":   return op_flow_to_ts(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
