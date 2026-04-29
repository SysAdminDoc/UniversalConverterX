"""Reframe engine — builds an FFmpeg filter graph for each crop mode.

Modes:
  - CENTER        : static center crop to target aspect.
  - SMART_TRACK   : per-second crop center from a tracked subject path,
                    optionally scene-aware (no panning across cuts).
  - BLUR_LETTERBOX: full frame over a blurred/scaled background.
  - MANUAL        : static crop column at user-specified x (0..1).

Post-processing:
  - optional `eq` filter appended for brightness / contrast / saturation
  - optional `setpts` for no-op trim slop
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .overlays import TextOverlay, build_filter_chain as build_overlay_chain
from .presets import Preset
from .probe import VideoInfo


# Hard ceiling on how many keyframes go into the FFmpeg crop-x expression.
# libavfilter parses the nested ``if(between(t,...))`` chain recursively;
# 512 levels deep on a release build is well within the safe zone across
# the FFmpeg versions we bundle (tested 4.4 → 7.1), and 128 keyframes is
# plenty for smooth pans over a long clip. Higher counts get strided
# down — we lose nothing in visual quality because the Savitzky-Golay
# pass has already low-passed the series.
_MAX_TRACK_EXPR_POINTS = 128


@dataclass
class Adjustments:
    brightness: float = 0.0   # -1.0 .. 1.0
    contrast: float = 1.0     #  0.0 .. 2.0
    saturation: float = 1.0   #  0.0 .. 3.0

    @property
    def is_identity(self) -> bool:
        return (
            abs(self.brightness) < 1e-3
            and abs(self.contrast - 1.0) < 1e-3
            and abs(self.saturation - 1.0) < 1e-3
        )

    def as_eq_filter(self) -> str:
        return (
            f"eq=brightness={self.brightness:.3f}"
            f":contrast={self.contrast:.3f}"
            f":saturation={self.saturation:.3f}"
        )


class ReframeMode(str, Enum):
    CENTER = "center"
    SMART_TRACK = "smart_track"
    BLUR_LETTERBOX = "blur_letterbox"
    MANUAL = "manual"


@dataclass
class ReframePlan:
    video_filter: str
    audio_args: list[str] = field(default_factory=list)
    requires_scale_fps: bool = True
    notes: str = ""


def build_plan(
    info: VideoInfo,
    preset: Preset,
    mode: ReframeMode,
    *,
    manual_x: float = 0.5,
    track_points: list | None = None,
    scenes: list[tuple[float, float]] | None = None,
    adjustments: Adjustments | None = None,
    overlays: list[TextOverlay] | None = None,
) -> ReframePlan:
    """Return a ReframePlan whose `video_filter` string can be dropped
    into an `ffmpeg -vf <...>` call.
    """
    target_w, target_h = preset.width, preset.height

    if mode is ReframeMode.CENTER:
        plan = _plan_center(info, target_w, target_h, preset.fps)
    elif mode is ReframeMode.MANUAL:
        plan = _plan_manual(info, target_w, target_h, preset.fps, manual_x)
    elif mode is ReframeMode.BLUR_LETTERBOX:
        plan = _plan_blur(info, target_w, target_h, preset.fps)
    elif mode is ReframeMode.SMART_TRACK:
        pts = _scene_clamp(track_points or [], scenes or [])
        plan = _plan_track(info, target_w, target_h, preset.fps, pts)
        if scenes:
            plan.notes += f"  \u00b7 {len(scenes)} scene(s)"
    else:
        raise ValueError(f"Unknown reframe mode: {mode}")

    if adjustments and not adjustments.is_identity:
        plan.video_filter += "," + adjustments.as_eq_filter()
        plan.notes += f"  \u00b7 adj({adjustments.brightness:+.2f}/{adjustments.contrast:.2f}/{adjustments.saturation:.2f})"

    if overlays:
        chain = build_overlay_chain(overlays)
        if chain:
            plan.video_filter += "," + chain
            plan.notes += f"  \u00b7 {len([o for o in overlays if o.text.strip()])} overlay(s)"

    return plan


# ---------------- crop column size ----------------

def _crop_dims(info: VideoInfo, target_w: int, target_h: int) -> tuple[int, int]:
    """Return (crop_w, crop_h) in source pixels that match target aspect.
    We keep the full source height and crop width; if source is taller than
    target aspect, we crop height instead.

    Guards all four inputs so a malformed preset or a corrupt probe can't
    raise ZeroDivisionError inside the export pipeline. On bad input we
    fall back to the source dimensions (no crop) which is a safe no-op.
    """
    if target_w <= 0 or target_h <= 0 or info.width <= 0 or info.height <= 0:
        w = max(2, info.width)
        h = max(2, info.height)
        # keep even dimensions for yuv420p downstream
        return w - w % 2, h - h % 2

    target_aspect = target_w / target_h
    src_aspect = info.width / info.height
    if src_aspect >= target_aspect:
        crop_h = info.height
        crop_w = int(round(info.height * target_aspect))
        crop_w -= crop_w % 2
    else:
        crop_w = info.width
        crop_h = int(round(info.width / target_aspect))
        crop_h -= crop_h % 2
    # Final clamp: never return < 2 (FFmpeg rejects 0-area crops).
    crop_w = max(2, crop_w)
    crop_h = max(2, crop_h)
    return crop_w, crop_h


# ---------------- strategies ----------------

def _plan_center(info: VideoInfo, tw: int, th: int, fps: int) -> ReframePlan:
    cw, ch = _crop_dims(info, tw, th)
    vf = (
        f"crop={cw}:{ch}:(iw-{cw})/2:(ih-{ch})/2,"
        f"scale={tw}:{th}:flags=lanczos,fps={fps},setsar=1"
    )
    return ReframePlan(video_filter=vf, notes="Center crop")


def _plan_manual(info: VideoInfo, tw: int, th: int, fps: int, x_norm: float) -> ReframePlan:
    cw, ch = _crop_dims(info, tw, th)
    x_norm = min(max(x_norm, 0.0), 1.0)
    max_x = max(0, info.width - cw)
    x_px = int(round(x_norm * max_x))
    x_px -= x_px % 2
    vf = (
        f"crop={cw}:{ch}:{x_px}:(ih-{ch})/2,"
        f"scale={tw}:{th}:flags=lanczos,fps={fps},setsar=1"
    )
    return ReframePlan(video_filter=vf, notes=f"Manual crop at x={x_norm:.2f}")


def _plan_blur(info: VideoInfo, tw: int, th: int, fps: int) -> ReframePlan:
    """Scaled-blur background with original video fit centered on top.

    We render two streams with split, blur one to fill tw:th, scale the other
    to fit inside, then overlay.
    """
    vf = (
        f"split=2[bg][fg];"
        f"[bg]scale={tw}:{th}:force_original_aspect_ratio=increase,"
        f"crop={tw}:{th},boxblur=luma_radius=40:luma_power=2[bgb];"
        f"[fg]scale={tw}:{th}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,fps={fps},setsar=1"
    )
    return ReframePlan(video_filter=vf, notes="Blurred letterbox background")


def _plan_track(
    info: VideoInfo,
    tw: int,
    th: int,
    fps: int,
    track_points: list,
) -> ReframePlan:
    """Piecewise-linear x position driven by track points.

    FFmpeg's crop filter accepts an expression for `x`. We build an
    `if(between(t,a,b), x, ...)` chain interpolating between samples.
    If no points provided, falls back to center crop.

    Before building the expression we apply a Savitzky-Golay low-pass
    filter to the x(t) series — kills micro-jitter from per-frame
    detection noise without introducing perceivable latency. Idea
    borrowed from bmezaris/RetargetVid (ICIP 2021).
    """
    import math

    cw, ch = _crop_dims(info, tw, th)
    if not track_points:
        return _plan_center(info, tw, th, fps)

    # Drop any track point with non-finite x or t before feeding FFmpeg's
    # expression parser; a single NaN/Inf poisons the whole crop filter.
    clean = [
        p for p in track_points
        if math.isfinite(getattr(p, "t", float("nan")))
        and math.isfinite(getattr(p, "x", float("nan")))
    ]
    if not clean:
        return _plan_center(info, tw, th, fps)

    max_x = max(0, info.width - cw)
    pts = sorted(clean, key=lambda p: p.t)
    pts = _smooth_track(pts, source_fps=info.fps)
    pts = _stride_for_expression(pts, _MAX_TRACK_EXPR_POINTS)
    expr = _x_expression(pts, cw, info.width, max_x)
    vf = (
        f"crop={cw}:{ch}:'{expr}':(ih-{ch})/2,"
        f"scale={tw}:{th}:flags=lanczos,fps={fps},setsar=1"
    )
    return ReframePlan(
        video_filter=vf,
        notes=f"Smart-track ({len(pts)} keyframes, smoothed)",
    )


def _smooth_track(points: list, source_fps: float) -> list:
    """Apply a Savitzky-Golay low-pass over the x-coordinate series.

    Falls back to the raw points if scipy is unavailable or if the
    sample count is too small for the chosen window.
    """
    if len(points) < 5:
        return points
    try:
        from scipy.signal import savgol_filter
        import numpy as np
    except ImportError:
        return points

    xs = np.array([p.x for p in points], dtype=float)

    # Window length tracks ~0.5 s at the source frame rate, clamped to
    # an odd value in [5, len(points) | odd-1]. Polyorder < window.
    target = max(5, int(round((source_fps or 30.0) * 0.5)))
    window = min(target, len(points) - (1 if len(points) % 2 == 0 else 0))
    if window % 2 == 0:
        window -= 1
    if window < 5:
        return points

    smoothed = savgol_filter(xs, window_length=window, polyorder=3, mode="nearest")
    smoothed = np.clip(smoothed, 0.0, 1.0)

    from .detect import TrackPoint
    return [
        TrackPoint(t=p.t, x=float(sx), confidence=p.confidence)
        for p, sx in zip(points, smoothed)
    ]


def _stride_for_expression(points: list, limit: int) -> list:
    """Downsample ``points`` to at most ``limit`` entries, preserving the
    first and last keyframes exactly.

    libavfilter parses the generated ``if()`` chain recursively, and a
    very long clip with a 2 fps track can produce 600+ points — enough
    to trigger expression-parser stack issues on some FFmpeg builds.
    Striding evenly keeps the start / end pose exact and trims the middle
    where smoothing has already flattened short-term variation.
    """
    n = len(points)
    if n <= limit or limit <= 2:
        return points
    # Pick ``limit`` indices spread evenly across [0, n-1]; round to the
    # nearest int so we don't truncate toward 0.
    step = (n - 1) / (limit - 1)
    kept: list = []
    last_idx = -1
    for i in range(limit):
        idx = int(round(i * step))
        if idx != last_idx:
            kept.append(points[idx])
            last_idx = idx
    # Guarantee the last point is included even when rounding lands short.
    if kept[-1] is not points[-1]:
        kept.append(points[-1])
    return kept


def _scene_clamp(pts: list, scenes: list[tuple[float, float]]) -> list:
    """Fold the track into per-scene segments so the viewport never pans
    across a cut.

    Strategy per scene: take the median x of points inside the scene, then
    emit a start-keyframe and end-keyframe at that x. The tiny dt at scene
    boundaries creates an instant jump in the piecewise-lerp graph rather
    than a smooth pan.
    """
    if not scenes or not pts:
        return pts

    from statistics import median

    out = []
    for (a, b) in scenes:
        inside = [p for p in pts if a <= p.t <= b]
        if not inside:
            xs = [p.x for p in pts if p.t <= b]
            if not xs:
                continue
            x = xs[-1]
        else:
            x = median(p.x for p in inside)

        from .detect import TrackPoint
        out.append(TrackPoint(t=a + 0.001, x=float(x), confidence=0.9))
        out.append(TrackPoint(t=max(a + 0.002, b - 0.001), x=float(x), confidence=0.9))

    return out


def _x_expression(pts, crop_w: int, src_w: int, max_x: int) -> str:
    """Piecewise-linear x(t) clamped to [0, max_x], nested if() chain.

    Shape:
        if(lt(t,t0), x0,
         if(between(t,t0,t1), lerp01,
          if(between(t,t1,t2), lerp12,
           ... xN)))
    """
    def to_x(p):
        cx_px = p.x * src_w
        left = cx_px - crop_w / 2
        return max(0.0, min(float(max_x), left))

    if len(pts) == 1:
        return f"{to_x(pts[0]):.2f}"

    first_x = f"{to_x(pts[0]):.2f}"
    expr = f"{to_x(pts[-1]):.2f}"  # tail: hold last value

    for i in range(len(pts) - 2, -1, -1):
        a, b = pts[i], pts[i + 1]
        xa, xb = to_x(a), to_x(b)
        dt = max(1e-6, b.t - a.t)
        lerp = f"{xa:.2f}+({xb - xa:.3f})*(t-{a.t:.3f})/{dt:.3f}"
        expr = f"if(between(t\\,{a.t:.3f}\\,{b.t:.3f})\\,{lerp}\\,{expr})"

    expr = f"if(lt(t\\,{pts[0].t:.3f})\\,{first_x}\\,{expr})"
    return expr
