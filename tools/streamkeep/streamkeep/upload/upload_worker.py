"""UploadWorker — background upload thread with progress (F68)."""

from PyQt6.QtCore import QThread, pyqtSignal

from .base import UploadDestination


class UploadWorker(QThread):
    """Run an upload in the background with progress signals."""

    progress = pyqtSignal(int, int)      # bytes_sent, total_bytes
    done = pyqtSignal(bool, str)         # ok, message
    log = pyqtSignal(str)

    def __init__(self, adapter_name, config, file_path, metadata=None):
        super().__init__()
        self._adapter_name = adapter_name
        self._config = config
        self._file_path = file_path
        self._metadata = metadata or {}

    def run(self):
        adapters = UploadDestination.all_adapters()
        cls = adapters.get(self._adapter_name)
        if not cls:
            self.done.emit(False, f"Unknown adapter: {self._adapter_name}")
            return

        try:
            dest = cls(self._config)
            self.log.emit(f"[UPLOAD] Starting {self._adapter_name}: {self._file_path}")

            def _progress(sent, total):
                self.progress.emit(sent, total)

            ok, msg = dest.upload(self._file_path, self._metadata, progress_cb=_progress)
        except Exception as e:
            ok, msg = False, f"{self._adapter_name} upload crashed: {e}"
        self.log.emit(f"[UPLOAD] {'OK' if ok else 'FAIL'}: {msg}")
        self.done.emit(ok, msg)
