"""Reframe plan hardening — guard against NaN/Inf track points."""

from __future__ import annotations

import math
import unittest
from dataclasses import dataclass
from pathlib import Path

from core.probe import VideoInfo
from core.reframe import ReframeMode, build_plan


@dataclass(frozen=True)
class _Pt:
    t: float
    x: float
    confidence: float = 1.0


def _info() -> VideoInfo:
    return VideoInfo(
        path=Path("/tmp/fake.mp4"),
        width=1920,
        height=1080,
        duration=10.0,
        fps=30.0,
        codec="h264",
        has_audio=False,
        audio_codec=None,
        r_fps=30.0,
        avg_fps=30.0,
    )


class TrackPointSanitisationTests(unittest.TestCase):
    def test_mixed_clean_and_dirty_points_sanitised(self) -> None:
        from core.presets import default_preset
        pts = [
            _Pt(t=0.0, x=0.5),
            _Pt(t=1.0, x=float("nan")),
            _Pt(t=2.0, x=float("inf")),
            _Pt(t=3.0, x=0.5),
        ]
        plan = build_plan(
            _info(),
            default_preset(),
            ReframeMode.SMART_TRACK,
            manual_x=0.5,
            track_points=pts,
        )
        self.assertIn("crop=", plan.video_filter)
        # No NaN / Inf should leak into the filter expression.
        self.assertNotIn("nan", plan.video_filter.lower())
        self.assertNotIn("inf", plan.video_filter.lower())

    def test_only_bad_points_falls_back_to_center(self) -> None:
        from core.presets import default_preset
        pts = [
            _Pt(t=float("nan"), x=0.4),
            _Pt(t=1.0, x=float("nan")),
        ]
        plan = build_plan(
            _info(),
            default_preset(),
            ReframeMode.SMART_TRACK,
            manual_x=0.5,
            track_points=pts,
        )
        # Must succeed (center fallback) rather than throw or emit NaN.
        self.assertIn("crop=", plan.video_filter)
        self.assertNotIn("nan", plan.video_filter.lower())


if __name__ == "__main__":
    unittest.main()
