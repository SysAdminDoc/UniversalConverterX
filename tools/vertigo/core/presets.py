"""Output presets for the major vertical platforms."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    tagline: str
    width: int
    height: int
    fps: int
    max_duration: int  # seconds; 0 = unlimited
    video_bitrate: str
    audio_bitrate: str

    @property
    def aspect(self) -> float:
        return self.width / self.height

    @property
    def resolution_label(self) -> str:
        return f"{self.width}x{self.height}"


PRESETS: dict[str, Preset] = {
    "shorts": Preset(
        id="shorts",
        label="YouTube Shorts",
        tagline="1080x1920 · 60fps · ≤60s",
        width=1080,
        height=1920,
        fps=60,
        max_duration=60,
        video_bitrate="8M",
        audio_bitrate="192k",
    ),
    "tiktok": Preset(
        id="tiktok",
        label="TikTok",
        tagline="1080x1920 · 60fps · ≤180s",
        width=1080,
        height=1920,
        fps=60,
        max_duration=180,
        video_bitrate="7M",
        audio_bitrate="192k",
    ),
    "reels": Preset(
        id="reels",
        label="Instagram Reels",
        tagline="1080x1920 · 30fps · ≤90s",
        width=1080,
        height=1920,
        fps=30,
        max_duration=90,
        video_bitrate="6M",
        audio_bitrate="192k",
    ),
    "square": Preset(
        id="square",
        label="Square (1:1)",
        tagline="1080x1080 · 30fps",
        width=1080,
        height=1080,
        fps=30,
        max_duration=0,
        video_bitrate="6M",
        audio_bitrate="192k",
    ),
}


def default_preset() -> Preset:
    return PRESETS["shorts"]
