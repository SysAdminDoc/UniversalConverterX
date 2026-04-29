"""BoxMOT-based multi-object tracker for speaker identity.

BoxMOT (https://github.com/mikel-brostrom/boxmot, AGPL-3.0) is a tracker
zoo — ByteTrack / BoT-SORT / OC-SORT / DeepOCSORT / StrongSORT /
HybridSORT — behind one API. It replaces Vertigo's simple proximity
matcher (``core.cameraman.SpeakerTracker``) with motion-model tracking
plus optional appearance features, giving stable per-speaker IDs across
occlusion, rapid camera motion, and multi-speaker crosses.

This module is a Vertigo-shaped adapter: it produces objects compatible
with ``core.cameraman.TrackedFace`` so the rest of the pipeline
(the crop planner, the cameraman smoother, the UI status) keeps
working unchanged.

Licensing: BoxMOT is AGPL-3.0. For Vertigo's desktop PyInstaller builds
this is acceptable (no network service). If Vertigo ever ships a
hosted/SaaS variant, the AGPL terms kick in — document the clean
fallback to ``SpeakerTracker`` in that build configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .cameraman import FaceObservation, SpeakerTracker, TrackedFace


# ---------------------------------------------------------------- availability

def is_available() -> bool:
    try:
        import boxmot  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_installed() -> bool:
    if is_available():
        return True
    from ._lazy import pip_install
    if not pip_install("boxmot>=11"):
        return False
    return is_available()


# ---------------------------------------------------------------- factory

def make_tracker(
    *,
    prefer: str = "botsort",
    reid_enabled: bool = True,
) -> "TrackerAdapter":
    """Return the best tracker available on the current install.

    Falls back cleanly to the built-in ``SpeakerTracker`` when BoxMOT is
    missing, so callers can always do::

        tracker = make_tracker()
        for frame_idx, obs in stream:
            tracked = tracker.step(frame_idx, obs)

    ``prefer`` selects the BoxMOT tracker kind ("botsort", "bytetrack",
    "ocsort", "deepocsort", "strongsort"). ``reid_enabled`` controls
    appearance-feature re-identification — disable for lighter CPUs.
    """
    if is_available():
        return BoxMotTrackerAdapter(prefer=prefer, reid_enabled=reid_enabled)
    return FallbackTrackerAdapter()


# ---------------------------------------------------------------- adapter base

class TrackerAdapter:
    """Uniform interface: identical to ``SpeakerTracker.step``.

    Produces a ``TrackedFace`` for the current "active speaker" (or
    None when no face is visible), so the rest of Vertigo can swap
    trackers without changing a line of downstream code.
    """

    def step(self, frame: int, observations: Iterable[FaceObservation]) -> TrackedFace | None:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError


class FallbackTrackerAdapter(TrackerAdapter):
    """Same ``SpeakerTracker`` that Vertigo has always used.

    Shipped as the default when BoxMOT isn't installed. This keeps the
    factory contract simple: ``make_tracker()`` always returns a usable
    object.
    """

    def __init__(self) -> None:
        self._inner = SpeakerTracker()

    def step(self, frame: int, observations: Iterable[FaceObservation]) -> TrackedFace | None:
        return self._inner.step(frame, observations)

    def reset(self) -> None:
        self._inner = SpeakerTracker()


# ---------------------------------------------------------------- BoxMOT impl

class BoxMotTrackerAdapter(TrackerAdapter):
    """BoT-SORT / ByteTrack-backed adapter with ID-sticky speaker pick.

    BoxMOT operates on (x1, y1, x2, y2, score, class) arrays, not our
    ``FaceObservation``. This class handles the conversion in both
    directions and layers the speaker-bonus / switch-cooldown logic on
    top — same heuristic ``SpeakerTracker`` uses so the UX remains
    identical.
    """

    _KIND_MAP = {
        "botsort":     "BoTSORT",
        "bytetrack":   "ByteTrack",
        "ocsort":      "OCSORT",
        "deepocsort":  "DeepOCSORT",
        "strongsort":  "StrongSORT",
    }

    def __init__(self, *, prefer: str, reid_enabled: bool) -> None:
        import boxmot  # guarded by is_available() at the factory
        import numpy as np  # noqa: F401  (imported for type & shape hints)

        klass_name = self._KIND_MAP.get(prefer, "BoTSORT")
        klass = getattr(boxmot, klass_name, None)
        if klass is None:
            raise RuntimeError(
                f"BoxMOT is installed but does not expose {klass_name}. "
                f"Upgrade with `pip install -U boxmot`."
            )

        kwargs: dict = {}
        # Most BoxMOT trackers accept 'with_reid' and a reid weights path;
        # we stay model-agnostic by only passing flags we know the class
        # accepts.
        try:
            import inspect
            sig = inspect.signature(klass)
            if "with_reid" in sig.parameters:
                kwargs["with_reid"] = bool(reid_enabled)
            if "half" in sig.parameters:
                kwargs["half"] = False
        except Exception:
            pass

        self._tracker = klass(**kwargs)
        self._prefer = prefer
        self._reid_enabled = reid_enabled
        self._active_id: int | None = None
        self._last_switch_frame: int = -10**9
        self._switch_cooldown = 30
        self._history: dict[int, TrackedFace] = {}

    def step(self, frame: int, observations: Iterable[FaceObservation]) -> TrackedFace | None:
        import numpy as np

        obs_list = list(observations)
        if not obs_list:
            self._decay(frame)
            return self._history.get(self._active_id) if self._active_id else None

        # BoxMOT expects N x 6 float array: [x1, y1, x2, y2, conf, cls]
        dets = np.asarray(
            [
                [
                    o.cx - o.w / 2.0,
                    o.cy - o.h / 2.0,
                    o.cx + o.w / 2.0,
                    o.cy + o.h / 2.0,
                    float(o.score),
                    0.0,
                ]
                for o in obs_list
            ],
            dtype=np.float32,
        )
        # BoxMOT requires an image reference for appearance features. We
        # don't have direct frame access here — that's a feature-flag
        # tradeoff for the non-reid trackers. When reid is enabled the
        # tracker will still work with a zero image; appearance is just
        # weaker. For best results wire the actual frame through via
        # `update(dets, frame)` at a later refactor.
        img = np.zeros((1, 1, 3), dtype=np.uint8)
        try:
            out = self._tracker.update(dets, img)
        except Exception:
            # Tracker couldn't process this frame — fall back to the
            # largest observation so the cameraman still has a target.
            biggest = max(obs_list, key=lambda o: o.area)
            tracked = TrackedFace(
                face_id=-1,
                first_seen=frame,
                last_seen=frame,
                cx=biggest.cx,
                cy=biggest.cy,
                w=biggest.w,
                h=biggest.h,
                activity=1.0,
            )
            self._history[-1] = tracked
            return tracked

        # out rows: [x1, y1, x2, y2, id, conf, cls, det_idx] in most
        # tracker flavours. We take x/y + id and discard the rest.
        current_frame_ids: set[int] = set()
        for row in out:
            try:
                x1, y1, x2, y2, tid = float(row[0]), float(row[1]), float(row[2]), float(row[3]), int(row[4])
            except (IndexError, ValueError, TypeError):
                continue
            current_frame_ids.add(tid)
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            w = max(0.0, x2 - x1)
            h = max(0.0, y2 - y1)
            prev = self._history.get(tid)
            self._history[tid] = TrackedFace(
                face_id=tid,
                first_seen=prev.first_seen if prev else frame,
                last_seen=frame,
                cx=cx,
                cy=cy,
                w=w,
                h=h,
                activity=1.0,
                speaker_bonus=0.0,
            )

        self._decay(frame, current_frame_ids)
        return self._pick_active(frame, current_frame_ids)

    def reset(self) -> None:
        """Re-create the underlying tracker. Call on new clip load."""
        self.__init__(prefer=self._prefer, reid_enabled=self._reid_enabled)

    # ------------------------------------------------------------------
    def _decay(self, frame: int, seen: set[int] | None = None) -> None:
        seen = seen or set()
        for tid, tr in list(self._history.items()):
            if tid in seen:
                continue
            self._history[tid] = TrackedFace(
                face_id=tr.face_id,
                first_seen=tr.first_seen,
                last_seen=tr.last_seen,
                cx=tr.cx, cy=tr.cy, w=tr.w, h=tr.h,
                activity=tr.activity * 0.85,
                speaker_bonus=0.0,
            )
            # Drop long-dead tracks so memory doesn't grow unbounded.
            if frame - tr.last_seen > 300 and tr.activity * 0.85 < 0.02:
                del self._history[tid]

    def _pick_active(self, frame: int, seen: set[int]) -> TrackedFace | None:
        candidates = [tr for tid, tr in self._history.items() if tid in seen]
        if not candidates:
            return self._history.get(self._active_id) if self._active_id else None

        # Apply sticky-speaker bonus to the current active track when
        # it's still in-frame, so a 1-frame blink to another face
        # doesn't swap the shot.
        for tr in candidates:
            if tr.face_id == self._active_id:
                self._history[tr.face_id] = TrackedFace(
                    **{**tr.__dict__, "speaker_bonus": 3.0}
                )
        candidates = [self._history[t.face_id] for t in candidates]

        best = max(candidates, key=lambda t: t.total_score)
        if best.face_id != self._active_id:
            if frame - self._last_switch_frame >= self._switch_cooldown:
                self._active_id = best.face_id
                self._last_switch_frame = frame
        if self._active_id is None:
            self._active_id = best.face_id
            self._last_switch_frame = frame
        return self._history.get(self._active_id)


