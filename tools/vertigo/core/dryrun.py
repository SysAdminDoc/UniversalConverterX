"""Dry-run plan reporter — shows what would happen, without encoding.

Pure synthesis over the existing probe / scenes / track / reframe
pipeline: no FFmpeg is invoked. Output is a human-readable report
suitable for rendering into a text panel, copying to the clipboard,
or printing to the console.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .detect import TrackPoint
from .encoders import Encoder
from .hook_score import score_hook
from .preflight import plan_preflight
from .presets import Preset
from .probe import VideoInfo
from .reframe import Adjustments, ReframeMode, build_plan


@dataclass(frozen=True)
class DryRunRow:
    label: str
    value: str


@dataclass(frozen=True)
class DryRunReport:
    rows: list[DryRunRow]

    def as_text(self) -> str:
        width = max((len(r.label) for r in self.rows), default=0)
        lines = [f"  {r.label.ljust(width)}  {r.value}" for r in self.rows]
        return "\n".join(lines)


def describe_scene_strategy(
    info: VideoInfo,
    scenes: list[tuple[float, float]],
    track_points: list[TrackPoint] | None,
    crop_width_frac: float | None,
) -> list[DryRunRow]:
    """Per-scene one-line summary: duration, strategy, mean subject x."""
    rows: list[DryRunRow] = []
    if not scenes:
        return rows

    points = track_points or []

    for i, (start, end) in enumerate(scenes, start=1):
        # Which track points fall inside this scene?
        window = [p for p in points if start <= p.t <= end]
        if window:
            mean_x = sum(p.x for p in window) / len(window)
            spread = max(p.x for p in window) - min(p.x for p in window)
            strategy = "TRACK" if spread > 0.08 else "HOLD"
            detail = f"subject ~{mean_x:.2f} \u00b7 spread {spread:.2f}"
        elif crop_width_frac and crop_width_frac >= 0.85:
            strategy = "CENTER"
            detail = "viewport spans most of the frame"
        else:
            strategy = "LETTERBOX"
            detail = "no face data \u2014 fill with blurred backdrop"

        rows.append(
            DryRunRow(
                label=f"Scene {i:>2}",
                value=(
                    f"{_fmt_time(start)} \u2192 {_fmt_time(end)}  "
                    f"\u00b7  {end - start:>5.1f}s  \u00b7  {strategy}  \u00b7  {detail}"
                ),
            )
        )
    return rows


def build_report(
    *,
    info: VideoInfo,
    preset: Preset,
    mode: ReframeMode,
    track_points: list[TrackPoint] | None,
    scenes: list[tuple[float, float]] | None,
    adjustments: Adjustments | None,
    encoder: Encoder | None,
    quality: int,
    speed_preset: str | None,
    trim_start: float,
    trim_end: float | None,
    crop_width_frac: float | None,
) -> DryRunReport:
    rows: list[DryRunRow] = []

    rows.append(DryRunRow("Source", f"{info.path.name}  \u00b7  {info.width}\u00d7{info.height}  \u00b7  {info.codec}  \u00b7  {_fmt_time(info.duration)}"))

    out_duration = (trim_end or info.duration) - (trim_start or 0.0)
    rows.append(DryRunRow(
        "Output",
        f"{preset.resolution_label}  \u00b7  {preset.fps}\u202ffps  \u00b7  {_fmt_time(out_duration)}",
    ))

    enc_label = encoder.label if encoder else "auto"
    rows.append(DryRunRow(
        "Encoder",
        f"{enc_label}  \u00b7  quality {quality}  \u00b7  speed {speed_preset or 'default'}",
    ))

    rows.append(DryRunRow("Mode", mode.value.replace("_", " ").title()))

    # Hook-energy score on the first 3 s of audio — a signal, not a verdict
    if info.has_audio:
        try:
            hook = score_hook(info.path, window_sec=3.0)
            rows.append(DryRunRow(
                "Hook (first 3s)",
                f"{hook.as_badge()}  \u00b7  voice {hook.voice_fraction * 100:.0f}%  "
                f"\u00b7  energy {hook.mean_voiced_energy * 100:.0f}%",
            ))
        except Exception:
            pass

    plan = build_plan(
        info,
        preset,
        mode,
        track_points=track_points,
        scenes=scenes,
        adjustments=adjustments,
    )
    rows.append(DryRunRow("Reframe", plan.notes or "-"))

    preflight = plan_preflight(info, preset.fps)
    if preflight.notes:
        for note in preflight.notes:
            rows.append(DryRunRow("Preflight", note))
    else:
        rows.append(DryRunRow("Preflight", "no corrections needed"))

    if adjustments and not adjustments.is_identity:
        rows.append(DryRunRow(
            "Adjust",
            f"brightness {adjustments.brightness:+.2f}  \u00b7  "
            f"contrast {adjustments.contrast:.2f}  \u00b7  "
            f"saturation {adjustments.saturation:.2f}",
        ))

    # Per-scene breakdown
    scene_rows = describe_scene_strategy(info, scenes or [], track_points, crop_width_frac)
    if scene_rows:
        rows.append(DryRunRow("", ""))
        rows.append(DryRunRow("Timeline", f"{len(scene_rows)} scene(s)"))
        rows.extend(scene_rows)
    elif track_points:
        rows.append(DryRunRow("Timeline", f"{len(track_points)} tracking keyframes, continuous"))

    rows.append(DryRunRow("", ""))
    rows.append(DryRunRow(
        "FFmpeg -vf",
        plan.video_filter if len(plan.video_filter) <= 240
        else plan.video_filter[:240] + "\u2026",
    ))

    return DryRunReport(rows=rows)


# ---------------------------------------------------------------- helpers

def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    m = int(seconds // 60)
    s = seconds - (m * 60)
    if m >= 60:
        h = m // 60
        m = m % 60
        return f"{h}:{m:02d}:{int(s):02d}"
    return f"{m:d}:{s:05.2f}".replace("0:0", "0:")
