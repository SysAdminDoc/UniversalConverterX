"""Closed-caption extraction + conversion sidecar (FFmpeg-based).

Complements subconvert (pysubs2 subtitle-file formats) with the broadcast /
container caption paths pysubs2 cannot do:

  * Extract an embedded subtitle/caption track from a video to SRT/VTT/ASS.
  * Extract EIA/CEA-608 captions carried in the video bitstream (SEI) via the
    FFmpeg `movie=...[out+subcc]` graph.
  * Convert a caption file to SRT/VTT/ASS, reading broadcast Scenarist SCC as an
    input (FFmpeg has no CEA-608 encoder, so SCC is input-only).
  * Detect which subtitle/caption streams a file carries.

Operations:
  detect    List subtitle/caption streams in a media file -> `stream` events.
  extract   Pull a caption track (or embedded 608) to a subtitle file.
  convert   Convert a caption file to another format (SCC-aware).

Requires FFmpeg + FFprobe (managed/bundled). Pure stdlib otherwise.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg, find_ffprobe, probe_media, run_ffmpeg


# Target format -> (extension, FFmpeg subtitle encoder args). Output is limited
# to text subtitle formats: FFmpeg has no CEA-608 encoder, so Scenarist SCC is
# supported as an INPUT only (SCC -> SRT/VTT/ASS), never as an output target.
_TARGETS = {
    "srt":    (".srt", ["-c:s", "srt"]),
    "subrip": (".srt", ["-c:s", "srt"]),
    "vtt":    (".vtt", ["-c:s", "webvtt"]),
    "webvtt": (".vtt", ["-c:s", "webvtt"]),
    "ass":    (".ass", ["-c:s", "ass"]),
}


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _ffprobe() -> str | None:
    return find_ffprobe(Path(__file__).resolve().parent)


def _ffmpeg() -> str | None:
    return find_ffmpeg(Path(__file__).resolve().parent)


def _resolve_target(fmt: str) -> tuple[str, list[str]] | None:
    return _TARGETS.get(fmt.lower().lstrip("."))


def _escape_movie_path(path: Path) -> str:
    """Escape a filesystem path for use inside an FFmpeg `movie=` filtergraph.

    Filtergraph parsing treats ':' and '\\' specially, so forward-slash the
    path and backslash-escape the drive colon (C\\:/dir/file.mp4)."""
    text = str(path.resolve()).replace("\\", "/")
    return text.replace(":", "\\:")


def op_detect(args: argparse.Namespace) -> int:
    ffprobe = _ffprobe()
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    info = probe_media(ffprobe, src)
    if not info:
        return fail("probe_failed", "Could not read input metadata.")

    count = 0
    for stream in info.get("streams", []):
        if stream.get("codec_type") != "subtitle":
            continue
        tags = stream.get("tags", {}) or {}
        emit("stream",
             index=stream.get("index"),
             codec=stream.get("codec_name"),
             language=tags.get("language"),
             title=tags.get("title"))
        count += 1

    emit("complete", output=str(src), size_bytes=0, count=count)
    return 0


def op_extract(args: argparse.Namespace) -> int:
    ffmpeg = _ffmpeg()
    ffprobe = _ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    target = _resolve_target(args.format)
    if target is None:
        return fail("bad_format",
                    f"Unknown target '{args.format}'. Use: {', '.join(sorted(_TARGETS))}.")
    out_ext, codec_args = target
    out_path = Path(args.output)
    if out_path.suffix.lower() != out_ext:
        out_path = out_path.with_suffix(out_ext)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe_media(ffprobe, src)
    duration = 0.0
    try:
        duration = float((info or {}).get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0

    if args.embedded_608:
        # CEA/EIA-608 carried in the video bitstream is surfaced by the movie
        # source filter's +subcc option, then muxed to the target format.
        graph = f"movie={_escape_movie_path(src)}[out+subcc]"
        cmd = [ffmpeg, "-y", "-hide_banner", "-f", "lavfi", "-i", graph,
               "-map", "0:s:0", *codec_args, str(out_path)]
    else:
        subtitle_streams = [
            s for s in (info or {}).get("streams", [])
            if s.get("codec_type") == "subtitle"
        ]
        if not subtitle_streams:
            return fail("no_captions",
                        "No embedded subtitle/caption track found. For CEA-608 "
                        "carried in the video stream, pass --embedded-608.")
        cmd = [ffmpeg, "-y", "-hide_banner", "-i", str(src),
               "-map", f"0:s:{args.track}", *codec_args, str(out_path)]

    rc = run_ffmpeg(cmd, duration, "extract", inject_progress_args=False)
    if rc != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        return fail("extract_failed",
                    "No captions were extracted. The track may be empty or the "
                    "source may carry no captions of the requested kind.")

    emit("caption", input=str(src), output=str(out_path),
         format=out_ext.lstrip("."), size_bytes=out_path.stat().st_size)
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def op_convert(args: argparse.Namespace) -> int:
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    target = _resolve_target(args.format)
    if target is None:
        return fail("bad_format",
                    f"Unknown target '{args.format}'. Use: {', '.join(sorted(_TARGETS))}.")
    out_ext, codec_args = target
    out_path = Path(args.output)
    if out_path.suffix.lower() != out_ext:
        out_path = out_path.with_suffix(out_ext)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), *codec_args, str(out_path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as exc:
        return fail("ffmpeg_failed", f"Conversion failed: {exc}")
    if result.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        tail = (result.stderr or "").strip().splitlines()[-1:] if result.stderr else []
        return fail("convert_failed",
                    f"Could not convert {src.name} to {out_ext}. {' '.join(tail)}".strip())

    emit("caption", input=str(src), output=str(out_path),
         format=out_ext.lstrip("."), size_bytes=out_path.stat().st_size)
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size, count=1)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ccextract-sidecar",
        description="Extract and convert closed captions / subtitle tracks via FFmpeg.")
    sub = p.add_subparsers(dest="op", required=True)

    detect = sub.add_parser("detect", help="List subtitle/caption streams in a media file")
    detect.add_argument("--input", required=True)

    extract = sub.add_parser("extract", help="Extract a caption track to a subtitle file")
    extract.add_argument("--input", required=True)
    extract.add_argument("--output", required=True)
    extract.add_argument("--format", default="srt",
                         help="Target: srt | vtt | ass (default srt)")
    extract.add_argument("--track", type=int, default=0,
                         help="Subtitle stream index within the file (default 0)")
    extract.add_argument("--embedded-608", action="store_true", dest="embedded_608",
                         help="Extract CEA/EIA-608 carried in the video bitstream "
                              "(SEI) rather than a container subtitle track.")

    convert = sub.add_parser("convert", help="Convert a caption file to another format")
    convert.add_argument("--input", required=True)
    convert.add_argument("--output", required=True)
    convert.add_argument("--format", required=True,
                         help="Target: srt | vtt | ass (SCC is input-only)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "detect":
            return op_detect(args)
        if args.op == "extract":
            return op_extract(args)
        if args.op == "convert":
            return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:  # noqa: BLE001 — surface any failure as NDJSON
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
