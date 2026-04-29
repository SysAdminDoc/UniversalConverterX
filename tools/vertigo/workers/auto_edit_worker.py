"""QThread — runs auto-editor off the UI thread.

auto-editor does a full audio-threshold / motion-delta sweep on the
clip and returns the "keep" spans (contiguous sections of the timeline
that survive the cut). This worker is the Qt-side adapter — a thin
wrapper over ``core.auto_edit.plan_cuts``.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from . import WORKER_CANCELLED_MSG


class AutoEditWorker(QThread):
    # finished_ok(list[KeepSpan]) — empty list is a valid "nothing kept".
    finished_ok = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        video_path: Path,
        *,
        threshold: float = 0.04,
        margin_sec: float = 0.2,
        edit_method: str = "audio",
    ) -> None:
        super().__init__()
        self._path = Path(video_path)
        self._threshold = threshold
        self._margin_sec = margin_sec
        self._edit_method = edit_method
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            from core import auto_edit

            spans = auto_edit.plan_cuts(
                self._path,
                threshold=self._threshold,
                margin_sec=self._margin_sec,
                edit_method=self._edit_method,
                cancel_cb=lambda: self._cancel,
            )
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
                return
            self.finished_ok.emit(list(spans))
        except Exception as e:
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
            else:
                self.failed.emit(f"{type(e).__name__}: {e}")
