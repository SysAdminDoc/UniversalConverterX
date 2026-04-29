"""Video / audio format + codec tables and ffmpeg encoder detection.

HW encoders are filtered at runtime based on what ffmpeg -encoders reports
AND whether each HW encoder actually initializes on this machine (compile-
time presence isn't enough — the GPU/driver must also be present).
"""

import subprocess

from ..paths import _CREATE_NO_WINDOW


VIDEO_CONTAINERS = ["mp4", "mkv", "webm", "mov", "avi", "ts", "flv"]
VIDEO_CODECS = {
    "copy":         "copy",
    "h264":         "libx264",
    "h265":         "libx265",
    "vp9":          "libvpx-vp9",
    "av1":          "libaom-av1",
    "mpeg4":        "mpeg4",
    # NVIDIA NVENC
    "h264 (NVENC)": "h264_nvenc",
    "h265 (NVENC)": "hevc_nvenc",
    "av1 (NVENC)":  "av1_nvenc",
    # Intel Quick Sync
    "h264 (QSV)":   "h264_qsv",
    "h265 (QSV)":   "hevc_qsv",
    "av1 (QSV)":    "av1_qsv",
    # AMD AMF
    "h264 (AMF)":   "h264_amf",
    "h265 (AMF)":   "hevc_amf",
    "av1 (AMF)":    "av1_amf",
    # Apple VideoToolbox
    "h264 (VT)":    "h264_videotoolbox",
    "h265 (VT)":    "hevc_videotoolbox",
}
AUDIO_CONTAINERS = ["mp3", "m4a", "ogg", "opus", "flac", "wav", "aac"]
AUDIO_CODECS = {
    "copy":   "copy",
    "mp3":    "libmp3lame",
    "aac":    "aac",
    "opus":   "libopus",
    "vorbis": "libvorbis",
    "flac":   "flac",
    "pcm":    "pcm_s16le",
}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts", ".flv", ".m4v"}
AUDIO_EXTS = {".mp3", ".m4a", ".ogg", ".opus", ".flac", ".wav", ".aac"}

_FFMPEG_ENCODERS_CACHE = None
_HW_RUNNABLE_CACHE = None


def detect_ffmpeg_encoders():
    """Return a set of ffmpeg video encoder names that are compiled in.
    Cached — only shells out to ffmpeg once per process."""
    global _FFMPEG_ENCODERS_CACHE
    if _FFMPEG_ENCODERS_CACHE is not None:
        return _FFMPEG_ENCODERS_CACHE
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=15,
            creationflags=_CREATE_NO_WINDOW,
        )
        encoders = set()
        for line in r.stdout.splitlines():
            # Format: " V..... libx264              libx264 H.264 ..."
            s = line.strip()
            if not s or not s[0] in "VAS":
                continue
            parts = s.split()
            if len(parts) >= 2 and parts[0].startswith("V"):
                encoders.add(parts[1])
        _FFMPEG_ENCODERS_CACHE = encoders
    except Exception:
        _FFMPEG_ENCODERS_CACHE = set()
    return _FFMPEG_ENCODERS_CACHE


def _probe_hw_encoder(encoder_name):
    """Try to initialize an HW encoder with a single frame of lavfi color.
    Returns True if the encoder actually works (compile-time presence isn't
    enough — the GPU / driver must also be present)."""
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=black:s=64x64:r=1:d=0.04",
                "-c:v", encoder_name, "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=10,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except Exception:
        return False


def available_video_codec_keys():
    """Return the subset of VIDEO_CODECS keys that can actually be used.
    Software encoders are included if ffmpeg reports them; hardware
    encoders are additionally probed in parallel to confirm they
    initialize. Cached per process."""
    global _HW_RUNNABLE_CACHE
    encoders = detect_ffmpeg_encoders()
    hw_suffixes = ("_nvenc", "_qsv", "_amf", "_videotoolbox")

    if _HW_RUNNABLE_CACHE is None:
        hw_to_probe = [
            enc for enc in VIDEO_CODECS.values()
            if any(s in enc for s in hw_suffixes) and enc in encoders
        ]
        runnable = set()
        if hw_to_probe:
            try:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = {
                        enc: pool.submit(_probe_hw_encoder, enc)
                        for enc in hw_to_probe
                    }
                    for enc, fut in futures.items():
                        try:
                            if fut.result(timeout=12):
                                runnable.add(enc)
                        except Exception:
                            pass
            except Exception:
                runnable = set(hw_to_probe)
        _HW_RUNNABLE_CACHE = runnable

    result = []
    for key, enc in VIDEO_CODECS.items():
        if enc == "copy":
            result.append(key)
        elif any(s in enc for s in hw_suffixes):
            if enc in _HW_RUNNABLE_CACHE:
                result.append(key)
        elif enc in encoders:
            result.append(key)
    return result


def video_codec_extra_args(ff_encoder):
    """Return the quality/preset args tuned for the given ffmpeg encoder."""
    if ff_encoder in ("libx264", "libx265"):
        return ["-crf", "23", "-preset", "medium"]
    if ff_encoder == "libvpx-vp9":
        return ["-crf", "32", "-b:v", "0"]
    if ff_encoder == "libaom-av1":
        return ["-crf", "30", "-b:v", "0", "-cpu-used", "4"]
    if ff_encoder == "mpeg4":
        return ["-q:v", "5"]
    if ff_encoder in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
        return ["-cq", "23", "-preset", "p5", "-rc", "vbr"]
    if ff_encoder in ("h264_qsv", "hevc_qsv", "av1_qsv"):
        return ["-global_quality", "23", "-preset", "medium"]
    if ff_encoder in ("h264_amf", "hevc_amf", "av1_amf"):
        return ["-quality", "balanced", "-rc", "cqp", "-qp_i", "22", "-qp_p", "24"]
    if ff_encoder in ("h264_videotoolbox", "hevc_videotoolbox"):
        return ["-q:v", "60"]
    return []
