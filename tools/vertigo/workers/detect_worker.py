"""QThread — runs FaceTracker off the UI thread.

When `crop_width_frac` is provided, uses the cameraman-driven pipeline
(`SpeakerTracker` + `SmoothedCameraman`) for multi-face, speaker-sticky
viewport motion. Without it, falls back to the legacy single-largest-
face-per-frame path so callers with no clip geometry still get a track.

Cancel contract (matches SubtitleWorker):
    * ``cancel()`` sets a flag polled by the tracker's cancel_cb.
    * On cancel, we emit ``failed(WORKER_CANCELLED_MSG)`` rather than
      ``finished_ok(partial_points)`` — the main window treats
      finished_ok as an authoritative track and would pass the
      half-finished data to the export pipeline.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from core.detect import FaceTracker

from . import WORKER_CANCELLED_MSG


class DetectWorker(QThread):
    progress = pyqtSignal(float)      # 0..1
    finished_ok = pyqtSignal(list)    # list[TrackPoint]
    failed = pyqtSignal(str)

    def __init__(
        self,
        video_path: Path,
        sample_fps: float = 2.0,
        smoothing: float = 0.6,
        *,
        crop_width_frac: float | None = None,
        use_cluster_filter: bool = True,
    ) -> None:
        super().__init__()
        self._path = Path(video_path)
        self._sample_fps = sample_fps
        self._smoothing = smoothing
        self._crop_width_frac = crop_width_frac
        self._use_cluster_filter = use_cluster_filter
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        tracker = FaceTracker(sample_fps=self._sample_fps, smoothing=self._smoothing)
        try:
            if self._crop_width_frac is not None and 0 < self._crop_width_frac <= 1.0:
                points = tracker.track_with_cameraman(
                    self._path,
                    crop_width_frac=self._crop_width_frac,
                    progress_cb=self.progress.emit,
                    cancel_cb=lambda: self._cancel,
                    use_cluster_filter=self._use_cluster_filter,
                )
            else:
                points = tracker.track(
                    self._path,
                    progress_cb=self.progress.emit,
                    cancel_cb=lambda: self._cancel,
                )
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
                return
            self.finished_ok.emit(points)
        except Exception as e:
            if self._cancel:
                # A cancel racing with a tracker-internal exception should
                # still surface as "Cancelled" so the UI reset path runs.
                self.failed.emit(WORKER_CANCELLED_MSG)
            else:
                self.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            tracker.close()
