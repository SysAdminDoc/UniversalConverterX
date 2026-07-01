"""ChapterMark sidecar — NDJSON read / write for embedded MKV / MP4 chapters.

Subcommands:
  read    Probe the input file and emit one `chapter` event per discovered marker.
  write   Replace the input's chapter table with markers from --chapters-json.

FFmpeg's metadata format is the canonical way to write chapters:
  ;FFMETADATA1
  [CHAPTER]
  TIMEBASE=1/1000
  START=0
  END=120000
  title=Intro
  ...
A reverse-encode is avoided — we use `-codec copy -map_metadata 1` so the
write path is fast and lossless.

Standard NDJSON contract: progress / log / complete / error / chapter events.
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
import tempfile
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


def progress(percent: float, stage: str = "") -> None:
    emit("progress", percent=round(percent, 1), stage=stage)


# ── tools ────────────────────────────────────────────────────────────────────

def find_tool(name: str) -> str | None:
    here = Path(__file__).resolve().parent
    for c in [
        os.environ.get(f"{name.upper()}_PATH"),
        shutil.which(name),
        str(here / f"{name}.exe"),
        str(here.parent / "_bin" / f"{name}.exe"),
    ]:
        if c and Path(c).is_file():
            return c
    return None


# ── read ─────────────────────────────────────────────────────────────────────

def op_read(args: argparse.Namespace) -> int:
    ffprobe = find_tool("ffprobe")
    if ffprobe is None:
        return fail("missing_ffprobe", "ffprobe not on PATH; set FFPROBE_PATH or install FFmpeg.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")

    progress(10.0, "probing chapters")
    result = subprocess.run(
        [ffprobe, "-v", "quiet", "-show_chapters", "-print_format", "json", str(in_path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return fail("ffprobe_failed", f"ffprobe exited {result.returncode}: {result.stderr.strip()[:300]}")

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        return fail("parse_failed", f"Could not parse ffprobe JSON: {exc}")

    chapters = data.get("chapters", [])
    for c in chapters:
        # ffprobe normalises start/end into seconds via start_time / end_time strings.
        start = float(c.get("start_time") or 0.0)
        end = float(c.get("end_time") or 0.0)
        title = (c.get("tags") or {}).get("title", "") or f"Chapter {c.get('id', '?')}"
        emit("chapter", id=int(c.get("id", 0)), start=start, end=end, title=title)

    progress(100.0, "done")
    emit("complete", count=len(chapters))
    return 0


# ── write ────────────────────────────────────────────────────────────────────

_FFMETA_HEADER = ";FFMETADATA1\n"


def _build_ffmetadata(chapters: list[dict], total_duration_s: float) -> str:
    """Render a list of {start, end?, title} dicts as an FFMETADATA1 chapter file.

    Missing `end` values are filled with the next chapter's start (or
    `total_duration_s` for the last chapter). Times are in seconds; we emit
    millisecond TIMEBASE for round-trip clarity with most NLEs.
    """
    lines = [_FFMETA_HEADER]
    sorted_ch = sorted(chapters, key=lambda c: float(c.get("start", 0)))
    for i, c in enumerate(sorted_ch):
        start_s = float(c.get("start", 0))
        if "end" in c and c["end"] is not None:
            end_s = float(c["end"])
        elif i + 1 < len(sorted_ch):
            end_s = float(sorted_ch[i + 1].get("start", start_s + 1))
        else:
            end_s = max(start_s + 1, total_duration_s)
        title = str(c.get("title", "") or f"Chapter {i + 1}")

        lines.append("[CHAPTER]\n")
        lines.append("TIMEBASE=1/1000\n")
        lines.append(f"START={int(round(start_s * 1000))}\n")
        lines.append(f"END={int(round(end_s * 1000))}\n")
        # FFmpeg's chapter title key is `title=` under the implicit chapter section.
        lines.append(f"title={title}\n")
    return "".join(lines)


def _probe_duration(ffprobe: str, path: Path) -> float:
    result = subprocess.run(
        [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=20,
    )
    try:
        return float(result.stdout.strip()) if result.returncode == 0 else 0.0
    except ValueError:
        return 0.0


def op_write(args: argparse.Namespace) -> int:
    ffmpeg = find_tool("ffmpeg")
    ffprobe = find_tool("ffprobe")
    if ffmpeg is None:
        return fail("missing_ffmpeg", "ffmpeg not on PATH; set FFMPEG_PATH or install FFmpeg.")
    if ffprobe is None:
        return fail("missing_ffprobe", "ffprobe not on PATH; set FFPROBE_PATH or install FFmpeg.")

    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")

    if not args.chapters_json or not Path(args.chapters_json).is_file():
        return fail("missing_chapters_json",
                    "Pass --chapters-json <file>; the file must be a JSON array of "
                    "{start (sec), end (sec, optional), title} objects.")

    try:
        chapters = json.loads(Path(args.chapters_json).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return fail("parse_failed", f"Could not parse chapter JSON: {exc}")
    if not isinstance(chapters, list):
        return fail("invalid_chapters", "chapters JSON must be a top-level list.")

    progress(10.0, "probing duration")
    duration = _probe_duration(ffprobe, in_path)

    progress(20.0, "building metadata")
    ffmeta = _build_ffmetadata(chapters, duration)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".ffmeta", delete=False, encoding="utf-8") as tmp:
        tmp.write(ffmeta)
        meta_path = Path(tmp.name)

    try:
        progress(40.0, "muxing chapters (codec copy)")
        # `-i input -i chapters.ffmeta -map_metadata 1 -codec copy` rewrites
        # the chapter table without re-encoding video/audio.
        cmd = [
            ffmpeg, "-y",
            "-i", str(in_path),
            "-i", str(meta_path),
            "-map_metadata", "1",
            "-codec", "copy",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            for ln in (result.stderr or "").splitlines()[-15:]:
                log("error", ln)
            return fail("mux_failed", f"ffmpeg exited {result.returncode}")

        if not out_path.is_file():
            return fail("output_missing", f"Output not produced: {out_path}")

        progress(100.0, "done")
        emit("complete",
             output=str(out_path),
             size_bytes=out_path.stat().st_size,
             chapters_written=len(chapters))
        return 0
    finally:
        try:
            meta_path.unlink()
        except OSError:
            pass


# ── argparse + main ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chaptermark-sidecar",
        description="UCX ChapterMark sidecar — read / write embedded MKV/MP4 chapters.",
    )
    sub = p.add_subparsers(dest="op", required=True)

    r = sub.add_parser("read", help="Read chapters from a media file")
    r.add_argument("--input", required=True)

    w = sub.add_parser("write", help="Write a chapter table into a media file (codec copy)")
    w.add_argument("--input", required=True)
    w.add_argument("--output", required=True)
    w.add_argument("--chapters-json", required=True,
                   help="Path to a JSON file: [{start, end?, title}, ...]. Times in seconds.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "read":
            return op_read(args)
        if args.op == "write":
            return op_write(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
