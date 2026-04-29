"""Scene detection worker — optional PySceneDetect integration.

Uses ``ContentDetector`` to find scene changes, then extracts a thumbnail
at each boundary via ffmpeg.  Results are cached as individual JPEG files
plus a ``scenes.json`` manifest inside ``.streamkeep_scenes/`` next to the
source video so re-opens are instant.
"""

import json
import os
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

from ..paths import _CREATE_NO_WINDOW

SCENE_THUMB_W = 120


def load_cached_scenes(source_path):
    """Return cached storyboard data or *None* if no cache exists."""
    src_dir = os.path.dirname(source_path) or "."
    manifest = os.path.join(src_dir, ".streamkeep_scenes", "scenes.json")
    if not os.path.isfile(manifest):
        return None
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class SceneWorker(QThread):
    """Detect scene changes via PySceneDetect and extract thumbnails."""

    progress = pyqtSignal(int, str)
    scenes_ready = pyqtSignal(list)   # [{"time": float, "thumb": str}]
    log = pyqtSignal(str)

    def __init__(self, source_path, *, threshold=27.0, max_scenes=200):
        super().__init__()
        self.source_path = source_path
        self.threshold = threshold
        self.max_scenes = max_scenes
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        cached = load_cached_scenes(self.source_path)
        if cached is not None:
            self.scenes_ready.emit(cached)
            return

        try:
            from scenedetect import detect, ContentDetector  # noqa: F811
        except ImportError:
            self.log.emit(
                "[SCENE] scenedetect not installed \u2014 "
                "run: pip install scenedetect[opencv]"
            )
            self.scenes_ready.emit([])
            return

        self.log.emit("[SCENE] Running scene detection\u2026")
        self.progress.emit(0, "Detecting scenes\u2026")

        try:
            scene_list = detect(
                self.source_path,
                ContentDetector(threshold=self.threshold),
            )
        except Exception as e:
            self.log.emit(f"[SCENE] Detection failed: {e}")
            self.scenes_ready.emit([])
            return

        if self._cancel:
            self.scenes_ready.emit([])
            return

        timestamps = [s[0].get_seconds() for s in scene_list]
        if len(timestamps) > self.max_scenes:
            timestamps = timestamps[:self.max_scenes]
        if not timestamps:
            self.log.emit("[SCENE] No scene changes detected.")
            self.scenes_ready.emit([])
            return

        self.log.emit(
            f"[SCENE] {len(timestamps)} scene(s) \u2014 extracting thumbnails\u2026")

        cache_dir = os.path.join(
            os.path.dirname(self.source_path) or ".", ".streamkeep_scenes")
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except OSError:
            self.scenes_ready.emit([])
            return

        results = []
        for i, ts in enumerate(timestamps):
            if self._cancel:
                break
            thumb_path = os.path.join(cache_dir, f"scene_{i:03d}.jpg")
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", f"{ts:.3f}", "-i", self.source_path,
                "-frames:v", "1",
                "-vf", f"scale={SCENE_THUMB_W}:-2",
                "-q:v", "4", "-y", thumb_path,
            ]
            try:
                subprocess.run(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=_CREATE_NO_WINDOW, timeout=15,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue
            if os.path.isfile(thumb_path):
                results.append({"time": ts, "thumb": thumb_path})
            pct = int((i + 1) / len(timestamps) * 100)
            self.progress.emit(pct, f"Thumbnails {i + 1}/{len(timestamps)}")

        if results:
            try:
                manifest = os.path.join(cache_dir, "scenes.json")
                with open(manifest, "w", encoding="utf-8") as f:
                    json.dump(results, f)
            except OSError:
                pass

        self.log.emit(f"[SCENE] Storyboard: {len(results)} thumbnail(s).")
        self.scenes_ready.emit(results)
