"""Clipboard monitor — polls for new URLs and emits them."""

import re

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication


class ClipboardMonitor(QObject):
    """Monitors clipboard for new URLs and emits them."""

    url_detected = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._last_clip = ""
        self._enabled = False
        self._timer = QTimer()
        self._timer.timeout.connect(self._check)

    def start(self):
        self._enabled = True
        self._last_clip = QApplication.clipboard().text() or ""
        self._timer.start(800)

    def stop(self):
        self._enabled = False
        self._timer.stop()

    @property
    def is_running(self):
        return self._enabled

    def _check(self):
        if not self._enabled:
            return
        try:
            text = QApplication.clipboard().text() or ""
            if text == self._last_clip:
                return
            self._last_clip = text
            # Extract the first http(s) URL on the first non-empty line so
            # pastes like "here's a link: https://..." still work, but
            # multi-line garbage + stray whitespace can't pollute the field.
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                m = re.search(r'https?://[^\s<>"\'\\]+', line)
                if m:
                    self.url_detected.emit(m.group(0))
                break
        except Exception:
            pass
