"""Caption / Word dataclasses without the transcoder import weight.

`core/subtitles.py` used to own these types, but it also pulls in
`caption_layout`, `caption_styles`, and `face_samples` — a fine set of
transitive imports for the full transcription pipeline, a waste for
callers that only want the dataclass shape (segment proposals,
downstream analysis, tests).

Both names are re-exported from `core.subtitles` so existing callers
keep working unchanged. New callers should import from here.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Word:
    """A single Whisper-emitted word with tight start/end timings."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Caption:
    """A caption segment with optional per-word timings.

    ``words`` is empty when word-level timestamps were not requested
    (non-karaoke presets). Downstream renderers (karaoke ASS, pycaps,
    segment proposals) take the tuple unchanged.
    """

    start: float
    end: float
    text: str
    words: tuple[Word, ...] = field(default_factory=tuple)
