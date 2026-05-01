"""VideoCrush sidecar — NDJSON CLI shim for the UCX Compressor module.

Reuses VideoCrush's two-pass FFmpeg compression strategy without the PyQt6 GUI
dependency. The C# host launches this with arguments, reads stdout line-by-line
as NDJSON, and updates the Compressor page's progress UI accordingly.

Contract: see ../README.md (sidecar contract) and ../../README.md (parent).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ─── NDJSON emitter ──────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    """Write a single NDJSON line to stdout and flush."""
    payload = {"event": event, **fields}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> "int":
    emit("error", code=code, message=message)
    return 1


# ─── FFmpeg discovery ────────────────────────────────────────────────────────

def find_ffmpeg() -> str | None:
    candidates = [
        os.environ.get("FFMPEG_PATH"),
        shutil.which("ffmpeg"),
    ]
    # Bundled locations (next to the sidecar exe, or under tools/_bin/)
    here = Path(__file__).resolve().parent
    candidates += [
        str(here / "ffmpeg.exe"),
        str(here.parent / "_bin" / "ffmpeg.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def find_ffprobe() -> str | None:
    candidates = [
        os.environ.get("FFPROBE_PATH"),
        shutil.which("ffprobe"),
    ]
    here = Path(__file__).resolve().parent
    candidates += [
        str(here / "ffprobe.exe"),
        str(here.parent / "_bin" / "ffprobe.exe"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def probe(ffprobe: str, path: str) -> dict | None:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


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

_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def run_ffmpeg(cmd: list[str], duration_sec: float, stage: str,
               start_pct: float, end_pct: float) -> int:
    """Run FFmpeg with -progress pipe:1, emit NDJSON progress events.

    Returns FFmpeg's exit code. start_pct..end_pct maps the linear ffmpeg
    progress into a sub-range of overall job progress.
    """
    full_cmd = cmd + ["-progress", "pipe:1", "-nostats"]
    proc = subprocess.Popen(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    started = time.monotonic()
    last_pct = -1.0
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            m = _TIME_RE.search(line)
            if m and duration_sec > 0:
                cur_sec = int(m.group(1)) / 1_000_000
                local = max(0.0, min(1.0, cur_sec / duration_sec))
                pct = start_pct + (end_pct - start_pct) * local
                if pct - last_pct >= 0.5:  # throttle to ~200 events max
                    last_pct = pct
                    elapsed = time.monotonic() - started
                    eta = (elapsed / local - elapsed) if local > 0.01 else None
                    emit("progress", percent=round(pct, 1),
                         stage=stage,
                         eta_seconds=int(eta) if eta and eta < 86400 else None)
            elif line.startswith("progress=end"):
                emit("progress", percent=end_pct, stage=stage, eta_seconds=0)
    finally:
        proc.wait()
        # Drain stderr for failure diagnostics
        if proc.returncode != 0 and proc.stderr is not None:
            tail = proc.stderr.read().splitlines()[-15:]
            for ln in tail:
                emit("log", level="error", message=ln)
    return proc.returncode


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
    codec = args.codec or preset_cfg.get("codec", "libx264")
    fpreset = args.ffmpeg_preset or preset_cfg.get("preset")
    resolution = args.resolution or preset_cfg.get("resolution", "Original")
    audio_codec = args.audio_codec or preset_cfg.get("audio_codec", "aac")
    audio_bitrate = args.audio_bitrate or preset_cfg.get("audio_bitrate", 128)

    # Resolve HW encoder; falls back to software if accelerator is unavailable
    hwaccel = getattr(args, "hwaccel", None)
    codec = resolve_encoder(codec, hwaccel)
    if hwaccel and hwaccel != "none":
        emit("log", level="info", message=f"Hardware accelerator: {hwaccel} -> encoder: {codec}")

    if target_mb is None and crf is None:
        return fail("invalid_args",
                    "Must specify either --target-mb (size-targeted) or --crf (quality-targeted), "
                    "or pick a preset that defines one.")

    emit("log", level="info", message=f"Probing {in_path.name}")
    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata via ffprobe.")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        return fail("probe_failed", "Could not determine input duration.")
    emit("log", level="info", message=f"Duration: {duration:.1f}s")

    # Build vf filter
    vf_filters: list[str] = []
    if resolution and resolution != "Original":
        height = int(resolution.replace("p", ""))
        vf_filters.append(f"scale=-2:{height}")

    is_av1 = codec == "libsvtav1"
    is_vp9 = codec == "libvpx-vp9"
    is_intermediate = codec in INTERMEDIATE_CODECS
    is_lossless = codec in LOSSLESS_CODECS

    # ─── ProRes / DNxHR / FFV1 — profile-driven encode (no CRF, no 2-pass) ──
    if is_intermediate or is_lossless:
        emit("progress", percent=0, stage="encoding (intermediate)", eta_seconds=None)
        cmd = [ffmpeg, "-y", "-i", str(in_path)]
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

        if audio_codec == "an":
            cmd += ["-an"]
        elif audio_codec == "copy":
            cmd += ["-c:a", "copy"]
        elif audio_codec in ("pcm_s16le", "pcm_s24le", "flac"):
            cmd += ["-c:a", audio_codec]
        else:
            cmd += ["-c:a", audio_codec, "-b:a", f"{audio_bitrate}k"]

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
        cmd = [ffmpeg, "-y", "-i", str(in_path)]
        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters)]
        cmd += ["-c:v", codec, "-crf", str(crf)]
        if fpreset and not is_av1:
            cmd += ["-preset", fpreset]
        if is_av1:
            cmd += ["-svtav1-params", f"crf={crf}"]
        if audio_codec == "an":
            cmd += ["-an"]
        elif audio_codec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", audio_codec, "-b:a", f"{audio_bitrate}k"]
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
    pass_log = str(out_path.parent / "ucx_ffmpeg2pass")

    # AV1: SVT-AV1 doesn't support 2-pass cleanly, fall back to single-pass with target bitrate
    if is_av1:
        cmd = [ffmpeg, "-y", "-i", str(in_path)]
        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters)]
        cmd += ["-c:v", codec, "-b:v", f"{video_kbps}k",
                "-svtav1-params", f"tbr={video_kbps}"]
        if audio_codec == "an":
            cmd += ["-an"]
        elif audio_codec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", audio_codec, "-b:a", f"{audio_bitrate}k"]
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

    if audio_codec == "an":
        pass2 += ["-an"]
    elif audio_codec == "copy":
        pass2 += ["-c:a", "copy"]
    else:
        pass2 += ["-c:a", audio_codec, "-b:a", f"{audio_bitrate}k"]
    pass2 += ["-movflags", "+faststart", str(out_path)]

    emit("log", level="info", message="Pass 2 of 2 — encoding")
    rc = run_ffmpeg(pass2, duration, "pass2", 50.0, 100.0)
    cleanup_pass_logs(pass_log)
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg pass 2 exited with code {rc}")
    return finalize(out_path)


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
                        "(web-1080p, email-10mb, archive-av1, prores-422-{proxy,lt,hq}, prores-4444, "
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
    p.add_argument("--audio-bitrate", type=int, help="Audio bitrate in kbps (ignored for PCM/FLAC)")
    p.add_argument("--hwaccel",
                   choices=["none", "nvenc", "amf", "qsv", "d3d12"],
                   default="none",
                   help="Hardware video encoder to use (default: none / software). "
                        "d3d12 enables h264_d3d12va / hevc_d3d12va / av1_d3d12va.")
    p.add_argument("--prores-profile", type=int, default=None,
                   help="ProRes profile when --codec=prores_ks: 0=Proxy / 1=LT / 2=SQ / 3=HQ / 4=4444 / 5=4444 XQ.")
    p.add_argument("--dnxhd-profile", default=None,
                   help="DNxHR profile when --codec=dnxhd: dnxhr_sq / dnxhr_hq / dnxhr_hqx / dnxhr_444.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return compress(args)
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
