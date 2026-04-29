"""Detect which hardware video encoders FFmpeg on the current machine
supports, then rank them by preference for H.264 and H.265 output.

We probe by running `ffmpeg -hide_banner -encoders` once and caching the
result, then map encoder names → a lightweight Encoder record the UI
and encode pipeline can use.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Encoder:
    id: str                  # internal key shown to the user
    ffmpeg_name: str         # the actual -c:v value
    label: str               # pretty label for the UI
    codec: str               # "h264" | "hevc"
    hardware: bool           # GPU-accelerated?
    quality_flag: str        # "crf" | "cq" | "qp" | "global_quality"
    quality_default: int
    preset_flag: str | None  # "preset" | "usage" | None
    preset_values: tuple[str, ...]
    preset_default: str | None


# ordered highest-priority first, per codec family
_H264_CANDIDATES: tuple[Encoder, ...] = (
    Encoder("nvenc_h264",  "h264_nvenc",        "NVIDIA NVENC (H.264)",  "h264", True,  "cq", 23, "preset", ("p1","p2","p3","p4","p5","p6","p7"), "p5"),
    Encoder("qsv_h264",    "h264_qsv",          "Intel QuickSync (H.264)","h264",True,  "global_quality", 23, "preset", ("veryfast","faster","fast","medium","slow","slower","veryslow"), "medium"),
    Encoder("amf_h264",    "h264_amf",          "AMD AMF (H.264)",       "h264", True,  "qp_i", 23, "usage", ("transcoding","ultralowlatency","lowlatency","webcam"), "transcoding"),
    Encoder("vt_h264",     "h264_videotoolbox", "Apple VideoToolbox (H.264)","h264",True,"q:v", 50, None, (), None),
    Encoder("x264",        "libx264",           "libx264 (CPU)",         "h264", False, "crf", 20, "preset", ("ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"), "medium"),
)
_HEVC_CANDIDATES: tuple[Encoder, ...] = (
    Encoder("nvenc_hevc",  "hevc_nvenc",        "NVIDIA NVENC (HEVC)",   "hevc", True,  "cq", 25, "preset", ("p1","p2","p3","p4","p5","p6","p7"), "p5"),
    Encoder("qsv_hevc",    "hevc_qsv",          "Intel QuickSync (HEVC)","hevc", True,  "global_quality", 25, "preset", ("veryfast","faster","fast","medium","slow","slower","veryslow"), "medium"),
    Encoder("amf_hevc",    "hevc_amf",          "AMD AMF (HEVC)",        "hevc", True,  "qp_i", 25, "usage", ("transcoding","ultralowlatency","lowlatency","webcam"), "transcoding"),
    Encoder("vt_hevc",     "hevc_videotoolbox", "Apple VideoToolbox (HEVC)","hevc",True,"q:v", 50, None, (), None),
    Encoder("x265",        "libx265",           "libx265 (CPU)",         "hevc", False, "crf", 24, "preset", ("ultrafast","superfast","veryfast","faster","fast","medium","slow","slower","veryslow"), "medium"),
)


@lru_cache(maxsize=1)
def ffmpeg_encoders() -> frozenset[str]:
    """Return the set of encoder names FFmpeg reports it can use."""
    bin_path = shutil.which("ffmpeg")
    if not bin_path:
        return frozenset()
    try:
        result = subprocess.run(
            [bin_path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=_no_window_flags(),
        )
    except Exception:
        return frozenset()
    names: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith(("-", "Encoders:", "Fixe", "Flags")):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            names.add(parts[1])
    return frozenset(names)


def available_encoders(codec: str = "h264") -> list[Encoder]:
    """Return encoders available on this machine for the requested codec."""
    present = ffmpeg_encoders()
    pool = _H264_CANDIDATES if codec == "h264" else _HEVC_CANDIDATES
    return [e for e in pool if e.ffmpeg_name in present]


def all_available() -> list[Encoder]:
    return available_encoders("h264") + available_encoders("hevc")


def pick_default(codec: str = "h264", *, prefer_hardware: bool = True) -> Encoder | None:
    pool = available_encoders(codec)
    if not pool:
        return None
    if prefer_hardware:
        for enc in pool:
            if enc.hardware:
                return enc
    return pool[-1]  # CPU fallback is always last


def encoder_args(encoder: Encoder, quality: int, speed_preset: str | None = None) -> list[str]:
    """Translate a user-chosen encoder + quality/speed into FFmpeg args.

    `quality` is a 1..100 slider; we map it into each encoder's native range.
    """
    q = max(1, min(100, int(quality)))

    args: list[str] = ["-c:v", encoder.ffmpeg_name]

    # Map 1..100 slider -> encoder-native quality scalar.
    if encoder.quality_flag in {"crf", "cq", "qp_i"}:
        # CRF/CQ: 0 best .. 51 worst for H.264, ~28 worst for HEVC
        lo, hi = (14, 32) if encoder.codec == "h264" else (18, 34)
        native = round(hi - (q / 100.0) * (hi - lo))
        args += [f"-{encoder.quality_flag}", str(native)]
    elif encoder.quality_flag == "global_quality":
        lo, hi = 18, 32
        native = round(hi - (q / 100.0) * (hi - lo))
        args += ["-global_quality", str(native)]
    elif encoder.quality_flag == "q:v":
        # VideoToolbox quality 0..100, bigger = better
        args += ["-q:v", str(q)]
    else:
        args += [f"-{encoder.quality_flag}", str(q)]

    if encoder.preset_flag and speed_preset and speed_preset in encoder.preset_values:
        args += [f"-{encoder.preset_flag}", speed_preset]

    return args


def _no_window_flags() -> int:
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0
