"""Sparse face sampling for caption layout decisions.

This is intentionally lighter than `core/detect.py`'s `FaceTracker.track()`:
we only need normalised bounding boxes over time, not smoothed tracks or
identity-sticky speakers. The caption-layout pass reads these samples to
decide whether a caption chunk would overlap a face and should flip to
top-align.

Call paths are kept decoupled so the face pass can run in parallel with
the whisper transcription without stepping on MediaPipe state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class FaceSample:
    """All faces on a single sampled frame, in normalised source coords.

    `boxes` entries are `(x, y, w, h)` with each value in [0, 1] relative
    to source width/height. An empty tuple means no face was detected.
    """
    t: float
    boxes: tuple[tuple[float, float, float, float], ...] = field(default_factory=tuple)

    @property
    def has_face(self) -> bool:
        return len(self.boxes) > 0


def sample_faces(
    video_path: str | Path,
    sample_fps: float = 2.0,
    progress_cb=None,
    cancel_cb=None,
) -> list[FaceSample]:
    """Sample `video_path` at `sample_fps` and return face boxes per sample.

    MediaPipe is preferred; Haar is used as a cascade fallback. Returns an
    empty list if the video can't be opened or no frames are decoded.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / src_fps if src_fps else 0.0
    step_frames = max(1, int(round(src_fps / max(0.25, sample_fps))))

    mp_detector = _make_mediapipe_detector()
    haar = None if mp_detector else _make_haar_cascade()

    samples: list[FaceSample] = []
    frame_idx = 0
    try:
        while True:
            if cancel_cb and cancel_cb():
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            h, w = frame.shape[:2]
            boxes = _detect_boxes(frame, w, h, mp_detector, haar)
            t = frame_idx / src_fps if src_fps else 0.0
            samples.append(FaceSample(t=t, boxes=boxes))

            if progress_cb and duration:
                progress_cb(min(1.0, t / duration))

            frame_idx += step_frames
            if total_frames and frame_idx >= total_frames:
                break
    finally:
        cap.release()
        if mp_detector:
            try:
                mp_detector.close()
            except Exception:
                pass
    return samples


def samples_overlapping(
    samples: list[FaceSample],
    t_start: float,
    t_end: float,
) -> list[FaceSample]:
    """Return samples whose timestamps fall inside [t_start, t_end]."""
    if t_end < t_start:
        t_start, t_end = t_end, t_start
    return [s for s in samples if t_start <= s.t <= t_end]


# ---------------------------------------------------------------- internal

def _make_mediapipe_detector():
    try:
        import mediapipe as mp
        return mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=0.5,
        )
    except Exception:
        return None


def _make_haar_cascade():
    try:
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        return cv2.CascadeClassifier(path)
    except Exception:
        return None


def _detect_boxes(
    frame: np.ndarray,
    w: int,
    h: int,
    mp_detector,
    haar,
) -> tuple[tuple[float, float, float, float], ...]:
    if mp_detector is not None:
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = mp_detector.process(rgb)
        except Exception:
            result = None
        if result and result.detections:
            out: list[tuple[float, float, float, float]] = []
            for det in result.detections:
                box = det.location_data.relative_bounding_box
                x = max(0.0, min(1.0, float(box.xmin)))
                y = max(0.0, min(1.0, float(box.ymin)))
                bw = max(0.0, min(1.0, float(box.width)))
                bh = max(0.0, min(1.0, float(box.height)))
                out.append((x, y, bw, bh))
            return tuple(out)

    if haar is not None:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = haar.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4)
        except Exception:
            faces = []
        return tuple(
            (
                float(fx) / w,
                float(fy) / h,
                float(fw) / w,
                float(fh) / h,
            )
            for (fx, fy, fw, fh) in faces
        )

    return ()
