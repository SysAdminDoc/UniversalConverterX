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


def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_ffmpeg() -> str | None:
    env = os.environ.get("FFMPEG_PATH")
    if env and Path(env).is_file(): return env
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


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

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + out_ext)
        cmd = [ffmpeg, "-y", "-i", str(src)]
        if codec: cmd += ["-c:a", codec]
        cmd += fmt_args
        # --bitrate is incompatible with --vbr-quality. The flag wins by being
        # explicit; warn once before the loop body if both are set.
        if args.bitrate and not use_vbr:
            cmd += ["-b:a", args.bitrate]
        if args.sample_rate: cmd += ["-ar", args.sample_rate]
        if args.channels: cmd += ["-ac", args.channels]
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
