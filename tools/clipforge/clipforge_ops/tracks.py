from __future__ import annotations

import argparse
from pathlib import Path

from .runtime import emit, fail, find_ffmpeg, find_ffprobe, probe, run_ffmpeg



def op_track_list(args: argparse.Namespace) -> int:
    """Enumerate every stream in a container. One `track` event per stream.

    Fields per event:
      stream_index  Container-level stream index (0,1,2,...)
      codec_type    video|audio|subtitle|data|attachment
      codec_name    h264, aac, ass, ...
      language      ISO-639 code if present, else null
      title         Stream title tag if present
      duration      Stream duration in seconds (best-effort)
      bit_rate      Per-stream bitrate (best-effort)
      width/height  For video streams
      channels      For audio streams
      default       Bool — disposition.default flag
    """
    ffprobe = find_ffprobe()
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    info = probe(ffprobe, str(src))
    if not info:
        return fail("probe_failed", "ffprobe could not read input.")

    streams = info.get("streams", [])
    for s in streams:
        tags = s.get("tags") or {}
        disp = s.get("disposition") or {}
        emit("track",
             stream_index=int(s.get("index", -1)),
             codec_type=str(s.get("codec_type") or ""),
             codec_name=str(s.get("codec_name") or ""),
             language=tags.get("language"),
             title=tags.get("title"),
             duration=float(s.get("duration") or 0) or None,
             bit_rate=int(s.get("bit_rate")) if s.get("bit_rate") else None,
             width=int(s.get("width") or 0) or None,
             height=int(s.get("height") or 0) or None,
             channels=int(s.get("channels") or 0) or None,
             default=bool(disp.get("default", 0)))
    emit("complete", output=str(src), size_bytes=src.stat().st_size,
         track_count=len(streams))
    return 0


def op_track_remove(args: argparse.Namespace) -> int:
    """Remove one or more streams without re-encoding.

    --remove takes a comma-separated list of container stream indices, e.g. "1,3,5".
    Builds an ffmpeg -map chain that includes every stream EXCEPT those, with -c copy
    so no re-encode happens. Output container is taken from --output's extension.
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src))
    if not info:
        return fail("probe_failed", "ffprobe could not read input.")
    duration = float(info.get("format", {}).get("duration", 0)) or 0.0

    try:
        drop = {int(x.strip()) for x in args.remove.split(",") if x.strip()}
    except ValueError:
        return fail("bad_remove_arg",
                    "--remove must be a comma-separated list of integer stream indices.")
    if not drop:
        return fail("nothing_to_remove", "--remove was empty.")

    keep_count = 0
    cmd: list[str] = [ffmpeg, "-y", "-i", str(src)]
    for s in info.get("streams", []):
        idx = int(s.get("index", -1))
        if idx in drop:
            continue
        cmd += ["-map", f"0:{idx}"]
        keep_count += 1
    if keep_count == 0:
        return fail("nothing_to_keep",
                    f"--remove {sorted(drop)} would strip every stream; refusing.")

    cmd += ["-c", "copy", "-map_metadata", "0"]
    if out.suffix.lower() in (".mp4", ".m4v", ".mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out))

    emit("log", level="info",
         message=f"Removing streams {sorted(drop)}; keeping {keep_count} of "
                 f"{len(info.get('streams', []))}.")
    emit("progress", percent=0, stage="track-remove", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "track-remove")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out.is_file():
        return fail("output_missing", f"Output not produced: {out}")
    emit("complete", output=str(out), size_bytes=out.stat().st_size)
    return 0


def op_track_add(args: argparse.Namespace) -> int:
    """Add an external audio (or subtitle) file as a new track without re-encoding.

    Stream-copies the original input plus all streams from --extra. Useful for:
      * attaching a dubbed audio language
      * adding an SRT/ASS subtitle into an MKV
      * attaching a commentary track to a finished cut
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    extra = Path(args.extra)
    if not extra.is_file():
        return fail("missing_extra", f"Extra track file not found: {args.extra}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src))
    duration = float((info or {}).get("format", {}).get("duration", 0)) or 0.0

    cmd = [ffmpeg, "-y",
           "-i", str(src),
           "-i", str(extra),
           "-map", "0",          # everything from primary
           "-map", "1",          # everything from extra
           "-c", "copy",
           "-map_metadata", "0"]
    if args.language:
        # Apply language to NEW streams only -- the metadata index is the count
        # of streams in the primary input.
        new_idx = len((info or {}).get("streams", []))
        cmd += [f"-metadata:s:{new_idx}", f"language={args.language}"]
    if args.title:
        new_idx = len((info or {}).get("streams", []))
        cmd += [f"-metadata:s:{new_idx}", f"title={args.title}"]
    if out.suffix.lower() in (".mp4", ".m4v", ".mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out))

    emit("log", level="info",
         message=f"Add track from {extra.name} -> {out.name}")
    emit("progress", percent=0, stage="track-add", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "track-add")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out.is_file():
        return fail("output_missing", f"Output not produced: {out}")
    emit("complete", output=str(out), size_bytes=out.stat().st_size)
    return 0


def op_track_extract(args: argparse.Namespace) -> int:
    """Export one stream from the container to a standalone file.

    Currently scoped to subtitle streams (Item 13 narrowed). The output codec
    is auto-picked from the output extension:

      .srt -> subrip
      .vtt -> webvtt
      .ass / .ssa -> ass / ssa
      .lrc -> lrc
      .sup -> copy (PGS bitmap, no decode/re-encode possible)

    --stream is the container-level stream index (matches what track-list
    reports as `stream_index`).

    Refuses to operate on non-subtitle streams to keep the contract narrow.
    Audio / video extraction would belong in a separate op so the option
    matrix doesn't blow up.
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        stream_idx = int(args.stream)
    except (TypeError, ValueError):
        return fail("bad_stream_arg", "--stream must be an integer index.")

    info = probe(ffprobe, str(src))
    if not info:
        return fail("probe_failed", "ffprobe could not read input.")

    target = next((s for s in info.get("streams", []) if int(s.get("index", -1)) == stream_idx), None)
    if target is None:
        return fail("missing_stream",
                    f"Stream index {stream_idx} not present in {src.name}.")
    if str(target.get("codec_type") or "").lower() != "subtitle":
        return fail("not_a_subtitle",
                    f"Stream {stream_idx} is a "
                    f"{target.get('codec_type', 'unknown')} stream; "
                    f"track-extract is currently subtitle-only.")

    out_ext = out.suffix.lower()
    codec_map = {
        ".srt":  "subrip",
        ".vtt":  "webvtt",
        ".ass":  "ass",
        ".ssa":  "ssa",
        ".lrc":  "lrc",
    }
    if out_ext == ".sup":
        # PGS / bitmap subs — copy through, no transcoding possible
        codec = "copy"
    elif out_ext in codec_map:
        codec = codec_map[out_ext]
    else:
        return fail("bad_output_ext",
                    f"Unsupported output extension '{out_ext}'. "
                    f"Choose one of: {sorted([*codec_map.keys(), '.sup'])}")

    src_codec = str(target.get("codec_name") or "").lower()
    # Bitmap PGS / DVD subs cannot be transcoded to text formats — error early.
    bitmap_codecs = {"hdmv_pgs_subtitle", "dvd_subtitle", "pgssub"}
    if src_codec in bitmap_codecs and codec != "copy":
        return fail("bitmap_to_text_unsupported",
                    f"Source stream is bitmap subtitles ({src_codec}); only "
                    f"--output ending in .sup (stream copy) is supported. "
                    f"OCR conversion to text formats lives in subocr / subkit sidecars.")

    duration = float(info.get("format", {}).get("duration", 0)) or 0.0

    cmd = [ffmpeg, "-y", "-i", str(src),
           "-map", f"0:{stream_idx}",
           "-c:s", codec,
           str(out)]

    emit("log", level="info",
         message=f"Extracting subtitle stream #{stream_idx} ({src_codec}) -> "
                 f"{out.name} ({codec})")
    emit("progress", percent=0, stage="track-extract", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "track-extract")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out.is_file():
        return fail("output_missing", f"Output not produced: {out}")
    emit("complete", output=str(out), size_bytes=out.stat().st_size,
         stream_index=stream_idx, source_codec=src_codec, output_codec=codec)
    return 0

