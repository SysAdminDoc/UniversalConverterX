"""Face/subject detection — lazy MediaPipe, sampled across timeline.

Two call paths are supported:

    * `track(video_path)` — legacy single-largest-face per frame with
      light exponential smoothing. Kept for zero-dep fallback when
      the crop geometry isn't known yet (e.g. precomputing tracks).

    * `track_with_cameraman(video_path, crop_width_frac)` — feeds all
      detected faces per frame through a `SpeakerTracker` +
      `SmoothedCameraman` pipeline (see `core.cameraman`) for stable,
      speaker-sticky, hysteresis-gated viewport motion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .cameraman import FaceObservation, SmoothedCameraman
from .tracker_boxmot import make_tracker


@dataclass(frozen=True)
class TrackPoint:
    """Normalized (0..1) horizontal subject position at time t seconds."""
    t: float
    x: float  # center x in 0..1
    confidence: float


# Sentinel state values for the lazy MediaPipe detector. Using typed
# constants (rather than ``False`` as an ad-hoc third value) avoids the
# is-a-bool-vs-is-an-object confusion the previous implementation had.
_MP_UNINITIALIZED = "uninitialized"
_MP_DISABLED = "disabled"


class FaceTracker:
    """Samples the video, runs MediaPipe face detection per frame,
    returns a smoothed track of horizontal subject positions over time.

    Falls back to Haar cascade if MediaPipe is unavailable.
    """

    def __init__(self, sample_fps: float = 2.0, smoothing: float = 0.6) -> None:
        self.sample_fps = max(0.25, sample_fps)
        self.smoothing = min(max(smoothing, 0.0), 0.95)
        # Tri-state: UNINITIALIZED → real object → DISABLED (permanently off).
        # Keeping it as a typed string sentinel (not None / False) makes the
        # hot-path check readable and prevents the accidental "try again on
        # every frame" loop that happened when DISABLED was stored as False.
        self._mp_detector_state: str | object = _MP_UNINITIALIZED
        self._haar: cv2.CascadeClassifier | None = None

    def track(
        self,
        video_path: str | Path,
        progress_cb=None,
        cancel_cb=None,
    ) -> list[TrackPoint]:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []

        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total_frames / src_fps if src_fps else 0.0
        step_frames = max(1, int(round(src_fps / self.sample_fps)))

        points: list[TrackPoint] = []
        last_x: float | None = None
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
                # Guard against 0-width frames from corrupted streams; the
                # downstream normalization would divide by `w`.
                if w <= 0 or h <= 0:
                    frame_idx += step_frames
                    if total_frames and frame_idx >= total_frames:
                        break
                    continue

                x_norm, conf = self._detect_center(frame, w, h)
                t = frame_idx / src_fps if src_fps else 0.0

                if x_norm is None:
                    x_norm = last_x if last_x is not None else 0.5
                    conf = 0.1

                if last_x is not None:
                    x_norm = self.smoothing * last_x + (1 - self.smoothing) * x_norm
                last_x = x_norm

                points.append(TrackPoint(t=t, x=float(x_norm), confidence=float(conf)))

                if progress_cb and duration:
                    progress_cb(min(1.0, t / duration))

                frame_idx += step_frames
                if total_frames and frame_idx >= total_frames:
                    break
        finally:
            cap.release()

        return points

    # ------------------------------------------------------------------
    # Cameraman-driven smart track.
    #
    # `crop_width_frac` is the 9:16 viewport's width as a fraction of the
    # source width. The cameraman tuning (dead-zone, big-jump threshold,
    # per-frame speeds) needs this to scale correctly per clip geometry.
    #
    # When ``use_cluster_filter`` is True we run a two-pass pipeline:
    # collect all per-frame observations, hand them to
    # ``core.cluster_track.cluster_filter`` to drop single-frame noise
    # and duplicate detections, then feed the cleaned stream through
    # the speaker + cameraman smoothing. The first pass owns 0–90% of
    # the progress bar (detection dominates wall time) and the second
    # owns 90–100%.
    # ------------------------------------------------------------------
    def track_with_cameraman(
        self,
        video_path: str | Path,
        crop_width_frac: float,
        progress_cb=None,
        cancel_cb=None,
        *,
        use_cluster_filter: bool = False,
    ) -> list[TrackPoint]:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return []

        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total_frames / src_fps if src_fps else 0.0
        step_frames = max(1, int(round(src_fps / self.sample_fps)))

        # Pass 1: detection. Collect per-frame observations plus the
        # source width and each frame's index/time so the second pass
        # can advance the cameraman without re-opening the video.
        detect_budget = 0.9 if use_cluster_filter else 1.0
        frames_obs: list[list[FaceObservation]] = []
        frame_indices: list[int] = []
        src_w: int | None = None

        def _det_progress(fraction: float) -> None:
            if progress_cb is None:
                return
            progress_cb(max(0.0, min(detect_budget, fraction * detect_budget)))

        try:
            frame_idx = 0
            while True:
                if cancel_cb and cancel_cb():
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ok, frame = cap.read()
                if not ok or frame is None:
                    break

                h, w = frame.shape[:2]
                if w <= 0 or h <= 0:
                    frame_idx += step_frames
                    if total_frames and frame_idx >= total_frames:
                        break
                    continue
                if src_w is None:
                    src_w = w

                t = frame_idx / src_fps if src_fps else 0.0
                observations = [
                    FaceObservation(
                        frame=frame_idx,
                        t=t,
                        cx=bx + bw / 2,
                        cy=by + bh / 2,
                        w=bw,
                        h=bh,
                        score=conf,
                    )
                    for (bx, by, bw, bh, conf) in self._detect_boxes(frame, w, h)
                ]
                frames_obs.append(observations)
                frame_indices.append(frame_idx)

                if duration > 0:
                    _det_progress(min(1.0, t / duration))

                frame_idx += step_frames
                if total_frames and frame_idx >= total_frames:
                    break
        finally:
            cap.release()

        if not frames_obs or src_w is None:
            return []

        if use_cluster_filter:
            try:
                from .cluster_track import cluster_filter
                frames_obs = cluster_filter(frames_obs, source_width=int(src_w))
            except Exception:
                # The filter is an enhancement — any failure should not
                # break Smart Track. Fall through to the raw stream.
                pass

        # Pass 2: speaker + cameraman smoothing over the (possibly
        # filtered) observation stream. The video file is already
        # released; everything we need is in-memory.
        #
        # ``make_tracker()`` picks BoxMOT's BoT-SORT when the boxmot
        # package is installed (stable IDs across occlusion, much
        # better on multi-speaker content) and falls back to the
        # existing SpeakerTracker when it isn't — same interface
        # either way so the cameraman loop below doesn't change.
        cameraman = SmoothedCameraman(
            crop_width_px=max(1.0, float(crop_width_frac) * src_w),
            source_width_px=float(src_w),
        )
        speakers = make_tracker()

        points: list[TrackPoint] = []
        total_steps = max(1, len(frames_obs))
        for i, (fi, observations) in enumerate(zip(frame_indices, frames_obs)):
            if cancel_cb and cancel_cb():
                break

            active = speakers.step(fi, observations)
            target_cx = active.cx if active else cameraman.center_x
            new_cx = cameraman.step(target_cx)

            t = fi / src_fps if src_fps else 0.0
            confidence = active.total_score if active else 0.1
            points.append(
                TrackPoint(
                    t=t,
                    x=float(new_cx / max(1, src_w)),
                    confidence=float(min(1.0, confidence / 4.0)),
                )
            )

            if progress_cb is not None:
                smoothed_fraction = (i + 1) / total_steps
                progress_cb(
                    detect_budget + (1.0 - detect_budget) * smoothed_fraction
                )

        return points

    # ------------------------------------------------------------------
    def _detect_boxes(self, frame: np.ndarray, w: int, h: int):
        boxes = self._mediapipe_boxes(frame, w, h)
        if not boxes:
            boxes = self._haar_boxes(frame, w, h)
        return boxes

    def _detect_center(self, frame: np.ndarray, w: int, h: int) -> tuple[float | None, float]:
        """Return (normalized_x_center, confidence) of the dominant subject, or (None, 0)."""
        boxes = self._mediapipe_boxes(frame, w, h)
        if not boxes:
            boxes = self._haar_boxes(frame, w, h)
        if not boxes:
            return None, 0.0

        # Pick largest box (closest subject).
        bx, by, bw, bh, conf = max(boxes, key=lambda b: b[2] * b[3])
        cx = (bx + bw / 2) / w
        return float(cx), float(conf)

    def _mediapipe_boxes(self, frame: np.ndarray, w: int, h: int):
        # Fast path: detector has been permanently disabled (import failed
        # or first process() raised). Skip without touching mediapipe so
        # every subsequent frame costs O(1) instead of re-entering the
        # try/except on each call.
        if self._mp_detector_state is _MP_DISABLED:
            return []

        if self._mp_detector_state is _MP_UNINITIALIZED:
            try:
                import mediapipe as mp
                self._mp_detector_state = mp.solutions.face_detection.FaceDetection(
                    model_selection=1,
                    min_detection_confidence=0.5,
                )
            except Exception:
                self._mp_detector_state = _MP_DISABLED
                return []

        detector = self._mp_detector_state
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = detector.process(rgb)
        except Exception:
            # Runtime failure — disable for the rest of this session so we
            # don't burn cycles retrying the same broken call.
            self._mp_detector_state = _MP_DISABLED
            try:
                detector.close()
            except Exception:
                pass
            return []

        if not result or not result.detections:
            return []
        out = []
        for det in result.detections:
            box = det.location_data.relative_bounding_box
            bx = max(0.0, box.xmin) * w
            by = max(0.0, box.ymin) * h
            bw = box.width * w
            bh = box.height * h
            out.append((bx, by, bw, bh, det.score[0] if det.score else 0.5))
        return out

    def _haar_boxes(self, frame: np.ndarray, w: int, h: int):
        try:
            if self._haar is None:
                cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                self._haar = cv2.CascadeClassifier(cascade_path)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._haar.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4)
        except Exception:
            return []
        return [(float(x), float(y), float(bw), float(bh), 0.5) for (x, y, bw, bh) in faces]

    def close(self) -> None:
        detector = self._mp_detector_state
        if detector is _MP_UNINITIALIZED or detector is _MP_DISABLED:
            return
        try:
            detector.close()
        except Exception:
            pass
        self._mp_detector_state = _MP_DISABLED
