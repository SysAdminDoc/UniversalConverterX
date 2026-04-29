"""Playlist expansion worker — probes a URL for playlist entries via yt-dlp."""

from PyQt6.QtCore import QThread, pyqtSignal

from ..http import http_interruptible
from ..extractors.ytdlp import YtDlpExtractor


class PlaylistExpandWorker(QThread):
    """Probe a URL for playlist entries via yt-dlp --flat-playlist."""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    log = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def _interrupted(self):
        return self.isInterruptionRequested()

    def run(self):
        try:
            with http_interruptible(self._interrupted):
                if self._interrupted():
                    return
                entries = YtDlpExtractor().list_playlist_entries(
                    self.url, log_fn=self.log.emit,
                )
                if self._interrupted():
                    return
                self.finished.emit(entries)
        except Exception as e:
            if not self._interrupted():
                self.error.emit(str(e))
