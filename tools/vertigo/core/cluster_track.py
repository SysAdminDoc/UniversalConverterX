"""Per-frame face/saliency clustering, then temporal filter.

Port of the "cluster + temporal-majority" step from bmezaris/RetargetVid
(MIT, ICIP 2021). The original uses saliency maps; we apply the same
idea to ``FaceObservation`` streams coming out of MediaPipe/Haar.

The problem it solves: given multiple competing faces per frame, the
crop planner currently picks one winner (largest box or speaker-sticky
best score) and can jitter when a second face briefly outranks the
intended subject. Clustering the per-frame observations spatially, then
requiring a cluster to persist across several frames before it can
become the "anchor", kills short-lived noise without adding latency.

Output shape matches input: ``list[list[FaceObservation]]`` keyed by
frame — but observations that didn't survive the cluster/time filter
are removed. Feed this directly into ``SpeakerTracker.step(frame, obs)``
in the existing detect pipeline for cleaner input.

Pure numpy — no new dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .cameraman import FaceObservation


DEFAULT_MIN_CLUSTER_PERSISTENCE = 3   # frames a cluster must appear in
DEFAULT_SPATIAL_TOL_FRAC = 0.15       # cluster radius as frac of source width
DEFAULT_TEMPORAL_WINDOW = 5           # rolling window over which we check persistence


@dataclass(frozen=True)
class _FrameObservations:
    frame: int
    t: float
    observations: list[FaceObservation]


def cluster_filter(
    frames: Iterable[Iterable[FaceObservation]],
    *,
    source_width: int,
    spatial_tol_frac: float = DEFAULT_SPATIAL_TOL_FRAC,
    min_persistence: int = DEFAULT_MIN_CLUSTER_PERSISTENCE,
    temporal_window: int = DEFAULT_TEMPORAL_WINDOW,
) -> list[list[FaceObservation]]:
    """Return filtered per-frame observations.

    Each input element is the list of ``FaceObservation``s detected on
    one frame. Output mirrors that shape but removes observations that
    belong to short-lived clusters.

    The algorithm has two passes:

    1. **Spatial cluster**: within each frame, group observations by
       centre-x proximity (within ``spatial_tol_frac * source_width``).
       This collapses duplicate detections from the two face detectors
       that sometimes disagree by a few pixels.
    2. **Temporal persistence**: over a rolling ``temporal_window`` of
       frames, only keep clusters whose centre-x is reproduced by
       neighbouring frames ``min_persistence`` times. A face that
       appears once and disappears is treated as noise and dropped.
    """
    buf = _to_frame_list(frames)
    if not buf:
        return []

    tol_px = max(1.0, float(spatial_tol_frac) * float(source_width))
    clustered: list[list[list[FaceObservation]]] = [
        _cluster_one_frame(f.observations, tol_px) for f in buf
    ]
    return _temporal_filter(
        frames=buf,
        clusters=clustered,
        min_persistence=max(1, int(min_persistence)),
        window=max(1, int(temporal_window)),
        tol_px=tol_px,
    )


# ---------------------------------------------------------------- stage 1

def _cluster_one_frame(
    observations: Iterable[FaceObservation],
    tol_px: float,
) -> list[list[FaceObservation]]:
    """Group observations whose centres lie within ``tol_px``.

    Greedy single-pass clustering — O(n^2) in the number of faces per
    frame. Typical counts are 1–5 so the overhead is negligible.
    """
    obs = list(observations)
    clusters: list[list[FaceObservation]] = []
    for o in obs:
        placed = False
        for c in clusters:
            cx_mean = sum(x.cx for x in c) / len(c)
            if abs(o.cx - cx_mean) <= tol_px:
                c.append(o)
                placed = True
                break
        if not placed:
            clusters.append([o])
    return clusters


def _cluster_centroid(cluster: list[FaceObservation]) -> float:
    return sum(o.cx for o in cluster) / max(1, len(cluster))


# ---------------------------------------------------------------- stage 2

def _temporal_filter(
    *,
    frames: list[_FrameObservations],
    clusters: list[list[list[FaceObservation]]],
    min_persistence: int,
    window: int,
    tol_px: float,
) -> list[list[FaceObservation]]:
    """Drop clusters that aren't reproduced in at least ``min_persistence``
    frames inside a rolling window of ``window`` frames around the
    current one.
    """
    out: list[list[FaceObservation]] = []
    n = len(clusters)
    # Pre-compute centroids for each frame's clusters so the rolling-window
    # check is just an inner distance comparison.
    centroids = [
        [_cluster_centroid(c) for c in frame_clusters]
        for frame_clusters in clusters
    ]

    for i, frame_clusters in enumerate(clusters):
        kept: list[FaceObservation] = []
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        for k, cluster in enumerate(frame_clusters):
            cx = centroids[i][k]
            count = 0
            for j in range(lo, hi):
                for oc in centroids[j]:
                    if abs(cx - oc) <= tol_px:
                        count += 1
                        break  # at most one hit per neighbour frame
                if count >= min_persistence:
                    break
            if count >= min_persistence:
                kept.extend(cluster)
        out.append(kept)
    return out


# ---------------------------------------------------------------- helpers

def _to_frame_list(
    frames: Iterable[Iterable[FaceObservation]],
) -> list[_FrameObservations]:
    """Normalise the input so stage-2 can index by frame number."""
    out: list[_FrameObservations] = []
    last_frame = -1
    last_t = 0.0
    for idx, obs in enumerate(frames):
        obs_list = list(obs)
        if obs_list:
            frame_no = obs_list[0].frame
            t_val = obs_list[0].t
        else:
            # Empty-frame case: reuse the previous t/frame so the buffer
            # stays monotonic. Better than dropping the slot, which would
            # break the rolling window.
            frame_no = last_frame + 1
            t_val = last_t
        out.append(_FrameObservations(frame=frame_no, t=t_val, observations=obs_list))
        last_frame = frame_no
        last_t = t_val
    return out
