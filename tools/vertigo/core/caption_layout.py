"""Face-aware caption layout.

Given sampled face bounding boxes and the dialogue time-ranges that the
caption writer is about to emit, decide per-chunk whether to flip from
the preset's default alignment (bottom-center, ASS code 2) to a safer
position that won't occlude the face (top-center, ASS code 8).

Algorithm (intentionally simple for v1):

    * Build a "caption zone" in normalised source-y coordinates based
      on the preset's `margin_v_fraction` and a conservative two-line
      caption height estimate (~12 % of source height).
    * For each chunk, take all face samples whose `t` lies inside the
      chunk's time range.
    * If ANY sampled face overlaps the caption zone (bbox y_max >=
      zone_top AND bbox y_min <= zone_bottom), tag the chunk for
      top-align. Otherwise keep default.

For `Blur Letterbox` reframe mode the output has letterboxed bars
above/below the source content, and the bottom-of-output caption zone
falls onto the blurred letterbox area — no subject is there, so no
flip is ever needed. Callers should pass `letterbox=True` to
short-circuit the check.
"""

from __future__ import annotations

from typing import Iterable

from .caption_styles import CaptionPreset
from .face_samples import FaceSample, samples_overlapping


# ASS alignment codes (numpad layout).
ALIGN_BOTTOM_CENTER = 2
ALIGN_TOP_CENTER = 8


def caption_zone_norm(preset: CaptionPreset, caption_height_frac: float = 0.12) -> tuple[float, float]:
    """Return `(y_top, y_bottom)` of the caption zone in normalised y.

    `margin_v_fraction` is the distance from the bottom of the frame to
    the caption baseline. A two-line caption is roughly 12 % of height
    in typography-scaled units at the preset's font size.
    """
    zone_bottom = max(0.0, 1.0 - max(0.0, preset.margin_v_fraction))
    zone_top = max(0.0, zone_bottom - caption_height_frac)
    return zone_top, zone_bottom


def chunk_alignment(
    preset: CaptionPreset,
    t_start: float,
    t_end: float,
    samples: list[FaceSample],
    *,
    letterbox: bool = False,
    min_face_area: float = 0.015,
) -> int:
    """Return the ASS alignment code to use for a caption chunk.

    Returns `ALIGN_BOTTOM_CENTER` by default (preset behavior). Flips
    to `ALIGN_TOP_CENTER` only when a detected face overlaps the caption
    zone and would be occluded.

    `min_face_area` filters tiny spurious detections (bbox area as
    fraction of source area).
    """
    default_align = preset.alignment or ALIGN_BOTTOM_CENTER
    if letterbox:
        return default_align
    if default_align != ALIGN_BOTTOM_CENTER:
        # Preset already puts captions at the top — nothing to do.
        return default_align
    if not samples:
        return default_align

    window = samples_overlapping(samples, t_start, t_end)
    if not window:
        return default_align

    zone_top, zone_bottom = caption_zone_norm(preset)
    for sample in window:
        for (_x, y, w, h) in sample.boxes:
            if w * h < min_face_area:
                continue
            face_top, face_bottom = y, y + h
            if face_bottom <= zone_top or face_top >= zone_bottom:
                continue
            return ALIGN_TOP_CENTER
    return default_align


def plan_alignments(
    preset: CaptionPreset,
    chunks: Iterable[tuple[float, float]],
    samples: list[FaceSample],
    *,
    letterbox: bool = False,
) -> list[int]:
    """Vectorised helper — one alignment code per chunk."""
    return [
        chunk_alignment(preset, s, e, samples, letterbox=letterbox)
        for (s, e) in chunks
    ]
