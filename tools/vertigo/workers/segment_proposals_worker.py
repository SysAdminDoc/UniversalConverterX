"""QThread — runs core.segment_proposals.propose_segments off the UI thread.

Consumes an already-computed caption list (produced by the subtitle
worker). TextTiling + scoring is pure numpy / stdlib and fast enough
to run synchronously, but we keep it on a worker anyway so slider
interaction stays silky on very long clips.
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from . import WORKER_CANCELLED_MSG


class SegmentProposalsWorker(QThread):
    # finished_ok(list[SegmentProposal]) — may be empty; caller decides UX.
    finished_ok = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        captions: list,
        *,
        min_sec: float = 30.0,
        max_sec: float = 90.0,
        target_sec: float = 45.0,
        top_n: int = 8,
    ) -> None:
        super().__init__()
        self._captions = list(captions or [])
        self._min_sec = min_sec
        self._max_sec = max_sec
        self._target_sec = target_sec
        self._top_n = top_n
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            from core.segment_proposals import propose_segments

            proposals = propose_segments(
                self._captions,
                min_sec=self._min_sec,
                max_sec=self._max_sec,
                target_sec=self._target_sec,
                top_n=self._top_n,
                cancel_cb=lambda: self._cancel,
            )
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
                return
            self.finished_ok.emit(list(proposals))
        except Exception as e:
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
            else:
                self.failed.emit(f"{type(e).__name__}: {e}")
