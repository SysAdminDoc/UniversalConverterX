"""Audio diarization — who spoke when.

pyannote.audio (https://github.com/pyannote/pyannote-audio, MIT) is the
reference open-source speaker-diarization stack. Given a clip it returns
``(start, end, speaker_label)`` tuples; combined with face tracks we
can pick which visible speaker to frame at any moment ("follow the
voice" instead of "follow the largest box").

This module is intentionally small:

  * ``diarize(path)`` → ``list[SpeakerSegment]`` in timeline order
  * ``align_to_faces(segments, face_track)`` → fused map that the
    crop planner can use to bias the active-speaker choice

The heavy model download happens on first use of
``pyannote/speaker-diarization-3.1``; the repo card requires accepting
its terms on HuggingFace and providing a ``HF_TOKEN``. We surface that
as a clear error message rather than a silent failure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SpeakerSegment:
    start: float
    end: float
    speaker: str  # pyannote assigns labels like "SPEAKER_00"

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


# ---------------------------------------------------------------- availability

def is_available() -> bool:
    try:
        import pyannote.audio  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_installed() -> bool:
    if is_available():
        return True
    from ._lazy import pip_install
    if not pip_install("pyannote.audio>=3.3"):
        return False
    return is_available()


def has_hf_token() -> bool:
    """Most pyannote models require a HuggingFace access token at
    runtime. We surface the check so callers can prompt the user before
    invoking the heavy pipeline."""
    return bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN"))


# ---------------------------------------------------------------- public api

def diarize(
    path: Path,
    *,
    hf_token: str | None = None,
    num_speakers: int | None = None,
    cancel_cb=None,
) -> list[SpeakerSegment]:
    """Run speaker diarization and return per-speaker time ranges.

    Raises ``RuntimeError`` when pyannote isn't installed or when no
    HuggingFace token is configured — this keeps the error surface
    close to the failure instead of crashing during model load.

    ``num_speakers`` can pin the expected count; leave None to let the
    pipeline infer it.
    """
    if not is_available():
        raise RuntimeError(
            "pyannote.audio is not installed. Install with:\n"
            "    pip install pyannote.audio"
        )
    token = hf_token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")
    if not token:
        raise RuntimeError(
            "pyannote requires a HuggingFace access token. Get one from "
            "https://huggingface.co/settings/tokens and set HF_TOKEN in "
            "the environment, or pass hf_token= to diarize()."
        )
    if cancel_cb and cancel_cb():
        return []

    from pyannote.audio import Pipeline  # lazy

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=token,
    )
    if pipeline is None:
        raise RuntimeError(
            "pyannote returned no pipeline — check the HF terms for "
            "pyannote/speaker-diarization-3.1 have been accepted."
        )

    kwargs: dict = {}
    if num_speakers is not None:
        kwargs["num_speakers"] = int(num_speakers)

    annotation = pipeline(str(path), **kwargs)
    segments: list[SpeakerSegment] = []
    for turn, _, label in annotation.itertracks(yield_label=True):
        segments.append(
            SpeakerSegment(
                start=float(turn.start),
                end=float(turn.end),
                speaker=str(label),
            )
        )
    segments.sort(key=lambda s: s.start)
    return segments


def align_to_faces(
    segments: list[SpeakerSegment],
    face_track,  # list[core.detect.TrackPoint]
    *,
    tolerance_sec: float = 0.25,
) -> dict[str, list[int]]:
    """Heuristic audio-visual fusion.

    For each ``SpeakerSegment``, find the face-track point whose time
    falls inside it (±tolerance). We don't claim to match faces to
    speakers — that requires cross-modal embeddings. Instead we return
    a dict mapping ``speaker_label`` → list of ``TrackPoint`` indices
    that likely overlap in time, which the crop planner can use to
    "bias toward the face that's speaking right now".

    The crop planner then picks, at export time, the face-track index
    whose normalised x most closely tracks the currently-speaking
    ``speaker_label``.
    """
    lookup: dict[str, list[int]] = {}
    if not segments or not face_track:
        return lookup
    pts = list(face_track)
    for seg in segments:
        lo = seg.start - max(0.0, tolerance_sec)
        hi = seg.end + max(0.0, tolerance_sec)
        hits = [i for i, p in enumerate(pts) if lo <= p.t <= hi]
        if hits:
            lookup.setdefault(seg.speaker, []).extend(hits)
    return lookup


