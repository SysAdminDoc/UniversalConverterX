#!/usr/bin/env python3
"""CUDA-only NVIDIA Parakeet TDT v3 speech-to-text sidecar.

Model weights are never downloaded by the transcribe command. The user must
explicitly run ``download-model --accept-license`` first; inference then loads
the pinned local snapshot with ``local_files_only=True``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg  # noqa: E402


MODEL_REPO = "nvidia/parakeet-tdt-0.6b-v3"
MODEL_SLUG = "parakeet-tdt-0.6b-v3"
MODEL_REVISION = "7c35754d166cca382ad1e53e68b01e7c575f3a1d"
MODEL_LICENSE = "CC-BY-4.0"
REQUIRED_MODEL_FILES = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "processor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
SUPPORTED_LANGUAGES = frozenset({
    "auto", "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr",
    "de", "el", "hu", "it", "lv", "lt", "mt", "pl", "pt", "ro",
    "sk", "sl", "es", "sv", "ru", "uk",
})


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def resolve_model_dir(root: str | Path | None = None) -> Path:
    configured = root or os.environ.get("UCX_MODEL_DIR")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.name == MODEL_SLUG or (candidate / "config.json").is_file():
            return candidate.resolve()
        return (candidate / MODEL_SLUG).resolve()
    runtime_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent
    return (runtime_dir / "models" / MODEL_SLUG).resolve()


def missing_model_files(model_dir: Path) -> list[str]:
    return [name for name in REQUIRED_MODEL_FILES if not (model_dir / name).is_file()]


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def install_downloaded_model(stage: Path, target: Path) -> None:
    """Promote a complete staged snapshot and roll back on promotion failure."""
    missing = missing_model_files(stage)
    if missing:
        raise RuntimeError("Downloaded snapshot is incomplete: " + ", ".join(missing))

    marker = {
        "model": MODEL_REPO,
        "revision": MODEL_REVISION,
        "license": MODEL_LICENSE,
    }
    (stage / ".ucx-model.json").write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8")

    backup = target.with_name(target.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        os.replace(target, backup)
    try:
        os.replace(stage, target)
    except Exception:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def download_model(args: argparse.Namespace) -> int:
    if not args.accept_license:
        return fail(
            "license_acceptance_required",
            f"Parakeet is licensed under {MODEL_LICENSE}. Re-run the explicit "
            "download action after accepting that license.",
        )
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return fail(
            "missing_dep",
            "huggingface-hub is not bundled. Rebuild parakeet-stt with its "
            "declared requirements.",
        )

    target = resolve_model_dir(args.model_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{MODEL_SLUG}-", dir=target.parent))
    emit("progress", percent=1.0, stage="Downloading pinned model snapshot", eta_seconds=None)
    emit(
        "log", level="info",
        message=f"Downloading {MODEL_REPO}@{MODEL_REVISION[:12]} to a staging directory.",
    )
    try:
        snapshot_download(
            repo_id=MODEL_REPO,
            revision=MODEL_REVISION,
            local_dir=str(stage),
            allow_patterns=list(REQUIRED_MODEL_FILES),
        )
        emit("progress", percent=95.0, stage="Validating model pack", eta_seconds=None)
        install_downloaded_model(stage, target)
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        return fail("model_download_failed", str(exc))

    size = directory_size(target)
    emit("progress", percent=100.0, stage="Model ready", eta_seconds=0)
    emit("complete", output=str(target), size_bytes=size)
    return 0


def model_status(args: argparse.Namespace) -> int:
    model_dir = resolve_model_dir(args.model_dir)
    missing = missing_model_files(model_dir)
    emit(
        "model",
        name=MODEL_SLUG,
        path=str(model_dir),
        ready=not missing,
        revision=MODEL_REVISION,
        license=MODEL_LICENSE,
    )
    if missing:
        return fail(
            "model_not_installed",
            "Parakeet model pack is not installed. Use the explicit Download "
            f"Model action first ({', '.join(missing)} missing).",
        )
    emit("complete", output=str(model_dir), size_bytes=directory_size(model_dir))
    return 0


def timestamp(seconds: float, *, vtt: bool = False) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02}:{minutes:02}:{whole_seconds:02}{separator}{millis:03}"


def words_to_segments(
    words: Iterable[dict],
    *,
    max_seconds: float = 6.0,
    max_characters: int = 84,
) -> list[dict]:
    """Group timestamped word chunks into readable subtitle cues."""
    result: list[dict] = []
    current: list[dict] = []
    for raw in words:
        text = str(raw.get("text") or "").strip()
        stamp = raw.get("timestamp")
        if not text or not isinstance(stamp, (list, tuple)) or len(stamp) != 2:
            continue
        start, end = stamp
        if start is None or end is None:
            continue
        word = {"start": float(start), "end": float(end), "text": text}
        current.append(word)
        cue_text = " ".join(item["text"] for item in current)
        cue_duration = current[-1]["end"] - current[0]["start"]
        sentence_end = text.endswith((".", "!", "?"))
        if sentence_end or cue_duration >= max_seconds or len(cue_text) >= max_characters:
            result.append({
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "text": cue_text,
                "words": list(current),
            })
            current.clear()
    if current:
        result.append({
            "start": current[0]["start"],
            "end": current[-1]["end"],
            "text": " ".join(item["text"] for item in current),
            "words": list(current),
        })
    return result


def render_segments(segments: list[dict], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(segments, ensure_ascii=False, indent=2) + "\n"
    if output_format == "txt":
        return "\n".join(segment["text"].strip() for segment in segments) + "\n"
    lines = ["WEBVTT", ""] if output_format == "vtt" else []
    for index, segment in enumerate(segments, 1):
        if output_format == "srt":
            lines.append(str(index))
        lines.append(
            f"{timestamp(segment['start'], vtt=output_format == 'vtt')} --> "
            f"{timestamp(segment['end'], vtt=output_format == 'vtt')}")
        lines.extend([segment["text"].strip(), ""])
    return "\n".join(lines)


def convert_to_pcm(source: Path, destination: Path) -> tuple[bool, str]:
    ffmpeg = find_ffmpeg(Path(__file__).resolve().parent)
    if not ffmpeg:
        return False, "FFmpeg was not found. Install the managed FFmpeg tool first."
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-vn", "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(destination)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0, result.stderr.strip()


def load_pcm(path: Path):
    import numpy as np

    with wave.open(str(path), "rb") as stream:
        if stream.getnchannels() != 1 or stream.getframerate() != 16000 or stream.getsampwidth() != 2:
            raise ValueError("Expected mono 16 kHz signed 16-bit PCM WAV")
        frames = stream.readframes(stream.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(args: argparse.Namespace) -> int:
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    if not source.is_file():
        return fail("input_not_found", f"Input file not found: {source}")
    language = args.language.lower()
    if language not in SUPPORTED_LANGUAGES:
        return fail(
            "unsupported_language",
            f"Parakeet TDT v3 does not support '{language}'. Choose Auto or one "
            "of its 25 supported European languages.",
        )

    model_dir = resolve_model_dir(args.model_dir)
    missing = missing_model_files(model_dir)
    if missing:
        return fail(
            "model_not_installed",
            "Parakeet does not download weights during transcription. Use the "
            "explicit Download Model action first.",
        )

    try:
        import torch
        from transformers import AutoModelForTDT, AutoProcessor, pipeline
    except ImportError as exc:
        return fail("missing_dep", f"Parakeet runtime dependency missing: {exc}")
    if not torch.cuda.is_available():
        return fail(
            "cuda_required",
            "Parakeet TDT v3 requires an NVIDIA CUDA GPU in Universal Converter X. "
            "Use faster-whisper or whisper.cpp for CPU transcription.",
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    emit("progress", percent=2.0, stage="Preparing 16 kHz audio", eta_seconds=None)
    with tempfile.TemporaryDirectory(prefix="ucx-parakeet-") as temp_dir:
        pcm_path = Path(temp_dir) / "audio.wav"
        converted, diagnostic = convert_to_pcm(source, pcm_path)
        if not converted:
            return fail("ffmpeg_failed", diagnostic or "FFmpeg could not decode the input.")
        audio = load_pcm(pcm_path)

        emit("progress", percent=8.0, stage="Loading pinned Parakeet model", eta_seconds=None)
        try:
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            processor = AutoProcessor.from_pretrained(str(model_dir), local_files_only=True)
            model = AutoModelForTDT.from_pretrained(
                str(model_dir), local_files_only=True, dtype=dtype)
            model.to("cuda").eval()
            recognizer = pipeline(
                "automatic-speech-recognition",
                model=model,
                tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor,
                device=0,
            )
        except Exception as exc:
            return fail("model_load_failed", str(exc))

        sample_rate = 16000
        chunk_samples = max(30, min(args.chunk_seconds, 900)) * sample_rate
        chunks = max(1, (len(audio) + chunk_samples - 1) // chunk_samples)
        segments: list[dict] = []
        for index, start in enumerate(range(0, len(audio), chunk_samples), 1):
            end = min(len(audio), start + chunk_samples)
            offset = start / sample_rate
            percent = 10.0 + (index - 1) / chunks * 84.0
            emit(
                "progress", percent=round(percent, 1),
                stage=f"Transcribing chunk {index} of {chunks}", eta_seconds=None,
            )
            try:
                result = recognizer(
                    {"array": audio[start:end], "sampling_rate": sample_rate},
                    return_timestamps="word",
                )
            except Exception as exc:
                return fail("transcription_failed", str(exc))

            raw_words = []
            for item in result.get("chunks", []):
                stamp = item.get("timestamp")
                if isinstance(stamp, (list, tuple)) and len(stamp) == 2:
                    raw_words.append({
                        "text": item.get("text", ""),
                        "timestamp": (
                            None if stamp[0] is None else float(stamp[0]) + offset,
                            None if stamp[1] is None else float(stamp[1]) + offset,
                        ),
                    })
            chunk_segments = words_to_segments(raw_words)
            if not chunk_segments and str(result.get("text") or "").strip():
                chunk_segments = [{
                    "start": offset,
                    "end": end / sample_rate,
                    "text": str(result["text"]).strip(),
                    "words": [],
                }]
            segments.extend(chunk_segments)

    if not segments:
        return fail("empty_transcript", "Parakeet produced no speech segments.")
    if not args.word_timestamps:
        for segment in segments:
            segment.pop("words", None)
    for segment in segments:
        emit(
            "segment", start=segment["start"], end=segment["end"],
            text=segment["text"],
        )

    output.write_text(render_segments(segments, args.format), encoding="utf-8")
    emit("progress", percent=100.0, stage="Done", eta_seconds=0)
    emit("complete", output=str(output), size_bytes=output.stat().st_size)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parakeet-stt",
        description="Opt-in CUDA speech-to-text with NVIDIA Parakeet TDT 0.6B v3.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("model-status", help="Check the local pinned model pack.")
    status.add_argument("--model-dir")
    status.set_defaults(handler=model_status)

    download = commands.add_parser("download-model", help="Explicitly download the pinned model pack.")
    download.add_argument("--model-dir")
    download.add_argument("--accept-license", action="store_true")
    download.set_defaults(handler=download_model)

    run = commands.add_parser("transcribe", help="Transcribe without network access.")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--format", choices=("srt", "vtt", "txt", "json"), default="srt")
    run.add_argument("--language", default="auto")
    run.add_argument("--word-timestamps", action="store_true")
    run.add_argument("--model-dir")
    run.add_argument("--chunk-seconds", type=int, default=600)
    run.set_defaults(handler=transcribe)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
