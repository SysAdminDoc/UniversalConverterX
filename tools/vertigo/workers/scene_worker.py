"""QThread — runs PySceneDetect off the UI thread.

Runs automatically on every clip load so the trim timeline can draw
shot-boundary tick marks and magnet-snap trim handles to real cuts.
Results are cheap (histogram fallback under a second for a 1080 p
clip) so this is safe to run speculatively.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from core.scenes import detect_scenes


class SceneWorker(QThread):
    finished_ok = pyqtSignal(str, list)   # path, list[tuple[float, float]] (start, end)
    failed = pyqtSignal(str)

    def __init__(self, video_path: Path) -> None:
        super().__init__()
        self._path = Path(video_path)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            scenes = detect_scenes(self._path)
            if self._cancel:
                return
            self.finished_ok.emit(str(self._path), scenes)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
