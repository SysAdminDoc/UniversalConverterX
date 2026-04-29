"""Smooth camera motion + sticky speaker tracking.

Port of the two key ideas from `mutonby/openshorts` (MIT, 459 stars):

    * **SmoothedCameraman** — safe-zone hysteresis + speed-adaptive
      motion that decides, per frame, how much to move the viewport
      toward the current subject. Prevents both jitter and slam-cuts.

    * **SpeakerTracker** — ID-sticky face tracking with exponential
      decay, a "currently active" bonus, and a switch cool-down so
      multi-person framing doesn't ping-pong between heads.

Both emit *x-coordinates in source pixels* (centre of the 9:16 viewport),
so the existing `reframe._plan_track` can consume them after a light
conversion to normalised `TrackPoint`s.

Kept intentionally free of Qt / FFmpeg imports so the logic stays
testable and reusable for future per-frame preview rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# ---------------------------------------------------------------- datatypes

@dataclass
class FaceObservation:
    """Bounding box + score for a single face on a single frame."""
    frame: int
    t: float
    cx: float           # centre x in source pixels
    cy: float           # centre y in source pixels
    w: float
    h: float
    score: float = 1.0  # detector confidence

    @property
    def area(self) -> float:
        return max(0.0, self.w * self.h)


@dataclass
class TrackedFace:
    """Persistent track of a face across frames, keyed by identity."""
    face_id: int
    first_seen: int
    last_seen: int
    cx: float
    cy: float
    w: float
    h: float
    activity: float = 1.0          # exponentially-decayed recency score
    speaker_bonus: float = 0.0     # temporary bonus applied while active

    @property
    def total_score(self) -> float:
        return self.activity + self.speaker_bonus


# ---------------------------------------------------------------- smoothed camera

class SmoothedCameraman:
    """Viewport-centre controller with safe-zone hysteresis.

    The camera only moves when the subject leaves a configurable
    "dead-zone" around the current viewport centre. When it must
    move it uses an adaptive speed: gentle for small corrections,
    aggressive for big jumps (e.g. subject switches). An overshoot
    clamp kills oscillation.
    """

    # Tuning constants, direct ports from openshorts/main.py
    DEADZONE_FRAC = 0.25     # subject may roam within ±25% of crop width
    NORMAL_SPEED_PX = 3.0    # per-frame motion when correcting
    BIG_JUMP_SPEED_PX = 15.0 # per-frame motion when subject switches
    BIG_JUMP_FRAC = 0.50     # delta > 50% of crop width ⇒ "big jump"

    def __init__(self, *, crop_width_px: float, source_width_px: float) -> None:
        self._crop_w = max(1.0, float(crop_width_px))
        self._src_w = max(1.0, float(source_width_px))
        self._x: float = self._src_w / 2.0      # current viewport centre
        self._max_x_left = self._src_w - self._crop_w

    @property
    def center_x(self) -> float:
        return self._x

    def reset(self, center_x: float | None = None) -> None:
        self._x = center_x if center_x is not None else self._src_w / 2.0

    def step(self, target_cx: float) -> float:
        """Advance one frame toward `target_cx`; returns new centre.

        Clamps so the viewport stays fully inside the source frame.
        """
        target = max(self._crop_w / 2.0,
                     min(self._src_w - self._crop_w / 2.0, float(target_cx)))
        delta = target - self._x
        abs_delta = abs(delta)

        deadzone = self._crop_w * self.DEADZONE_FRAC
        if abs_delta <= deadzone:
            return self._x

        speed = self.BIG_JUMP_SPEED_PX if abs_delta > self._crop_w * self.BIG_JUMP_FRAC else self.NORMAL_SPEED_PX
        step = speed if delta > 0 else -speed

        # Overshoot clamp — never move past the target in one step.
        if abs(step) > abs_delta:
            step = delta

        self._x = self._x + step
        return self._x


# ---------------------------------------------------------------- speaker tracker

class SpeakerTracker:
    """ID-sticky tracking of multiple faces with a switch cool-down.

    Assigns stable integer face IDs by nearest-centre proximity across
    frames; maintains an exponentially-decaying "activity" score that
    lets recently-visible faces keep primacy briefly after occlusion;
    applies a sticky speaker bonus to whichever face is currently
    marked as active; and refuses to switch the active speaker for
    `switch_cooldown` frames after a previous switch.
    """

    # Tuning constants ported from openshorts/main.py
    ACTIVITY_DECAY = 0.85
    SPEAKER_BONUS = 3.0
    SWITCH_COOLDOWN_FRAMES = 30
    # Proximity threshold for assigning an observation to an existing
    # track. Expressed as a fraction of the face's own width.
    PROXIMITY_FRAC = 1.5

    def __init__(self) -> None:
        self._tracks: dict[int, TrackedFace] = {}
        self._next_id: int = 1
        self._active_id: int | None = None
        self._last_switch_frame: int = -10**9

    # ------------------------------------------------------------ update
    def step(self, frame: int, observations: Iterable[FaceObservation]) -> TrackedFace | None:
        """Feed per-frame detections and get the currently-active face."""
        obs_list = list(observations)

        # 1. Decay all existing tracks
        for tr in self._tracks.values():
            tr.activity *= self.ACTIVITY_DECAY

        # 2. Assign observations to existing tracks by proximity
        seen_this_frame: set[int] = set()
        unmatched: list[FaceObservation] = []
        for ob in obs_list:
            match = self._nearest_track(ob)
            if match is None:
                unmatched.append(ob)
            else:
                match.last_seen = frame
                match.cx = ob.cx
                match.cy = ob.cy
                match.w = ob.w
                match.h = ob.h
                match.activity = 1.0  # refresh
                seen_this_frame.add(match.face_id)

        # 3. New tracks for unmatched observations
        for ob in unmatched:
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = TrackedFace(
                face_id=tid,
                first_seen=frame,
                last_seen=frame,
                cx=ob.cx,
                cy=ob.cy,
                w=ob.w,
                h=ob.h,
                activity=1.0,
            )
            seen_this_frame.add(tid)

        # 4. Retire dead tracks (no obs for 2 s @ 30 fps ≈ 60 f)
        dead = [fid for fid, tr in self._tracks.items()
                if tr.last_seen < frame - 60 and tr.activity < 0.05]
        for fid in dead:
            del self._tracks[fid]

        # 5. Apply sticky bonus *only when the active track was still
        #    observed in this frame*. An active speaker who walked out
        #    of shot must surrender the floor once a still-present
        #    candidate beats their decaying score.
        for tr in self._tracks.values():
            if tr.face_id == self._active_id and tr.face_id in seen_this_frame:
                tr.speaker_bonus = self.SPEAKER_BONUS
            else:
                tr.speaker_bonus = 0.0

        # 6. Decide who should be active now — restrict candidates to
        #    tracks seen this frame so we never promote a disappearing
        #    face just because its old activity hasn't fully decayed.
        candidates = [tr for tr in self._tracks.values() if tr.face_id in seen_this_frame]
        if not candidates:
            # Keep the last active speaker visible if they're still alive
            return self._tracks.get(self._active_id)

        best = max(candidates, key=lambda t: t.total_score)

        if best.face_id != self._active_id:
            if frame - self._last_switch_frame >= self.SWITCH_COOLDOWN_FRAMES:
                self._active_id = best.face_id
                self._last_switch_frame = frame
                for tr in self._tracks.values():
                    tr.speaker_bonus = self.SPEAKER_BONUS if tr.face_id == self._active_id else 0.0
            # else: hold previous speaker, return below

        if self._active_id is None or self._active_id not in self._tracks:
            self._active_id = best.face_id
            self._last_switch_frame = frame

        return self._tracks.get(self._active_id)

    # ------------------------------------------------------------ helpers
    def _nearest_track(self, ob: FaceObservation) -> TrackedFace | None:
        if not self._tracks:
            return None
        best: TrackedFace | None = None
        best_distance = float("inf")
        threshold = max(ob.w, 1.0) * self.PROXIMITY_FRAC
        for tr in self._tracks.values():
            dx = tr.cx - ob.cx
            dy = tr.cy - ob.cy
            distance = (dx * dx + dy * dy) ** 0.5
            if distance < best_distance:
                best_distance = distance
                best = tr
        if best is None or best_distance > threshold:
            return None
        return best
