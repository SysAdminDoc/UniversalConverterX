"""Storage Health Monitor — continuous disk space tracking with alerts (F67).

Polls free disk space every 30 seconds on the configured output drives.
Emits signals for status bar updates and critical-low-space alerts.

Usage::

    monitor = DiskMonitor(output_dirs=["/path/to/downloads"])
    monitor.space_changed.connect(on_space_update)  # (path, free_bytes, total_bytes)
    monitor.space_critical.connect(on_critical)       # (path, free_bytes)
    monitor.start()
"""

import shutil

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class DiskMonitor(QObject):
    """Periodic disk space monitor with configurable thresholds."""

    space_changed = pyqtSignal(str, int, int)   # path, free_bytes, total_bytes
    space_critical = pyqtSignal(str, int)        # path, free_bytes
    space_warning = pyqtSignal(str, int)         # path, free_bytes

    def __init__(self, parent=None, *, interval_ms=30000):
        super().__init__(parent)
        self._paths = []
        self._warning_bytes = 20 * 1024 ** 3   # 20 GB default
        self._critical_bytes = 5 * 1024 ** 3    # 5 GB default
        self._auto_pause = False
        self._last_state = {}   # path -> "ok" | "warning" | "critical"

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    def configure(self, *, warning_gb=20, critical_gb=5, auto_pause=False):
        """Set thresholds in GB."""
        self._warning_bytes = int(warning_gb * 1024 ** 3)
        self._critical_bytes = int(critical_gb * 1024 ** 3)
        self._auto_pause = auto_pause

    def set_paths(self, paths):
        """Set the output directories to monitor."""
        self._paths = [p for p in paths if p]

    def start(self):
        if self._paths:
            self._poll()
            self._timer.start()

    def stop(self):
        self._timer.stop()

    @property
    def auto_pause(self):
        return self._auto_pause

    def _poll(self):
        for path in self._paths:
            try:
                usage = shutil.disk_usage(path)
            except (OSError, ValueError):
                continue

            free = usage.free
            total = usage.total
            self.space_changed.emit(path, free, total)

            prev = self._last_state.get(path, "ok")

            if free < self._critical_bytes:
                if prev != "critical":
                    self.space_critical.emit(path, free)
                    self._last_state[path] = "critical"
            elif free < self._warning_bytes:
                if prev != "warning":
                    self.space_warning.emit(path, free)
                    self._last_state[path] = "warning"
            else:
                self._last_state[path] = "ok"

    def format_status(self):
        """Return a summary string for the status bar."""
        parts = []
        for path in self._paths:
            try:
                usage = shutil.disk_usage(path)
                free_gb = usage.free / 1024 ** 3
                parts.append(f"{free_gb:.1f} GB free")
            except (OSError, ValueError):
                parts.append("N/A")
        return " | ".join(parts) if parts else ""

    def get_color(self):
        """Return a theme-appropriate color hex based on worst state."""
        states = list(self._last_state.values())
        if "critical" in states:
            return "#f38ba8"   # red
        if "warning" in states:
            return "#f9e2af"   # yellow
        return "#a6e3a1"      # green
