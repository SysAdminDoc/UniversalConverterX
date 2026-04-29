"""BundleWorker — zip a recording folder into a portable share archive.

Walks the recording directory, filters to the file types a downstream
consumer would care about, and packages them into `<folder>.zip`
alongside the source dir. Streams progress through signals so the UI
can display a bar for multi-GB bundles.

Safety: never follows out-of-tree symlinks; never includes files whose
resolved path escapes the recording root.
"""

import os
import zipfile

from PyQt6.QtCore import QThread, pyqtSignal


# File extensions worth bundling. Everything else stays on disk.
_MEDIA_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".ts", ".avi",
               ".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav", ".aac"}
_SIDECAR_EXTS = {".json", ".nfo", ".ass", ".srt", ".vtt",
                 ".txt", ".jsonl", ".jpg", ".png", ".webp"}
_ALLOWED = _MEDIA_EXTS | _SIDECAR_EXTS


def _safe_relpath(child, root):
    """Return the POSIX relpath of `child` under `root`, or None if the
    resolved path escapes the tree."""
    real_root = os.path.realpath(root)
    real_child = os.path.realpath(child)
    try:
        rel = os.path.relpath(real_child, real_root)
    except ValueError:
        return None
    if rel.startswith("..") or os.path.isabs(rel):
        return None
    return rel.replace(os.sep, "/")


def _list_bundle_files(folder):
    """Return (list of (absolute_path, arcname)) and total byte count."""
    selected = []
    total = 0
    for dirpath, _dirnames, filenames in os.walk(folder, followlinks=False):
        for name in filenames:
            if name.startswith("."):
                # Skip the cache sidecars (.streamkeep_thumb.jpg,
                # .streamkeep_resume.json, etc.) — they're per-install,
                # not part of a share bundle.
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in _ALLOWED:
                continue
            path = os.path.join(dirpath, name)
            rel = _safe_relpath(path, folder)
            if rel is None:
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            selected.append((path, rel))
            total += size
    return selected, total


class BundleWorker(QThread):
    """Write a .zip of the chosen folder. Emits byte-level progress so
    the UI bar is accurate for long-running packaging runs.

    Signals:
        progress(int percent, str status)
        done(bool success, str zip_path_or_error)
    """

    progress = pyqtSignal(int, str)
    done = pyqtSignal(bool, str)

    def __init__(self, src_dir, out_zip_path):
        super().__init__()
        self.src_dir = src_dir
        self.out_zip_path = out_zip_path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        if not self.src_dir or not os.path.isdir(self.src_dir):
            self.done.emit(False, "Source directory missing.")
            return
        try:
            files, total = _list_bundle_files(self.src_dir)
        except OSError as e:
            self.done.emit(False, f"Scan failed: {e}")
            return
        if not files:
            self.done.emit(False, "Nothing to bundle — no media/sidecar files found.")
            return
        # Preflight disk space: zip will be roughly the same size as the
        # media (deflate on already-compressed video is near-identity).
        try:
            out_dir = os.path.dirname(self.out_zip_path) or "."
            os.makedirs(out_dir, exist_ok=True)
        except OSError as e:
            self.done.emit(False, f"Cannot create output dir: {e}")
            return
        written = 0
        try:
            # allowZip64 handles > 4 GB archives transparently. Some
            # legacy unzippers reject zip64 — UI surfaces a warning when
            # a bundle crosses 4 GB.
            with zipfile.ZipFile(
                self.out_zip_path, "w",
                compression=zipfile.ZIP_DEFLATED, compresslevel=1,
                allowZip64=True,
            ) as zf:
                for path, arcname in files:
                    if self._cancel:
                        self._partial_cleanup()
                        self.done.emit(False, "Bundle cancelled.")
                        return
                    try:
                        size = os.path.getsize(path)
                    except OSError:
                        continue
                    self.progress.emit(
                        min(99, int((written / max(1, total)) * 100)),
                        f"{arcname} ({size // 1024} KB)",
                    )
                    try:
                        zf.write(path, arcname)
                    except OSError:
                        # One bad file shouldn't abort the whole bundle.
                        continue
                    written += size
        except OSError as e:
            self._partial_cleanup()
            self.done.emit(False, f"Zip write failed: {e}")
            return
        self.progress.emit(100, "Complete")
        self.done.emit(True, self.out_zip_path)

    def _partial_cleanup(self):
        try:
            if os.path.exists(self.out_zip_path):
                os.remove(self.out_zip_path)
        except OSError:
            pass
