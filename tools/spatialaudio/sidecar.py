"""Offline spatial-audio conversion through FFmpeg."""

from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg, find_ffprobe, probe_media, run_ffmpeg


MODES = (
    "foa-to-binaural",
    "foa-to-5.1",
    "foa-to-7.1",
    "stereo-to-5.1",
    "stereo-to-7.1",
    "surround-to-binaural",
)


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _here() -> Path:
    return Path(__file__).resolve().parent


def _term(coefficient: float, channel: str, *, first: bool = False) -> str:
    sign = "" if first and coefficient >= 0 else ("+" if coefficient >= 0 else "-")
    return f"{sign}{abs(coefficient):.4f}*{channel}"


def _foa_expression(angle_degrees: float) -> str:
    # ACN/SN3D channel order: W, Y, Z, X. Horizontal decoder ignores Z.
    radians = math.radians(angle_degrees)
    return (
        _term(0.7071, "c0", first=True)
        + _term(0.5 * math.cos(radians), "c3")
        + _term(0.5 * math.sin(radians), "c1")
    )


def foa_pan_graph(layout: str) -> str:
    if layout == "stereo":
        return (
            "pan=stereo|c0=" + _foa_expression(30)
            + "|c1=" + _foa_expression(-30)
        )
    if layout == "5.1":
        speakers = (("FL", 30), ("FR", -30), ("FC", 0), ("BL", 110), ("BR", -110))
        parts = [f"{label}={_foa_expression(angle)}" for label, angle in speakers]
        parts.insert(3, "LFE=0*c0")
        return "pan=5.1|" + "|".join(parts)
    if layout == "7.1":
        speakers = (
            ("FL", 30), ("FR", -30), ("FC", 0),
            ("BL", 150), ("BR", -150), ("SL", 90), ("SR", -90),
        )
        parts = [f"{label}={_foa_expression(angle)}" for label, angle in speakers]
        parts.insert(3, "LFE=0*c0")
        return "pan=7.1|" + "|".join(parts)
    raise ValueError(f"Unsupported FOA output layout: {layout}")


def _filter_escape(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    return value.replace("'", "\\'").replace(":", "\\:")


def filter_for_mode(mode: str, sofa: Path | None = None) -> tuple[str, str]:
    if mode == "foa-to-binaural":
        return foa_pan_graph("stereo"), "stereo"
    if mode == "foa-to-5.1":
        return foa_pan_graph("5.1"), "5.1"
    if mode == "foa-to-7.1":
        return foa_pan_graph("7.1"), "7.1"
    if mode == "stereo-to-5.1":
        return "surround=chl_in=stereo:chl_out=5.1", "5.1"
    if mode == "stereo-to-7.1":
        return "surround=chl_in=stereo:chl_out=7.1", "7.1"
    if mode == "surround-to-binaural":
        if sofa is None:
            raise ValueError("surround-to-binaural requires a local --sofa HRTF file.")
        return f"sofalizer=sofa='{_filter_escape(sofa)}':normalize=true", "stereo"
    raise ValueError(f"Unsupported spatial mode: {mode}")


def codec_args(output: Path) -> list[str]:
    extension = output.suffix.lower()
    if extension == ".wav":
        return ["-c:a", "pcm_s24le"]
    if extension == ".flac":
        return ["-c:a", "flac"]
    if extension in {".m4a", ".mp4"}:
        return ["-c:a", "aac", "-b:a", "384k"]
    if extension in {".opus", ".ogg"}:
        return ["-c:a", "libopus", "-b:a", "256k"]
    raise ValueError("Output extension must be wav, flac, m4a, mp4, opus, or ogg.")


def op_probe(_: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg(_here())
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg was not found.")
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30
    )
    text = (result.stdout or "") + (result.stderr or "")
    filters = {
        name: re.search(rf"^\s*.{{2}}\s+{name}\s+A->A", text, re.MULTILINE) is not None
        for name in ("pan", "surround", "sofalizer")
    }
    emit("backend", available=all(filters.values()), ffmpeg=ffmpeg, filters=filters)
    emit("complete", output="", size_bytes=0, available=all(filters.values()))
    return 0 if all(filters.values()) else 1


def op_convert(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg(_here())
    ffprobe = find_ffprobe(_here())
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe was not found.")

    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input not found: {source}")
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    sofa = Path(args.sofa).resolve() if args.sofa else None
    if sofa is not None and not sofa.is_file():
        return fail("missing_sofa", f"SOFA HRTF file not found: {sofa}")
    try:
        graph, layout = filter_for_mode(args.mode, sofa)
        encoding = codec_args(output)
    except ValueError as ex:
        return fail("invalid_option", str(ex))

    info = probe_media(ffprobe, source)
    if not info:
        return fail("probe_failed", "FFprobe could not read the input.")
    audio = next(
        (stream for stream in info.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    channels = int((audio or {}).get("channels") or 0)
    if args.mode.startswith("foa-") and channels < 4:
        return fail("invalid_channels", "First-order Ambisonics input requires four ACN/SN3D channels (W,Y,Z,X).")
    if args.mode.startswith("stereo-") and channels != 2:
        return fail("invalid_channels", "Stereo upmix requires a two-channel input.")

    duration = float(info.get("format", {}).get("duration", 0)) or 0.0
    command = [
        ffmpeg, "-y", "-i", str(source.resolve()),
        "-map", "0:a:0", "-af", graph,
        "-channel_layout", layout,
        *encoding,
        str(output),
    ]
    emit("log", level="info", message=f"Spatial conversion {args.mode}: {channels}ch -> {layout}")
    emit("progress", percent=0, stage="spatial-audio", eta_seconds=None)
    rc = run_ffmpeg(command, duration, "spatial-audio")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not output.is_file():
        return fail("output_missing", f"Output not produced: {output}")
    emit(
        "complete", output=str(output), size_bytes=output.stat().st_size,
        mode=args.mode, input_channels=channels, output_layout=layout,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spatialaudio-sidecar",
        description="Offline Ambisonics, binaural, and surround conversion.",
    )
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("probe", help="Check required FFmpeg spatial filters.")
    convert = sub.add_parser("convert", help="Convert one spatial-audio file.")
    convert.add_argument("--input", required=True)
    convert.add_argument("--output", required=True)
    convert.add_argument("--mode", choices=MODES, required=True)
    convert.add_argument("--sofa", help="Local SOFA HRTF file for surround-to-binaural.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":
            return op_probe(args)
        if args.op == "convert":
            return op_convert(args)
        return fail("unknown_op", f"Unknown operation: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
