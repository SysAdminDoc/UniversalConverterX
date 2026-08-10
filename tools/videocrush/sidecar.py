"""VideoCrush sidecar — NDJSON CLI shim for the UCX Compressor module.

Reuses VideoCrush's two-pass FFmpeg compression strategy without the PyQt6 GUI
dependency. The C# host launches this with arguments, reads stdout line-by-line
as NDJSON, and updates the Compressor page's progress UI accordingly.

Contract: see ../README.md (sidecar contract) and ../../README.md (parent).
"""
from __future__ import annotations

import argparse
from functools import partial
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import (
    find_ffmpeg as shared_find_ffmpeg,
    find_ffprobe as shared_find_ffprobe,
    probe_media,
    run_ffmpeg as shared_run_ffmpeg,
)


# ─── NDJSON emitter ──────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    """Write one ASCII-safe NDJSON line and flush.

    Windows console code pages cannot encode every Unicode character. JSON
    escapes preserve the original text while keeping the host protocol safe
    whether stdout is a pipe or a legacy console.
    """
    payload = json.dumps({"event": event, **fields}, ensure_ascii=True, separators=(",", ":"))
    sys.stdout.write(payload + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> "int":
    emit("error", code=code, message=message)
    return 1


# ─── FFmpeg discovery ────────────────────────────────────────────────────────

find_ffmpeg = partial(shared_find_ffmpeg, Path(__file__).resolve().parent)


find_ffprobe = partial(shared_find_ffprobe, Path(__file__).resolve().parent)


def probe(ffprobe: str, path: str) -> dict | None:
    return probe_media(ffprobe, path)


# ─── Hardware accelerator → encoder mapping ──────────────────────────────────

# Maps codec names to their hardware-accelerated equivalents per accelerator.
# "none" means software encoder (unchanged). If a codec has no HW variant for a
# given accelerator, fall back to software silently.
_HW_ENCODER: dict[str, dict[str, str]] = {
    "nvenc": {
        "libx264":    "h264_nvenc",
        "libx265":    "hevc_nvenc",
        "libvpx-vp9": "libvpx-vp9",   # no NVENC VP9 encoder in FFmpeg
        "libsvtav1":  "av1_nvenc",
    },
    "amf": {
        "libx264":    "h264_amf",
        "libx265":    "hevc_amf",
        "libvpx-vp9": "libvpx-vp9",
        "libsvtav1":  "av1_amf",
    },
    "qsv": {
        "libx264":    "h264_qsv",
        "libx265":    "hevc_qsv",
        "libvpx-vp9": "vp9_qsv",
        "libsvtav1":  "libsvtav1",      # no QSV AV1 encoder broadly available
    },
    "d3d12": {
        "libx264":    "h264_d3d12va",
        "libx265":    "hevc_d3d12va",
        "libvpx-vp9": "libvpx-vp9",
        "libsvtav1":  "av1_d3d12va",
    },
}


def resolve_encoder(codec: str, hwaccel: str | None) -> str:
    """Return the best available encoder for the given codec + accelerator."""
    if not hwaccel or hwaccel == "none":
        return codec
    mapping = _HW_ENCODER.get(hwaccel, {})
    return mapping.get(codec, codec)


def d3d12_filter_chain(resolution: str | None, deinterlace: bool) -> list[str]:
    """Build a hardware-frame-only D3D12 filter chain."""
    filters: list[str] = []
    if deinterlace:
        filters.append("deinterlace_d3d12=method=default:mode=field:deint=interlaced")
    if resolution and resolution != "Original":
        height = int(resolution.replace("p", ""))
        filters.append(f"scale_d3d12=w=-2:h={height}")
    return filters


def software_filter_chain(resolution: str | None, deinterlace: bool) -> list[str]:
    """Build the behavior-preserving CPU fallback for the requested filters."""
    filters: list[str] = []
    if deinterlace:
        filters.append("bwdif=mode=send_field:parity=auto:deint=interlaced")
    if resolution and resolution != "Original":
        height = int(resolution.replace("p", ""))
        filters.append(f"scale=-2:{height}")
    return filters


def d3d12_quality_args(crf: int) -> list[str]:
    """Translate the user CRF target to D3D12VA's QVBR quality control."""
    return ["-rc_mode", "QVBR", "-global_quality", str(crf)]


def probe_d3d12_pipeline(
    ffmpeg: str,
    input_path: Path,
    encoder: str,
    filters: list[str],
    crf: int,
) -> tuple[bool, str]:
    """Exercise one decoded, filtered, encoded frame before the real job.

    Listing filters/codecs is insufficient because FFmpeg exposes D3D12
    components even when the installed driver cannot create the video
    processor or encoder. The one-frame probe catches that runtime boundary.
    """
    null_out = "NUL" if sys.platform == "win32" else "/dev/null"
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-hwaccel", "d3d12va", "-hwaccel_output_format", "d3d12",
        "-i", str(input_path), "-map", "0:v:0", "-frames:v", "1",
    ]
    if filters:
        command += ["-vf", ",".join(filters)]
    command += ["-an", "-c:v", encoder, *d3d12_quality_args(crf),
                "-f", "null", null_out]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"probe could not run: {type(exc).__name__}: {exc}"
    if result.returncode == 0:
        return True, ""
    diagnostic = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
    lines = [line.strip() for line in diagnostic.splitlines() if line.strip()]
    return False, (lines[-1] if lines else f"exit code {result.returncode}")[:500]


# ─── Preset → encoding parameters ────────────────────────────────────────────

PRESETS = {
    "web-1080p": {
        "target_mb": None,           # use CRF instead
        "crf": 23,
        "codec": "libx264",
        "preset": "medium",
        "resolution": "1080p",
        "audio_codec": "aac",
        "audio_bitrate": 192,
    },
    "email-10mb": {
        "target_mb": 9.5,
        "crf": None,
        "codec": "libx264",
        "preset": "slow",
        "resolution": "720p",
        "audio_codec": "aac",
        "audio_bitrate": 96,
    },
    # Platform caps reserve 5% for MP4 muxing/metadata overhead so the final
    # artifact remains at or below the user-visible limit.
    "discord-10mb": {
        "target_mb": 9.5,
        "crf": None,
        "codec": "libx264",
        "preset": "slow",
        "resolution": "720p",
        "audio_codec": "aac",
        "audio_bitrate": 96,
    },
    "discord-25mb": {
        "target_mb": 23.75,
        "crf": None,
        "codec": "libx264",
        "preset": "slow",
        "resolution": "720p",
        "audio_codec": "aac",
        "audio_bitrate": 96,
    },
    "discord-50mb": {
        "target_mb": 47.5,
        "crf": None,
        "codec": "libx264",
        "preset": "slow",
        "resolution": "1080p",
        "audio_codec": "aac",
        "audio_bitrate": 128,
    },
    "email-25mb": {
        "target_mb": 23.75,
        "crf": None,
        "codec": "libx264",
        "preset": "slow",
        "resolution": "720p",
        "audio_codec": "aac",
        "audio_bitrate": 96,
    },
    "archive-av1": {
        "target_mb": None,
        "crf": 28,
        "codec": "libsvtav1",
        "preset": None,
        "resolution": "Original",
        "audio_codec": "libopus",
        "audio_bitrate": 128,
    },
    # SVT-AV1 v2 (FFmpeg 7.1+) presets -- much faster than the original v1.
    "archive-av1-fast": {
        # SVT-AV1 preset 8 is 4-6x faster than preset 4, ~5% file-size penalty.
        "target_mb": None, "crf": 32,
        "codec": "libsvtav1", "preset": "8",
        "resolution": "Original",
        "audio_codec": "libopus", "audio_bitrate": 96,
    },
    "archive-av1-quality": {
        # SVT-AV1 preset 4 = strong compression, slow but 1080p real-time on modern CPUs.
        "target_mb": None, "crf": 24,
        "codec": "libsvtav1", "preset": "4",
        "resolution": "Original",
        "audio_codec": "libopus", "audio_bitrate": 160,
    },
    "stream-av1-1080p": {
        # AV1 streaming preset for YouTube / Vimeo upload at 1080p.
        "target_mb": None, "crf": 30,
        "codec": "libsvtav1", "preset": "6",
        "resolution": "1080p",
        "audio_codec": "libopus", "audio_bitrate": 128,
    },
    # APV camera masters (RFC 9924 / FFmpeg 8.1 liboapv decoder) to broadly
    # editable and playable interchange formats. APV sources are normally
    # 10-bit 4:2:2; H.265 keeps 10-bit precision while H.264 favors playback
    # compatibility. ProRes follows the professional intermediate branch.
    "apv-to-h265": {
        "target_mb": None, "crf": 18,
        "codec": "libx265", "preset": "slow",
        "resolution": "Original", "pixel_format": "yuv420p10le",
        "audio_codec": "aac", "audio_bitrate": 256,
    },
    "apv-to-prores-422-hq": {
        "target_mb": None, "crf": None,
        "codec": "prores_ks", "prores_profile": 3,
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s24le", "audio_bitrate": 0,
    },
    "apv-to-h264": {
        "target_mb": None, "crf": 16,
        "codec": "libx264", "preset": "slow",
        "resolution": "Original", "pixel_format": "yuv420p",
        "audio_codec": "aac", "audio_bitrate": 256,
    },
    # ── Professional-tier intermediate codecs (HandBrake 1.11 / FFmpeg 8.1) ──
    "prores-422-proxy": {
        "target_mb": None, "crf": None,
        "codec": "prores_ks", "prores_profile": 0,
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s16le", "audio_bitrate": 0,
    },
    "prores-422-lt": {
        "target_mb": None, "crf": None,
        "codec": "prores_ks", "prores_profile": 1,
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s16le", "audio_bitrate": 0,
    },
    "prores-422": {
        "target_mb": None, "crf": None,
        "codec": "prores_ks", "prores_profile": 2,
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s16le", "audio_bitrate": 0,
    },
    "prores-422-hq": {
        "target_mb": None, "crf": None,
        "codec": "prores_ks", "prores_profile": 3,
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s16le", "audio_bitrate": 0,
    },
    "prores-4444": {
        "target_mb": None, "crf": None,
        "codec": "prores_ks", "prores_profile": 4,
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s16le", "audio_bitrate": 0,
    },
    "dnxhr-sq": {
        "target_mb": None, "crf": None,
        "codec": "dnxhd", "dnxhd_profile": "dnxhr_sq",
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s16le", "audio_bitrate": 0,
    },
    "dnxhr-hq": {
        "target_mb": None, "crf": None,
        "codec": "dnxhd", "dnxhd_profile": "dnxhr_hq",
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s16le", "audio_bitrate": 0,
    },
    "dnxhr-hqx": {
        "target_mb": None, "crf": None,
        "codec": "dnxhd", "dnxhd_profile": "dnxhr_hqx",
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s16le", "audio_bitrate": 0,
    },
    "dnxhr-444": {
        "target_mb": None, "crf": None,
        "codec": "dnxhd", "dnxhd_profile": "dnxhr_444",
        "preset": None, "resolution": "Original",
        "audio_codec": "pcm_s16le", "audio_bitrate": 0,
    },
    # ── Archival lossless (#31) — FFV1 + FLAC in MKV. Checksummed lossless. ──
    "archive-ffv1": {
        "target_mb": None, "crf": None,
        "codec": "ffv1",
        "preset": None, "resolution": "Original",
        "audio_codec": "flac", "audio_bitrate": 0,
    },
}


# ─── Codec families that bypass CRF/two-pass logic ──────────────────────────
INTERMEDIATE_CODECS = {"prores_ks", "prores_aw", "dnxhd"}
LOSSLESS_CODECS = {"ffv1"}


# ─── FFmpeg progress parsing ─────────────────────────────────────────────────

def run_ffmpeg(cmd: list[str], duration_sec: float, stage: str,
               start_pct: float, end_pct: float) -> int:
    """Run FFmpeg with -progress pipe:1, emit NDJSON progress events.

    Returns FFmpeg's exit code. start_pct..end_pct maps the linear ffmpeg
    progress into a sub-range of overall job progress.
    """
    full_cmd = [
        cmd[0], "-hide_banner", "-loglevel", "error",
        "-progress", "pipe:1", "-nostats", *cmd[1:],
    ]
    return shared_run_ffmpeg(
        full_cmd,
        duration_sec,
        stage,
        event_emitter=emit,
        start_percent=start_pct,
        end_percent=end_pct,
        inject_progress_args=False,
    )


# ─── Job ─────────────────────────────────────────────────────────────────────

def compress(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve preset
    preset_cfg = PRESETS.get(args.preset, {}) if args.preset else {}
    target_mb = args.target_mb if args.target_mb is not None else preset_cfg.get("target_mb")
    crf = args.crf if args.crf is not None else preset_cfg.get("crf")
    software_codec = args.codec or preset_cfg.get("codec", "libx264")
    fpreset = args.ffmpeg_preset or preset_cfg.get("preset")
    resolution = args.resolution or preset_cfg.get("resolution", "Original")
    audio_codec = args.audio_codec or preset_cfg.get("audio_codec", "aac")
    audio_bitrate = args.audio_bitrate or preset_cfg.get("audio_bitrate", 128)
    audio_vbr_quality = (
        args.audio_vbr_quality
        if args.audio_vbr_quality is not None
        else preset_cfg.get("audio_vbr_quality")
    )
    pixel_format = preset_cfg.get("pixel_format")

    # Resolve HW encoder. D3D12 is activated only after an actual one-frame
    # decode/filter/encode probe succeeds; all other paths keep prior behavior.
    hwaccel = getattr(args, "hwaccel", None)
    d3d12_requested = hwaccel == "d3d12"
    d3d12_active = False
    codec = software_codec if d3d12_requested else resolve_encoder(software_codec, hwaccel)
    if hwaccel and hwaccel not in ("none", "d3d12"):
        emit("log", level="info", message=f"Hardware accelerator: {hwaccel} -> encoder: {codec}")

    if (target_mb is None and crf is None
            and codec not in INTERMEDIATE_CODECS
            and codec not in LOSSLESS_CODECS):
        return fail("invalid_args",
                    "Must specify either --target-mb (size-targeted) or --crf (quality-targeted), "
                    "or pick a preset that defines one.")

    emit("log", level="info", message=f"Probing {in_path.name}")
    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata via ffprobe.")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        if in_path.suffix.lower() != ".apv":
            return fail("probe_failed", "Could not determine input duration.")
        # RFC 9924 raw elementary streams have no container-level duration.
        # FFmpeg can still decode them; run_ffmpeg emits an indeterminate
        # stage followed by progress=end instead of calculating a percentage.
        emit("log", level="warn",
             message="Raw APV has no container duration; progress is indeterminate.")
    else:
        emit("log", level="info", message=f"Duration: {duration:.1f}s")

    deinterlace = bool(getattr(args, "d3d12_deinterlace", False))
    vf_filters = software_filter_chain(resolution, deinterlace)
    input_args: list[str] = []
    if d3d12_requested:
        d3d12_encoder = resolve_encoder(software_codec, "d3d12")
        if target_mb is not None:
            fallback_reason = "size-targeted two-pass mode is not supported by D3D12VA"
        elif crf is None:
            fallback_reason = "the selected workflow has no quality target for the D3D12VA probe"
        elif d3d12_encoder == software_codec:
            fallback_reason = f"codec {software_codec} has no D3D12VA encoder"
        else:
            hardware_filters = d3d12_filter_chain(resolution, deinterlace)
            emit("log", level="info",
                 message=f"Probing D3D12 zero-copy path with {d3d12_encoder}")
            d3d12_active, fallback_reason = probe_d3d12_pipeline(
                ffmpeg, in_path, d3d12_encoder, hardware_filters, int(crf)
            )
            if d3d12_active:
                codec = d3d12_encoder
                vf_filters = hardware_filters
                input_args = ["-hwaccel", "d3d12va", "-hwaccel_output_format", "d3d12"]
                emit("log", level="info",
                     message=f"D3D12 zero-copy enabled: decode -> "
                             f"{','.join(hardware_filters) if hardware_filters else 'direct'} -> {codec}")
        if not d3d12_active:
            codec = software_codec
            emit("log", level="warn",
                 message=f"D3D12 zero-copy unavailable ({fallback_reason}); "
                         f"falling back to software {software_codec}.")

    is_av1 = codec == "libsvtav1"
    is_vp9 = codec == "libvpx-vp9"
    is_intermediate = codec in INTERMEDIATE_CODECS
    is_lossless = codec in LOSSLESS_CODECS

    # ─── ProRes / DNxHR / FFV1 — profile-driven encode (no CRF, no 2-pass) ──
    if is_intermediate or is_lossless:
        emit("progress", percent=0, stage="encoding (intermediate)", eta_seconds=None)
        cmd = [ffmpeg, "-y", *input_args, "-i", str(in_path)]
        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters)]

        # Force pixel format compatible with the chosen codec.
        if codec == "prores_ks":
            profile = int(preset_cfg.get("prores_profile", args.prores_profile or 3))
            cmd += ["-c:v", "prores_ks", "-profile:v", str(profile),
                    "-pix_fmt", "yuv422p10le" if profile <= 3 else "yuva444p10le"]
        elif codec == "dnxhd":
            profile = preset_cfg.get("dnxhd_profile", args.dnxhd_profile or "dnxhr_hq")
            cmd += ["-c:v", "dnxhd", "-profile:v", profile]
            # DNxHR expects yuv422p (sq/hq), yuv422p10le (hqx), or yuv444p10le (444)
            pix = "yuv444p10le" if profile == "dnxhr_444" else (
                  "yuv422p10le" if profile == "dnxhr_hqx" else "yuv422p")
            cmd += ["-pix_fmt", pix]
        elif codec == "ffv1":
            cmd += ["-c:v", "ffv1", "-level", "3",
                    "-coder", "1", "-context", "1",
                    "-g", "1", "-slices", "24", "-slicecrc", "1",
                    "-pix_fmt", "yuv420p"]

        cmd += audio_args(audio_codec, audio_bitrate, audio_vbr_quality)

        # Container hint: ProRes/DNxHR → MOV is conventional, FFV1 → MKV.
        # We honour the user's explicit output extension, but warn on unusual combos.
        out_ext = out_path.suffix.lower()
        if codec == "ffv1" and out_ext != ".mkv":
            emit("log", level="warn",
                 message=f"FFV1 archival is conventionally muxed in MKV; "
                         f"got {out_ext} — proceeding anyway.")
        if (codec == "prores_ks" or codec == "dnxhd") and out_ext not in (".mov", ".mxf"):
            emit("log", level="warn",
                 message=f"ProRes/DNxHR is conventionally muxed in MOV (or MXF); "
                         f"got {out_ext} — proceeding anyway.")

        cmd += [str(out_path)]
        rc = run_ffmpeg(cmd, duration, "encoding", 0.0, 100.0)
        if rc != 0:
            return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
        return finalize(out_path)

    # ─── CRF mode (single-pass) ──────────────────────────────────────────────
    if crf is not None:
        emit("progress", percent=0, stage="encoding", eta_seconds=None)
        cmd = [ffmpeg, "-y", *input_args, "-i", str(in_path)]
        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters)]
        if d3d12_active:
            cmd += ["-c:v", codec, *d3d12_quality_args(int(crf))]
        else:
            cmd += ["-c:v", codec, "-crf", str(crf)]
        if pixel_format and not d3d12_active:
            cmd += ["-pix_fmt", pixel_format]
        if fpreset and not is_av1 and not d3d12_active:
            cmd += ["-preset", fpreset]

        # ROADMAP Item 91 — Cross-encoder capped-CRF harmonization. The user
        # asks for "Quality CRF X with no more than N kbps"; each encoder
        # exposes the cap differently, so the sidecar speaks one canonical
        # `--max-bitrate` flag and translates per-codec at this layer.
        max_kbps = getattr(args, "max_bitrate", None)
        if max_kbps is not None and max_kbps > 0:
            buf_kbps = max_kbps * 2  # standard 2× cap = 2× rate-control buffer
            if is_av1:
                # SVT-AV1 understands `mbr` (max bitrate, kbps) inside -svtav1-params.
                cmd += ["-svtav1-params", f"crf={crf}:mbr={max_kbps}"]
            elif is_vp9:
                # libvpx-vp9 uses -maxrate/-bufsize in kbps suffix form.
                cmd += ["-maxrate", f"{max_kbps}k", "-bufsize", f"{buf_kbps}k"]
            else:
                # x264 / x265 / hardware-accelerated H.26x all honour -maxrate
                # alongside -crf, which produces capped-CRF behaviour where the
                # encoder degrades to capped-bitrate only when CRF would exceed
                # the cap. Same flag works for h264_nvenc / h264_amf / hevc_*.
                cmd += ["-maxrate", f"{max_kbps}k", "-bufsize", f"{buf_kbps}k"]
            emit("log", level="info",
                 message=f"capped-CRF: crf={crf}, max bitrate {max_kbps} kbps "
                         f"(buf {buf_kbps} kbps) — encoder {codec}")
        elif is_av1:
            cmd += ["-svtav1-params", f"crf={crf}"]
        cmd += audio_args(audio_codec, audio_bitrate, audio_vbr_quality)
        cmd += ["-movflags", "+faststart", str(out_path)]

        rc = run_ffmpeg(cmd, duration, "encoding", 0.0, 100.0)
        if rc != 0:
            return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
        return finalize(out_path)

    # ─── Size-targeted mode (two-pass) ───────────────────────────────────────
    target_bits = float(target_mb) * 8 * 1024 * 1024
    audio_kbps = audio_bitrate if audio_codec not in ("copy", "an") else 0
    if audio_codec == "copy":
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "audio":
                audio_kbps = int(stream.get("bit_rate", 128_000)) // 1000
                break
    audio_bits = audio_kbps * 1000 * duration
    video_bits = target_bits - audio_bits
    if video_bits <= 0:
        return fail("target_too_small",
                    "Target size too small for the chosen audio settings. "
                    "Increase target or lower audio bitrate.")
    video_kbps = int(video_bits / duration / 1000)
    if video_kbps < 50:
        return fail("target_too_small",
                    f"Calculated video bitrate ({video_kbps} kbps) is unusably low. Increase target.")

    emit("log", level="info", message=f"Target: {target_mb} MB → video {video_kbps} kbps + audio {audio_kbps} kbps")

    null_out = "NUL" if sys.platform == "win32" else "/dev/null"
    pass_log = str(out_path.parent / f"ucx_ffmpeg2pass_{os.getpid()}_{out_path.stem}")

    # AV1: SVT-AV1 doesn't support 2-pass cleanly, fall back to single-pass with target bitrate
    if is_av1:
        cmd = [ffmpeg, "-y", "-i", str(in_path)]
        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters)]
        cmd += ["-c:v", codec, "-b:v", f"{video_kbps}k",
                "-svtav1-params", f"tbr={video_kbps}"]
        cmd += audio_args(audio_codec, audio_bitrate, audio_vbr_quality)
        cmd += ["-movflags", "+faststart", str(out_path)]
        rc = run_ffmpeg(cmd, duration, "encoding", 0.0, 100.0)
        if rc != 0:
            return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
        return finalize(out_path)

    # H.264/H.265/VP9 two-pass
    pass1 = [ffmpeg, "-y", "-i", str(in_path)]
    if vf_filters:
        pass1 += ["-vf", ",".join(vf_filters)]
    pass1 += ["-c:v", codec, "-b:v", f"{video_kbps}k",
              "-pass", "1", "-passlogfile", pass_log, "-an"]
    if is_vp9:
        pass1 += ["-speed", "4", "-f", "webm", null_out]
    else:
        if fpreset:
            pass1 += ["-preset", fpreset]
        pass1 += ["-f", "null", null_out]

    emit("log", level="info", message="Pass 1 of 2 — analyzing")
    rc = run_ffmpeg(pass1, duration, "pass1", 0.0, 50.0)
    if rc != 0:
        cleanup_pass_logs(pass_log)
        return fail("ffmpeg_failed", f"FFmpeg pass 1 exited with code {rc}")

    pass2 = [ffmpeg, "-y", "-i", str(in_path)]
    if vf_filters:
        pass2 += ["-vf", ",".join(vf_filters)]
    pass2 += ["-c:v", codec, "-b:v", f"{video_kbps}k",
              "-pass", "2", "-passlogfile", pass_log]
    if is_vp9:
        pass2 += ["-speed", "2"]
    elif fpreset:
        pass2 += ["-preset", fpreset]

    pass2 += audio_args(audio_codec, audio_bitrate, audio_vbr_quality)
    pass2 += ["-movflags", "+faststart", str(out_path)]

    emit("log", level="info", message="Pass 2 of 2 — encoding")
    rc = run_ffmpeg(pass2, duration, "pass2", 50.0, 100.0)
    cleanup_pass_logs(pass_log)
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg pass 2 exited with code {rc}")
    return finalize(out_path)


def audio_args(audio_codec: str, audio_bitrate: int, vbr_quality: int | None) -> list[str]:
    """Build the FFmpeg `-c:a` / `-b:a` / `-q:a` argument list for one audio
    output configuration.

    `audio_codec` accepts the special pseudo-values "an" (drop audio entirely)
    and "copy" (stream-copy the source). PCM/FLAC variants ignore both bitrate
    and VBR quality (they're lossless).

    When `vbr_quality` is None, falls back to constant-bitrate (CBR) using
    `audio_bitrate` in kbps. When set, switches to VBR per codec:

      libmp3lame   -> -q:a 0..9 (0 best, ~245 kbps; 9 worst, ~65 kbps)
      libvorbis    -> -q:a -2..10 (we accept 0..9 input and remap)
      libfdk_aac   -> -vbr 1..5  (1 ~32 kbps, 5 ~96 kbps per channel)
      aac (native) -> -q:a 0.1..2 mapped from 0..9 input
      libopus      -> -b:a + -vbr on (Opus is VBR by default; treat input as
                      target bitrate hint, not a quality scale)

    Unknown codec + vbr_quality: emit a log warning and fall back to CBR.
    """
    if audio_codec == "an":
        return ["-an"]
    if audio_codec == "copy":
        return ["-c:a", "copy"]
    if audio_codec in ("pcm_s16le", "pcm_s24le", "flac"):
        return ["-c:a", audio_codec]

    if vbr_quality is None:
        return ["-c:a", audio_codec, "-b:a", f"{audio_bitrate}k"]

    q = max(0, min(9, int(vbr_quality)))

    if audio_codec == "libmp3lame":
        return ["-c:a", audio_codec, "-q:a", str(q)]
    if audio_codec == "libvorbis":
        # User scale 0=best..9=worst; libvorbis is opposite (10 best, -2 worst).
        # Map: 0 -> 9, 1 -> 8, ..., 9 -> 0 (so user "0" really is best quality).
        return ["-c:a", audio_codec, "-q:a", str(9 - q)]
    if audio_codec == "libfdk_aac":
        # libfdk_aac VBR is 1..5; map 0..9 -> 5..1 (best to worst).
        # 0..1 -> 5, 2..3 -> 4, 4..5 -> 3, 6..7 -> 2, 8..9 -> 1.
        vbr = max(1, min(5, 5 - q // 2))
        return ["-c:a", audio_codec, "-vbr", str(vbr)]
    if audio_codec == "aac":
        # FFmpeg native AAC -q:a 0.1..2.0; tighter than user scale, so
        # interpolate: 0 -> 2.0, 9 -> 0.1 (linear).
        v = round(2.0 - (q / 9.0) * 1.9, 2)
        return ["-c:a", audio_codec, "-q:a", str(v)]
    if audio_codec == "libopus":
        # Opus is variable-bit-rate by default; the user-facing "quality"
        # mapping is bitrate-driven. Approximate: q=0 -> 192, q=9 -> 32.
        kbps = max(32, 192 - q * 18)
        return ["-c:a", audio_codec, "-b:a", f"{kbps}k", "-vbr", "on"]

    emit("log", level="warn",
         message=f"VBR quality requested but codec '{audio_codec}' has no known "
                 f"mapping; falling back to CBR at {audio_bitrate} kbps.")
    return ["-c:a", audio_codec, "-b:a", f"{audio_bitrate}k"]


def cleanup_pass_logs(pass_log: str) -> None:
    for ext in ("-0.log", "-0.log.mbtree", ".log", ".log.mbtree"):
        p = Path(pass_log + ext)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def finalize(out_path: Path) -> int:
    if not out_path.is_file():
        return fail("output_missing", f"Expected output file was not produced: {out_path}")
    size = out_path.stat().st_size
    emit("complete", output=str(out_path), size_bytes=size)
    return 0


# ─── Entry point ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="videocrush-sidecar",
                                description="UCX VideoCrush sidecar — FFmpeg compression with NDJSON progress.")
    p.add_argument("--input", required=True, help="Input video path")
    p.add_argument("--output", required=True, help="Output video path")
    p.add_argument("--preset", choices=list(PRESETS.keys()),
                   help="Predefined preset — see PRESETS dict in sidecar.py for the full list "
                        "(web-1080p, email-10mb, discord-{10mb,25mb,50mb}, email-25mb, "
                        "archive-av1, apv-to-{h265,prores-422-hq,h264}, "
                        "prores-422-{proxy,lt,hq}, prores-4444, "
                        "dnxhr-{sq,hq,hqx,444}, archive-ffv1).")
    p.add_argument("--target-mb", type=float, help="Target file size in megabytes")
    p.add_argument("--crf", type=int, help="Constant Rate Factor (quality-targeted)")
    p.add_argument("--codec",
                   help="Video codec. Lossy: libx264, libx265, libvpx-vp9, libsvtav1. "
                        "Intermediate: prores_ks, dnxhd. Archival: ffv1.")
    p.add_argument("--ffmpeg-preset", help="FFmpeg encoder preset (ultrafast..veryslow)")
    p.add_argument("--resolution", help="Target height (Original, 1080p, 720p, 480p)")
    p.add_argument("--audio-codec",
                   help="Audio codec, or 'copy' / 'an' (none). For ProRes/DNxHR use pcm_s16le or pcm_s24le; "
                        "for FFV1 archival use flac.")
    p.add_argument("--audio-bitrate", type=int, help="Audio bitrate in kbps (ignored for PCM/FLAC and when --audio-vbr-quality is set)")
    p.add_argument("--audio-vbr-quality", type=int,
                   dest="audio_vbr_quality",
                   help="Variable-bitrate quality target on a unified 0..9 scale "
                        "(0=highest quality, 9=lowest). Mapped per codec: "
                        "libmp3lame -> -q:a 0..9 directly; libvorbis -> -q:a 9..0 "
                        "(scale inverted); libfdk_aac -> -vbr 5..1; aac (native) "
                        "-> -q:a 2.0..0.1 interpolated; libopus -> -b:a 192..32 "
                        "kbps + -vbr on. When set, --audio-bitrate is ignored.")
    p.add_argument("--hwaccel",
                   choices=["none", "nvenc", "amf", "qsv", "d3d12"],
                   default="none",
                   help="Hardware video encoder to use (default: none / software). "
                        "d3d12 probes a zero-copy D3D12VA decode/filter/encode path "
                        "and falls back to software when the driver rejects it.")
    p.add_argument("--d3d12-deinterlace", action="store_true",
                   help="When --hwaccel=d3d12, request deinterlace_d3d12 before "
                        "scaling. The guarded fallback uses CPU bwdif with the "
                        "same interlaced-frame-only behavior.")
    p.add_argument("--max-bitrate", type=int, default=None, dest="max_bitrate",
                   help="Capped-CRF mode: maximum video bitrate ceiling in kbps "
                        "(ROADMAP Item 91). Translated per-encoder: x264/x265/h264_*/"
                        "hevc_* receive -maxrate/-bufsize, libsvtav1 receives mbr "
                        "via -svtav1-params, libvpx-vp9 receives -maxrate/-bufsize. "
                        "Has no effect outside CRF mode.")
    p.add_argument("--prores-profile", type=int, default=None,
                   help="ProRes profile when --codec=prores_ks: 0=Proxy / 1=LT / 2=SQ / 3=HQ / 4=4444 / 5=4444 XQ.")
    p.add_argument("--dnxhd-profile", default=None,
                   help="DNxHR profile when --codec=dnxhd: dnxhr_sq / dnxhr_hq / dnxhr_hqx / dnxhr_444.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
        from ucx_log import sidecar_logger
        _log = sidecar_logger("videocrush")
        _log.info("compress start", input=getattr(args, "input", None),
                  preset=getattr(args, "preset", None))
    except Exception:
        pass
    try:
        rc = compress(args)
        try: _log.info("compress done", rc=rc)  # noqa: E702
        except Exception: pass
        return rc
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        try: _log.error("unhandled", exception=f"{type(exc).__name__}: {exc}")  # noqa: E702
        except Exception: pass
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
