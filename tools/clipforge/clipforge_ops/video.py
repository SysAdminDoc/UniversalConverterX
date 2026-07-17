from __future__ import annotations

import argparse
from pathlib import Path

from .runtime import emit, fail, find_ffmpeg, find_ffprobe, probe, run_ffmpeg


INTERLACED_FIELD_ORDERS = {"tt", "bb", "tb", "bt"}


def detected_field_order(info: dict) -> str:
    stream = next(
        (item for item in info.get("streams", []) if item.get("codec_type") == "video"),
        None,
    )
    return str((stream or {}).get("field_order") or "unknown").lower()


def build_deinterlace_filter(filter_name: str, rate: str) -> str:
    mode = "send_frame" if rate == "single" else "send_field"
    return f"{filter_name}=mode={mode}:parity=auto:deint=interlaced"


def build_deinterlace_command(
    ffmpeg: str,
    source: Path,
    output: Path,
    *,
    field_order: str,
    filter_name: str,
    rate: str,
    codec: str,
    crf: int,
    preset: str,
) -> tuple[list[str], bool, str]:
    interlaced = field_order in INTERLACED_FIELD_ORDERS
    # Stream-copy progressive input only when the container stays unchanged.
    # Otherwise encode to avoid incompatible codec/container combinations.
    if not interlaced and source.suffix.lower() == output.suffix.lower():
        return (
            [
                ffmpeg, "-y", "-i", str(source), "-map", "0", "-c", "copy",
                "-map_metadata", "0", "-map_chapters", "0", str(output),
            ],
            False,
            "copy-progressive",
        )

    command = [
        ffmpeg, "-y", "-i", str(source),
        "-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-map", "0:d?",
    ]
    mode = "encode-progressive"
    if interlaced:
        graph = build_deinterlace_filter(filter_name, rate)
        command += ["-vf", graph]
        mode = "double-rate" if rate != "single" else "single-rate"
    command += [
        "-c:v", codec, "-crf", str(crf), "-preset", preset,
        "-c:a", "copy", "-c:s", "copy", "-c:d", "copy",
        "-map_metadata", "0", "-map_chapters", "0",
    ]
    if output.suffix.lower() in (".mp4", ".m4v", ".mov"):
        command += ["-movflags", "+faststart"]
    command.append(str(output))
    return command, interlaced, mode


def op_deinterlace(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(source))
    if not info:
        return fail("probe_failed", "ffprobe could not read input.")
    if not any(item.get("codec_type") == "video" for item in info.get("streams", [])):
        return fail("missing_video", "Input does not contain a video stream.")
    field_order = detected_field_order(info)
    duration = float(info.get("format", {}).get("duration", 0)) or 0.0
    command, interlaced, mode = build_deinterlace_command(
        ffmpeg,
        source,
        output,
        field_order=field_order,
        filter_name=args.filter,
        rate=args.rate,
        codec=args.codec,
        crf=args.crf,
        preset=args.preset,
    )
    emit(
        "log",
        level="info",
        message=f"Field order={field_order}; deinterlace mode={mode}",
    )
    emit("progress", percent=0, stage="deinterlace", eta_seconds=None)
    rc = run_ffmpeg(command, duration, "deinterlace")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not output.is_file():
        return fail("output_missing", f"Output not produced: {output}")
    emit(
        "complete",
        output=str(output),
        size_bytes=output.stat().st_size,
        field_order=field_order,
        interlaced=interlaced,
        mode=mode,
    )
    return 0
