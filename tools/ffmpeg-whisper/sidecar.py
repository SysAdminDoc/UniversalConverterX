"""Offline speech-to-text through FFmpeg's native whisper audio filter."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg as shared_find_ffmpeg


SUPPORTED_FORMATS = {"srt", "vtt", "txt", "json"}


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _here() -> Path:
    return Path(__file__).resolve().parent


def find_ffmpeg() -> str | None:
    return shared_find_ffmpeg(_here())


def discover_models() -> list[Path]:
    roots = [
        _here() / "models",
        _here().parent / "whisper-cpp" / "models",
    ]
    configured = os.environ.get("UCX_MODEL_DIR")
    if configured:
        roots.append(Path(configured) / "whisper-cpp")

    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for model in sorted(root.glob("ggml-*.bin")):
            found.setdefault(str(model.resolve()).lower(), model.resolve())
    return list(found.values())


def resolve_model(value: str) -> Path | None:
    candidate = Path(value)
    if candidate.is_file():
        return candidate.resolve()

    wanted = value.lower()
    names = {wanted, f"ggml-{wanted}", f"ggml-{wanted}.bin"}
    for model in discover_models():
        if model.name.lower() in names or model.stem.lower() in names:
            return model
    return None


def _filter_escape(path: Path) -> str:
    # FFmpeg's filter parser interprets ':' separately from argv parsing.
    value = str(path.resolve()).replace("\\", "/")
    return value.replace("'", "\\'").replace(":", "\\:")


def _format_from_output(path: Path, explicit: str | None) -> str:
    value = (explicit or path.suffix.lstrip(".") or "srt").lower()
    if value not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported transcript format: {value}")
    return value


def _srt_to_vtt(source: Path, destination: Path) -> None:
    text = source.read_text(encoding="utf-8-sig", errors="replace")
    timestamps = re.sub(
        r"(\d{2}:\d{2}:\d{2}),(\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2}),(\d{3})",
        r"\1.\2 --> \3.\4",
        text,
    )
    destination.write_text("WEBVTT\n\n" + timestamps.lstrip(), encoding="utf-8")


def op_probe(_: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return fail("missing_ffmpeg", "FFmpeg was not found in the managed tools directory or PATH.")
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    available = result.returncode == 0 and re.search(
        r"^\s*\.\.\s+whisper\s+A->A", (result.stdout or "") + (result.stderr or ""), re.MULTILINE
    ) is not None
    emit("backend", available=available, ffmpeg=ffmpeg, filter="whisper")
    emit("complete", output="", size_bytes=0, available=available)
    return 0 if available else 1


def op_models(_: argparse.Namespace) -> int:
    models = discover_models()
    for model in models:
        emit("model", name=model.stem, path=str(model), size_bytes=model.stat().st_size)
    emit("complete", output="", size_bytes=0, count=len(models))
    return 0


def op_transcribe(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return fail("missing_ffmpeg", "FFmpeg was not found in the managed tools directory or PATH.")

    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input not found: {source}")
    model = resolve_model(args.model)
    if model is None:
        return fail(
            "missing_model",
            f"Local GGUF model {args.model!r} was not found. Install it for whisper.cpp; "
            "the FFmpeg backend reuses the same offline model directory.",
        )

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        transcript_format = _format_from_output(output, args.format)
    except ValueError as ex:
        return fail("invalid_format", str(ex))

    if args.word_timestamps:
        emit("log", level="warn", message="FFmpeg's whisper filter emits segment timestamps, not word timestamps.")

    work: tempfile.TemporaryDirectory[str] | None = None
    destination = output
    ffmpeg_format = transcript_format
    if transcript_format == "vtt":
        work = tempfile.TemporaryDirectory(prefix="ucx_ffmpeg_whisper_")
        destination = Path(work.name) / "transcript.srt"
        ffmpeg_format = "srt"

    options = [
        f"model='{_filter_escape(model)}'",
        f"language='{args.language or 'auto'}'",
        f"destination='{_filter_escape(destination)}'",
        f"format={ffmpeg_format}",
        f"use_gpu={'true' if args.use_gpu else 'false'}",
        f"gpu_device={args.gpu_device}",
    ]
    if args.vad_model:
        vad_model = Path(args.vad_model)
        if not vad_model.is_file():
            if work is not None:
                work.cleanup()
            return fail("missing_vad_model", f"VAD model not found: {vad_model}")
        options.extend([
            f"vad_model='{_filter_escape(vad_model)}'",
            f"vad_threshold={args.vad_threshold}",
        ])
    elif args.vad:
        emit("log", level="warn", message="VAD requested without --vad-model; continuing without VAD.")

    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source.resolve()),
        "-af", "whisper=" + ":".join(options),
        "-f", "null", "NUL" if os.name == "nt" else "/dev/null",
    ]
    emit("progress", percent=1, stage="transcribing", eta_seconds=None)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout)
        if result.returncode != 0:
            return fail("ffmpeg_failed", (result.stderr or result.stdout or "FFmpeg failed").strip()[-1000:])
        if not destination.is_file():
            return fail("missing_output", "FFmpeg completed without creating a transcript.")
        if transcript_format == "vtt":
            _srt_to_vtt(destination, output)
        if not output.is_file():
            return fail("missing_output", "Transcript promotion failed.")
        emit("progress", percent=100, stage="complete", eta_seconds=0)
        emit("complete", output=str(output), size_bytes=output.stat().st_size, format=transcript_format)
        return 0
    finally:
        if work is not None:
            work.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ffmpeg-whisper-sidecar",
        description="Offline transcription through FFmpeg's native whisper filter.",
    )
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("probe", help="Check whether the managed FFmpeg includes the whisper filter.")
    sub.add_parser("models", help="List local whisper.cpp GGUF models.")
    transcribe = sub.add_parser("transcribe", help="Transcribe one local media file.")
    transcribe.add_argument("--input", required=True)
    transcribe.add_argument("--output", required=True)
    transcribe.add_argument("--model", default="base")
    transcribe.add_argument("--language", default="auto")
    transcribe.add_argument("--format", choices=sorted(SUPPORTED_FORMATS))
    transcribe.add_argument("--use-gpu", action=argparse.BooleanOptionalAction, default=True)
    transcribe.add_argument("--gpu-device", type=int, default=0)
    transcribe.add_argument("--vad", action="store_true")
    transcribe.add_argument("--vad-model")
    transcribe.add_argument("--vad-threshold", type=float, default=0.5)
    transcribe.add_argument("--word-timestamps", action="store_true")
    transcribe.add_argument("--timeout", type=int, default=7200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":
            return op_probe(args)
        if args.op == "models":
            return op_models(args)
        if args.op == "transcribe":
            return op_transcribe(args)
        return fail("unknown_op", f"Unknown operation: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
