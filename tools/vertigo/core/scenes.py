"""Scene detection — content-change segmentation via PySceneDetect if
available, else a fast histogram-delta fallback using OpenCV.

Output is a list of (start_sec, end_sec) tuples covering the timeline.
Smart-Track uses these to prevent panning across hard cuts.
"""

from __future__ import annotations

from pathlib import Path


def detect_scenes(
    video_path: str | Path,
    threshold: float = 27.0,
    min_scene_len_sec: float = 1.0,
) -> list[tuple[float, float]]:
    path = Path(video_path)
    try:
        return _scenedetect(path, threshold, min_scene_len_sec)
    except Exception:
        return _histogram_scenes(path, min_scene_len_sec)


def _scenedetect(path: Path, threshold: float, min_len: float) -> list[tuple[float, float]]:
    from scenedetect import open_video, SceneManager
    from scenedetect.detectors import ContentDetector

    video = open_video(str(path))
    mgr = SceneManager()
    mgr.add_detector(ContentDetector(threshold=threshold, min_scene_len=int(min_len * 15)))
    mgr.detect_scenes(video)
    scenes = mgr.get_scene_list()
    return [(s[0].get_seconds(), s[1].get_seconds()) for s in scenes]


def _histogram_scenes(path: Path, min_len: float) -> list[tuple[float, float]]:
    """Cheap scene detection — color histogram frame-to-frame delta.

    Good enough to prevent panning across obvious cuts when PySceneDetect
    isn't installed. Samples at ~4 fps for speed.
    """
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total / fps if fps else 0.0
        if duration <= 0:
            return []

        sample_step = max(1, int(round(fps / 4.0)))
        prev_hist = None
        cuts: list[float] = [0.0]

        idx = 0
        while idx < total:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            small = cv2.resize(frame, (160, 90))
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            if prev_hist is not None:
                corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if corr < 0.55:
                    t = idx / fps
                    if t - cuts[-1] >= min_len:
                        cuts.append(t)
            prev_hist = hist
            idx += sample_step
    finally:
        cap.release()

    cuts.append(duration)

    scenes: list[tuple[float, float]] = []
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        if b - a >= min_len:
            scenes.append((a, b))
    if not scenes:
        scenes = [(0.0, duration)]
    return scenes
