"""Animated captions via pycaps — real API wrapper.

pycaps (https://github.com/francozanardi/pycaps, MIT) burns animated
captions directly onto an input video. It does *not* produce a
standalone RGBA overlay — you hand it a source MP4 and a transcript,
it re-encodes the video with subtitles composited on top.

Vertigo integrates pycaps as a post-encode pass:

    1. EncodeWorker produces the reframed / trimmed output the usual
       way (without burning captions, when pycaps is selected).
    2. ``render_composited(source, out, captions, template)`` feeds
       the reframed output + the Whisper transcript back through
       pycaps, which re-encodes with animated subtitles on top.
    3. The result replaces the stage-1 output in-place.

Heavy dep: ``pycaps`` on PyPI. Optional, lazy-imported. ``is_available()``
reports current state; ``ensure_installed()`` does a lazy pip install
matching the rest of the optional-integrations pattern.

Template names below are the *real* ones pycaps ships with (see
https://github.com/francozanardi/pycaps/tree/main/src/pycaps/template/preset).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# Canonical pycaps template names (built-in presets under
# ``src/pycaps/template/preset/``). A subset is exposed to the UI —
# the full list is: classic, default, explosive, fast, hype,
# line-focus, minimalist, model, neo-minimal, retro-gaming, vibrant,
# word-focus. We pick six that span the visual space from clean to
# punchy so the user has meaningful choice without drowning.
TEMPLATE_DEFAULT = "default"
TEMPLATE_HYPE = "hype"
TEMPLATE_MINIMALIST = "minimalist"
TEMPLATE_WORD_FOCUS = "word-focus"
TEMPLATE_EXPLOSIVE = "explosive"
TEMPLATE_VIBRANT = "vibrant"

DEFAULT_TEMPLATE = TEMPLATE_HYPE


# ---------------------------------------------------------------- availability

def is_available() -> bool:
    try:
        import pycaps  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_installed() -> bool:
    if is_available():
        return True
    from ._lazy import pip_install
    if not pip_install("pycaps>=0.2"):
        return False
    return is_available()


# ---------------------------------------------------------------- public api

def available_templates() -> list[str]:
    """Template identifiers safe to pass to ``render_composited``.

    These are a curated subset of pycaps' bundled templates — the ones
    with the clearest visual distinction, suitable for a UI picker.
    Pycaps itself ships more; users who want the full set can pass
    any template name that lives under ``src/pycaps/template/preset/``
    in the installed package.
    """
    return [
        TEMPLATE_DEFAULT,
        TEMPLATE_HYPE,
        TEMPLATE_MINIMALIST,
        TEMPLATE_WORD_FOCUS,
        TEMPLATE_EXPLOSIVE,
        TEMPLATE_VIBRANT,
    ]


def render_composited(
    source_video: Path,
    out_path: Path,
    captions: list,                 # list[core.subtitles.Caption]
    *,
    template: str = DEFAULT_TEMPLATE,
    cancel_cb=None,
) -> Path:
    """Run pycaps on ``source_video`` with the given transcript and
    write an animated-caption-burned MP4 at ``out_path``.

    ``captions`` is Vertigo's ``core.subtitles.Caption`` list. We
    convert it to whisper-shape JSON (which pycaps accepts via
    ``with_transcription(...)``) so pycaps uses our existing Whisper
    output instead of running its own.

    Raises ``RuntimeError`` when pycaps isn't importable. Callers
    should guard with ``is_available()`` and offer the user a clear
    install path.
    """
    if not is_available():
        raise RuntimeError(
            "pycaps is not installed. Install with:\n"
            "    pip install pycaps"
        )
    if template not in available_templates():
        # Permissive: accept any string (pycaps has more templates than
        # we expose in the curated list), just log through the usual
        # channels when caller supplied something we can't vet.
        pass
    if cancel_cb and cancel_cb():
        raise RuntimeError("Cancelled.")

    # Lazy import — matches the rest of the optional modules.
    from pycaps import CapsPipelineBuilder, TemplateLoader

    # Ensure the output directory exists so pycaps's writer doesn't
    # crash on a missing parent.
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # pycaps expects a Whisper-JSON-shape dict when a transcript is
    # supplied. The crucial detail: per-word entries use ``word`` as
    # the key (not ``text``), and times are floats in seconds.
    transcript = _captions_to_whisper_json(captions)

    builder = (
        TemplateLoader(template)
        .with_input_video(str(source_video))
        .load(False)  # don't auto-apply the template yet; wire the rest first
    )
    builder = (
        builder
        .with_output_video(str(out_path))
        .with_transcription(transcript, format="whisper_json")
    )
    if cancel_cb and cancel_cb():
        raise RuntimeError("Cancelled.")

    pipeline = builder.build()
    pipeline.run()

    if cancel_cb and cancel_cb():
        # pycaps doesn't expose a cancel hook — best we can do is
        # surface a failure so the caller doesn't swap the output file
        # into place. The partial MP4 at out_path is left on disk and
        # the worker is expected to unlink it.
        raise RuntimeError("Cancelled.")
    return Path(out_path)


# ---------------------------------------------------------------- helpers

def _captions_to_whisper_json(captions: Iterable) -> dict:
    """Convert Vertigo ``Caption`` records to the whisper-json shape
    pycaps accepts via ``with_transcription(format='whisper_json')``.

    Whisper-json segments look like::

        {
          "segments": [
            {
              "start": 0.0, "end": 3.4, "text": "...",
              "words": [{"word": "hi", "start": 0.0, "end": 0.2}, ...]
            },
            ...
          ]
        }

    Vertigo's Caption uses ``text`` for the word body; pycaps expects
    ``word``. We rename the key here so the pycaps ingestion doesn't
    silently fall back to an empty word list.
    """
    segments: list[dict] = []
    for cap in captions:
        if not getattr(cap, "text", "").strip():
            continue
        words = []
        for w in getattr(cap, "words", ()) or ():
            body = (getattr(w, "text", "") or "").strip()
            if not body:
                continue
            words.append({
                "word": body,
                "start": float(getattr(w, "start", 0.0) or 0.0),
                "end": float(getattr(w, "end", 0.0) or 0.0),
            })
        seg: dict = {
            "start": float(cap.start),
            "end": float(cap.end),
            "text": cap.text,
        }
        if words:
            seg["words"] = words
        segments.append(seg)
    return {"segments": segments}


