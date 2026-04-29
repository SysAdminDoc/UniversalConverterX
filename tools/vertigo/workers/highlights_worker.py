"""QThread — runs core.highlights.score_spans off the UI thread.

Emits a ranked list of ``Highlight`` records when done. The Lighthouse
path can take seconds on longer clips; the fallback heuristic does one
ffmpeg pass per sliding window and finishes in a second or two. Either
way we keep it off the GUI thread so the scrubber stays responsive.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from . import WORKER_CANCELLED_MSG


class HighlightsWorker(QThread):
    # finished_ok(list[Highlight]) — list may be empty, caller handles.
    finished_ok = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        video_path: Path,
        *,
        query: str | None = None,
        window_sec: float = 3.0,
        top_n: int = 5,
    ) -> None:
        super().__init__()
        self._path = Path(video_path)
        self._query = query
        self._window_sec = window_sec
        self._top_n = top_n
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            from core import highlights

            found = highlights.score_spans(
                self._path,
                query=self._query,
                window_sec=self._window_sec,
                top_n=self._top_n,
                cancel_cb=lambda: self._cancel,
            )
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
                return
            self.finished_ok.emit(list(found))
        except Exception as e:
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
            else:
                self.failed.emit(f"{type(e).__name__}: {e}")
