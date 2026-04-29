"""ThumbLoader + PreviewLoader — throttled async thumbnail loader for table views.

Usage: one instance per table. Call `request(row_key, media_path)` — when
the thumb is ready (either from disk cache or freshly generated) the
`thumb_ready(row_key, qpixmap)` signal fires. At most
`max_concurrent` ffmpeg jobs run at the same time.

PreviewLoader (F46): generates 5-frame hover previews cached as a
`.streamkeep_preview.jpg` sprite strip alongside the recording.
"""

import os
from collections import OrderedDict, deque

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap

from ..postprocess import ThumbWorker, single_thumb_path

_PREVIEW_CACHE_MAX = 32


class ThumbLoader(QObject):
    thumb_ready = pyqtSignal(object, QPixmap)   # row_key, pixmap

    def __init__(self, parent=None, *, max_concurrent=2, size=(160, 90)):
        super().__init__(parent)
        self._pending = deque()                  # (row_key, media_path)
        self._in_flight = {}                     # row_key -> ThumbWorker
        self._max = int(max_concurrent)
        self._size = size

    def request(self, row_key, media_path):
        """Queue a thumbnail request. If the cache already has one, emits
        immediately on the event loop. De-dups by row_key."""
        if not media_path or not os.path.exists(media_path):
            return
        if row_key in self._in_flight:
            return
        cache = single_thumb_path(media_path)
        if cache and os.path.exists(cache) and os.path.getsize(cache) > 0:
            pix = QPixmap(cache)
            if not pix.isNull():
                self.thumb_ready.emit(row_key, pix)
                return
        # Remove any stale pending entry for this row (scroll re-requests).
        self._pending = deque(
            (k, p) for (k, p) in self._pending if k != row_key
        )
        self._pending.append((row_key, media_path))
        self._pump()

    def clear(self):
        """Forget all pending requests (but let in-flight workers finish)."""
        self._pending.clear()

    def _pump(self):
        while self._pending and len(self._in_flight) < self._max:
            row_key, media_path = self._pending.popleft()
            worker = ThumbWorker(media_path, count=1, width=self._size[0])
            worker.thumb_ready.connect(
                lambda _idx, path, rk=row_key:
                self._on_worker_thumb(rk, path)
            )
            worker.done.connect(
                lambda _ok, rk=row_key: self._on_worker_done(rk)
            )
            self._in_flight[row_key] = worker
            worker.start()

    def _on_worker_thumb(self, row_key, path):
        pix = QPixmap(path)
        if not pix.isNull():
            self.thumb_ready.emit(row_key, pix)

    def _on_worker_done(self, row_key):
        w = self._in_flight.pop(row_key, None)
        if w is not None:
            try:
                w.wait(100)
            except Exception:
                pass
        self._pump()


# ── Preview Loader (F46) ────────────────────────────────────────────

PREVIEW_FRAMES = 5
PREVIEW_FRAME_WIDTH = 160


def _preview_cache_path(media_path):
    """Return the path to the cached 5-frame preview sprite strip."""
    d = os.path.dirname(media_path)
    return os.path.join(d, ".streamkeep_preview.jpg") if d else ""


class PreviewLoader(QObject):
    """Generates and cycles through 5-frame hover previews.

    Call ``start_preview(row_key, media_path, callback)`` when the mouse
    enters a thumbnail cell. Call ``stop_preview()`` when it leaves.
    The callback receives ``(row_key, QPixmap)`` every 200ms with the
    next frame.
    """

    frame_ready = pyqtSignal(object, QPixmap)  # row_key, pixmap

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_key = None
        self._frames = []         # list of QPixmap
        self._frame_idx = 0
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._next_frame)
        self._worker = None
        self._cache = OrderedDict()  # media_path -> list[QPixmap], LRU-capped

    def start_preview(self, row_key, media_path):
        """Begin animating frames for *media_path*. If cached, starts
        immediately. Otherwise generates via ThumbWorker (5 frames)."""
        self.stop_preview()
        if not media_path or not os.path.exists(media_path):
            return
        self._active_key = row_key

        # Check in-memory cache (LRU: move to end on hit)
        if media_path in self._cache:
            self._cache.move_to_end(media_path)
            self._frames = self._cache[media_path]
            self._frame_idx = 0
            self._timer.start()
            return

        # Check on-disk cache
        cache_path = _preview_cache_path(media_path)
        if cache_path and os.path.exists(cache_path):
            frames = self._split_sprite(cache_path)
            if frames:
                self._cache[media_path] = frames
                while len(self._cache) > _PREVIEW_CACHE_MAX:
                    self._cache.popitem(last=False)
                self._frames = frames
                self._frame_idx = 0
                self._timer.start()
                return

        # Generate via ThumbWorker (5 evenly-spaced frames)
        worker = ThumbWorker(media_path, count=PREVIEW_FRAMES, width=PREVIEW_FRAME_WIDTH)
        self._worker = worker
        _media = media_path  # capture for closure

        def _on_done(ok):
            if not ok or self._active_key != row_key:
                return
            # ThumbWorker writes individual files; compose a sprite strip
            # from the cache dir
            thumb_dir = os.path.join(
                os.path.dirname(media_path), ".streamkeep_thumbs"
            )
            if not os.path.isdir(thumb_dir):
                return
            frame_files = sorted(
                f for f in os.listdir(thumb_dir) if f.endswith(".jpg")
            )[:PREVIEW_FRAMES]
            if not frame_files:
                return
            pixmaps = []
            for fn in frame_files:
                p = QPixmap(os.path.join(thumb_dir, fn))
                if not p.isNull():
                    pixmaps.append(p)
            if pixmaps:
                self._cache[_media] = pixmaps
                while len(self._cache) > _PREVIEW_CACHE_MAX:
                    self._cache.popitem(last=False)
                self._frames = pixmaps
                self._frame_idx = 0
                self._timer.start()

        worker.done.connect(_on_done)
        worker.start()

    def stop_preview(self):
        """Stop the current preview animation."""
        self._timer.stop()
        self._active_key = None
        self._frames = []
        self._frame_idx = 0
        if self._worker is not None:
            try:
                self._worker.requestInterruption()
            except Exception:
                pass
            self._worker = None

    def _next_frame(self):
        if not self._frames or self._active_key is None:
            self._timer.stop()
            return
        pix = self._frames[self._frame_idx % len(self._frames)]
        self.frame_ready.emit(self._active_key, pix)
        self._frame_idx += 1

    def _split_sprite(self, sprite_path):
        """Split a horizontal sprite strip into individual QPixmaps."""
        src = QPixmap(sprite_path)
        if src.isNull():
            return []
        w = src.width() // PREVIEW_FRAMES
        h = src.height()
        if w < 1:
            return []
        frames = []
        for i in range(PREVIEW_FRAMES):
            crop = src.copy(i * w, 0, w, h)
            if not crop.isNull():
                frames.append(crop)
        return frames
