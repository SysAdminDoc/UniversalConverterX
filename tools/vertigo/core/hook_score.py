"""Hook-energy score — quantify the first-N-second "engagement strength"
of an audio clip without pretending to predict virality.

Inputs are read via FFmpeg so we stay on dependencies already present
(no librosa / silero-vad / torch bloat). The score is a 0–100 number
with an explicit label so downstream UI doesn't over-promise:

    70–100  : strong       (sustained voice, high RMS, no silence gap)
    40–70   : moderate     (some voice + energy, with quiet patches)
    0–40    : weak         (mostly silence or very low energy)

Algorithm — deterministic, explainable, no ML:

    1. Extract first ``window_sec`` of mono 16-bit PCM at 16 kHz via
       ``ffmpeg -t <window_sec> -af loudnorm=disabled -ar 16000 -ac 1``.
    2. Window the samples into 20 ms frames.
    3. Compute per-frame RMS → normalise against a percentile ceiling
       (robust to loud bursts) → ``energy`` in [0, 1].
    4. Voice-activity heuristic per frame: zero-crossing-rate and RMS
       thresholds that correlate with speech. This is the silero-vad
       contract without the torch dep. Coarse but sufficient for a
       0–100 score.
    5. Blend:  ``score = 60·voice_fraction + 40·mean_voiced_energy``.

The resulting number is a *signal*, not a verdict. It pairs best with
the future Tier-3b "segment proposals" panel.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HookScore:
    score: int                # 0–100
    label: str                # "strong" / "moderate" / "weak" / "silent"
    voice_fraction: float     # 0–1, fraction of window classified as voice
    mean_voiced_energy: float # 0–1, mean RMS inside voice frames
    window_sec: float         # size of the analysis window

    def as_badge(self) -> str:
        """Short human-readable form, e.g. '72 · strong'."""
        return f"{self.score} \u00b7 {self.label}"


def score_hook(path: Path, *, window_sec: float = 3.0) -> HookScore:
    """Produce a HookScore for the first `window_sec` of audio.

    Returns a 0-score "silent" result on any failure (no FFmpeg, no
    audio track, decode error) so callers never have to special-case.
    """
    pcm = _extract_pcm(Path(path), window_sec=window_sec)
    if not pcm:
        return HookScore(
            score=0, label="silent",
            voice_fraction=0.0, mean_voiced_energy=0.0,
            window_sec=window_sec,
        )

    samples = _decode_mono_s16le(pcm)
    if not samples:
        return HookScore(
            score=0, label="silent",
            voice_fraction=0.0, mean_voiced_energy=0.0,
            window_sec=window_sec,
        )

    voice_fraction, mean_voiced_energy = _analyse(samples, sample_rate=16000)

    raw = 60.0 * voice_fraction + 40.0 * mean_voiced_energy
    score = int(round(max(0.0, min(100.0, raw))))
    label = _label_for(score)
    return HookScore(
        score=score,
        label=label,
        voice_fraction=float(voice_fraction),
        mean_voiced_energy=float(mean_voiced_energy),
        window_sec=window_sec,
    )


# ---------------------------------------------------------------- extraction

def _extract_pcm(path: Path, *, window_sec: float) -> bytes:
    """Grab the first `window_sec` of audio as mono 16-bit PCM at 16 kHz."""
    if not path.exists():
        return b""
    bin_path = shutil.which("ffmpeg")
    if not bin_path:
        return b""

    cmd = [
        bin_path, "-hide_banner", "-nostats", "-loglevel", "error",
        "-ss", "0", "-t", f"{max(0.1, float(window_sec)):.3f}",
        "-i", str(path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "s16le",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
            creationflags=_no_window_flags(),
        )
    except Exception:
        return b""
    return proc.stdout or b""


def _decode_mono_s16le(raw: bytes) -> list[int]:
    """Decode an s16le byte stream into a list of signed 16-bit samples.

    An odd-length buffer drops the trailing byte — libavcodec's s16le
    pipe output should never emit a partial sample (each sample is two
    bytes, aligned at the container edge) so this branch is effectively
    defensive: we prefer losing a half-sample over raising in the
    analysis path.
    """
    if not raw:
        return []
    n = len(raw) // 2
    if n == 0:
        return []
    return list(struct.unpack(f"<{n}h", raw[: n * 2]))


# ---------------------------------------------------------------- analysis

def _analyse(samples: list[int], *, sample_rate: int) -> tuple[float, float]:
    """Return (voice_fraction, mean_voiced_energy), both 0–1."""
    if not samples or sample_rate <= 0:
        return 0.0, 0.0

    frame_len = max(1, int(sample_rate * 0.020))  # 20 ms frames

    total_frames = len(samples) // frame_len
    if total_frames == 0:
        return 0.0, 0.0

    # Pass 1: RMS + ZCR per frame. We normalise RMS to a 95th-percentile
    # ceiling so a single loud burst doesn't flatten the rest of the
    # window to near-zero.
    rms: list[float] = []
    zcr: list[float] = []
    for i in range(total_frames):
        frame = samples[i * frame_len : (i + 1) * frame_len]
        rms.append(_rms(frame))
        zcr.append(_zcr(frame))

    ceiling = _percentile(rms, 0.95)
    if ceiling <= 0:
        return 0.0, 0.0
    norm_rms = [min(1.0, r / ceiling) for r in rms]

    # Pass 2: per-frame voice heuristic. Speech in the 80–255 Hz vocal
    # band has moderate ZCR (avoids very-low ≈ rumble and very-high ≈
    # hiss) paired with non-trivial RMS. Rough but stable.
    def is_voice(i: int) -> bool:
        return norm_rms[i] > 0.08 and 0.02 <= zcr[i] <= 0.35

    voiced = [i for i in range(total_frames) if is_voice(i)]
    voice_fraction = len(voiced) / total_frames
    mean_voiced_energy = (
        sum(norm_rms[i] for i in voiced) / len(voiced)
        if voiced else 0.0
    )
    return voice_fraction, mean_voiced_energy


def _rms(frame: list[int]) -> float:
    if not frame:
        return 0.0
    acc = 0
    for s in frame:
        acc += s * s
    # 16-bit PCM, normalise by 32768 to land in 0..1
    return (acc / len(frame)) ** 0.5 / 32768.0


def _zcr(frame: list[int]) -> float:
    if len(frame) < 2:
        return 0.0
    changes = 0
    prev = frame[0]
    for s in frame[1:]:
        if (s >= 0) != (prev >= 0):
            changes += 1
        prev = s
    return changes / (len(frame) - 1)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    idx = max(0, min(len(xs) - 1, int(round((len(xs) - 1) * p))))
    return xs[idx]


def _label_for(score: int) -> str:
    if score >= 70:
        return "strong"
    if score >= 40:
        return "moderate"
    if score >= 10:
        return "weak"
    return "silent"


def _no_window_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0
