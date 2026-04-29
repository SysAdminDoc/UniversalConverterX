"""ThumbWorker — async thumbnail generator for video files.

Two shapes of request:

  ThumbWorker(path, at_secs=N)         -> one thumbnail at N seconds
  ThumbWorker(path, count=20)          -> N evenly-spaced thumbnails

Cache layout: siblings of the source file.

  <src_dir>/.streamkeep_thumb.jpg                 (single-thumb cache)
  <src_dir>/.streamkeep_thumbs/<sig>_NN.jpg       (filmstrip cache)

`sig` is a short hash of (source size, mtime, count) so the cache invalidates
when the source file changes. Silent on all errors — a missing thumb must
never break the surrounding feature (History table row, trim dialog).
"""

import hashlib
import os
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

from ..paths import _CREATE_NO_WINDOW

SINGLE_CACHE_NAME = ".streamkeep_thumb.jpg"
STRIP_CACHE_DIR = ".streamkeep_thumbs"


def _file_signature(path, count):
    try:
        st = os.stat(path)
    except OSError:
        return "0"
    key = f"{st.st_size}-{int(st.st_mtime)}-{int(count)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def single_thumb_path(src_path):
    """Deterministic path for a single-thumb cache entry. Returns None if
    the source is missing / unreadable. Includes a hash of the source
    filename so multiple videos in the same directory don't collide."""
    if not src_path or not os.path.exists(src_path):
        return None
    name = os.path.basename(src_path)
    sig = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return os.path.join(os.path.dirname(src_path), f".streamkeep_thumb_{sig}.jpg")


def strip_thumb_paths(src_path, count):
    """List the expected cache paths for a filmstrip of `count` thumbs."""
    if not src_path or count <= 0:
        return []
    sig = _file_signature(src_path, count)
    cache_dir = os.path.join(os.path.dirname(src_path), STRIP_CACHE_DIR)
    return [
        os.path.join(cache_dir, f"{sig}_{i:03d}.jpg")
        for i in range(count)
    ]


def probe_duration(path):
    """Seconds via ffprobe; 0.0 on failure. Kept here (not imported from
    clip_dialog) to avoid a UI-layer import from a background worker."""
    if not path or not os.path.exists(path):
        return 0.0
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            creationflags=_CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace",
            timeout=10,
        )
        return float(out.strip() or 0.0)
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired, ValueError, OSError):
        return 0.0


def _run_ffmpeg_thumb(src, at_secs, dst, width=240):
    """Blocking: generate one thumbnail. Return True on success."""
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    except OSError:
        return False
    # -ss before -i for a fast keyframe seek — good enough for thumbs.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, at_secs):.3f}",
        "-i", src,
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", "5",
        "-y", dst,
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_CREATE_NO_WINDOW,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return (proc.returncode == 0
            and os.path.exists(dst)
            and os.path.getsize(dst) > 0)


class ThumbWorker(QThread):
    """Generate thumbnails off the UI thread.

    Signals:
        thumb_ready(int index, str path)   emitted once per thumb as it lands
        done(bool all_ok)                  emitted when the batch finishes
    """

    thumb_ready = pyqtSignal(int, str)
    done = pyqtSignal(bool)

    def __init__(self, src_path, *, count=1, at_secs=None, width=240):
        super().__init__()
        self.src_path = src_path
        self.count = max(1, int(count))
        self.at_secs = at_secs   # Used when count == 1 for a specific moment
        self.width = int(width)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _run_single(self):
        dst = single_thumb_path(self.src_path)
        if dst is None:
            self.done.emit(False)
            return
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            self.thumb_ready.emit(0, dst)
            self.done.emit(True)
            return
        dur = probe_duration(self.src_path)
        # Seek to the earliest of: user-specified, 10% in, or 5 seconds.
        # Very early frames are often black on stream captures.
        if self.at_secs is not None:
            at = float(self.at_secs)
        elif dur > 0:
            at = max(5.0, dur * 0.1)
        else:
            at = 5.0
        ok = _run_ffmpeg_thumb(self.src_path, at, dst, width=self.width)
        if ok:
            self.thumb_ready.emit(0, dst)
        self.done.emit(ok)

    def _run_strip(self):
        paths = strip_thumb_paths(self.src_path, self.count)
        dur = probe_duration(self.src_path)
        if dur <= 0:
            self.done.emit(False)
            return
        # Sample positions: evenly spaced but avoid the last 2% (tail often
        # ends on a static post-stream screen).
        step = (dur * 0.98) / max(1, self.count)
        any_ok = False
        for i, dst in enumerate(paths):
            if self._cancel:
                break
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                self.thumb_ready.emit(i, dst)
                any_ok = True
                continue
            at = step * i + (step * 0.5)
            if _run_ffmpeg_thumb(self.src_path, at, dst, width=self.width):
                self.thumb_ready.emit(i, dst)
                any_ok = True
        self.done.emit(any_ok and not self._cancel)

    def run(self):
        try:
            if self.count <= 1:
                self._run_single()
            else:
                self._run_strip()
        except Exception:
            # Never let a thumb failure crash the worker thread.
            self.done.emit(False)
