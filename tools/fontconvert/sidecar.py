"""Font converter sidecar -- TTF / OTF / WOFF / WOFF2 mutual conversion via
fonttools (+ brotli for WOFF2).

Frozen-guard: deps are bundled at PyInstaller-build time; no runtime pip.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# (target_extension)
TARGETS = {"ttf", "otf", "woff", "woff2"}


def _import_fonttools():
    try:
        from fontTools.ttLib import TTFont  # noqa: F401
        return True
    except ImportError:
        return False


def op_info(args: argparse.Namespace) -> int:
    if not _import_fonttools():
        return fail("missing_fonttools", "fonttools not installed in this build.")
    from fontTools.ttLib import TTFont
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Font not found: {args.input}")
    try:
        with TTFont(str(src), lazy=True) as f:
            sfnt = f.sfntVersion
            flavor = f.flavor or "sfnt"
            family = ""
            try:
                name_table = f["name"]
                for rec in name_table.names:
                    if rec.nameID == 1:
                        family = rec.toUnicode()
                        break
            except Exception:
                pass
            tables = sorted(f.keys())
            emit("font_info",
                 path=str(src),
                 sfnt_version=sfnt,
                 flavor=flavor,
                 family=family,
                 num_glyphs=f.getGlyphOrder().__len__(),
                 tables=tables)
    except Exception as ex:
        return fail("parse_failed", f"fontTools could not parse {src.name}: {ex}")
    emit("complete", output=str(src), size_bytes=src.stat().st_size)
    return 0


def op_convert(args: argparse.Namespace) -> int:
    if not _import_fonttools():
        return fail("missing_fonttools", "fonttools not installed in this build.")
    from fontTools.ttLib import TTFont

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Font(s) not found: {missing}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    if target not in TARGETS:
        return fail("bad_format",
                    f"Unknown target '{target}'. Use: ttf | otf | woff | woff2")

    if target == "woff2":
        try:
            import brotli  # noqa: F401
        except ImportError:
            return fail("missing_brotli",
                        "Brotli wasn't bundled in this build; rebuild with pip install brotli.")

    emit("log", level="info",
         message=f"Convert {len(inputs)} font(s) -> .{target}")
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            font = TTFont(str(src))
            if target == "woff":
                font.flavor = "woff"
            elif target == "woff2":
                font.flavor = "woff2"
            else:
                # Strip flavor when writing TTF/OTF.
                font.flavor = None

            out_path = out_dir / (src.stem + "." + target)
            font.save(str(out_path))
            font.close()
        except Exception as ex:
            emit("log", level="error", message=f"{src.name}: {ex}")
            return fail("convert_failed", f"Could not convert {src.name}: {ex}")

        emit("font",
             input=str(src),
             output=str(out_path),
             size_bytes=out_path.stat().st_size)

        pct = (i + 1) / len(inputs) * 100.0
        emit("progress", percent=round(pct, 1),
             stage=f"converted {i + 1}/{len(inputs)}",
             eta_seconds=None)

    total_size = sum((out_dir / (Path(p).stem + "." + target)).stat().st_size
                     for p in args.input
                     if (out_dir / (Path(p).stem + "." + target)).is_file())
    emit("complete", output=str(out_dir), size_bytes=total_size, count=len(inputs))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fontconvert-sidecar",
                                description="Font conversion (TTF/OTF/WOFF/WOFF2) via fonttools.")
    sub = p.add_subparsers(dest="op", required=True)

    cv = sub.add_parser("convert", help="Convert one or more fonts to a target format")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True, help="ttf | otf | woff | woff2")

    info = sub.add_parser("info", help="Probe a font and emit its core metadata")
    info.add_argument("--input", required=True)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "info":    return op_info(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
