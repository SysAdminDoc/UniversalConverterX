from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

from .runtime import emit, fail, find_ffmpeg, find_ffprobe, probe, run_ffmpeg



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
