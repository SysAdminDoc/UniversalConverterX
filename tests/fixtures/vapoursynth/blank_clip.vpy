"""Deterministic built-in-only VapourSynth smoke fixture."""

import vapoursynth as vs


clip = vs.core.std.BlankClip(
    width=64,
    height=64,
    length=12,
    fpsnum=24,
    fpsden=1,
    format=vs.YUV420P8,
    color=[16, 128, 128],
)
clip.set_output()
