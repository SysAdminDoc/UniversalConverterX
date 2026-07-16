"""ClipForge sidecar — NDJSON CLI shim for the UCX Editor module.

Supported ops:
  trim      Trim a clip by start/end seconds (lossless stream-copy or re-encode).
  crop      Crop video to W:H:X:Y via -vf crop.
  crop-meta Set H.264/H.265 SPS display-crop metadata without decoding frames.
  aspect-override Set container display aspect ratio without changing packets.
  rotate    Rotate/flip video via -vf transpose / hflip / vflip.
  loudnorm  EBU R128 loudness normalisation via -af loudnorm.
  rewrap    Change container without re-encoding (-c copy stream copy).

Contract: see ../README.md (sidecar contract) and ../../README.md (parent).
"""
from __future__ import annotations

import argparse
import json
import os
import math
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import (
    emit,
    find_ffmpeg as shared_find_ffmpeg,
    find_ffprobe as shared_find_ffprobe,
    probe_media,
    run_ffmpeg,
)




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_ffmpeg() -> str | None:
    return shared_find_ffmpeg(Path(__file__).resolve().parent)


def find_ffprobe() -> str | None:
    return shared_find_ffprobe(Path(__file__).resolve().parent)


def probe(ffprobe: str, path: str) -> dict | None:
    return probe_media(ffprobe, path)


def op_trim(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    src_dur = float(info.get("format", {}).get("duration", 0))
    if src_dur <= 0:
        return fail("probe_failed", "Could not determine input duration.")

    start = max(0.0, args.start)
    end = args.end if args.end is not None and args.end > 0 else src_dur
    end = min(end, src_dur)
    if end <= start:
        return fail("invalid_range", f"Trim end ({end:.2f}) must be greater than start ({start:.2f}).")
    span = end - start

    emit("log", level="info", message=f"Trim {start:.2f}-{end:.2f} ({span:.2f}s) of {src_dur:.2f}s")

    if args.lossless:
        # Stream-copy trim — fast but only cuts on keyframes; output may be slightly off.
        cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", str(in_path), "-c", "copy",
               "-map_metadata", "0", "-movflags", "+faststart", str(out_path)]
        emit("progress", percent=0, stage="trim (lossless)", eta_seconds=None)
        rc = run_ffmpeg(cmd, span, "trim (lossless)")
    else:
        cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", str(in_path),
               "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset]
        if args.audio_codec == "an":
            cmd += ["-an"]
        elif args.audio_codec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", args.audio_codec, "-b:a", f"{args.audio_bitrate}k"]
        cmd += ["-movflags", "+faststart", str(out_path)]
        emit("progress", percent=0, stage="trim (re-encode)", eta_seconds=None)
        rc = run_ffmpeg(cmd, span, "trim (re-encode)")

    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_crop(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    crop_filter = f"crop={args.width}:{args.height}:{args.x}:{args.y}"
    emit("log", level="info", message=f"Crop filter: {crop_filter}")

    cmd = [ffmpeg, "-y", "-i", str(in_path),
           "-vf", crop_filter,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy",
           "-movflags", "+faststart", str(out_path)]
    emit("progress", percent=0, stage="crop", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "crop")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def _first_video_stream(info: dict) -> dict | None:
    return next(
        (stream for stream in info.get("streams", [])
         if stream.get("codec_type") == "video"),
        None,
    )


def _stream_copy_command(ffmpeg: str, in_path: Path, out_path: Path) -> list[str]:
    command = [
        ffmpeg, "-y", "-i", str(in_path),
        "-map", "0", "-c", "copy",
        "-map_metadata", "0", "-map_chapters", "0",
    ]
    if out_path.suffix.lower() in (".mp4", ".m4v", ".mov"):
        command += ["-movflags", "+faststart"]
    return command


def op_crop_meta(args: argparse.Namespace) -> int:
    """Set codec display-crop metadata without decoding or re-encoding.

    H.264 and H.265 carry cropping offsets in the SPS. FFmpeg's metadata
    bitstream filters rewrite those headers while copying every coded picture
    unchanged. Packet hashes can therefore differ at SPS packets, but decoded
    samples remain lossless when cropping is disabled by the decoder.
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    crop = {
        "left": args.left,
        "right": args.right,
        "top": args.top,
        "bottom": args.bottom,
    }
    if any(value < 0 for value in crop.values()):
        return fail("invalid_crop", "Crop offsets must be zero or greater.")
    if not any(crop.values()):
        return fail("invalid_crop", "At least one crop offset must be greater than zero.")

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    video = _first_video_stream(info)
    if video is None:
        return fail("missing_video", "Input has no video stream.")

    codec = str(video.get("codec_name", "")).lower()
    if codec not in {"h264", "hevc"}:
        return fail(
            "unsupported_codec",
            f"Lossless crop metadata supports H.264/H.265; input codec is {codec or 'unknown'}.",
        )

    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    expected_width = width - crop["left"] - crop["right"]
    expected_height = height - crop["top"] - crop["bottom"]
    if width <= 0 or height <= 0:
        return fail("probe_failed", "Could not determine source dimensions.")
    if expected_width <= 0 or expected_height <= 0:
        return fail("invalid_crop", "Crop offsets remove the entire video frame.")

    filter_name = "h264_metadata" if codec == "h264" else "hevc_metadata"
    filter_options = ":".join(
        f"crop_{edge}={value}" for edge, value in crop.items()
    )
    command = _stream_copy_command(ffmpeg, in_path, out_path)
    command += ["-bsf:v:0", f"{filter_name}={filter_options}", str(out_path)]
    duration = float(info.get("format", {}).get("duration") or 0)
    emit("log", level="info",
         message=f"{codec.upper()} display crop -> {expected_width}x{expected_height}; coded pictures are copied.")
    emit("progress", percent=0, stage="crop metadata (stream copy)", eta_seconds=None)
    rc = run_ffmpeg(command, duration, "crop metadata (stream copy)")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file() or out_path.stat().st_size <= 0:
        return fail("output_missing", f"Output not produced: {out_path}")

    output_info = probe(ffprobe, str(out_path)) or {}
    output_video = _first_video_stream(output_info)
    if output_video is None or int(output_video.get("width") or 0) != expected_width \
            or int(output_video.get("height") or 0) != expected_height:
        return fail(
            "verification_failed",
            f"Output did not report the requested {expected_width}x{expected_height} display crop.",
        )

    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         codec=codec, width=expected_width, height=expected_height,
         reencoded=False)
    return 0


def _parse_aspect_ratio(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d{1,5})\s*[:/]\s*(\d{1,5})\s*", value)
    if not match:
        return None
    numerator, denominator = (int(match.group(1)), int(match.group(2)))
    if numerator <= 0 or denominator <= 0:
        return None
    divisor = math.gcd(numerator, denominator)
    return numerator // divisor, denominator // divisor


def op_aspect_override(args: argparse.Namespace) -> int:
    """Override display aspect in the output container with packet stream-copy."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    aspect = _parse_aspect_ratio(args.aspect)
    if aspect is None:
        return fail("invalid_aspect", "Aspect must be a positive ratio such as 16:9 or 4/3.")

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    if _first_video_stream(info) is None:
        return fail("missing_video", "Input has no video stream.")

    aspect_text = f"{aspect[0]}:{aspect[1]}"
    command = _stream_copy_command(ffmpeg, in_path, out_path)
    command += ["-aspect:v:0", aspect_text, str(out_path)]
    duration = float(info.get("format", {}).get("duration") or 0)
    emit("log", level="info",
         message=f"Display aspect -> {aspect_text}; compressed packets are copied unchanged.")
    emit("progress", percent=0, stage="aspect override (stream copy)", eta_seconds=None)
    rc = run_ffmpeg(command, duration, "aspect override (stream copy)")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file() or out_path.stat().st_size <= 0:
        return fail("output_missing", f"Output not produced: {out_path}")

    output_info = probe(ffprobe, str(out_path)) or {}
    output_video = _first_video_stream(output_info)
    reported = str((output_video or {}).get("display_aspect_ratio") or "")
    if _parse_aspect_ratio(reported) != aspect:
        return fail(
            "verification_failed",
            f"Output reports display aspect {reported or 'unknown'}, expected {aspect_text}.",
        )

    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         display_aspect_ratio=aspect_text, reencoded=False)
    return 0


# Mapping from human-readable angle/flip to FFmpeg filter
_ROTATE_FILTERS: dict[str, str] = {
    "90":     "transpose=1",        # 90° clockwise
    "180":    "transpose=2,transpose=2",  # 180°
    "270":    "transpose=2",        # 90° counter-clockwise (270° clockwise)
    "flip_h": "hflip",
    "flip_v": "vflip",
}


def op_rotate(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    vf = _ROTATE_FILTERS.get(args.angle)
    if not vf:
        return fail("invalid_args", f"Unknown angle: {args.angle}. Use 90, 180, 270, flip_h, or flip_v.")

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    emit("log", level="info", message=f"Rotate filter: {vf}")

    cmd = [ffmpeg, "-y", "-i", str(in_path),
           "-vf", vf,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy",
           "-movflags", "+faststart", str(out_path)]
    emit("progress", percent=0, stage="rotate", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "rotate")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_loudnorm(args: argparse.Namespace) -> int:
    """Two-pass EBU R128 loudness normalisation.

    Pass 1 analyses the input and writes measured levels to a temp JSON.
    Pass 2 applies the linear normalisation filter with the measured values
    so the output has exactly the target integrated loudness.
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    il = args.integrated_lufs   # target integrated loudness (e.g. -14)
    tp = args.true_peak          # max true peak (e.g. -1.5)
    lra = args.lra               # loudness range (e.g. 11)

    # Pass 1: measure input levels
    emit("log", level="info", message="Loudnorm pass 1 — measuring levels")
    emit("progress", percent=0, stage="loudnorm (measure)", eta_seconds=None)
    p1_filter = f"loudnorm=I={il}:TP={tp}:LRA={lra}:print_format=json"
    p1_cmd = [ffmpeg, "-y", "-i", str(in_path),
              "-af", p1_filter,
              "-f", "null",
              "NUL" if sys.platform == "win32" else "/dev/null"]
    proc = subprocess.run(p1_cmd, capture_output=True, text=True)
    # loudnorm stats come on stderr as a JSON block
    measured: dict = {}
    try:
        stderr_text = proc.stderr or ""
        # Locate the JSON block in the stderr output
        start = stderr_text.rfind("{")
        end = stderr_text.rfind("}") + 1
        if start != -1 and end > start:
            measured = json.loads(stderr_text[start:end])
    except (json.JSONDecodeError, ValueError):
        pass

    if not measured:
        # Graceful fallback: single-pass without measured values
        emit("log", level="warning", message="Could not parse loudnorm measurements; falling back to single-pass.")
        p2_filter = f"loudnorm=I={il}:TP={tp}:LRA={lra}"
    else:
        p2_filter = (
            f"loudnorm=I={il}:TP={tp}:LRA={lra}"
            f":measured_I={measured.get('input_i', il)}"
            f":measured_TP={measured.get('input_tp', tp)}"
            f":measured_LRA={measured.get('input_lra', lra)}"
            f":measured_thresh={measured.get('input_thresh', -70)}"
            f":offset={measured.get('target_offset', 0)}"
            f":linear=true"
        )

    emit("log", level="info", message="Loudnorm pass 2 — applying normalisation")
    emit("progress", percent=50, stage="loudnorm (encode)", eta_seconds=None)
    p2_cmd = [ffmpeg, "-y", "-i", str(in_path),
              "-af", p2_filter,
              "-c:v", "copy",
              "-c:a", args.audio_codec, "-b:a", f"{args.audio_bitrate}k",
              "-ar", "48000",
              str(out_path)]
    rc = run_ffmpeg(p2_cmd, duration, "loudnorm (encode)")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


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


def op_timeline(args: argparse.Namespace) -> int:
    """Extract a thumbnail strip + waveform image so the UI can paint a visual
    scrub bar above the seek slider. Output dir gets:
       tn_0001.jpg, tn_0002.jpg, ...   (1 fps thumbnails, scaled to ~120px wide)
       waveform.png                    (showwavespic-rendered audio waveform)
    Emits one `thumb` event per generated frame so the host can lazy-load."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")

    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        return fail("probe_failed", "Zero / unknown duration.")

    fps = max(0.1, float(args.thumb_fps))
    thumb_height = int(args.thumb_height)
    expected = max(1, int(duration * fps))

    emit("log", level="info",
         message=f"Timeline: {expected} thumbs @ {fps} fps, scaled to h={thumb_height}px")
    emit("progress", percent=0, stage="thumbnails", eta_seconds=None)

    pattern = str(out_dir / "tn_%05d.jpg")
    cmd_tn = [
        ffmpeg, "-y",
        "-i", str(src),
        "-vf", f"fps={fps},scale=-2:{thumb_height}:flags=fast_bilinear",
        "-q:v", "5",   # JPEG quality 1-31, lower=better; 5 keeps strips crisp without bloat
        pattern,
    ]
    rc = run_ffmpeg(cmd_tn, duration, "thumbnails")
    if rc != 0:
        return fail("ffmpeg_failed", f"Thumbnail extraction failed (exit {rc})")

    # Enumerate the thumbs that actually landed and emit one event each.
    files = sorted(out_dir.glob("tn_*.jpg"))
    for i, f in enumerate(files):
        ts = i / fps
        emit("thumb",
             index=i,
             timestamp_seconds=round(ts, 3),
             path=str(f))

    # Waveform image (no failure if no audio track -- skip cleanly).
    has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    waveform = out_dir / "waveform.png"
    if has_audio:
        emit("progress", percent=0, stage="waveform", eta_seconds=None)
        cmd_wf = [
            ffmpeg, "-y",
            "-i", str(src),
            "-filter_complex",
            f"showwavespic=s={int(args.waveform_width)}x{int(args.waveform_height)}"
            f":colors={args.waveform_color}:split_channels=0",
            "-frames:v", "1",
            str(waveform),
        ]
        rc = run_ffmpeg(cmd_wf, duration, "waveform")
        if rc != 0:
            emit("log", level="warn",
                 message=f"Waveform render failed (exit {rc}); thumbnails still produced")

    emit("progress", percent=100, stage="timeline", eta_seconds=0)
    emit("complete",
         output=str(out_dir),
         size_bytes=sum(p.stat().st_size for p in out_dir.iterdir() if p.is_file()),
         thumb_count=len(files),
         duration_seconds=round(duration, 3),
         waveform_path=str(waveform) if waveform.is_file() else None,
         fps=fps)
    return 0


def op_keyframes(args: argparse.Namespace) -> int:
    """List the video keyframe timestamps so a lossless-cut UI can snap in/out
    points to a keyframe boundary. Stream-copy trims can only cut on keyframes,
    so exposing them lets the host show the exact frames a lossless cut will
    land on. Emits one `keyframes` event carrying the sorted timestamp list."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")

    cmd = [
        ffprobe, "-v", "quiet",
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-show_entries", "frame=pts_time,best_effort_timestamp_time",
        "-of", "json",
        str(src),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (subprocess.SubprocessError, OSError) as exc:
        return fail("ffprobe_failed", f"Keyframe probe failed: {exc}")
    if result.returncode != 0:
        return fail("ffprobe_failed", f"Keyframe probe exited {result.returncode}.")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return fail("ffprobe_failed", "Keyframe probe returned invalid JSON.")

    times: list[float] = []
    for frame in payload.get("frames", []):
        raw = frame.get("pts_time")
        if raw in (None, "N/A"):
            raw = frame.get("best_effort_timestamp_time")
        if raw in (None, "N/A"):
            continue
        try:
            times.append(round(float(raw), 3))
        except (TypeError, ValueError):
            continue

    times = sorted(set(times))
    emit("keyframes", input=str(src), count=len(times), timestamps=times)
    emit("complete", output=str(src), size_bytes=0, count=len(times))
    return 0


def op_vmaf(args: argparse.Namespace) -> int:
    """VMAF quality comparison: distorted vs. reference. Runs ffmpeg `libvmaf`
    with JSON log output, parses the file, emits per-frame `vmaf` events plus a
    final `complete` event carrying mean / harmonic-mean / min scores."""
    import math
    import tempfile

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")

    ref = Path(args.reference)
    dist = Path(args.distorted)
    if not ref.is_file():
        return fail("missing_input", f"Reference not found: {args.reference}")
    if not dist.is_file():
        return fail("missing_input", f"Distorted not found: {args.distorted}")

    with tempfile.NamedTemporaryFile(prefix="ucx_vmaf_", suffix=".json",
                                     delete=False, mode="w") as tmp:
        log_path = tmp.name

    # libvmaf options: log_path uses Windows-friendly forward slashes; embedded
    # colons in log_fmt require escaping per ffmpeg filter quoting rules.
    safe_log = log_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        ffmpeg, "-y",
        "-i", str(dist),
        "-i", str(ref),
        "-lavfi", f"libvmaf=log_path='{safe_log}':log_fmt=json",
        "-f", "null", "-",
    ]
    emit("log", level="info",
         message=f"VMAF: distorted={dist.name} ref={ref.name}")
    emit("progress", percent=0, stage="vmaf", eta_seconds=None)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    # ffmpeg writes progress to stderr for libvmaf runs (no -progress here so we
    # just count frames -- best-effort, no ETA).
    if proc.stderr is not None:
        for line in proc.stderr:
            line = line.rstrip()
            if line.startswith("frame="):
                # Cheap progress: we don't know total frame count up front
                # without an extra probe pass, so just parrot the frame counter.
                emit("log", level="debug", message=line)
    rc = proc.wait()
    if rc != 0:
        try: os.unlink(log_path)
        except OSError: pass
        return fail("ffmpeg_failed", f"FFmpeg/libvmaf exited with code {rc}")

    try:
        with open(log_path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as ex:
        try: os.unlink(log_path)
        except OSError: pass
        return fail("vmaf_parse_failed", f"Could not read VMAF report: {ex}")
    finally:
        try: os.unlink(log_path)
        except OSError: pass

    frames = doc.get("frames", [])
    pooled = doc.get("pooled_metrics", {}).get("vmaf", {})
    scores: list[float] = []
    total = max(1, len(frames))
    sample_every = max(1, total // 200)  # cap to ~200 vmaf events for huge clips
    for i, frame in enumerate(frames):
        s = frame.get("metrics", {}).get("vmaf")
        if s is None:
            continue
        scores.append(float(s))
        if i % sample_every == 0:
            emit("vmaf", frame=i, score=round(float(s), 3))
            emit("progress",
                 percent=round(i / total * 100, 1),
                 stage="vmaf",
                 eta_seconds=None)

    if not scores:
        return fail("vmaf_no_scores", "VMAF report contained no frame scores.")

    mean = sum(scores) / len(scores)
    minv = min(scores)
    maxv = max(scores)
    # Harmonic mean is the metric Netflix recommends for pooled VMAF, since it
    # penalizes worst-frame outliers more than arithmetic mean does.
    eps = 1e-9
    harmonic = len(scores) / sum(1.0 / max(s, eps) for s in scores)
    pct_below_70 = 100.0 * sum(1 for s in scores if s < 70) / len(scores)
    summary = {
        "frames":            len(scores),
        "mean":              round(mean, 3),
        "harmonic_mean":     round(harmonic, 3),
        "min":               round(minv, 3),
        "max":               round(maxv, 3),
        "pooled_mean":       round(float(pooled.get("mean", mean)), 3) if pooled else None,
        "pooled_harmonic":   round(float(pooled.get("harmonic_mean", harmonic)), 3) if pooled else None,
        "below_70_percent":  round(pct_below_70, 2),
    }
    emit("vmaf_summary", **summary)
    emit("progress", percent=100, stage="vmaf", eta_seconds=0)
    emit("complete", output="", size_bytes=0, summary=summary)
    return 0


def op_rewrap(args: argparse.Namespace) -> int:
    """Stream-copy into a new container — no re-encode, instant remux."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    in_ext = in_path.suffix.lower()
    out_ext = out_path.suffix.lower()
    emit("log", level="info", message=f"Rewrap {in_ext} -> {out_ext} (stream copy)")

    cmd = [ffmpeg, "-y", "-i", str(in_path),
           "-c", "copy",
           "-map_metadata", "0"]
    if out_ext in (".mp4", ".m4v", ".mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out_path))

    emit("progress", percent=0, stage="rewrap", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "rewrap")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_concat(args: argparse.Namespace) -> int:
    """Stream-copy concatenate via ffmpeg's concat demuxer when codecs match;
    fall back to filter_complex concat for mixed sources."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Input(s) not found: {missing}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Probe codecs to decide stream-copy vs re-encode.
    codecs = []
    total_dur = 0.0
    for p in inputs:
        info = probe(ffprobe, str(p))
        if info:
            v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
            codecs.append(v.get("codec_name", ""))
            total_dur += float(info.get("format", {}).get("duration", 0))
    can_copy = len(set(codecs)) == 1 and not args.reencode

    if can_copy:
        # Concat demuxer: needs a list file with one "file 'path'" per line.
        list_path = Path(out_path.parent / f".concat_{os.getpid()}.txt")
        list_path.write_text(
            "\n".join(f"file '{str(p).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
                      for p in inputs),
            encoding="utf-8")
        try:
            cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0",
                   "-i", str(list_path), "-c", "copy", str(out_path)]
            emit("log", level="info", message=f"Concat (stream copy) of {len(inputs)} clip(s)")
            emit("progress", percent=0, stage="concat", eta_seconds=None)
            rc = run_ffmpeg(cmd, total_dur, "concat")
        finally:
            try: list_path.unlink()
            except OSError: pass
    else:
        # filter_complex concat -- normalises to one resolution / codec.
        emit("log", level="info", message=f"Concat (re-encode) of {len(inputs)} clip(s)")
        cmd = [ffmpeg, "-y"]
        for p in inputs: cmd += ["-i", str(p)]
        n = len(inputs)
        filter_str = "".join(f"[{i}:v:0][{i}:a:0?]" for i in range(n)) \
                   + f"concat=n={n}:v=1:a=1[v][a]"
        cmd += ["-filter_complex", filter_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k", str(out_path)]
        emit("progress", percent=0, stage="concat", eta_seconds=None)
        rc = run_ffmpeg(cmd, total_dur, "concat")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         input_count=len(inputs))
    return 0


def op_speed(args: argparse.Namespace) -> int:
    """Speed-up / slow-down a clip via setpts (video) + atempo (audio)."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))
    factor = float(args.factor)
    if factor <= 0: return fail("bad_factor", "--factor must be > 0")

    # Video: setpts=PTS/factor (factor>1 = speed up, <1 = slow down).
    # Audio: atempo accepts 0.5-100; chain multiple stages for extreme factors.
    def _atempo_chain(f: float) -> str:
        chain = []
        while f > 100:
            chain.append("atempo=100"); f /= 100
        while f < 0.5:
            chain.append("atempo=0.5"); f /= 0.5
        chain.append(f"atempo={f}")
        return ",".join(chain)

    streams = info.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not has_video and not has_audio:
        return fail("no_streams", "Input has no video or audio streams.")

    if has_video and has_audio:
        fc = f"[0:v]setpts=PTS/{factor}[v];[0:a]{_atempo_chain(factor)}[a]"
        maps = ["-map", "[v]", "-map", "[a]"]
        codecs = ["-c:v", "libx264", "-crf", "20", "-preset", "medium",
                  "-c:a", "aac", "-b:a", "192k"]
    elif has_video:
        fc = f"[0:v]setpts=PTS/{factor}[v]"
        maps = ["-map", "[v]"]
        codecs = ["-c:v", "libx264", "-crf", "20", "-preset", "medium"]
    else:
        fc = f"[0:a]{_atempo_chain(factor)}[a]"
        maps = ["-map", "[a]"]
        codecs = ["-c:a", "aac", "-b:a", "192k"]

    cmd = [ffmpeg, "-y", "-i", str(src),
           "-filter_complex", fc, *maps, *codecs, str(out_path)]
    emit("progress", percent=0, stage=f"speed x{factor}", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration / factor, f"speed x{factor}")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_reverse(args: argparse.Namespace) -> int:
    """Reverse video and (optionally) audio."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    streams = info.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    cmd = [ffmpeg, "-y", "-i", str(src)]
    if has_video:
        cmd += ["-vf", "reverse", "-c:v", "libx264", "-crf", "20", "-preset", "medium"]
    if has_audio:
        cmd += ["-af", "areverse" if args.reverse_audio else "anull",
                "-c:a", "aac", "-b:a", "192k"]
    elif not has_video:
        return fail("no_streams", "Input has no video or audio streams.")
    cmd.append(str(out_path))
    emit("progress", percent=0, stage="reverse", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "reverse")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_lut(args: argparse.Namespace) -> int:
    """Apply a 3D LUT (.cube) to a video via ffmpeg's lut3d filter."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input); lut = Path(args.lut)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    if not lut.is_file(): return fail("missing_lut", f"LUT file not found: {args.lut}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    safe_lut = str(lut).replace("\\", "/").replace(":", "\\:")
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", f"lut3d='{safe_lut}'",
           "-c:v", "libx264", "-crf", "20", "-preset", "medium",
           "-c:a", "copy", str(out_path)]
    emit("progress", percent=0, stage="lut3d", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "lut3d")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


_TONEMAP_OPERATORS = {"hable", "reinhard", "mobius", "clip", "linear", "gamma"}


def op_hdr_to_sdr(args: argparse.Namespace) -> int:
    """Tone-map HDR (BT.2020 / HLG / PQ) to SDR (BT.709) via FFmpeg's
    `zscale` -> `tonemap` -> `zscale` filter chain. The tonemap operator is
    user-selectable (Item 17): hable / reinhard / mobius are the three most
    commonly recommended for SDR delivery; clip / linear / gamma are kept as
    debug-style escape hatches."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    operator = (getattr(args, "operator", None) or "hable").lower()
    if operator not in _TONEMAP_OPERATORS:
        return fail("invalid_args",
                    f"Unknown tonemap operator: {operator}. "
                    f"Use one of {sorted(_TONEMAP_OPERATORS)}.")
    desat = max(0.0, min(1.0, getattr(args, "desat", 0.0) or 0.0))
    peak = getattr(args, "peak_nits", None) or 100
    crf = getattr(args, "crf", None) or 20

    # zscale path is the most portable across ffmpeg builds. tonemap accepts
    # an optional desat=… arg to control colour-saturation falloff in highlights.
    vf = (f"zscale=t=linear:npl={peak},format=gbrpf32le,"
          f"zscale=p=bt709,tonemap=tonemap={operator}:desat={desat},"
          f"zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", vf,
           "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
           "-c:a", "copy", str(out_path)]
    emit("log", level="info",
         message=f"hdr->sdr operator={operator} desat={desat} peak={peak} crf={crf}")
    emit("progress", percent=0, stage="hdr->sdr", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "hdr->sdr")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc} (zscale not built? Try a "
                                              "newer ffmpeg with --enable-libzimg).")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Intro/outro editor (Item 36) ────────────────────────────────────────────

def op_intro_outro(args: argparse.Namespace) -> int:
    """Prepend an intro and/or append an outro to the primary --input video.
    Thin wrapper over op_concat: builds the [intro?, primary, outro?] list,
    delegates to the existing concat machinery (stream-copy when codecs match,
    filter_complex when not), and produces a single output. Keeps the
    intro/outro UX clean for callers who don't want to think about `nargs="+"`."""
    primary = Path(args.input)
    if not primary.is_file():
        return fail("missing_input", f"Primary input not found: {args.input}")
    pieces: list[Path] = []
    if args.intro:
        ip = Path(args.intro)
        if not ip.is_file():
            return fail("missing_intro", f"Intro file not found: {args.intro}")
        pieces.append(ip)
    pieces.append(primary)
    if args.outro:
        op = Path(args.outro)
        if not op.is_file():
            return fail("missing_outro", f"Outro file not found: {args.outro}")
        pieces.append(op)

    if len(pieces) == 1:
        return fail("nothing_to_concat",
                    "intro-outro requires at least one --intro or --outro file.")

    # Synthesise the args namespace op_concat expects.
    concat_args = argparse.Namespace(
        input=[str(p) for p in pieces],
        output=args.output,
        reencode=bool(args.reencode))
    return op_concat(concat_args)


# ─── 360° / VR projection (Item 38) ──────────────────────────────────────────

_V360_INPUT_PROJECTIONS = {"e", "equirect", "c3x2", "c6x1", "c1x6", "fisheye", "flat", "dfisheye", "barrel", "cube"}
_V360_OUTPUT_PROJECTIONS = {"e", "equirect", "c3x2", "c6x1", "c1x6", "fisheye", "flat", "dfisheye", "barrel", "cube"}


def op_v360(args: argparse.Namespace) -> int:
    """Convert between 360° / VR projections via FFmpeg's `v360` filter.
    Common moves: equirectangular -> rectilinear (flat) viewport, equirect
    -> 6x1 cubemap for game-engine import, fisheye -> equirect, etc."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    src_proj = (args.input_projection or "equirect").lower()
    dst_proj = (args.output_projection or "flat").lower()
    if src_proj not in _V360_INPUT_PROJECTIONS:
        return fail("invalid_args",
                    f"Unknown --input-projection: {src_proj}. "
                    f"Known: {sorted(_V360_INPUT_PROJECTIONS)}.")
    if dst_proj not in _V360_OUTPUT_PROJECTIONS:
        return fail("invalid_args",
                    f"Unknown --output-projection: {dst_proj}. "
                    f"Known: {sorted(_V360_OUTPUT_PROJECTIONS)}.")

    parts = [f"v360={src_proj}:{dst_proj}",
             f"yaw={args.yaw}", f"pitch={args.pitch}", f"roll={args.roll}"]
    if args.h_fov: parts.append(f"h_fov={args.h_fov}")
    if args.v_fov: parts.append(f"v_fov={args.v_fov}")
    if args.width and args.height:
        parts.append(f"w={args.width}")
        parts.append(f"h={args.height}")
    vf = ":".join(parts)

    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", vf,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
    emit("log", level="info", message=f"v360 {src_proj} -> {dst_proj}")
    emit("progress", percent=0, stage="v360", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "v360")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during v360 conversion.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Lens correction (Item 24) ───────────────────────────────────────────────

def op_lens_correct(args: argparse.Namespace) -> int:
    """Apply FFmpeg's `lenscorrection` filter for barrel / pincushion
    distortion correction. Useful for action cam / wide-angle footage where
    a vendor lens-distortion model is unavailable. K1 < 0 = pincushion
    correction; K1 > 0 = barrel correction. Cx/Cy default to centre."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    cx = max(0.0, min(1.0, args.cx))
    cy = max(0.0, min(1.0, args.cy))
    vf = f"lenscorrection=cx={cx}:cy={cy}:k1={args.k1}:k2={args.k2}"
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", vf,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
    emit("log", level="info", message=f"lenscorrection k1={args.k1} k2={args.k2}")
    emit("progress", percent=0, stage="lens-correct", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "lens-correct")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during lens correction.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Watermark overlay (Item 31) ─────────────────────────────────────────────

# 9-point grid -> FFmpeg overlay x/y expressions. Anchors derived from main
# video dimensions (W,H) and overlay dimensions (w,h).
_WATERMARK_POSITIONS = {
    "tl": ("(M)", "(M)"),
    "tc": ("(W-w)/2", "(M)"),
    "tr": ("W-w-(M)", "(M)"),
    "ml": ("(M)", "(H-h)/2"),
    "mc": ("(W-w)/2", "(H-h)/2"),
    "mr": ("W-w-(M)", "(H-h)/2"),
    "bl": ("(M)", "H-h-(M)"),
    "bc": ("(W-w)/2", "H-h-(M)"),
    "br": ("W-w-(M)", "H-h-(M)"),
}


def op_watermark(args: argparse.Namespace) -> int:
    """Stamp a PNG/JPEG logo onto the video via FFmpeg's `overlay` filter.
    9-point position grid + opacity (0..1) + scale (% of frame width).
    The overlay is alpha-pre-multiplied via the `format=rgba,colorchannelmixer`
    chain so users can dial opacity without baking it into the source PNG."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    overlay = Path(args.overlay)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    if not overlay.is_file():
        return fail("missing_overlay", f"Overlay image not found: {args.overlay}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    pos = (args.position or "br").lower()
    coords = _WATERMARK_POSITIONS.get(pos)
    if coords is None:
        return fail("invalid_args", f"Unknown position: {pos}. "
                                     f"Use one of {sorted(_WATERMARK_POSITIONS)}.")
    margin = max(0, args.margin)
    x_expr = coords[0].replace("(M)", str(margin))
    y_expr = coords[1].replace("(M)", str(margin))

    opacity = max(0.0, min(1.0, args.opacity))
    scale_pct = max(1.0, min(100.0, args.scale))
    # scale2ref pegs the overlay width to the main video width % so the stamp
    # stays proportional regardless of source resolution.
    fc = (
        f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wm0];"
        f"[wm0][0:v]scale2ref=w=main_w*{scale_pct/100.0}:h=ow/iw*ih[wm][bg];"
        f"[bg][wm]overlay={x_expr}:{y_expr}"
    )
    cmd = [ffmpeg, "-y", "-i", str(src), "-i", str(overlay),
           "-filter_complex", fc,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
    emit("log", level="info",
         message=f"watermark {overlay.name} pos={pos} opacity={opacity} scale={scale_pct}%")
    emit("progress", percent=0, stage="watermark", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "watermark")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during watermark overlay.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Subtitle burn-in (Item 14) ──────────────────────────────────────────────

# 9-point grid -> ASS \an alignment (libass numbering: 1=BL, 2=BC, 3=BR,
# 4=ML, 5=MC, 6=MR, 7=TL, 8=TC, 9=TR).
_BURN_POSITION_TO_AN = {
    "tl": 7, "tc": 8, "tr": 9,
    "ml": 4, "mc": 5, "mr": 6,
    "bl": 1, "bc": 2, "br": 3,
}


def _ffmpeg_subfile_arg(path: Path) -> str:
    """Escape a Windows path so FFmpeg's `subtitles=` filter parses it."""
    s = str(path).replace("\\", "/")
    s = s.replace("'", "\\'")
    s = s.replace(":", "\\:")
    s = s.replace("[", "\\[").replace("]", "\\]")
    s = s.replace(";", "\\;")
    return s


import re as _re
_SAFE_FONT_RE = _re.compile(r"^[A-Za-z0-9 \-_.']+$")
_SAFE_HEX_RE = _re.compile(r"^[0-9A-Fa-f]{6,8}$")


def op_subtitle_burn(args: argparse.Namespace) -> int:
    """Burn an external subtitle file (.srt / .ass / .ssa / .vtt) into the
    video using FFmpeg's `subtitles=` filter. Honours user font / size /
    colour / outline / position controls via libass `force_style` overrides."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    sub = Path(args.subtitles)
    if not sub.is_file():
        return fail("missing_subtitles", f"Subtitle file not found: {args.subtitles}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    pos = (args.position or "bc").lower()
    alignment = _BURN_POSITION_TO_AN.get(pos)
    if alignment is None:
        return fail("invalid_args", f"Unknown position: {pos}. "
                                     f"Use one of {sorted(_BURN_POSITION_TO_AN)}.")

    font = args.font
    if not _SAFE_FONT_RE.match(font):
        font = _re.sub(r"[^A-Za-z0-9 \-_.]", "", font) or "Arial"
    for color_name in ("color", "outline_color", "shadow_color"):
        val = getattr(args, color_name, "")
        if val and not _SAFE_HEX_RE.match(val):
            return fail("invalid_args", f"--{color_name.replace('_', '-')} must be a hex color (e.g. FFFFFF)")

    style_pairs = [
        f"FontName={font}",
        f"FontSize={args.size}",
        f"PrimaryColour=&H{args.color}",
        f"OutlineColour=&H{args.outline_color}",
        f"BackColour=&H{args.shadow_color}",
        f"BorderStyle={args.border_style}",
        f"Outline={args.outline}",
        f"Shadow={args.shadow}",
        f"MarginV={args.margin_v}",
        f"Alignment={alignment}",
    ]
    if args.bold:   style_pairs.append("Bold=-1")
    if args.italic: style_pairs.append("Italic=-1")
    style = ",".join(style_pairs)

    sub_arg = _ffmpeg_subfile_arg(sub)
    vf = f"subtitles='{sub_arg}':force_style='{style}'"
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", vf,
           "-c:v", "libx264", "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy",
           "-movflags", "+faststart", str(out_path)]
    emit("log", level="info", message=f"burn subtitles {sub.name} -> {out_path.name}")
    emit("progress", percent=0, stage="burn-in", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "burn-in")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during subtitle burn-in.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Auto-crop (Item 23) ─────────────────────────────────────────────────────

_CROPDETECT_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def _detect_crop(ffmpeg: str, src: Path, sample_seconds: float, threshold: int) -> str | None:
    """Run a short cropdetect pass over the first <sample_seconds> seconds
    and return the most-frequently observed `crop=W:H:X:Y` rectangle. Returns
    None when no rectangle could be detected."""
    cmd = [ffmpeg, "-y",
           "-t", f"{max(1.0, sample_seconds):.1f}",
           "-i", str(src),
           "-vf", f"cropdetect={threshold}:16:0",
           "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    counts: dict[str, int] = {}
    for ln in (proc.stderr or "").splitlines():
        m = _CROPDETECT_RE.search(ln)
        if not m:
            continue
        key = m.group(0)  # "crop=W:H:X:Y"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.__getitem__)


def op_auto_crop(args: argparse.Namespace) -> int:
    """Detect black borders via FFmpeg's cropdetect filter and apply the
    detected rectangle. Useful for letterboxed / pillarboxed content
    captured from broadcast or DVD."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    emit("progress", percent=0, stage="cropdetect", eta_seconds=None)
    sample = min(args.sample_seconds, max(1.0, duration))
    crop = _detect_crop(ffmpeg, src, sample, args.threshold)
    if crop is None:
        return fail("crop_undetected",
                    "cropdetect did not return a stable rectangle. "
                    "Try --threshold higher (e.g. 36) or a longer --sample-seconds.")
    emit("log", level="info", message=f"detected {crop}")

    if args.detect_only:
        # Probe-only mode — print the detected rectangle and exit successfully
        # without producing an output file.
        m = _CROPDETECT_RE.search(crop)
        if m:
            emit("complete", output=None,
                 detected={"width": int(m.group(1)), "height": int(m.group(2)),
                           "x": int(m.group(3)), "y": int(m.group(4))})
        return 0

    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", crop,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
    emit("progress", percent=0, stage="auto-crop", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "auto-crop")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during auto-crop.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Video stabilization (Item 19) ───────────────────────────────────────────

def op_stabilize(args: argparse.Namespace) -> int:
    """Two-pass video stabilization via FFmpeg's vidstab filters.

    Pass 1 runs `vidstabdetect` writing motion vectors to a temp `.trf` file.
    Pass 2 runs `vidstabtransform` consuming that file and crops or fills
    the borders introduced by the warp."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    border = (args.border or "keep").lower()
    if border not in ("keep", "black", "crop"):
        return fail("invalid_args",
                    f"Unknown --border: {border}. Use keep, black, or crop.")
    shakiness = max(1, min(10, args.shakiness))
    smoothing = max(1, min(60, args.smoothing))

    transforms = out_path.parent / f"{src.stem}_{os.getpid()}.trf"
    try:
        # Pass 1: detect.
        detect_filter = f"vidstabdetect=shakiness={shakiness}:result={_ffmpeg_subfile_arg(transforms)}"
        cmd1 = [ffmpeg, "-y", "-i", str(src),
                "-vf", detect_filter,
                "-f", "null", "-"]
        emit("log", level="info",
             message=f"stabilize pass1 shakiness={shakiness} -> {transforms.name}")
        emit("progress", percent=0, stage="stabilize-detect", eta_seconds=None)
        rc = run_ffmpeg(cmd1, duration, "stabilize-detect")
        if rc != 0:
            return fail("vidstab_missing",
                        f"FFmpeg exited {rc}. The vidstab filter requires a "
                        "build with --enable-libvidstab. BtbN's "
                        "ffmpeg-master-latest-win64-gpl includes it.")

        # Pass 2: transform.
        if border == "crop":
            transform_filter = (
                f"vidstabtransform=smoothing={smoothing}:input={_ffmpeg_subfile_arg(transforms)}"
                f":crop=keep,unsharp=5:5:0.8:3:3:0.4")
        else:
            crop_arg = "black" if border == "black" else "keep"
            transform_filter = (
                f"vidstabtransform=smoothing={smoothing}:input={_ffmpeg_subfile_arg(transforms)}"
                f":crop={crop_arg},unsharp=5:5:0.8:3:3:0.4")
        cmd2 = [ffmpeg, "-y", "-i", str(src),
                "-vf", transform_filter,
                "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
                "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
        emit("log", level="info",
             message=f"stabilize pass2 smoothing={smoothing} border={border}")
        emit("progress", percent=0, stage="stabilize-transform", eta_seconds=None)
        rc = run_ffmpeg(cmd2, duration, "stabilize-transform")
        if rc != 0:
            return fail("ffmpeg_failed",
                        f"FFmpeg exited {rc} during vidstabtransform pass.")
        if not out_path.is_file():
            return fail("output_missing", f"Output not produced: {out_path}")
        emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
        return 0
    finally:
        try: transforms.unlink(missing_ok=True)
        except OSError: pass


def _expand_face_box(
    box: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
    padding_percent: int,
) -> tuple[int, int, int, int]:
    x, y, width, height = (int(value) for value in box)
    padding_x = round(width * padding_percent / 100)
    padding_y = round(height * padding_percent / 100)
    left = max(0, x - padding_x)
    top = max(0, y - padding_y)
    right = min(frame_width, x + width + padding_x)
    bottom = min(frame_height, y + height + padding_y)
    return left, top, max(0, right - left), max(0, bottom - top)


def _blur_face_regions(frame, boxes, strength: int, padding_percent: int):
    """Blur every detected region in-place and return expanded coordinates."""
    import cv2  # type: ignore

    expanded = []
    frame_height, frame_width = frame.shape[:2]
    for raw_box in boxes:
        left, top, width, height = _expand_face_box(
            tuple(raw_box), frame_width, frame_height, padding_percent)
        if width < 2 or height < 2:
            continue
        region = frame[top:top + height, left:left + width]
        kernel = max(3, round(min(width, height) * strength / 100))
        if kernel % 2 == 0:
            kernel += 1
        kernel = min(kernel, 99)
        blurred = cv2.GaussianBlur(region, (kernel, kernel), sigmaX=0)
        # A low-resolution round trip prevents residual identity detail even
        # when the detected face is large relative to the blur kernel.
        block = max(2, round(2 + strength / 8))
        small = cv2.resize(
            blurred,
            (max(1, width // block), max(1, height // block)),
            interpolation=cv2.INTER_AREA,
        )
        frame[top:top + height, left:left + width] = cv2.resize(
            small, (width, height), interpolation=cv2.INTER_NEAREST)
        expanded.append((left, top, width, height))
    return expanded


def _load_face_detector():
    import cv2  # type: ignore

    if not hasattr(cv2, "CascadeClassifier"):
        raise RuntimeError(
            "OpenCV native bindings are unavailable "
            f"(module={getattr(cv2, '__file__', None)!r}, "
            f"version={getattr(cv2, '__version__', None)!r}).")
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        raise RuntimeError(f"Could not load OpenCV face cascade: {cascade_path}")
    return detector


def op_face_blur(args: argparse.Namespace, detector_override=None) -> int:
    """Detect and irreversibly obscure frontal faces in every video frame."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    try:
        import cv2  # type: ignore
    except ImportError:
        return fail(
            "missing_opencv",
            "Face blur requires the managed opencv-python-headless dependency. "
            "Rebuild or reinstall the ClipForge sidecar.",
        )

    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input file does not exist: {source}")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not 1 <= args.strength <= 100:
        return fail("invalid_strength", "--strength must be between 1 and 100.")
    if not 0 <= args.padding <= 100:
        return fail("invalid_padding", "--padding must be between 0 and 100.")
    if not 1.01 <= args.scale_factor <= 2.0:
        return fail("invalid_scale_factor", "--scale-factor must be between 1.01 and 2.0.")
    if not 1 <= args.min_neighbors <= 20 or not 8 <= args.min_face <= 4096:
        return fail("invalid_detector_settings", "Face detector settings are out of range.")

    info = probe(ffprobe, str(source))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0) or 0)

    try:
        detector = detector_override or _load_face_detector()
    except Exception as exc:
        return fail("detector_unavailable", str(exc))

    import tempfile
    descriptor, temporary_name = tempfile.mkstemp(prefix="ucx-face-blur-", suffix=".avi")
    os.close(descriptor)
    temporary_video = Path(temporary_name)
    staged_output: Path | None = None
    try:
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            return fail("decode_failed", f"OpenCV could not decode {source.name}.")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or width <= 0 or height <= 0:
            capture.release()
            return fail("decode_failed", "Video dimensions or frame rate are unavailable.")

        writer = cv2.VideoWriter(
            str(temporary_video),
            cv2.VideoWriter_fourcc(*"MJPG"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            capture.release()
            return fail("temporary_encoder_failed", "Could not open the private frame encoder.")

        frame_index = 0
        faces_detected = 0
        frames_with_faces = 0
        emit("progress", percent=0, stage="detecting faces", eta_seconds=None)
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                grayscale = cv2.equalizeHist(grayscale)
                boxes = detector.detectMultiScale(
                    grayscale,
                    scaleFactor=args.scale_factor,
                    minNeighbors=args.min_neighbors,
                    minSize=(args.min_face, args.min_face),
                )
                blurred = _blur_face_regions(frame, boxes, args.strength, args.padding)
                if blurred:
                    faces_detected += len(blurred)
                    frames_with_faces += 1
                writer.write(frame)
                frame_index += 1
                if total_frames > 0 and (frame_index == 1 or frame_index % 5 == 0):
                    emit(
                        "progress",
                        percent=round(min(100.0, frame_index / total_frames * 100), 1),
                        stage="detecting faces",
                        eta_seconds=None,
                    )
        finally:
            capture.release()
            writer.release()

        if frame_index == 0:
            return fail("decode_failed", "No video frames could be decoded.")
        if faces_detected == 0:
            return fail(
                "no_faces_detected",
                "No frontal faces were detected, so no privacy-labelled output was written.",
            )

        emit(
            "log",
            level="info",
            message=(
                f"Blurred {faces_detected} face region(s) across "
                f"{frames_with_faces}/{frame_index} frames."
            ),
        )
        staged_output = output.with_name(
            f".{output.stem}-{os.getpid()}-{time.time_ns()}.tmp{output.suffix}")
        command = [
            ffmpeg, "-y",
            "-i", str(temporary_video),
            "-i", str(source),
            "-map", "0:v:0", "-map", "1:a?",
            "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
            "-c:a", "aac", "-b:a", "192k",
            "-map_metadata", "1",
            "-movflags", "+faststart",
            str(staged_output),
        ]
        rc = run_ffmpeg(command, duration, "encoding privacy filter")
        if rc != 0:
            return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}.")
        if not staged_output.is_file() or staged_output.stat().st_size == 0:
            return fail("output_missing", f"Output not produced: {staged_output}")
        os.replace(staged_output, output)
        emit(
            "complete",
            output=str(output),
            size_bytes=output.stat().st_size,
            frames=frame_index,
            faces_detected=faces_detected,
            frames_with_faces=frames_with_faces,
        )
        return 0
    finally:
        try: temporary_video.unlink(missing_ok=True)
        except OSError: pass
        if staged_output is not None:
            try: staged_output.unlink(missing_ok=True)
            except OSError: pass


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clipforge-sidecar",
                                description="UCX ClipForge sidecar — video editor operations with NDJSON progress.")
    sub = p.add_subparsers(dest="op", required=True)

    # ── trim ──────────────────────────────────────────────────────────────────
    trim = sub.add_parser("trim", help="Trim a video clip")
    trim.add_argument("--input", required=True)
    trim.add_argument("--output", required=True)
    trim.add_argument("--start", type=float, default=0.0, help="Start time (seconds)")
    trim.add_argument("--end", type=float, help="End time (seconds); omit or 0 for end of clip")
    trim.add_argument("--lossless", action="store_true",
                      help="Stream-copy mode (fast, keyframe-bounded). Skips re-encode.")
    trim.add_argument("--codec", default="libx264", help="Video codec when re-encoding")
    trim.add_argument("--crf", type=int, default=18, help="CRF when re-encoding")
    trim.add_argument("--preset", default="medium", help="FFmpeg encoder preset")
    trim.add_argument("--audio-codec", default="aac")
    trim.add_argument("--audio-bitrate", type=int, default=192)

    # ── crop ──────────────────────────────────────────────────────────────────
    crop = sub.add_parser("crop", help="Crop video to a rectangle")
    crop.add_argument("--input", required=True)
    crop.add_argument("--output", required=True)
    crop.add_argument("--width", type=int, required=True, help="Output width in pixels")
    crop.add_argument("--height", type=int, required=True, help="Output height in pixels")
    crop.add_argument("--x", type=int, default=0, help="Left edge of crop (pixels from left)")
    crop.add_argument("--y", type=int, default=0, help="Top edge of crop (pixels from top)")
    crop.add_argument("--codec", default="libx264")
    crop.add_argument("--crf", type=int, default=18)
    crop.add_argument("--preset", default="medium")

    crop_meta = sub.add_parser(
        "crop-meta",
        help="Set H.264/H.265 display-crop metadata without re-encoding")
    crop_meta.add_argument("--input", required=True)
    crop_meta.add_argument("--output", required=True)
    crop_meta.add_argument("--left", type=int, default=0)
    crop_meta.add_argument("--right", type=int, default=0)
    crop_meta.add_argument("--top", type=int, default=0)
    crop_meta.add_argument("--bottom", type=int, default=0)

    aspect_override = sub.add_parser(
        "aspect-override",
        help="Override display aspect ratio with packet stream-copy")
    aspect_override.add_argument("--input", required=True)
    aspect_override.add_argument("--output", required=True)
    aspect_override.add_argument(
        "--aspect", required=True,
        help="Display aspect ratio, for example 16:9 or 4/3")

    # ── rotate ────────────────────────────────────────────────────────────────
    rotate = sub.add_parser("rotate", help="Rotate or flip video")
    rotate.add_argument("--input", required=True)
    rotate.add_argument("--output", required=True)
    rotate.add_argument("--angle", required=True,
                        choices=list(_ROTATE_FILTERS.keys()),
                        help="90 | 180 | 270 | flip_h | flip_v")
    rotate.add_argument("--codec", default="libx264")
    rotate.add_argument("--crf", type=int, default=18)
    rotate.add_argument("--preset", default="medium")

    # ── loudnorm ──────────────────────────────────────────────────────────────
    loudnorm = sub.add_parser("loudnorm", help="EBU R128 loudness normalisation")
    loudnorm.add_argument("--input", required=True)
    loudnorm.add_argument("--output", required=True)
    loudnorm.add_argument("--integrated-lufs", type=float, default=-14.0,
                          dest="integrated_lufs",
                          help="Target integrated loudness in LUFS (default: -14)")
    loudnorm.add_argument("--true-peak", type=float, default=-1.5, dest="true_peak",
                          help="Max true peak in dBTP (default: -1.5)")
    loudnorm.add_argument("--lra", type=float, default=11.0,
                          help="Loudness range target in LU (default: 11)")
    loudnorm.add_argument("--audio-codec", default="aac", dest="audio_codec")
    loudnorm.add_argument("--audio-bitrate", type=int, default=192, dest="audio_bitrate")

    # ── rewrap ────────────────────────────────────────────────────────────────
    rewrap = sub.add_parser("rewrap", help="Remux into a different container without re-encoding")
    rewrap.add_argument("--input", required=True)
    rewrap.add_argument("--output", required=True)

    # ── tracks ────────────────────────────────────────────────────────────────
    track_list = sub.add_parser("track-list",
                                help="Enumerate every stream in a container")
    track_list.add_argument("--input", required=True)

    track_remove = sub.add_parser("track-remove",
                                  help="Remove specific streams without re-encoding")
    track_remove.add_argument("--input", required=True)
    track_remove.add_argument("--output", required=True)
    track_remove.add_argument("--remove", required=True,
                              help="Comma-separated list of stream indices to drop, e.g. '1,3'")

    track_add = sub.add_parser("track-add",
                               help="Add an external audio/subtitle file as a new track")
    track_add.add_argument("--input", required=True)
    track_add.add_argument("--extra", required=True,
                           help="Audio (.mp3/.aac/.flac/...) or subtitle (.srt/.ass) file to attach")
    track_add.add_argument("--output", required=True)
    track_add.add_argument("--language",
                           help="Optional ISO-639 language code for the new track (e.g. 'eng', 'jpn')")
    track_add.add_argument("--title",
                           help="Optional title metadata for the new track")

    track_extract = sub.add_parser(
        "track-extract",
        help="Export a single subtitle stream from the container to a standalone file")
    track_extract.add_argument("--input", required=True)
    track_extract.add_argument("--stream", required=True,
                               help="Container-level stream index (as reported by track-list)")
    track_extract.add_argument("--output", required=True,
                               help="Output path; extension drives the target format "
                                    "(.srt / .vtt / .ass / .ssa / .lrc / .sup)")

    # ── concat ────────────────────────────────────────────────────────────────
    concat = sub.add_parser("concat", help="Concatenate clips (stream-copy when codecs match, re-encode otherwise)")
    concat.add_argument("--input", nargs="+", required=True)
    concat.add_argument("--output", required=True)
    concat.add_argument("--reencode", action="store_true",
                        help="Force re-encode via filter_complex concat.")

    # ── speed ─────────────────────────────────────────────────────────────────
    speed = sub.add_parser("speed", help="Speed up / slow down (factor > 1 speeds up; < 1 slows)")
    speed.add_argument("--input", required=True)
    speed.add_argument("--output", required=True)
    speed.add_argument("--factor", required=True, help="0.25 = quarter speed, 2 = double speed")

    # ── reverse ───────────────────────────────────────────────────────────────
    reverse = sub.add_parser("reverse", help="Play video backwards")
    reverse.add_argument("--input", required=True)
    reverse.add_argument("--output", required=True)
    reverse.add_argument("--reverse-audio", action="store_true", dest="reverse_audio",
                         help="Also reverse the audio (default keeps audio forward).")

    # ── lut3d ─────────────────────────────────────────────────────────────────
    lut = sub.add_parser("lut3d", help="Apply a 3D LUT (.cube) for colour grading")
    lut.add_argument("--input", required=True)
    lut.add_argument("--output", required=True)
    lut.add_argument("--lut", required=True, help="Path to a .cube LUT file")

    # ── hdr-to-sdr ────────────────────────────────────────────────────────────
    h2s = sub.add_parser("hdr-to-sdr", help="Tone-map HDR (BT.2020/HLG/PQ) -> SDR (BT.709)")
    h2s.add_argument("--input", required=True)
    h2s.add_argument("--output", required=True)
    h2s.add_argument("--operator", default="hable",
                     help="Tonemap operator: hable, reinhard, mobius, clip, linear, gamma. "
                          "Default 'hable' is the safest default for general SDR delivery.")
    h2s.add_argument("--desat", type=float, default=0.0,
                     help="Highlight desaturation 0.0..1.0 (default 0).")
    h2s.add_argument("--peak-nits", type=int, default=100, dest="peak_nits",
                     help="Reference SDR peak in nits passed to zscale (default 100).")
    h2s.add_argument("--crf", type=int, default=20,
                     help="CRF for the libx264 output (default 20).")

    # ── subtitle-burn ─────────────────────────────────────────────────────────
    burn = sub.add_parser("subtitle-burn",
                          help="Burn an external subtitle file into the video (libass)")
    burn.add_argument("--input", required=True)
    burn.add_argument("--output", required=True)
    burn.add_argument("--subtitles", required=True,
                      help="Path to .srt / .ass / .ssa / .vtt subtitle file")
    burn.add_argument("--font", default="Arial", help="Font family name (default Arial)")
    burn.add_argument("--size", type=int, default=24, help="Font size px (default 24)")
    burn.add_argument("--color", default="00FFFFFF",
                      help="Primary fill colour as ASS BBGGRR or AABBGGRR hex (default 00FFFFFF = white).")
    burn.add_argument("--outline-color", dest="outline_color", default="00000000",
                      help="Outline colour as ASS hex (default 00000000 = black).")
    burn.add_argument("--shadow-color", dest="shadow_color", default="80000000",
                      help="Shadow colour as ASS hex (default 80000000 = 50%% black).")
    burn.add_argument("--border-style", dest="border_style", type=int, default=1,
                      help="Border style: 1=outline+shadow, 3=opaque box (default 1).")
    burn.add_argument("--outline", type=float, default=2.0,
                      help="Outline thickness in pixels (default 2.0).")
    burn.add_argument("--shadow", type=float, default=0.0,
                      help="Drop-shadow offset in pixels (default 0).")
    burn.add_argument("--margin-v", dest="margin_v", type=int, default=24,
                      help="Vertical margin from edge in pixels (default 24).")
    burn.add_argument("--position", default="bc",
                      help="9-point grid: tl tc tr ml mc mr bl bc br (default bc).")
    burn.add_argument("--bold", action="store_true")
    burn.add_argument("--italic", action="store_true")
    burn.add_argument("--codec", default="libx264")
    burn.add_argument("--crf", type=int, default=20)
    burn.add_argument("--preset", default="medium")

    # ── auto-crop ─────────────────────────────────────────────────────────────
    autocrop = sub.add_parser("auto-crop",
                              help="Detect black borders via cropdetect and apply the rectangle")
    autocrop.add_argument("--input", required=True)
    autocrop.add_argument("--output", required=True)
    autocrop.add_argument("--threshold", type=int, default=24,
                          help="cropdetect black-pixel threshold (default 24).")
    autocrop.add_argument("--sample-seconds", dest="sample_seconds", type=float, default=10.0,
                          help="Seconds of source to sample for detection (default 10).")
    autocrop.add_argument("--detect-only", dest="detect_only", action="store_true",
                          help="Detect and report the rectangle without producing an output file.")
    autocrop.add_argument("--codec", default="libx264")
    autocrop.add_argument("--crf", type=int, default=20)
    autocrop.add_argument("--preset", default="medium")

    # ── intro-outro ───────────────────────────────────────────────────────────
    io_p = sub.add_parser("intro-outro",
                          help="Prepend an intro and/or append an outro to the primary input")
    io_p.add_argument("--input", required=True, help="Primary video file")
    io_p.add_argument("--output", required=True)
    io_p.add_argument("--intro", help="Optional pre-clip prepended to the primary video")
    io_p.add_argument("--outro", help="Optional post-clip appended to the primary video")
    io_p.add_argument("--reencode", action="store_true",
                      help="Force a filter_complex re-encode even when codecs match.")

    # ── v360 ──────────────────────────────────────────────────────────────────
    v360 = sub.add_parser("v360",
                          help="Reproject 360°/VR video between equirectangular, cubemap, fisheye, flat (FFmpeg v360 filter)")
    v360.add_argument("--input", required=True)
    v360.add_argument("--output", required=True)
    v360.add_argument("--input-projection", dest="input_projection", default="equirect",
                      help=f"Source projection. Default 'equirect'. Known: {sorted(_V360_INPUT_PROJECTIONS)}.")
    v360.add_argument("--output-projection", dest="output_projection", default="flat",
                      help=f"Target projection. Default 'flat' (rectilinear viewport).")
    v360.add_argument("--yaw", type=float, default=0.0, help="Yaw rotation in degrees (default 0).")
    v360.add_argument("--pitch", type=float, default=0.0, help="Pitch rotation in degrees (default 0).")
    v360.add_argument("--roll", type=float, default=0.0, help="Roll rotation in degrees (default 0).")
    v360.add_argument("--h-fov", dest="h_fov", type=float, default=0.0,
                      help="Horizontal FOV (degrees) for output projection (0 = filter default).")
    v360.add_argument("--v-fov", dest="v_fov", type=float, default=0.0,
                      help="Vertical FOV (degrees) for output projection (0 = filter default).")
    v360.add_argument("--width", type=int, default=0, help="Output width in pixels (0 = source).")
    v360.add_argument("--height", type=int, default=0, help="Output height in pixels (0 = source).")
    v360.add_argument("--codec", default="libx264")
    v360.add_argument("--crf", type=int, default=20)
    v360.add_argument("--preset", default="medium")

    # ── lens-correct ──────────────────────────────────────────────────────────
    lensc = sub.add_parser("lens-correct",
                           help="Barrel/pincushion correction via FFmpeg lenscorrection filter")
    lensc.add_argument("--input", required=True)
    lensc.add_argument("--output", required=True)
    lensc.add_argument("--k1", type=float, default=-0.2,
                       help="Quadratic correction. <0 = pincushion correction (default -0.2 for action cams).")
    lensc.add_argument("--k2", type=float, default=0.0,
                       help="Quartic correction (default 0).")
    lensc.add_argument("--cx", type=float, default=0.5, help="Optical centre X (0..1, default 0.5).")
    lensc.add_argument("--cy", type=float, default=0.5, help="Optical centre Y (0..1, default 0.5).")
    lensc.add_argument("--codec", default="libx264")
    lensc.add_argument("--crf", type=int, default=20)
    lensc.add_argument("--preset", default="medium")

    # ── watermark ─────────────────────────────────────────────────────────────
    wm = sub.add_parser("watermark",
                        help="Overlay a PNG/JPEG logo with 9-point positioning, opacity, and scale")
    wm.add_argument("--input", required=True)
    wm.add_argument("--output", required=True)
    wm.add_argument("--overlay", required=True,
                    help="Path to a PNG (with alpha) or JPEG logo file")
    wm.add_argument("--position", default="br",
                    help="9-point grid: tl tc tr ml mc mr bl bc br (default br).")
    wm.add_argument("--opacity", type=float, default=0.7,
                    help="Overlay opacity 0..1 (default 0.7).")
    wm.add_argument("--scale", type=float, default=15.0,
                    help="Overlay width as percent of frame width (default 15).")
    wm.add_argument("--margin", type=int, default=24,
                    help="Edge margin in pixels (default 24).")
    wm.add_argument("--codec", default="libx264")
    wm.add_argument("--crf", type=int, default=20)
    wm.add_argument("--preset", default="medium")

    # ── stabilize ─────────────────────────────────────────────────────────────
    stab = sub.add_parser("stabilize",
                          help="Two-pass video stabilization via vidstabdetect + vidstabtransform")
    stab.add_argument("--input", required=True)
    stab.add_argument("--output", required=True)
    stab.add_argument("--shakiness", type=int, default=5,
                      help="Detection shakiness 1..10 (default 5).")
    stab.add_argument("--smoothing", type=int, default=15,
                      help="Smoothing window in frames 1..60 (default 15).")
    stab.add_argument("--border", default="keep",
                      help="Border handling: keep | black | crop (default keep).")
    stab.add_argument("--codec", default="libx264")
    stab.add_argument("--crf", type=int, default=20)
    stab.add_argument("--preset", default="medium")

    # ── face blur ────────────────────────────────────────────────────────────
    face_blur = sub.add_parser(
        "face-blur",
        help="Detect and irreversibly blur frontal faces in every frame")
    face_blur.add_argument("--input", required=True)
    face_blur.add_argument("--output", required=True)
    face_blur.add_argument("--strength", type=int, default=70,
                           help="Blur/pixelation strength 1..100 (default 70).")
    face_blur.add_argument("--padding", type=int, default=20,
                           help="Expand each detected face box by this percent (default 20).")
    face_blur.add_argument("--scale-factor", dest="scale_factor", type=float, default=1.1,
                           help="OpenCV cascade scale factor 1.01..2.0 (default 1.1).")
    face_blur.add_argument("--min-neighbors", dest="min_neighbors", type=int, default=5,
                           help="Cascade consensus threshold 1..20 (default 5).")
    face_blur.add_argument("--min-face", dest="min_face", type=int, default=24,
                           help="Smallest detected face in pixels (default 24).")
    face_blur.add_argument("--codec", choices=("libx264", "libx265"), default="libx264")
    face_blur.add_argument("--crf", type=int, choices=range(0, 52), default=18)
    face_blur.add_argument("--preset", default="medium")

    # ── timeline ──────────────────────────────────────────────────────────────
    timeline = sub.add_parser("timeline",
                              help="Extract a thumbnail strip + waveform image for the UI scrub bar")
    timeline.add_argument("--input", required=True)
    timeline.add_argument("--output-dir", required=True, dest="output_dir")
    timeline.add_argument("--thumb-fps", type=float, default=1.0, dest="thumb_fps",
                          help="Thumbnails per second (default 1.0).")
    timeline.add_argument("--thumb-height", type=int, default=72, dest="thumb_height",
                          help="Thumbnail height in pixels (default 72).")
    timeline.add_argument("--waveform-width", type=int, default=2400, dest="waveform_width",
                          help="Waveform image width in pixels (default 2400).")
    timeline.add_argument("--waveform-height", type=int, default=80, dest="waveform_height",
                          help="Waveform image height in pixels (default 80).")
    timeline.add_argument("--waveform-color", default="0x6dd3ff", dest="waveform_color",
                          help="Waveform fill colour (default brand cyan).")

    # ── keyframes ─────────────────────────────────────────────────────────────
    keyframes = sub.add_parser(
        "keyframes",
        help="List video keyframe timestamps for lossless-cut snapping")
    keyframes.add_argument("--input", required=True)

    # ── vmaf ──────────────────────────────────────────────────────────────────
    vmaf = sub.add_parser("vmaf",
                          help="VMAF quality comparison: distorted vs. reference (libvmaf)")
    vmaf.add_argument("--reference", required=True,
                      help="Reference (high-quality master) video.")
    vmaf.add_argument("--distorted", required=True,
                      help="Distorted (compressed / re-encoded) video to score.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "trim":
            return op_trim(args)
        if args.op == "crop":
            return op_crop(args)
        if args.op == "crop-meta":
            return op_crop_meta(args)
        if args.op == "aspect-override":
            return op_aspect_override(args)
        if args.op == "rotate":
            return op_rotate(args)
        if args.op == "loudnorm":
            return op_loudnorm(args)
        if args.op == "rewrap":
            return op_rewrap(args)
        if args.op == "vmaf":
            return op_vmaf(args)
        if args.op == "timeline":
            return op_timeline(args)
        if args.op == "keyframes":
            return op_keyframes(args)
        if args.op == "track-list":
            return op_track_list(args)
        if args.op == "track-remove":
            return op_track_remove(args)
        if args.op == "track-add":
            return op_track_add(args)
        if args.op == "track-extract":
            return op_track_extract(args)
        if args.op == "concat":
            return op_concat(args)
        if args.op == "speed":
            return op_speed(args)
        if args.op == "reverse":
            return op_reverse(args)
        if args.op == "lut3d":
            return op_lut(args)
        if args.op == "hdr-to-sdr":
            return op_hdr_to_sdr(args)
        if args.op == "subtitle-burn":
            return op_subtitle_burn(args)
        if args.op == "auto-crop":
            return op_auto_crop(args)
        if args.op == "stabilize":
            return op_stabilize(args)
        if args.op == "face-blur":
            return op_face_blur(args)
        if args.op == "lens-correct":
            return op_lens_correct(args)
        if args.op == "watermark":
            return op_watermark(args)
        if args.op == "v360":
            return op_v360(args)
        if args.op == "intro-outro":
            return op_intro_outro(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
