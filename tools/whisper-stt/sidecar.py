#!/usr/bin/env python3
"""
UCX Whisper STT Sidecar — headless NDJSON wrapper for local Whisper transcription.

Backends tried in order:
  1. faster-whisper (ctranslate2, significantly faster than openai-whisper)
  2. openai-whisper  (reference implementation, slower)
  Both are auto-installed via bootstrap() if missing.

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


def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


def log(message: str, level: str = "info") -> None:
    emit({"event": "log", "level": level, "message": message})


def progress(percent: float, stage: str = "", eta: int = -1) -> None:
    emit({"event": "progress", "percent": round(percent, 1), "stage": stage, "eta_seconds": eta})


def error_exit(code: str, message: str) -> None:
    emit({"event": "error", "code": code, "message": message})
    sys.exit(1)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def _pip_install(*packages: str) -> bool:
    for extra in [[], ["--user"], ["--break-system-packages"]]:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", *packages, *extra],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True
    return False


def bootstrap() -> str:
    """Install faster-whisper or openai-whisper and return which backend was used."""
    # When frozen with PyInstaller, sys.executable is this sidecar exe — a pip
    # install would re-spawn this exe and fork-bomb the host. Bundle deps at
    # build time instead of relying on runtime install.
    if getattr(sys, "frozen", False):
        try:
            import faster_whisper  # noqa: F401
            return "faster-whisper"
        except ImportError:
            pass
        try:
            import whisper  # noqa: F401
            return "openai-whisper"
        except ImportError:
            error_exit("missing_dep",
                       "Neither faster-whisper nor openai-whisper is bundled into "
                       "this frozen sidecar. Rebuild with PyInstaller after "
                       "`pip install faster-whisper`.")

    # Try faster-whisper first
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"
    except ImportError:
        pass

    log("faster-whisper not found — installing...")
    progress(0.5, "Installing faster-whisper...")
    if _pip_install("faster-whisper>=1.0.0"):
        log("faster-whisper installed.")
        return "faster-whisper"

    # Fall back to openai-whisper
    try:
        import whisper  # noqa: F401
        return "openai-whisper"
    except ImportError:
        pass

    log("openai-whisper not found — installing...", "warn")
    progress(0.5, "Installing openai-whisper...")
    if not _pip_install("openai-whisper>=20240930"):
        error_exit("install_failed", "Could not install openai-whisper or faster-whisper.")
    log("openai-whisper installed.")
    return "openai-whisper"


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
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


def segments_to_vtt(segments: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_ts_vtt(seg['start'])} --> {_ts_vtt(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


def segments_to_txt(segments: list[dict]) -> str:
    return "\n".join(seg["text"].strip() for seg in segments)


def segments_to_json(segments: list[dict]) -> str:
    return json.dumps(segments, ensure_ascii=False, indent=2)


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
) -> list[dict]:
    from faster_whisper import WhisperModel  # type: ignore

    progress(5.0, f"Loading {model_name} model...")
    log(f"Using faster-whisper model: {model_name}")

    download_root = str(model_dir) if model_dir else None
    model = WhisperModel(model_name, download_root=download_root,
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

    result_segments, info = model.transcribe(str(audio_path), **transcribe_kwargs)

    for seg in result_segments:
        seg_dict = {"start": seg.start, "end": seg.end, "text": seg.text}
        all_segments.append(seg_dict)
        emit({"event": "segment", "start": seg.start, "end": seg.end, "text": seg.text.strip()})

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
    import whisper  # type: ignore

    progress(5.0, f"Loading {model_name} model...")
    log(f"Using openai-whisper model: {model_name}")

    download_root = str(model_dir) if model_dir else None
    model = whisper.load_model(model_name, download_root=download_root)

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
        emit({"event": "segment", "start": seg["start"], "end": seg["end"], "text": seg["text"].strip()})
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
    parser.add_argument("--input", required=True, help="Input audio/video file")
    parser.add_argument("--output", required=True, help="Output transcript file (.srt/.txt/.vtt/.json)")
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
    parser.add_argument("--vad", action="store_true",
                        help="Use Silero VAD to skip silence (faster + cleaner segments)")
    parser.add_argument("--diarize", action="store_true",
                        help="Speaker diarization via pyannote 3.1 (requires HF token in HF_TOKEN env)")
    args = parser.parse_args()

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
            )
        else:
            segments = transcribe_openai(
                input_path, args.model, language,
                args.word_timestamps, model_dir,
            )

        # Optional speaker diarization via pyannote 3.1.
        if args.diarize:
            try:
                from pyannote.audio import Pipeline as PyaPipeline  # type: ignore
                token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
                if not token:
                    log("Diarization skipped: set HF_TOKEN to use pyannote/speaker-diarization-3.1.", "warn")
                else:
                    progress(95.0, "Running speaker diarization...")
                    pipe = PyaPipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1", use_auth_token=token)
                    diar = pipe(str(input_path))
                    # Assign speaker to each segment by max overlap.
                    for seg in segments:
                        best, best_overlap = None, 0.0
                        for turn, _, speaker in diar.itertracks(yield_label=True):
                            ov = max(0.0, min(turn.end, seg["end"]) - max(turn.start, seg["start"]))
                            if ov > best_overlap:
                                best, best_overlap = speaker, ov
                        if best:
                            seg["speaker"] = best
            except ImportError as ex:
                log(f"Diarization unavailable: {ex}", "warn")
            except Exception as ex:
                log(f"Diarization failed: {ex}", "warn")
    except Exception as exc:
        error_exit("transcription_failed", str(exc))
        return

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
