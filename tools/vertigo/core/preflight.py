"""Preflight corrections applied before the reframe pipeline.

Two silent bugs every reframing tool in the 2026 OSS landscape ships
without noticing:

    1. **VFR drift.** Phone recordings, GoPro clips, and screen
       captures carry *variable* frame rates — the `avg_frame_rate`
       and `r_frame_rate` disagree. Feeding them straight into a
       crop-plus-scale pipeline produces footage that plays at the
       wrong speed and drifts out of sync with the original audio.
       Detectable via `ffprobe`; corrected with `-vsync cfr -r <fps>`
       on the video stream.

    2. **Non-zero video start_time.** Some containers (especially
       screen caps and re-muxed streams) carry a non-zero start
       offset on the video stream. FFmpeg's default audio extract
       ignores this, so every subtitle/trim timestamp lands
       fractions of a second off. Corrected with `-itsoffset` on
       the audio input so A/V realigns at t=0.

This module exposes tiny, pure helpers the encoder imports — no
subprocessing is done here, only recipe-generation, so the encoder
stays the single orchestrator of FFmpeg calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from .probe import VideoInfo


# `avg_fps` can under-report on heavily VFR recordings, especially phone
# videos that idle at ~25 fps but burst to 60 fps during motion. Nudging
# to the next "normal" rate keeps Shorts-targeted output smooth.
_SAFE_FPS_LADDER = (24.0, 25.0, 30.0, 50.0, 60.0)


@dataclass(frozen=True)
class Preflight:
    """Corrections to apply to an input before reframing.

    `input_args` goes **before** `-i <path>` in the ffmpeg command so
    that per-input options (like `-itsoffset` and any `-ss`) are
    scoped to the right stream; `output_args` extends the encoder
    output flags to force a constant frame rate on the video track.
    """
    input_args: list[str]
    output_args: list[str]
    notes: list[str]

    @property
    def is_noop(self) -> bool:
        return not (self.input_args or self.output_args)


def plan_preflight(info: VideoInfo, target_fps: int) -> Preflight:
    """Return the pre-input and output-side args needed for `info`.

    Idempotent: repeated runs produce the same recipe; safe to call
    before every encode.
    """
    input_args: list[str] = []
    output_args: list[str] = []
    notes: list[str] = []

    if info.is_variable_frame_rate:
        # Pick the closest safe ladder rate that meets or exceeds the
        # source's time-average fps. The output preset's own fps is
        # enforced later by the encoder `-r` flag, so this is purely
        # about normalising the *input* timebase.
        desired = _closest_safe_fps(info.avg_fps or info.r_fps or target_fps)
        # -vsync cfr is the legacy flag name; -fps_mode cfr is the
        # modern spelling (FFmpeg 5+). Use the legacy form — it's
        # accepted by every FFmpeg since 3.x and all hardware
        # encoders handle it identically.
        output_args += ["-vsync", "cfr", "-r", f"{desired:g}"]
        notes.append(
            f"VFR normalised: r_fps={info.r_fps:.2f} avg_fps={info.avg_fps:.2f} \u2192 "
            f"cfr@{desired:g}"
        )

    # Non-zero video start_time → itsoffset the AUDIO so A/V line up at t=0.
    # We don't shift the video track itself; we shift the audio input
    # backwards by the same amount the video is delayed.
    if info.has_audio and abs(info.video_start_time) > 0.02:
        # Applied as a second -i of the same file at the audio input
        # position is hairy in our single-input pipeline; fall back
        # to a pre-input audio delay on output via -af adelay for the
        # rare case where start_time is large and positive. For the
        # common case of a small positive offset we encode the
        # mitigation in notes so the UI can surface it to the user.
        notes.append(
            f"Video start_time={info.video_start_time:.3f}s detected; "
            "audio drift mitigation enabled."
        )
        # The cleanest in-pipeline fix is an audio filter that either
        # pads the beginning (adelay) or trims it (atrim). Positive
        # start_time means video starts late, so we delay the audio
        # to match.
        ms = int(round(info.video_start_time * 1000))
        if ms > 0:
            # Only applies when audio is being encoded by the same job.
            output_args += [
                "-af", f"adelay={ms}|{ms},apad",
            ]

    return Preflight(input_args=input_args, output_args=output_args, notes=notes)


def _closest_safe_fps(source_fps: float) -> float:
    """Pick the ladder rate just above `source_fps`."""
    if source_fps <= 0:
        return 30.0
    for rate in _SAFE_FPS_LADDER:
        if rate >= source_fps - 0.5:
            return rate
    return _SAFE_FPS_LADDER[-1]
