"""QThread — runs the pycaps animated-caption post-encode pass off the UI.

pycaps re-encodes the reframed output through its own FFmpeg pipeline
to composite animated captions on top. That's a full video re-encode
and can take minutes on long clips, so it must not run on the Qt GUI
thread. This worker is a thin wrapper around
``core.animated_captions.render_composited`` with cancellation
cooperation and a stable signal surface matching the other post-encode
workers.

Signals
-------
finished_ok(str)
    Path to the freshly-composited MP4 (caller swaps it into place).
failed(str)
    Human-readable error. The sentinel ``WORKER_CANCELLED_MSG``
    (currently ``"Cancelled."``) is reserved for user-triggered
    cancel so the controller can suppress the toast on that path.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from . import WORKER_CANCELLED_MSG


class PycapsWorker(QThread):
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        source_video: Path,
        out_path: Path,
        captions: list,
        *,
        template: str,
    ) -> None:
        super().__init__()
        self._source = Path(source_video)
        self._out = Path(out_path)
        self._captions = list(captions)
        self._template = template
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            from core import animated_captions

            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
                return
            animated_captions.render_composited(
                self._source,
                self._out,
                self._captions,
                template=self._template,
                cancel_cb=lambda: self._cancel,
            )
            if self._cancel:
                # render_composited completes the FFmpeg pass before the
                # final cancel check fires — unlink the partial output
                # so the controller never swaps a half-baked file into
                # place.
                try:
                    self._out.unlink(missing_ok=True)
                except Exception:
                    pass
                self.failed.emit(WORKER_CANCELLED_MSG)
                return
            self.finished_ok.emit(str(self._out))
        except Exception as e:
            if self._cancel:
                self.failed.emit(WORKER_CANCELLED_MSG)
            else:
                self.failed.emit(f"{type(e).__name__}: {e}")
