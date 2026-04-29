"""QThread — drives core.encode.run with progress + log signals."""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from core.encode import EncodeJob, run as encode_run

from . import WORKER_CANCELLED_MSG


class EncodeWorker(QThread):
    progress = pyqtSignal(float)   # 0..1
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(str)  # output path
    failed = pyqtSignal(str)

    def __init__(self, job: EncodeJob) -> None:
        super().__init__()
        self._job = job
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            rc = encode_run(
                self._job,
                on_progress=self.progress.emit,
                on_log=self.log.emit,
                cancel_cb=lambda: self._cancel,
            )
            if self._cancel:
                self._unlink_partial()
                self.failed.emit(WORKER_CANCELLED_MSG)
            elif rc == 0:
                self.finished_ok.emit(str(self._job.out_path))
            else:
                self._unlink_partial()
                self.failed.emit(f"FFmpeg exited {rc}")
        except Exception as e:
            self._unlink_partial()
            self.failed.emit(f"{type(e).__name__}: {e}")

    def _unlink_partial(self) -> None:
        """Scrub the half-written output file so the user doesn't end up
        with a truncated orphan (often hundreds of MB) alongside their
        real exports. The pycaps swap path already does this for its
        temp sibling; this brings the main encode path to parity.
        """
        try:
            self._job.out_path.unlink(missing_ok=True)
        except Exception:
            pass
