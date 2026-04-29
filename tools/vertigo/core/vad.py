"""Voice-activity detection via Silero VAD (ONNX).

Silero VAD is a tiny (<2 MB) neural model that tags 16 kHz mono audio
frames as speech or non-speech with very low latency. It's used here to
drive two features:

  * ``detect_speech(path)``    → list of ``(start, end)`` speech spans
  * ``plan_tight_trim(...)``   → (low, high) trim bounds that hug the
                                  outer speech edges with configurable
                                  padding, so the user can "tighten" a
                                  clip to speech-only without losing
                                  breath-in / cadence.

Both are exposed as normal functions so UI code doesn't have to learn
the VAD internals. The heavy dependency (``silero-vad`` on PyPI) is
optional — ``is_available()`` reports the current state and
``ensure_installed()`` matches the pattern ``core.subtitles`` uses.

The PCM extract path reuses the same ``ffmpeg -f s16le`` technique as
``core.hook_score`` so we stay on dependencies the product already
depends on.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_SAMPLE_RATE = 16000  # Silero is trained at 16 kHz
_DEFAULT_MIN_SILENCE_SEC = 0.40
_DEFAULT_MIN_SPEECH_SEC = 0.25
_DEFAULT_PAD_SEC = 0.10


@dataclass(frozen=True)
class SpeechSpan:
    start: float  # seconds
    end: float    # seconds

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


# ---------------------------------------------------------------- availability

def is_available() -> bool:
    """True when the silero-vad package is importable."""
    try:
        import silero_vad  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_installed() -> bool:
    """Lazy pip-install of silero-vad; matches core.subtitles pattern."""
    if is_available():
        return True
    from ._lazy import pip_install
    if not pip_install("silero-vad>=5.1"):
        return False
    return is_available()


# ---------------------------------------------------------------- public api

def detect_speech(
    path: Path,
    *,
    min_silence_sec: float = _DEFAULT_MIN_SILENCE_SEC,
    min_speech_sec: float = _DEFAULT_MIN_SPEECH_SEC,
    cancel_cb=None,
) -> list[SpeechSpan]:
    """Return contiguous speech intervals in ``path``.

    Raises ``RuntimeError`` if silero-vad isn't installed — callers
    should guard with ``is_available()`` and offer the user a clear
    install path.
    """
    if not is_available():
        raise RuntimeError(
            "silero-vad is not installed. Install with:\n"
            "    pip install silero-vad"
        )
    pcm = _extract_pcm(Path(path))
    if not pcm:
        return []

    samples = _decode_pcm_f32(pcm)
    if not samples:
        return []
    if cancel_cb and cancel_cb():
        return []

    # Import after availability check so the module loads cleanly in
    # environments without silero-vad for tests / fallback paths.
    from silero_vad import get_speech_timestamps, load_silero_vad
    import numpy as np

    model = load_silero_vad(onnx=True)
    timestamps = get_speech_timestamps(
        np.asarray(samples, dtype=np.float32),
        model,
        sampling_rate=_SAMPLE_RATE,
        min_silence_duration_ms=int(max(0.0, min_silence_sec) * 1000),
        min_speech_duration_ms=int(max(0.0, min_speech_sec) * 1000),
        return_seconds=True,
    )
    return [SpeechSpan(float(ts["start"]), float(ts["end"])) for ts in timestamps]


def plan_tight_trim(
    spans: Iterable[SpeechSpan],
    *,
    duration: float,
    pad_sec: float = _DEFAULT_PAD_SEC,
) -> tuple[float, float] | None:
    """Return (trim_low, trim_high) that hugs the outer speech edges.

    Both ends get padded by ``pad_sec`` so a plosive-like clipping
    artefact doesn't eat the first consonant. Returns ``None`` when
    no speech was detected (caller should keep the existing trim).
    """
    spans = list(spans)
    if not spans:
        return None
    first = spans[0].start - max(0.0, pad_sec)
    last = spans[-1].end + max(0.0, pad_sec)
    first = max(0.0, first)
    last = min(float(duration), last) if duration > 0 else last
    if last <= first:
        return None
    return first, last


def speech_coverage(spans: Iterable[SpeechSpan], duration: float) -> float:
    """Fraction of ``duration`` covered by speech. Useful for a summary
    badge ("clip is 62% speech")."""
    if duration <= 0:
        return 0.0
    total = sum(s.duration for s in spans)
    return max(0.0, min(1.0, total / duration))


# ---------------------------------------------------------------- extraction

def _extract_pcm(path: Path) -> bytes:
    """Decode the whole file as 16 kHz mono float32 PCM via FFmpeg.

    We use f32le (not s16le) because silero-vad expects float input; the
    extra ffmpeg-side conversion is cheaper than doing it in Python.
    """
    if not path.exists():
        return b""
    bin_path = shutil.which("ffmpeg")
    if not bin_path:
        return b""

    cmd = [
        bin_path, "-hide_banner", "-nostats", "-loglevel", "error",
        "-i", str(path),
        "-vn",
        "-ac", "1",
        "-ar", str(_SAMPLE_RATE),
        "-f", "f32le",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=_no_window_flags(),
        )
    except Exception:
        return b""
    return proc.stdout or b""


def _decode_pcm_f32(raw: bytes) -> list[float]:
    """Little-endian float32 PCM → Python list of floats."""
    import struct
    if not raw:
        return []
    n = len(raw) // 4
    if n == 0:
        return []
    return list(struct.unpack(f"<{n}f", raw[: n * 4]))


# ---------------------------------------------------------------- helpers


def _no_window_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0
