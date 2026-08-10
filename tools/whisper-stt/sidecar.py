#!/usr/bin/env python3
"""
UCX Whisper STT Sidecar — headless NDJSON wrapper for local Whisper transcription.

Backends tried in order:
  1. faster-whisper (ctranslate2, significantly faster than openai-whisper)
  2. openai-whisper  (reference implementation, slower)
  Dependencies must be provisioned by the sidecar build or its managed
  environment; runtime conversion never installs packages.

Usage:
    sidecar.py --input <path> --output <path.srt|.txt|.vtt|.json>
               --model base --language auto --format srt --word-timestamps

NDJSON events emitted to stdout:
    {"event": "log",      "level": "info|warn|error", "message": "..."}
    {"event": "progress", "percent": 0-100, "stage": "...", "eta_seconds": N}
    {"event": "segment",  "start": 1.23, "end": 4.56, "text": "Hello world"}
    {"event": "complete", "output": "<path>"}
    {"event": "error",    "code": "...", "message": "..."}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit
from ucx_assets import enforce_offline
from diarization_pack import (  # noqa: E402
    PACK_ID,
    PACK_LICENSE,
    PACK_TERMS_URL,
    download_pack,
    resolve_pack_dir,
    validate_pack,
)


def log(message: str, level: str = "info") -> None:
    emit({"event": "log", "level": level, "message": message})


def progress(percent: float, stage: str = "", eta: int = -1) -> None:
    emit({"event": "progress", "percent": round(percent, 1), "stage": stage, "eta_seconds": eta})


def error_exit(code: str, message: str) -> None:
    emit({"event": "error", "code": code, "message": message})
    sys.exit(1)


# ---------------------------------------------------------------------------
# Backend discovery
# ---------------------------------------------------------------------------

def bootstrap() -> str:
    """Return an available backend without mutating the Python environment."""
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"
    except ImportError:
        pass

    try:
        import whisper  # noqa: F401
        return "openai-whisper"
    except ImportError:
        pass

    if getattr(sys, "frozen", False):
        message = (
            "Neither faster-whisper nor openai-whisper is bundled into this "
            "sidecar. Reinstall Universal Converter X or rebuild the sidecar "
            "with its declared dependencies."
        )
    else:
        message = (
            "Neither faster-whisper nor openai-whisper is installed in the "
            "sidecar environment. Provision faster-whisper>=1.1.0 in the "
            "managed environment, then retry."
        )
    error_exit("missing_dep", message)
    raise AssertionError("error_exit must terminate")


# ---------------------------------------------------------------------------
# Language mapping
# ---------------------------------------------------------------------------

_LANG_MAP: dict[str, str | None] = {
    "auto": None,
    "en": "en", "english": "en",
    "es": "es", "spanish": "es",
    "fr": "fr", "french": "fr",
    "de": "de", "german": "de",
    "ja": "ja", "japanese": "ja",
    "zh": "zh", "chinese": "zh",
    "pt": "pt", "portuguese": "pt",
    "it": "it", "italian": "it",
    "ru": "ru", "russian": "ru",
    "ko": "ko", "korean": "ko",
    "ar": "ar", "arabic": "ar",
    "hi": "hi", "hindi": "hi",
    "nl": "nl", "dutch": "nl",
    "pl": "pl", "polish": "pl",
    "tr": "tr", "turkish": "tr",
}


def resolve_language(lang_arg: str) -> str | None:
    return _LANG_MAP.get(lang_arg.lower(), lang_arg.lower() if lang_arg.lower() != "auto" else None)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _ts_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ts_vtt(seconds: float) -> str:
    return _ts_srt(seconds).replace(",", ".")


def segments_to_srt(segments: list[dict]) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_ts_srt(seg['start'])} --> {_ts_srt(seg['end'])}")
        lines.append(_render_segment_text(seg))
        lines.append("")
    return "\n".join(lines)


def segments_to_vtt(segments: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_ts_vtt(seg['start'])} --> {_ts_vtt(seg['end'])}")
        lines.append(_render_segment_text(seg))
        lines.append("")
    return "\n".join(lines)


def segments_to_txt(segments: list[dict]) -> str:
    return "\n".join(_render_segment_text(seg) for seg in segments)


def segments_to_json(segments: list[dict]) -> str:
    return json.dumps(segments, ensure_ascii=False, indent=2)


def _render_segment_text(segment: dict) -> str:
    text = str(segment.get("text") or "").strip()
    speaker = str(segment.get("speaker") or "").strip()
    return f"[{speaker}] {text}" if speaker else text


def assign_speakers(segments: list[dict], turns: list[tuple[float, float, str]]) -> list[dict]:
    """Assign the label with the greatest overlap to each transcript segment."""
    for segment in segments:
        best: str | None = None
        best_overlap = 0.0
        for start, end, speaker in turns:
            overlap = max(
                0.0,
                min(float(end), float(segment["end"]))
                - max(float(start), float(segment["start"])),
            )
            if overlap > best_overlap:
                best = str(speaker)
                best_overlap = overlap
        segment["speaker"] = best or "SPEAKER_UNKNOWN"
    return segments


def diarization_turns(diarization) -> list[tuple[float, float, str]]:
    return [
        (float(turn.start), float(turn.end), str(speaker))
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]


def run_diarization(audio_path: Path, segments: list[dict], pack_dir: Path) -> None:
    """Run pyannote strictly from the validated local pack."""
    ready, reason = validate_pack(pack_dir)
    if not ready:
        raise RuntimeError(f"Diarization model pack is not ready: {reason}")

    # Set all offline/telemetry switches before importing pyannote. Passing a
    # local path also prevents the library from resolving a Hub identifier.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    enforce_offline()
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    try:
        from pyannote.audio import Pipeline as PyaPipeline  # type: ignore
    except ImportError as exc:
        raise RuntimeError(f"pyannote.audio is not provisioned: {exc}") from exc

    config_path = pack_dir / "pyannote_diarization_config.yaml"
    progress(95.0, "Running offline speaker diarization...")
    current_dir = Path.cwd()
    try:
        # pyannote 3.1 resolves relative model paths against the process CWD.
        os.chdir(pack_dir)
        pipeline = PyaPipeline.from_pretrained(str(config_path))
        diarization = pipeline(str(audio_path))
    finally:
        os.chdir(current_dir)
    assign_speakers(segments, diarization_turns(diarization))


# ---------------------------------------------------------------------------
# Transcription with faster-whisper
# ---------------------------------------------------------------------------

def transcribe_faster(
    audio_path: Path,
    model_name: str,
    language: str | None,
    word_timestamps: bool,
    model_dir: Path | None,
    total_duration: float,
    batch_size: int = 1,
) -> list[dict]:
    enforce_offline()
    from faster_whisper import WhisperModel  # type: ignore

    progress(5.0, f"Loading {model_name} model...")
    log(f"Using faster-whisper model: {model_name}")

    download_root = str(model_dir) if model_dir else None
    model = WhisperModel(
        model_name, download_root=download_root, local_files_only=True,
        device="auto", compute_type="auto")

    progress(10.0, "Transcribing...")
    start = time.time()
    all_segments: list[dict] = []

    transcribe_kwargs: dict = {"word_timestamps": word_timestamps}
    if language:
        transcribe_kwargs["language"] = language
    if getattr(model, "_ucx_use_vad", False):
        transcribe_kwargs["vad_filter"] = True
        transcribe_kwargs["vad_parameters"] = {"min_silence_duration_ms": 500}

    # faster-whisper >=1.1 ships BatchedInferencePipeline (~4x throughput on
    # long-form audio). Fall back to the streaming path if the host has
    # an older version pinned, or if BatchedInferencePipeline raises (some
    # CPU-only builds reject batch>1).
    pipeline = None
    if batch_size > 1:
        try:
            from faster_whisper import BatchedInferencePipeline  # type: ignore
            pipeline = BatchedInferencePipeline(model=model)
            log(f"Using BatchedInferencePipeline (batch_size={batch_size})")
        except ImportError:
            log("faster-whisper <1.1 detected; batched inference unavailable, falling back to sequential.", "warn")
            pipeline = None
        except Exception as ex:
            log(f"BatchedInferencePipeline init failed ({ex}); falling back to sequential.", "warn")
            pipeline = None

    try:
        if pipeline is not None:
            result_segments, info = pipeline.transcribe(
                str(audio_path), batch_size=batch_size, **transcribe_kwargs)
        else:
            result_segments, info = model.transcribe(str(audio_path), **transcribe_kwargs)
    except TypeError as ex:
        # Older faster-whisper rejects unknown kwargs — retry without batch_size.
        log(f"transcribe rejected kwargs ({ex}); retrying sequential.", "warn")
        result_segments, info = model.transcribe(str(audio_path), **transcribe_kwargs)

    for seg in result_segments:
        seg_dict = {"start": seg.start, "end": seg.end, "text": seg.text}
        all_segments.append(seg_dict)

        # Estimate progress from segment end time vs duration
        if total_duration > 0:
            pct = 10.0 + 85.0 * min(seg.end / total_duration, 1.0)
            elapsed = time.time() - start
            eta = int(elapsed / (pct / 100.0) * (1 - pct / 100.0)) if pct > 0 else -1
            progress(pct, f"{seg.end:.1f}s / {total_duration:.1f}s transcribed", eta)

    return all_segments


# ---------------------------------------------------------------------------
# Transcription with openai-whisper
# ---------------------------------------------------------------------------

def transcribe_openai(
    audio_path: Path,
    model_name: str,
    language: str | None,
    word_timestamps: bool,
    model_dir: Path | None,
) -> list[dict]:
    enforce_offline()
    import whisper  # type: ignore

    progress(5.0, f"Loading {model_name} model...")
    log(f"Using openai-whisper model: {model_name}")

    root = model_dir or Path.home() / ".cache" / "whisper"
    model_path = root / f"{model_name}.pt"
    if not model_path.is_file():
        raise FileNotFoundError(
            f"Local OpenAI Whisper model is not installed: {model_path}. Automatic downloads are disabled.")
    model = whisper.load_model(str(model_path), download_root=str(root))

    progress(10.0, "Transcribing...")
    transcribe_kwargs: dict = {"verbose": False, "word_timestamps": word_timestamps}
    if language:
        transcribe_kwargs["language"] = language

    result = model.transcribe(str(audio_path), **transcribe_kwargs)

    all_segments: list[dict] = []
    segments = result.get("segments", [])
    n = len(segments)
    for i, seg in enumerate(segments):
        seg_dict = {"start": seg["start"], "end": seg["end"], "text": seg["text"]}
        all_segments.append(seg_dict)
        pct = 10.0 + 85.0 * (i + 1) / max(n, 1)
        progress(pct, f"Segment {i + 1}/{n}")

    return all_segments


# ---------------------------------------------------------------------------
# Duration probe (via ffprobe if available)
# ---------------------------------------------------------------------------

def probe_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="UCX Whisper STT sidecar")
    parser.add_argument(
        "command", nargs="?", choices=("model-status", "download-model"),
        help="Manage the explicit offline diarization model pack.",
    )
    parser.add_argument("--input", help="Input audio/video file")
    parser.add_argument("--output", help="Output transcript file (.srt/.txt/.vtt/.json)")
    parser.add_argument("--model", default="large-v3-turbo",
                        choices=[
                            # Multilingual base
                            "tiny", "base", "small", "medium",
                            "large", "large-v2", "large-v3",
                            # 2024-10: Whisper Large v3 Turbo (8x faster than v3, ~minimal quality loss)
                            "large-v3-turbo",
                            # Distil-Whisper (HF, 6x faster than v3, English-mostly)
                            "distil-large-v3", "distil-large-v2",
                            "distil-medium.en", "distil-small.en",
                        ],
                        help="Whisper model size. Recommended: large-v3-turbo (best speed/quality, multilingual)")
    parser.add_argument("--language", default="auto",
                        help="Language code (auto, en, es, fr, de, ja, zh, pt ...)")
    parser.add_argument("--format", default="srt",
                        choices=["srt", "txt", "vtt", "json"],
                        help="Output format")
    parser.add_argument("--word-timestamps", action="store_true",
                        help="Enable word-level timestamps")
    parser.add_argument("--model-dir", default=None,
                        help="Directory for cached model weights")
    parser.add_argument("--diarization-model-dir", default=None,
                        help="Directory for the verified offline diarization pack")
    parser.add_argument("--vad", action="store_true",
                        help="Use Silero VAD to skip silence (faster + cleaner segments)")
    parser.add_argument("--diarize", action="store_true",
                        help="Opt-in offline speaker labels from the installed pyannote 3.1 pack")
    parser.add_argument("--accept-license", action="store_true",
                        help="Confirm the pyannote model terms for the explicit download command")
    parser.add_argument("--batch-size", type=int, default=8,
                        help="Batched inference size (faster-whisper>=1.1; ~4x throughput on long-form GPU audio). "
                             "Set to 1 to force sequential streaming.")
    args = parser.parse_args()

    if args.command == "model-status":
        pack_dir = resolve_pack_dir(args.diarization_model_dir)
        ready, reason = validate_pack(pack_dir)
        emit({
            "event": "model",
            "name": PACK_ID,
            "path": str(pack_dir),
            "ready": ready,
            "license": PACK_LICENSE,
            "terms_url": PACK_TERMS_URL,
        })
        if not ready:
            error_exit("model_not_installed", f"Offline diarization pack is not ready: {reason}")
        emit({"event": "complete", "output": str(pack_dir)})
        return

    if args.command == "download-model":
        if not args.accept_license:
            error_exit(
                "license_acceptance_required",
                f"Accept the {PACK_LICENSE} terms at {PACK_TERMS_URL} before downloading the gated model pack.",
            )
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        if not token:
            error_exit(
                "credentials_required",
                "A Hugging Face access token is required only for the explicit model download. "
                "Set HF_TOKEN after accepting the model terms, then retry.",
            )
        try:
            emit({"event": "progress", "percent": 1.0, "stage": "Downloading pinned diarization pack...", "eta_seconds": -1})
            download_pack(resolve_pack_dir(args.diarization_model_dir), token)
        except ImportError as exc:
            error_exit("missing_dep", f"huggingface-hub is required for model download: {exc}")
        except Exception as exc:
            error_exit("model_download_failed", str(exc))
        pack_dir = resolve_pack_dir(args.diarization_model_dir)
        emit({"event": "progress", "percent": 100.0, "stage": "Offline diarization pack ready", "eta_seconds": 0})
        emit({"event": "complete", "output": str(pack_dir)})
        return

    if not args.input or not args.output:
        parser.error("--input and --output are required for transcription")

    model_dir_env = os.environ.get("UCX_MODEL_DIR")
    model_dir = Path(args.model_dir) if args.model_dir else (
        Path(model_dir_env) if model_dir_env else None
    )

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        error_exit("input_not_found", f"Input file not found: {input_path}")

    language = resolve_language(args.language)
    log(f"Input: {input_path.name}  Model: {args.model}  Language: {language or 'auto'}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Duration for progress estimation
    total_duration = probe_duration(input_path)

    # Apply the network guard before importing any inference backend. The
    # diarization pack is validated and loaded locally after this point.
    enforce_offline()
    backend = bootstrap()
    log(f"Backend: {backend}")
    progress(2.0, "Initializing...")

    try:
        if backend == "faster-whisper":
            # Stash VAD flag where transcribe_faster can read it.
            from faster_whisper import WhisperModel  # type: ignore
            _orig_init = WhisperModel.__init__
            def _patched_init(self_, *a, **kw):
                _orig_init(self_, *a, **kw)
                self_._ucx_use_vad = bool(args.vad)
            WhisperModel.__init__ = _patched_init  # type: ignore[assignment]
            segments = transcribe_faster(
                input_path, args.model, language,
                args.word_timestamps, model_dir, total_duration,
                batch_size=max(1, args.batch_size),
            )
        else:
            segments = transcribe_openai(
                input_path, args.model, language,
                args.word_timestamps, model_dir,
            )

        # Optional, governed speaker diarization from the local pack.
        if args.diarize:
            run_diarization(input_path, segments, resolve_pack_dir(args.diarization_model_dir))
    except Exception as exc:
        error_exit("transcription_failed", str(exc))
        return

    for seg in segments:
        event = {
            "event": "segment",
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"].strip(),
        }
        if seg.get("speaker"):
            event["speaker"] = seg["speaker"]
        emit(event)

    # Write output
    progress(97.0, "Writing transcript...")
    fmt = args.format
    if fmt == "srt":
        text = segments_to_srt(segments)
    elif fmt == "vtt":
        text = segments_to_vtt(segments)
    elif fmt == "json":
        text = segments_to_json(segments)
    else:
        text = segments_to_txt(segments)

    output_path.write_text(text, encoding="utf-8")
    log(f"Wrote {len(segments)} segments to {output_path.name}")

    progress(100.0, "Done")
    emit({"event": "complete", "output": str(output_path)})


if __name__ == "__main__":
    main()
