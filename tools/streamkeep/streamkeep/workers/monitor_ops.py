"""Workers for monitor-side background operations."""

import os
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from ..extractors import Extractor
from ..http import http_interruptible
from ..utils import safe_filename


class SeedArchiveWorker(QThread):
    """Fetch existing VOD sources for a monitored channel off the UI thread."""

    finished = pyqtSignal(str, list)
    error = pyqtSignal(str, str)
    log = pyqtSignal(str)

    def __init__(self, url, channel_id=""):
        super().__init__()
        self.url = url
        self.channel_id = channel_id

    def _interrupted(self):
        return self.isInterruptionRequested()

    def run(self):
        try:
            with http_interruptible(self._interrupted):
                if self._interrupted():
                    return
                ext = Extractor.detect(self.url)
                if not ext or not ext.supports_vod_listing():
                    self.finished.emit(self.channel_id or self.url, [])
                    return
                channel_id = self.channel_id or ext.extract_channel_id(self.url) or self.url
                vods = ext.list_vods(self.url, log_fn=self.log.emit)
                if self._interrupted():
                    return
                sources = [v.source for v in vods if getattr(v, "source", "")]
                self.finished.emit(channel_id, sources)
        except Exception as e:
            if not self._interrupted():
                self.error.emit(self.channel_id or self.url, str(e))


class AutoRecordResolveWorker(QThread):
    """Resolve a live channel to a downloadable stream off the UI thread."""

    resolved = pyqtSignal(str, object, object, str)
    error = pyqtSignal(str, str)
    log = pyqtSignal(str)

    def __init__(self, channel_id, url, base_out):
        super().__init__()
        self.channel_id = channel_id
        self.url = url
        self.base_out = base_out

    def _interrupted(self):
        return self.isInterruptionRequested()

    def run(self):
        try:
            with http_interruptible(self._interrupted):
                if self._interrupted():
                    return
                ext = Extractor.detect(self.url)
                if not ext:
                    self.error.emit(self.channel_id, f"No extractor for {self.url}")
                    return
                info = ext.resolve(self.url, log_fn=self.log.emit)
                if self._interrupted():
                    return
                if not info or not info.qualities:
                    self.error.emit(self.channel_id, f"Failed to resolve {self.url}")
                    return
                q = info.qualities[0]
                out_dir = os.path.join(
                    self.base_out,
                    f"auto_{safe_filename(self.channel_id)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                )
                self.resolved.emit(self.channel_id, info, q, out_dir)
        except Exception as e:
            if not self._interrupted():
                self.error.emit(self.channel_id, str(e))
