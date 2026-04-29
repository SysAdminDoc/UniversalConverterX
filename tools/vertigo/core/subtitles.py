"""Subtitle generation via faster-whisper.

`faster-whisper` is a heavy dependency (~200 MB incl. CTranslate2 runtime),
so we keep it **opt-in**: it is not in the bootstrap list; the first call
to `transcribe_to_file()` will pip-install it on demand.

Output format is chosen by the active caption preset:

    * animation="none" / "pop"    → .srt            (libass styles it)
    * animation="karaoke"         → .ass with \\kf  (per-word sweep)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .caption_layout import ALIGN_BOTTOM_CENTER, ALIGN_TOP_CENTER, plan_alignments
from .caption_styles import CaptionPreset, default_preset, style_for_height
from .caption_types import Caption, Word  # re-exported for binary compat
from .face_samples import FaceSample, sample_faces


DEFAULT_MODEL = "small"
AVAILABLE_MODELS = ("tiny", "base", "small", "medium", "large-v3")

__all__ = [
    "AVAILABLE_MODELS",
    "Caption",
    "DEFAULT_MODEL",
    "TranscribeResult",
    "Word",
    "ensure_installed",
    "is_installed",
    "transcribe",
    "transcribe_and_write",
    "transcribe_to_file",
    "transcribe_to_srt",
    "write_ass",
    "write_srt",
]


def is_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_installed() -> bool:
    """Return True if faster-whisper is importable. Attempts lazy install."""
    if is_installed():
        return True
    from ._lazy import pip_install
    if not pip_install("faster-whisper>=1.0.3"):
        return False
    return is_installed()


def transcribe(
    source: Path,
    *,
    model_name: str = DEFAULT_MODEL,
    language: str | None = None,
    word_level: bool = False,
    progress_cb=None,
    cancel_cb=None,
) -> list[Caption]:
    """Run faster-whisper. Set `word_level=True` to capture per-word timings."""
    if not ensure_installed():
        raise RuntimeError("faster-whisper is not installed and could not be auto-installed.")

    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="auto", compute_type="auto")
    segments_iter, info = model.transcribe(
        str(source),
        language=language,
        vad_filter=True,
        word_timestamps=word_level,
    )
    total = max(1e-6, float(info.duration or 0.0))

    out: list[Caption] = []
    for seg in segments_iter:
        if cancel_cb and cancel_cb():
            break
        words: tuple[Word, ...] = ()
        if word_level and getattr(seg, "words", None):
            words = tuple(
                Word(
                    start=float(w.start or 0.0),
                    end=float(w.end or 0.0),
                    text=(w.word or "").strip(),
                )
                for w in seg.words
                if (w.word or "").strip()
            )
        out.append(
            Caption(
                start=float(seg.start or 0.0),
                end=float(seg.end or 0.0),
                text=(seg.text or "").strip(),
                words=words,
            )
        )
        if progress_cb:
            progress_cb(min(1.0, (seg.end or 0.0) / total))
    if progress_cb:
        progress_cb(1.0)
    return out


# ---------------------------------------------------------- writers

def write_srt(captions: list[Caption], out_path: Path) -> Path:
    lines: list[str] = []
    for i, c in enumerate(captions, start=1):
        if not c.text:
            continue
        lines.append(str(i))
        lines.append(f"{_fmt_srt(c.start)} --> {_fmt_srt(c.end)}")
        lines.append(_wrap(c.text))
        lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_ass(
    captions: list[Caption],
    out_path: Path,
    preset: CaptionPreset,
    height_px: int,
    *,
    width_px: int | None = None,
    face_samples: list[FaceSample] | None = None,
    letterbox: bool = False,
) -> Path:
    """Write a styled ASS file.

    When ``preset.animation == "karaoke"`` and per-word timings exist,
    each Dialogue line carries inline ``\\kf<cs>`` sweep tags so libass
    fills words in sync with speech. Falls back to plain dialogue when
    no word-level timings are present.

    If ``face_samples`` is provided, per-chunk alignment is decided by
    ``caption_layout.plan_alignments``: chunks whose time-range overlaps
    a face in the bottom caption zone are flipped to top-center via an
    inline ``{\\an8}`` override. Letterbox reframe is exempt (see the
    caption_layout docstring).
    """
    play_res_x = width_px if width_px else int(round(height_px * 9 / 16))
    play_res_y = height_px

    style = style_for_height(preset, height_px)
    header = _ass_header(style, play_res_x, play_res_y)

    # Build chunks first so we can plan alignments over the exact time ranges.
    chunks: list[tuple[float, float, str, tuple[Word, ...]]] = []
    for cap in captions:
        if not cap.text:
            continue
        cap_chunks = _chunk_words(cap, preset) if preset.animation == "karaoke" and cap.words \
            else [(cap.start, cap.end, cap.text, cap.words)]
        chunks.extend(cap_chunks)

    alignments: list[int]
    if face_samples:
        alignments = plan_alignments(
            preset,
            [(s, e) for (s, e, _t, _w) in chunks],
            face_samples,
            letterbox=letterbox,
        )
    else:
        alignments = [preset.alignment or ALIGN_BOTTOM_CENTER] * len(chunks)

    default_align = preset.alignment or ALIGN_BOTTOM_CENTER
    dialogues: list[str] = []
    for (start, end, text, words), align in zip(chunks, alignments):
        body = _format_body(text, words, preset)
        if align != default_align:
            body = f"{{\\an{align}}}{body}"
        dialogues.append(_ass_dialogue(start, end, body))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(header + "\n".join(dialogues) + "\n", encoding="utf-8")
    return out_path


@dataclass(frozen=True)
class TranscribeResult:
    """What ``transcribe_and_write`` returns.

    ``path`` is the written SRT or ASS file (preserves the previous
    ``transcribe_to_file`` return contract). ``captions`` is the full
    list of transcribed ``Caption`` objects, exposed so callers can
    hand them to a downstream renderer (e.g. pycaps) without running
    Whisper a second time.
    """
    path: Path
    captions: list["Caption"]


def transcribe_to_file(
    source: Path,
    out_dir: Path,
    *,
    preset: CaptionPreset | None = None,
    height_px: int = 1920,
    model_name: str = DEFAULT_MODEL,
    language: str | None = None,
    face_aware: bool = False,
    letterbox: bool = False,
    face_sample_fps: float = 2.0,
    force_word_level: bool = False,
    progress_cb=None,
    cancel_cb=None,
) -> Path:
    """Transcribe `source`, writing the format the preset requires.

    Returns the path to the generated subtitle file (.srt or .ass).
    Callers that also want the parsed caption list (e.g. to hand to
    pycaps) should use :func:`transcribe_and_write` — this function
    is kept with the original return shape for binary compatibility.

    ``force_word_level`` requests word-level Whisper timings even when
    the preset wouldn't normally need them. The animated-caption
    renderer needs per-word timings to produce the per-word sweep.
    """
    return transcribe_and_write(
        source,
        out_dir,
        preset=preset,
        height_px=height_px,
        model_name=model_name,
        language=language,
        face_aware=face_aware,
        letterbox=letterbox,
        face_sample_fps=face_sample_fps,
        force_word_level=force_word_level,
        progress_cb=progress_cb,
        cancel_cb=cancel_cb,
    ).path


def transcribe_and_write(
    source: Path,
    out_dir: Path,
    *,
    preset: CaptionPreset | None = None,
    height_px: int = 1920,
    model_name: str = DEFAULT_MODEL,
    language: str | None = None,
    face_aware: bool = False,
    letterbox: bool = False,
    face_sample_fps: float = 2.0,
    force_word_level: bool = False,
    progress_cb=None,
    cancel_cb=None,
) -> TranscribeResult:
    """Transcribe `source` and return both the written SRT/ASS path and
    the full Caption list so callers can post-process without a second
    Whisper pass.
    """
    preset = preset or default_preset()
    want_words = preset.animation == "karaoke" or bool(force_word_level)

    face_samples: list[FaceSample] | None = None
    if face_aware and not letterbox:
        face_samples = sample_faces(
            source,
            sample_fps=face_sample_fps,
            cancel_cb=cancel_cb,
        )

    captions = transcribe(
        source,
        model_name=model_name,
        language=language,
        word_level=want_words,
        progress_cb=progress_cb,
        cancel_cb=cancel_cb,
    )

    stem = source.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    want_ass = (preset.animation == "karaoke" and any(c.words for c in captions)) or face_aware
    if want_ass:
        path = write_ass(
            captions,
            out_dir / f"{stem}.vertigo.ass",
            preset,
            height_px,
            face_samples=face_samples,
            letterbox=letterbox,
        )
    else:
        # Non-karaoke presets without face-aware use SRT; libass will
        # still apply force_style from the preset at burn-in time.
        path = write_srt(captions, out_dir / f"{stem}.vertigo.srt")
    return TranscribeResult(path=path, captions=captions)


# ---------------------------------------------------------- helpers

def _fmt_srt(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_ass(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    if cs == 100:
        s += 1
        cs = 0
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _wrap(text: str, max_per_line: int = 18) -> str:
    """Soft-wrap at word boundaries for mobile legibility.

    Max two lines per caption (2026 creator-tool consensus).
    """
    text = " ".join(text.split())
    if len(text) <= max_per_line:
        return text
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for w in words:
        if not current:
            current = w
        elif len(current) + 1 + len(w) <= max_per_line:
            current += " " + w
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)
    return "\n".join(lines[:2])


def _chunk_words(cap: Caption, preset: CaptionPreset) -> list[tuple[float, float, str, tuple[Word, ...]]]:
    """Split a caption into ≤ preset.max_words_per_chunk / max_seconds_per_chunk
    groups for karaoke rendering. Returns (start, end, joined_text, words)."""
    if not cap.words:
        return [(cap.start, cap.end, cap.text, ())]

    chunks: list[tuple[float, float, str, tuple[Word, ...]]] = []
    current: list[Word] = []
    first_start = cap.words[0].start

    def _flush() -> None:
        nonlocal current, first_start
        if current:
            text = " ".join(w.text for w in current).strip()
            if text:
                chunks.append((first_start, current[-1].end, text, tuple(current)))
        current = []

    for w in cap.words:
        if not current:
            first_start = w.start
            current.append(w)
            continue
        # close the chunk if it would overflow in words or duration
        duration = w.end - first_start
        if (len(current) >= preset.max_words_per_chunk
                or duration > preset.max_seconds_per_chunk):
            _flush()
            first_start = w.start
            current.append(w)
        else:
            current.append(w)
    _flush()
    return chunks


def _format_body(text: str, words: tuple[Word, ...], preset: CaptionPreset) -> str:
    """Build the inline ASS body.

    Karaoke uses `\\kf<cs>` per word, emitted into a single Dialogue
    line. Non-karaoke presets get plain text with soft-wrapping.
    """
    if preset.animation == "karaoke" and words:
        parts: list[str] = []
        for i, w in enumerate(words):
            cs = max(1, int(round((w.end - w.start) * 100)))
            # Preserve leading spaces between karaoke groups via `\h` hardspace.
            sep = " " if i > 0 else ""
            parts.append(f"{sep}{{\\kf{cs}}}{_escape_ass(w.text)}")
        return "".join(parts)

    # plain text — apply wrapping and escape
    wrapped = _wrap(text, max_per_line=preset.max_chars_per_line)
    return _escape_ass(wrapped).replace("\n", "\\N")


def _escape_ass(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def _ass_header(style: dict, play_res_x: int, play_res_y: int) -> str:
    style_line = (
        "Style: Default,"
        f"{style['FontName']},{style['FontSize']},"
        f"{style['PrimaryColour']},{style['SecondaryColour']},"
        f"{style['OutlineColour']},{style['BackColour']},"
        f"{style['Bold']},{style['Italic']},0,0,100,100,0,0,"
        f"{style['BorderStyle']},{style['Outline']},{style['Shadow']},"
        f"{style['Alignment']},{style['MarginL']},{style['MarginR']},{style['MarginV']},1"
    )
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: None\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style_line}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _ass_dialogue(start: float, end: float, body: str) -> str:
    return f"Dialogue: 0,{_fmt_ass(start)},{_fmt_ass(end)},Default,,0,0,0,,{body}"


# ---------------------------------------------------------- legacy aliases

# Kept for the existing subtitle worker / callers until they move over.
def transcribe_to_srt(
    source: Path,
    out_path: Path,
    *,
    model_name: str = DEFAULT_MODEL,
    language: str | None = None,
    progress_cb=None,
    cancel_cb=None,
) -> Path:
    captions = transcribe(
        source,
        model_name=model_name,
        language=language,
        word_level=False,
        progress_cb=progress_cb,
        cancel_cb=cancel_cb,
    )
    return write_srt(captions, out_path)
