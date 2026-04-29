"""QThread that runs faster-whisper off the UI thread.

Output format is selected by the active caption preset:

  * preset.animation == "karaoke" with word-level timings → .ass with
    \\kf per-word sweep tags
  * anything else → .srt (libass applies force_style at burn-in time)

When an animated pycaps style is active (signalled by the controller
via the ``force_word_level`` kwarg), the worker guarantees word-level
Whisper output so the post-encode pycaps pass has the timings it needs.
The pycaps render itself lives in the controller's post-encode step,
not here — pycaps re-encodes the finished export rather than producing
an RGBA overlay.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from core.caption_styles import CaptionPreset, default_preset
from core.subtitles import DEFAULT_MODEL, transcribe_and_write

from . import WORKER_CANCELLED_MSG


class SubtitleWorker(QThread):
    progress = pyqtSignal(float)           # 0..1
    status = pyqtSignal(str)               # log line
    finished_ok = pyqtSignal(str)          # final subtitle file path
    captions_ready = pyqtSignal(object)    # list[Caption] — for pycaps post-pass
    failed = pyqtSignal(str)

    def __init__(
        self,
        source: Path,
        out_dir: Path,
        *,
        preset: CaptionPreset | None = None,
        height_px: int = 1920,
        model_name: str = DEFAULT_MODEL,
        language: str | None = None,
        face_aware: bool = False,
        letterbox: bool = False,
        force_word_level: bool = False,
    ) -> None:
        super().__init__()
        self._source = Path(source)
        self._out_dir = Path(out_dir)
        self._preset = preset or default_preset()
        self._height = height_px
        self._model = model_name
        self._language = language
        self._face_aware = face_aware
        self._letterbox = letterbox
        self._force_word_level = force_word_level
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            face_note = "  \u00b7  face-aware layout" if self._face_aware and not self._letterbox else ""
            word_note = (
                "  \u00b7  word-level timings" if self._force_word_level else ""
            )
            self.status.emit(
                f"Loading faster-whisper ({self._model}) \u2014 "
                f"{self._preset.label} preset{face_note}{word_note}"
            )
            if self._face_aware and not self._letterbox:
                self.status.emit("Sampling faces for caption placement\u2026")

            result = transcribe_and_write(
                self._source,
                self._out_dir,
                preset=self._preset,
                height_px=self._height,
                model_name=self._model,
                language=self._language,
                face_aware=self._face_aware,
                letterbox=self._letterbox,
                force_word_level=self._force_word_level,
                progress_cb=self.progress.emit,
                cancel_cb=lambda: self._cancel,
            )
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
                return
            # Hand the caption list out so the controller can cache it
            # for a post-encode pycaps pass without re-running Whisper.
            self.captions_ready.emit(list(result.captions))
            self.finished_ok.emit(str(result.path))
        except Exception as e:
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
            else:
                self.failed.emit(f"{type(e).__name__}: {e}")
