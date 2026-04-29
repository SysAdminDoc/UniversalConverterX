"""In-app notifications center — ring buffer + file-backed JSONL persistence.

Decoupled from the Qt UI so the main window only wires the dropdown; the
ring buffer itself is a pure data structure that can be unit-tested.
File persistence (F4) appends every notification to ``notifications.jsonl``
inside the config directory.
"""

import json
import os
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from .paths import CONFIG_DIR

NOTIF_LOG = CONFIG_DIR / "notifications.jsonl"
NOTIF_LOG_MAX_BYTES = 5 * 1024 * 1024
NOTIF_LOG_KEEP_LINES = 20000
_NOTIF_FILE_LOCK = threading.Lock()


@dataclass
class Notification:
    ts: str = ""
    text: str = ""
    level: str = "info"   # "info" | "success" | "warning" | "error"


class NotificationCenter:
    """Bounded history of recent events. Newest first."""

    def __init__(self, capacity=50):
        self._buf = deque(maxlen=int(capacity))
        self._unread = 0
        self._lock = threading.Lock()

    def push(self, text, level="info"):
        now = datetime.now()
        note = Notification(
            ts=now.strftime("%H:%M:%S"),
            text=str(text or "")[:200],
            level=str(level or "info"),
        )
        with self._lock:
            self._buf.appendleft(note)
            self._unread += 1
        self._persist(note, now)
        return note

    def _persist(self, note, now):
        with _NOTIF_FILE_LOCK:
            try:
                NOTIF_LOG.parent.mkdir(parents=True, exist_ok=True)
                with open(NOTIF_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "ts": now.isoformat(timespec="seconds"),
                        "text": note.text,
                        "level": note.level,
                    }) + "\n")
                self._compact_log_locked()
            except OSError:
                pass

    def _compact_log_locked(self):
        try:
            if NOTIF_LOG_MAX_BYTES <= 0 or NOTIF_LOG_KEEP_LINES <= 0:
                return
            if not NOTIF_LOG.is_file() or NOTIF_LOG.stat().st_size <= NOTIF_LOG_MAX_BYTES:
                return
        except OSError:
            return

        lines = deque(maxlen=max(1, int(NOTIF_LOG_KEEP_LINES or 1)))
        try:
            with open(NOTIF_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        lines.append(line.rstrip("\r\n"))
        except OSError:
            return

        tmp_path = NOTIF_LOG.with_name(NOTIF_LOG.name + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                for line in lines:
                    f.write(line + "\n")
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except (OSError, AttributeError):
                    pass
            os.replace(tmp_path, NOTIF_LOG)
        except OSError:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

    def load_history(self, limit=5000):
        """Load notification history from the JSONL file."""
        try:
            limit = max(1, int(limit or 1))
        except (TypeError, ValueError):
            limit = 5000
        entries = deque(maxlen=limit)
        with _NOTIF_FILE_LOCK:
            try:
                if not NOTIF_LOG.is_file():
                    return []
                with open(NOTIF_LOG, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entries.append(json.loads(line))
                        except (json.JSONDecodeError, TypeError):
                            continue
            except OSError:
                pass
        return list(entries)

    def mark_all_read(self):
        with self._lock:
            self._unread = 0

    @property
    def unread(self):
        with self._lock:
            return self._unread

    def items(self):
        with self._lock:
            return list(self._buf)

    def clear(self):
        with self._lock:
            self._buf.clear()
            self._unread = 0
