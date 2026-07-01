"""Subtitle converter sidecar -- format conversion + retime / shift / scale via
pysubs2. Independent of clipforge's subtitle burn-in path; this is pure
subtitle-file manipulation.

Supports: SRT, WebVTT, ASS, SSA, MicroDVD, SBV (loose), TMP.

Frozen-guard: pysubs2 is bundled at build time; no runtime pip.
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
import sys
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


# Map UI-friendly names to pysubs2 format ids.
FORMAT_ALIASES = {
    "srt":     "srt",
    "subrip":  "srt",
    "vtt":     "vtt",
    "webvtt":  "vtt",
    "ass":     "ass",
    "ssa":     "ssa",
    "microdvd": "microdvd",
    "sub":     "microdvd",
    "tmp":     "tmp",
    "json":    "json",
}


def _import_pysubs2():
    try:
        import pysubs2  # noqa: F401
        return pysubs2
    except ImportError:
        return None


def op_convert(args: argparse.Namespace) -> int:
    pysubs2 = _import_pysubs2()
    if not pysubs2:
        return fail("missing_pysubs2", "pysubs2 not installed in this build.")

    target_alias = args.format.lower().lstrip(".")
    target = FORMAT_ALIASES.get(target_alias)
    if target is None:
        return fail("bad_format",
                    f"Unknown target '{args.format}'. Use one of: "
                    + ", ".join(sorted(set(FORMAT_ALIASES.keys()))))

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Subtitle file(s) not found: {missing}")

    total = len(inputs)
    out_ext = "." + target_alias if not target_alias.startswith(".") else target_alias
    if target_alias in ("subrip",): out_ext = ".srt"
    if target_alias in ("webvtt",): out_ext = ".vtt"
    if target_alias in ("microdvd", "sub"): out_ext = ".sub"

    emit("log", level="info",
         message=f"Convert {total} subtitle(s) -> .{target_alias} (pysubs2 format '{target}')")
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    for i, src in enumerate(inputs):
        try:
            subs = pysubs2.load(str(src), encoding=args.encoding or "utf-8")
        except Exception as ex:
            emit("log", level="error",
                 message=f"Failed to read {src.name}: {ex}")
            return fail("parse_failed", f"Could not parse {src.name}: {ex}")

        # Optional retiming
        if args.shift_ms:
            subs.shift(ms=int(args.shift_ms))
        if args.fps_in and args.fps_out:
            # Convert frame-based timings (e.g. MicroDVD captured at 23.976
            # but the video plays at 25). pysubs2 handles this with its
            # transform_framerate helper.
            try:
                subs.transform_framerate(float(args.fps_in), float(args.fps_out))
            except Exception as ex:
                emit("log", level="warn", message=f"Framerate transform failed: {ex}")

        out_path = out_dir / (src.stem + out_ext)
        try:
            subs.save(str(out_path), format_=target,
                      encoding=args.output_encoding or "utf-8")
        except Exception as ex:
            return fail("write_failed", f"Could not write {out_path.name}: {ex}")

        emit("subtitle",
             input=str(src),
             output=str(out_path),
             entries=len(subs),
             size_bytes=out_path.stat().st_size)

        pct = (i + 1) / total * 100.0
        emit("progress",
             percent=round(pct, 1),
             stage=f"converted {i + 1}/{total}",
             eta_seconds=None)

    total_size = sum(p.stat().st_size for p in out_dir.glob(f"*{out_ext}") if p.is_file())
    emit("complete", output=str(out_dir), size_bytes=total_size, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="subconvert-sidecar",
                                description="Subtitle file converter via pysubs2.")
    sub = p.add_subparsers(dest="op", required=True)

    cv = sub.add_parser("convert", help="Convert subtitles to a target format")
    cv.add_argument("--input", nargs="+", required=True)
    cv.add_argument("--output-dir", required=True, dest="output_dir")
    cv.add_argument("--format", required=True,
                    help="Target: srt | vtt | ass | ssa | microdvd | tmp | json")
    cv.add_argument("--encoding",
                    help="Source encoding (default utf-8). Try cp1252 / cp1251 for legacy.")
    cv.add_argument("--output-encoding", dest="output_encoding",
                    help="Target encoding (default utf-8).")
    cv.add_argument("--shift-ms", dest="shift_ms", type=int, default=0,
                    help="Shift every cue by this many milliseconds (negative = earlier).")
    cv.add_argument("--fps-in", dest="fps_in", type=float,
                    help="Source FPS for framerate-correct retiming.")
    cv.add_argument("--fps-out", dest="fps_out", type=float,
                    help="Target FPS for framerate-correct retiming.")

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
