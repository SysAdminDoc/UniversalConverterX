"""Vertigo core — reframing, detection, encoding."""

from .presets import PRESETS, Preset
from .probe import VideoInfo, probe
from .reframe import Adjustments, ReframeMode, ReframePlan, build_plan
from .detect import FaceTracker, TrackPoint
from .scenes import detect_scenes

__all__ = [
    "PRESETS",
    "Preset",
    "VideoInfo",
    "probe",
    "Adjustments",
    "ReframeMode",
    "ReframePlan",
    "build_plan",
    "FaceTracker",
    "TrackPoint",
    "detect_scenes",
]
