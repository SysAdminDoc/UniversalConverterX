"""Niche audio-codec sidecar.

Wraps FFmpeg to convert legacy / audiophile / broadcast audio formats that
the mainline `audioconvert` flow doesn't cover by default:

  Lossless:  APE (Monkey's Audio), WV (WavPack), TAK, TTA, ALAC, MLP/TrueHD
  DSD:       DSF, DFF (Sony / Philips audiophile)
  Broadcast: AC3, E-AC3, DTS, DTS-HD, MLP, TrueHD
  Mobile:    AMR, AMR-WB, SPEEX, GSM
  Legacy:    AU/SND, VOC, RA / RM (Real Audio), WMA, MusePack (.mpc)
  Bluetooth: SBC, aptX (read-only)

Operations:
  to-wav      Decode any supported format -> 16/24/32-bit WAV
  to-flac     Decode -> FLAC (lossless)
  to-mp3      Decode -> MP3 (lossy, configurable bitrate)
  to-opus     Decode -> Opus (lossy, modern)
  to-aac      Decode -> AAC (M4A container)
  encode      Encode WAV / FLAC -> any of the niche formats
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import (
    emit,
    find_ffmpeg as shared_find_ffmpeg,
    find_ffprobe as shared_find_ffprobe,
    probe_media,
)




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_ffmpeg() -> str | None:
    return shared_find_ffmpeg(Path(__file__).resolve().parent)


def _find_ffprobe() -> str | None:
    return shared_find_ffprobe(Path(__file__).resolve().parent)


def _ambisonic_order(channels: int) -> int | None:
    """Return the full-sphere ambisonic order for a channel count, or None if
    the count is not a valid ACN/SN3D layout. Order n needs (n+1)^2 channels:
    first order = 4, second = 9, third = 16, ..."""
    if channels < 4:
        return None
    root = round(channels ** 0.5)
    if root * root == channels and root >= 2:
        return root - 1
    return None


def _input_channels(src: Path) -> int | None:
    """Best-effort probe of an input's first audio stream channel count."""
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return None
    info = probe_media(ffprobe, src)
    if not info:
        return None
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "audio":
            try:
                return int(stream.get("channels"))
            except (TypeError, ValueError):
                return None
    return None


# Maps target format alias -> (FFmpeg codec name, output extension, default args).
TARGETS = {
    # Lossless
    "wav":      (None, ".wav", []),
    "flac":     ("flac", ".flac", ["-compression_level", "8"]),
    "alac":     ("alac", ".m4a", []),
    "wavpack":  ("wavpack", ".wv", ["-compression_level", "5"]),
    "tta":      ("tta", ".tta", []),
    # DSD (encode requires libfdk-dsd; decode always works)
    "dsf":      ("dsd_lsbf", ".dsf", []),
    "dff":      ("dsd_lsbf", ".dff", []),
    # Lossy
    "mp3":      ("libmp3lame", ".mp3", ["-q:a", "2"]),
    "opus":     ("libopus", ".opus", ["-b:a", "128k"]),
    "aac":      ("aac", ".m4a", ["-b:a", "192k"]),
    "fdk-aac":  ("libfdk_aac", ".m4a", ["-vbr", "4"]),
    "vorbis":   ("libvorbis", ".ogg", ["-q:a", "6"]),
    "ac3":      ("ac3", ".ac3", ["-b:a", "640k"]),
    "eac3":     ("eac3", ".eac3", ["-b:a", "640k"]),
    "amr":      ("libopencore_amrnb", ".amr", ["-ar", "8000", "-ac", "1", "-b:a", "12.2k"]),
    "amrwb":    ("libvo_amrwbenc", ".awb", ["-ar", "16000", "-ac", "1", "-b:a", "23.85k"]),
    "speex":    ("libspeex", ".spx", []),
    "gsm":      ("libgsm", ".gsm", ["-ar", "8000", "-ac", "1"]),
    "wma":      ("wmav2", ".wma", ["-b:a", "192k"]),
    "musepack": ("mpc", ".mpc", []),
    "au":       ("pcm_s16be", ".au", []),
}


def _unique_output_path(path: Path) -> Path:
    """Return a non-existing sibling path without overwriting prior output."""
    if not path.exists():
        return path
    for suffix in range(1, 10_000):
        candidate = path.with_name(f"{path.stem} ({suffix}){path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}-{time.time_ns()}{path.suffix}")


# Input extensions audiopro is expected to recognize.
INPUT_EXTS = {
    ".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aac",
    ".ape", ".wv", ".tak", ".tta", ".alac",
    ".dsf", ".dff",
    ".ac3", ".eac3", ".dts", ".thd", ".mlp",
    ".amr", ".awb", ".spx", ".gsm",
    ".wma", ".mpc", ".au", ".snd", ".voc", ".ra", ".rm", ".sbc",
}


def op_convert(args: argparse.Namespace) -> int:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found on PATH.")

    fmt = args.format.lower().lstrip(".")
    if fmt not in TARGETS:
        return fail("bad_format",
                    f"Unsupported target '{fmt}'. Choose: {sorted(TARGETS)}")
    codec, out_ext, fmt_args = TARGETS[fmt]

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Audio file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="convert", eta_seconds=None)

    # When --vbr-quality is set, REPLACE the format's default fmt_args (which
    # may carry CBR -b:a values like 128k for opus / 192k for aac) with codec-
    # appropriate VBR flags. Same 0..9 user scale as videocrush's
    # --audio-vbr-quality (0=highest quality, 9=lowest), with codec-specific
    # remapping for libvorbis / libfdk_aac / libopus.
    vbr_q = getattr(args, "vbr_quality", None)
    use_vbr = vbr_q is not None
    if use_vbr:
        q = max(0, min(9, int(vbr_q)))
        if codec == "libmp3lame":
            fmt_args = ["-q:a", str(q)]
        elif codec == "libopus":
            kbps = max(32, 192 - q * 18)
            fmt_args = ["-b:a", f"{kbps}k", "-vbr", "on"]
        elif codec == "aac":
            fmt_args = ["-q:a", str(round(2.0 - (q / 9.0) * 1.9, 2))]
        elif codec == "libfdk_aac":
            fmt_args = ["-vbr", str(max(1, min(5, 5 - q // 2)))]
        elif codec == "libvorbis":
            fmt_args = ["-q:a", str(9 - q)]
        else:
            emit("log", level="warn",
                 message=f"--vbr-quality requested but '{codec}' has no known VBR mapping; "
                         f"keeping format default flags.")

    # ROADMAP Item 90 — Opus 1.5 advanced controls. Application profile
    # (voip / audio / lowdelay) and frame duration (2.5..60 ms) are exposed
    # only when the codec is libopus; ignored silently otherwise so the
    # flags can live on a global convert preset without erroring on AAC etc.
    opus_application = (getattr(args, "opus_application", None) or "").lower() or None
    opus_frame_duration = getattr(args, "opus_frame_duration", None)
    if opus_application and opus_application not in ("voip", "audio", "lowdelay"):
        return fail("bad_arg",
                    f"--opus-application must be voip|audio|lowdelay, got '{opus_application}'.")
    if opus_frame_duration is not None and opus_frame_duration not in (2.5, 5, 10, 20, 40, 60):
        return fail("bad_arg",
                    f"--opus-frame-duration must be 2.5/5/10/20/40/60 ms, got {opus_frame_duration}.")

    # ROADMAP Item 90 — higher-order ambisonics. Opus mapping family 2 packs an
    # ACN/SN3D ambisonic stream; the layout is only valid for full-sphere
    # channel counts ((order+1)^2). Resolve the effective channel count from
    # --channels (an explicit remap wins) or by probing the first input, and
    # reject a request that cannot produce a valid ambisonic layout.
    opus_ambisonics = (getattr(args, "opus_ambisonics", None) or "off").lower()
    opus_mapping_family: int | None = None
    if opus_ambisonics == "acn-sn3d":
        if codec != "libopus":
            emit("log", level="info",
                 message=f"--opus-ambisonics ignored — codec is {codec}, not libopus.")
        else:
            if args.channels:
                try:
                    effective_channels = int(args.channels)
                except (TypeError, ValueError):
                    return fail("bad_arg",
                                f"--channels must be an integer for ambisonics, got '{args.channels}'.")
            else:
                effective_channels = _input_channels(inputs[0]) or 0
            order = _ambisonic_order(effective_channels)
            if order is None:
                return fail(
                    "bad_arg",
                    "--opus-ambisonics=acn-sn3d needs a full-sphere channel count "
                    f"(4, 9, 16, 25, ...); got {effective_channels or 'unknown'}. "
                    "Set --channels to a valid ambisonic count.")
            opus_mapping_family = 2
            emit("log", level="info",
                 message=f"Ambisonics: order {order} ({effective_channels} channels), "
                         "Opus mapping family 2 (ACN/SN3D).")

    # ROADMAP Item 58 — encoder-specific advanced parameters. Each flag
    # only applies to one encoder family; the sidecar matches against the
    # active codec and ignores the others silently so a single advanced
    # preset can ship across formats without spurious errors.
    fdk_cutoff = getattr(args, "fdk_cutoff", None)
    fdk_afterburner = getattr(args, "fdk_afterburner", None)
    fdk_profile = (getattr(args, "fdk_profile", None) or "").strip().lower() or None
    vorbis_managed = bool(getattr(args, "vorbis_managed", False))
    if fdk_cutoff is not None and not (0 <= fdk_cutoff <= 24000):
        return fail("bad_arg",
                    f"--fdk-cutoff must be 0..24000 Hz, got {fdk_cutoff}.")
    if fdk_profile and fdk_profile not in ("aac_low", "aac_he", "aac_he_v2", "aac_ld", "aac_eld"):
        return fail("bad_arg",
                    f"--fdk-profile must be aac_low|aac_he|aac_he_v2|aac_ld|aac_eld, got '{fdk_profile}'.")

    for i, src in enumerate(inputs):
        out_path = _unique_output_path(out_dir / (src.stem + out_ext))
        cmd = [ffmpeg, "-y", "-i", str(src)]
        if codec: cmd += ["-c:a", codec]
        cmd += fmt_args
        # --bitrate is incompatible with --vbr-quality. The flag wins by being
        # explicit; warn once before the loop body if both are set.
        if args.bitrate and not use_vbr and not (codec == "libvorbis" and vorbis_managed):
            cmd += ["-b:a", args.bitrate]
        if args.sample_rate: cmd += ["-ar", args.sample_rate]
        if args.channels: cmd += ["-ac", args.channels]

        if codec == "libopus":
            if opus_application:
                cmd += ["-application", opus_application]
            if opus_frame_duration is not None:
                cmd += ["-frame_duration", str(opus_frame_duration)]
            if opus_mapping_family is not None:
                cmd += ["-mapping_family", str(opus_mapping_family)]
        elif opus_application or opus_frame_duration is not None:
            emit("log", level="info",
                 message=f"opus-* flags ignored — codec is {codec}, not libopus.")

        # FDK-AAC advanced parameters (Item 58). FDK-AAC's cutoff is the
        # low-pass cap (0 = encoder default — usually too aggressive on
        # high frequencies), afterburner is a quality/CPU tradeoff knob,
        # profile selects between LC / HE-AAC / HE-AAC v2 / LD / ELD.
        if codec == "libfdk_aac":
            if fdk_cutoff is not None:
                cmd += ["-cutoff", str(fdk_cutoff)]
            if fdk_afterburner is not None:
                cmd += ["-afterburner", "1" if fdk_afterburner else "0"]
            if fdk_profile:
                cmd += ["-profile:a", fdk_profile]
        elif fdk_cutoff is not None or fdk_afterburner is not None or fdk_profile:
            emit("log", level="info",
                 message=f"fdk-* flags ignored — codec is {codec}, not libfdk_aac.")

        # libvorbis managed bitrate mode (Item 58). Vorbis is VBR by default;
        # managed mode produces ABR-like output bounded between min/max
        # bitrate. Useful when shipping to platforms that mandate a bitrate
        # ceiling. -b:a is required when --vorbis-managed is set; otherwise
        # vorbis falls back to its quality-targeted VBR.
        if codec == "libvorbis" and vorbis_managed:
            if not (args.bitrate or use_vbr):
                emit("log", level="warn",
                     message="--vorbis-managed needs --bitrate or --vbr-quality; "
                             "encoder will pick its default bounds.")
            cmd += ["-b:a", args.bitrate or "192k", "-minrate", "64k",
                    "-maxrate", args.bitrate or "256k"]
        elif vorbis_managed and codec != "libvorbis":
            emit("log", level="info",
                 message=f"vorbis-managed ignored — codec is {codec}, not libvorbis.")

        cmd += [str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("convert_failed", f"{src.name}: rc={proc.returncode}")

        emit("audio_codec",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=fmt, codec=codec or "auto")
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def op_codecs(_args: argparse.Namespace) -> int:
    """Probe FFmpeg for which target codecs are actually compiled in."""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")
    proc = subprocess.run([ffmpeg, "-hide_banner", "-codecs"],
                          capture_output=True, text=True)
    haystack = proc.stdout.lower()
    for fmt, (codec, ext, _args) in TARGETS.items():
        present = bool(codec) and codec.lower() in haystack
        emit("audio_codec_info",
             format=fmt, codec=codec or "(passthrough)",
             extension=ext, available=present)
    emit("complete", output="", size_bytes=0, count=len(TARGETS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="audiopro-sidecar",
                                description="Niche audio codec conversion via FFmpeg.")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert audio to a target codec.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help=f"Target: {sorted(TARGETS)}")
    c.add_argument("--bitrate", default=None,
                   help="Override audio bitrate (e.g. 192k). Mutually exclusive "
                        "with --vbr-quality (the latter wins when both are set).")
    c.add_argument("--vbr-quality", default=None, type=int, dest="vbr_quality",
                   help="Variable-bitrate quality target on a unified 0..9 scale "
                        "(0=highest quality, 9=lowest). Codec mapping: libmp3lame "
                        "-> -q:a 0..9 directly; libvorbis -> -q:a 9..0 "
                        "(scale inverted); libfdk_aac -> -vbr 5..1; aac (native) "
                        "-> -q:a 2.0..0.1 interpolated; libopus -> -b:a 192..32 "
                        "kbps + -vbr on. Codecs without a known VBR mapping log "
                        "a warning and keep their format defaults.")
    c.add_argument("--sample-rate", default=None, dest="sample_rate",
                   help="Override sample rate (e.g. 44100).")
    c.add_argument("--channels", default=None,
                   help="Override channel count (1 mono, 2 stereo, 6 5.1).")
    c.add_argument("--opus-application", default=None, dest="opus_application",
                   help="libopus application profile (voip / audio / lowdelay). "
                        "voip = speech-tuned (DRED-eligible at low bitrates), "
                        "audio = music / general, lowdelay = real-time. Ignored "
                        "for non-Opus targets.")
    c.add_argument("--opus-frame-duration", default=None, type=float,
                   dest="opus_frame_duration",
                   help="libopus packet length in ms: 2.5, 5, 10, 20 (default), "
                        "40, or 60. Smaller = lower latency (RTC); larger = "
                        "better compression. Ignored for non-Opus targets.")
    c.add_argument("--opus-ambisonics", default="off", dest="opus_ambisonics",
                   choices=["off", "acn-sn3d"],
                   help="Encode higher-order ambisonics with libopus mapping "
                        "family 2 (ACN channel order, SN3D normalisation). "
                        "Requires a full-sphere channel count: 4 (1st order), "
                        "9 (2nd), 16 (3rd), ... Ignored for non-Opus targets.")
    c.add_argument("--fdk-cutoff", type=int, default=None, dest="fdk_cutoff",
                   help="libfdk_aac low-pass cutoff in Hz (0..24000). 0 = "
                        "encoder default. Higher values preserve more high-"
                        "frequency content. Ignored for non-FDK-AAC targets.")
    c.add_argument("--fdk-afterburner", default=None, type=lambda s: s.lower() in ("1", "true", "on", "yes"),
                   dest="fdk_afterburner",
                   help="libfdk_aac afterburner quality knob (true/false). "
                        "Default off (encoder default); true is roughly +5%% CPU "
                        "for marginally cleaner output.")
    c.add_argument("--fdk-profile", default=None, dest="fdk_profile",
                   help="libfdk_aac profile: aac_low (default LC), aac_he "
                        "(HE-AAC v1), aac_he_v2 (HE-AAC v2), aac_ld (low "
                        "delay), aac_eld (enhanced low delay).")
    c.add_argument("--vorbis-managed", action="store_true", dest="vorbis_managed",
                   help="libvorbis managed bitrate mode (ABR-bounded). Requires "
                        "--bitrate. Ignored for non-Vorbis targets.")
    sub.add_parser("codecs", help="Probe which target codecs FFmpeg supports.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        if args.op == "codecs":  return op_codecs(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
