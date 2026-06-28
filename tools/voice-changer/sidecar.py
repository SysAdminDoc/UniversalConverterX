"""Offline voice transformation sidecar.

Uses FFmpeg audio filters for local pitch, EQ, dynamics, and modulation based
voice-style changes. The workflow is deterministic, has no Python runtime
dependencies, and can process audio-only files or remux transformed audio back
into video containers without re-encoding the video stream.

NDJSON contract: emits progress, log, complete, and error events.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".alac", ".ape", ".wv", ".aif", ".aiff",
}

VIDEO_EXTS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v",
}

FORMATS = {
    "wav": ("pcm_s16le", ".wav"),
    "mp3": ("libmp3lame", ".mp3"),
    "m4a": ("aac", ".m4a"),
    "flac": ("flac", ".flac"),
    "opus": ("libopus", ".opus"),
}

STYLE_BASE_PITCH = {
    "neutral": 0.0,
    "lower": -4.0,
    "higher": 4.0,
    "robotic": 0.0,
    "whisper": 1.0,
}


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_ffmpeg() -> str | None:
    env = os.environ.get("FFMPEG_PATH")
    if env and Path(env).is_file():
        return env
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def _find_ffprobe() -> str | None:
    env = os.environ.get("FFPROBE_PATH")
    if env and Path(env).is_file():
        return env
    return shutil.which("ffprobe") or shutil.which("ffprobe.exe")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pitch_filters(semitones: float) -> list[str]:
    if abs(semitones) < 0.01:
        return []

    semitones = _clamp(semitones, -12.0, 12.0)
    factor = 2 ** (semitones / 12.0)
    tempo = _clamp(1.0 / factor, 0.5, 2.0)
    shifted_rate = 48000.0 * factor
    return [
        "aresample=48000",
        f"asetrate={shifted_rate:.3f}",
        "aresample=48000",
        f"atempo={tempo:.6f}",
    ]


def _style_filters(style: str, intensity: float) -> list[str]:
    amount = _clamp(intensity / 100.0, 0.0, 1.0)
    if style == "neutral":
        return [
            "highpass=f=80",
            "lowpass=f=12000",
            "afftdn=nf=-20",
            "dynaudnorm=f=150:g=8",
        ]
    if style == "lower":
        lowpass = 11500 - (3500 * amount)
        boost = 1.5 + (3.0 * amount)
        return [
            f"equalizer=f=160:t=q:w=1:g={boost:.2f}",
            f"lowpass=f={lowpass:.0f}",
            "dynaudnorm=f=150:g=8",
        ]
    if style == "higher":
        highpass = 80 + (130 * amount)
        boost = 1.0 + (3.0 * amount)
        return [
            f"highpass=f={highpass:.0f}",
            f"equalizer=f=2800:t=q:w=1:g={boost:.2f}",
            "dynaudnorm=f=150:g=9",
        ]
    if style == "robotic":
        depth = 0.18 + (0.34 * amount)
        delay = 4 + (8 * amount)
        bits = 12 - round(4 * amount)
        return [
            f"tremolo=f=32:d={depth:.2f}",
            f"aecho=0.80:0.72:{delay:.0f}:0.25",
            "flanger=delay=3:depth=3:regen=20:width=60:speed=0.2",
            f"acrusher=bits={bits}:mode=log",
            "dynaudnorm=f=150:g=8",
        ]
    if style == "whisper":
        return [
            "highpass=f=220",
            "lowpass=f=6500",
            "afftdn=nf=-24",
            "compand=attacks=0.02:decays=0.20:points=-80/-80|-35/-22|-10/-8|0/-6",
            "volume=0.92",
        ]
    return []


def build_filter(style: str, pitch_semitones: float, intensity: float) -> str:
    if style not in STYLE_BASE_PITCH:
        raise ValueError(f"unknown style: {style}")
    amount = _clamp(intensity / 100.0, 0.0, 1.0)
    style_pitch = STYLE_BASE_PITCH[style] * amount
    filters = _pitch_filters(pitch_semitones + style_pitch)
    filters.extend(_style_filters(style, intensity))
    return ",".join(filters) if filters else "anull"


def _probe_has_video(src: Path, ffprobe: str | None) -> bool:
    if src.suffix.lower() in AUDIO_EXTS:
        return False
    if src.suffix.lower() in VIDEO_EXTS and not ffprobe:
        return True
    if not ffprobe:
        return False
    try:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                str(src),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return src.suffix.lower() in VIDEO_EXTS
    return proc.returncode == 0 and "video" in (proc.stdout or "")


def _resolve_output(src: Path, out_dir: Path, style: str, fmt: str, has_video: bool) -> Path:
    if fmt == "video" and has_video:
        ext = src.suffix if src.suffix.lower() in VIDEO_EXTS else ".mp4"
    elif fmt == "video":
        ext = ".wav"
    else:
        ext = FORMATS[fmt][1]

    stem = f"{src.stem}_voice_{style}"
    candidate = out_dir / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    for i in range(1, 10000):
        numbered = out_dir / f"{stem} ({i}){ext}"
        if not numbered.exists():
            return numbered
    return out_dir / f"{stem}_{int(time.time())}{ext}"


def _run_ffmpeg(src: Path, out_path: Path, filter_str: str, fmt: str,
                has_video: bool, ffmpeg: str) -> tuple[int, str | None]:
    if fmt == "video" and has_video:
        cmd = [
            ffmpeg, "-y", "-i", str(src),
            "-map", "0:v:0?", "-map", "0:a:0",
            "-filter:a", filter_str,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(out_path),
        ]
    else:
        actual = "wav" if fmt == "video" else fmt
        codec, _ = FORMATS[actual]
        cmd = [ffmpeg, "-y", "-i", str(src), "-vn", "-filter:a", filter_str, "-c:a", codec]
        if actual == "mp3":
            cmd += ["-q:a", "2"]
        elif actual == "m4a":
            cmd += ["-b:a", "192k"]
        elif actual == "opus":
            cmd += ["-b:a", "128k"]
        cmd.append(str(out_path))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return 0, None
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
    return proc.returncode, "; ".join(tail)


def op_transform(args: argparse.Namespace) -> int:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found on PATH (set FFMPEG_PATH).")

    src = Path(args.input).resolve()
    if not src.is_file():
        return fail("missing_input", f"Input file not found: {src}")

    style = args.style.lower()
    if style not in STYLE_BASE_PITCH:
        return fail("unknown_style", f"Unknown style '{args.style}'.")
    if args.format not in {*FORMATS, "video"}:
        return fail("unknown_format", f"Unknown format '{args.format}'.")

    intensity = _clamp(float(args.intensity), 0.0, 100.0)
    pitch = _clamp(float(args.pitch_semitones), -12.0, 12.0)
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    emit("progress", percent=0, stage="probing", eta_seconds=None)
    ffprobe = _find_ffprobe()
    has_video = _probe_has_video(src, ffprobe)
    out_path = _resolve_output(src, out_dir, style, args.format, has_video)

    try:
        filter_str = build_filter(style, pitch, intensity)
    except ValueError as ex:
        return fail("invalid_filter", str(ex))

    emit("log", level="info", message=f"style={style} pitch={pitch:.1f} intensity={intensity:.0f}")
    emit("progress", percent=18, stage="rendering", eta_seconds=None)
    rc, err_tail = _run_ffmpeg(src, out_path, filter_str, args.format, has_video, ffmpeg)
    if rc != 0:
        if err_tail:
            emit("log", level="error", message=err_tail)
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}.")

    try:
        size = out_path.stat().st_size
    except OSError:
        size = 0

    emit("progress", percent=100, stage="done", eta_seconds=0)
    emit("complete", output=str(out_path), size_bytes=size, count=1)
    return 0


def op_presets(_args: argparse.Namespace) -> int:
    for name, base in STYLE_BASE_PITCH.items():
        emit("preset", name=name, base_pitch_semitones=base)
    emit("complete", output="", size_bytes=0, count=len(STYLE_BASE_PITCH))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-changer-sidecar",
        description="FFmpeg-backed offline voice style transformation.",
    )
    sub = parser.add_subparsers(dest="op", required=True)

    t = sub.add_parser("transform", help="Transform one audio or video file.")
    t.add_argument("--input", required=True)
    t.add_argument("--output-dir", required=True, dest="output_dir")
    t.add_argument("--style", choices=sorted(STYLE_BASE_PITCH), default="neutral")
    t.add_argument("--pitch-semitones", type=float, default=0.0)
    t.add_argument("--intensity", type=float, default=65.0)
    t.add_argument("--format", choices=sorted([*FORMATS, "video"]), default="wav")

    sub.add_parser("presets", help="List available style presets.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "transform":
            return op_transform(args)
        if args.op == "presets":
            return op_presets(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:  # noqa: BLE001
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
