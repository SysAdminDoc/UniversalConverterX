"""QThread — runs Silero voice-activity detection off the UI thread.

Thin wrapper around ``core.vad.detect_speech`` + ``plan_tight_trim``.
Emits the proposed ``(trim_low, trim_high)`` so the controller can
apply it to the active player + trim slider without blocking Qt.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from . import WORKER_CANCELLED_MSG


class VadWorker(QThread):
    # trim_ready(low_sec, high_sec, coverage_0_to_1)
    trim_ready = pyqtSignal(float, float, float)
    failed = pyqtSignal(str)

    def __init__(
        self,
        video_path: Path,
        duration_sec: float,
        *,
        pad_sec: float = 0.10,
        min_silence_sec: float = 0.40,
        min_speech_sec: float = 0.25,
    ) -> None:
        super().__init__()
        self._path = Path(video_path)
        self._duration = float(duration_sec)
        self._pad_sec = pad_sec
        self._min_silence_sec = min_silence_sec
        self._min_speech_sec = min_speech_sec
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            from core import vad

            spans = vad.detect_speech(
                self._path,
                min_silence_sec=self._min_silence_sec,
                min_speech_sec=self._min_speech_sec,
                cancel_cb=lambda: self._cancel,
            )
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
                return
            if not spans:
                self.failed.emit(
                    "No speech detected. The clip looks silent or music-only."
                )
                return

            trim = vad.plan_tight_trim(
                spans, duration=self._duration, pad_sec=self._pad_sec
            )
            if trim is None:
                self.failed.emit("Speech spans did not yield a usable trim.")
                return

            coverage = vad.speech_coverage(spans, self._duration)
            self.trim_ready.emit(trim[0], trim[1], coverage)
        except Exception as e:
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
            else:
                self.failed.emit(f"{type(e).__name__}: {e}")
