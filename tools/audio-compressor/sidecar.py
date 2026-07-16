"""Audio dynamic-range compression sidecar.

Wraps FFmpeg's `acompressor` filter to apply broadcast/podcast-style dynamic
range compression to audio (or video audio tracks) without re-encoding the
video stream when the input is video.

Two operations:

  compress   Apply explicit threshold/ratio/attack/release/makeup parameters.
  preset     Apply a named preset (light / medium / heavy / podcast / broadcast)
             that maps to a tested parameter set.

Output preserves container + codec by default. With `--encode-bitrate` the
output is re-encoded to MP3 / AAC / Opus / FLAC at the chosen bitrate (matches
the audiopro flow when the user wants size reduction together with DRC).

NDJSON contract: emits `progress`, `log`, `complete`, `error`, `audio_compressed`.
The `audio_compressed` event reports applied parameters + size delta per file
so the UI can render before/after info.
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
)




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_ffmpeg() -> str | None:
    return shared_find_ffmpeg(Path(__file__).resolve().parent)


def _find_ffprobe() -> str | None:
    return shared_find_ffprobe(Path(__file__).resolve().parent)


# Audio-only inputs we recognize without inspecting via ffprobe.
AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".alac", ".ape", ".wv", ".aif", ".aiff",
}


# Tested DRC presets. Threshold in dB (negative); ratio is :1; attack/release in ms;
# makeup in dB. These mirror the reference points used by Audacity's
# Compressor / Voxengo Marvel GEQ default sets.
PRESETS = {
    # Gentle, transparent — mastering bus.
    "light":      dict(threshold=-18.0, ratio=2.0,  attack=20.0, release=250.0, makeup=2.0),
    # Default, all-purpose.
    "medium":     dict(threshold=-20.0, ratio=3.0,  attack=10.0, release=200.0, makeup=4.0),
    # Pumping, obvious — for noisy podcast guests / level-mismatched sources.
    "heavy":      dict(threshold=-24.0, ratio=6.0,  attack=5.0,  release=150.0, makeup=6.0),
    # Spoken-word optimized.
    "podcast":    dict(threshold=-22.0, ratio=4.0,  attack=8.0,  release=180.0, makeup=5.0),
    # Broadcast loudness control before loudnorm — heavy ratio, fast attack.
    "broadcast":  dict(threshold=-18.0, ratio=8.0,  attack=3.0,  release=120.0, makeup=4.0),
}


# Output codec aliases the user can pass via --encode.
ENCODE_TARGETS = {
    "mp3":  ("libmp3lame", ".mp3"),
    "aac":  ("aac",        ".m4a"),
    "opus": ("libopus",    ".opus"),
    "flac": ("flac",       ".flac"),
    "wav":  ("pcm_s16le",  ".wav"),
}


def _validate_params(threshold: float, ratio: float, attack: float, release: float,
                     makeup: float) -> str | None:
    """Return an error message if any DRC param is out of FFmpeg's accepted range."""
    if not -60.0 <= threshold <= 0.0:
        return f"threshold must be -60..0 dB, got {threshold}"
    if not 1.0 <= ratio <= 20.0:
        return f"ratio must be 1..20, got {ratio}"
    if not 0.01 <= attack <= 2000.0:
        return f"attack must be 0.01..2000 ms, got {attack}"
    if not 0.01 <= release <= 9000.0:
        return f"release must be 0.01..9000 ms, got {release}"
    if not 0.0 <= makeup <= 24.0:
        return f"makeup must be 0..24 dB, got {makeup}"
    return None


def _build_filter(threshold: float, ratio: float, attack: float, release: float,
                  makeup: float) -> str:
    """Compose the FFmpeg `acompressor` filter string from validated params."""
    threshold_lin = 10 ** (threshold / 20.0)
    return (
        f"acompressor=threshold={threshold_lin:.6f}"
        f":ratio={ratio}"
        f":attack={attack}"
        f":release={release}"
        f":makeup={makeup}"
    )


def _resolve_output(src: Path, out_dir: Path, encode: str | None,
                    suffix: str) -> Path:
    """Compose unique output path: <out_dir>/<stem>_<suffix>.<ext> with collision-safe rename."""
    if encode:
        ext = ENCODE_TARGETS[encode][1]
    else:
        ext = src.suffix or ".out"
    out = out_dir / f"{src.stem}_{suffix}{ext}"
    if not out.exists():
        return out
    for i in range(1, 10000):
        cand = out_dir / f"{src.stem}_{suffix} ({i}){ext}"
        if not cand.exists():
            return cand
    return out_dir / f"{src.stem}_{suffix}_{int(time.time())}{ext}"


def _is_video(src: Path, ffprobe: str | None) -> bool:
    """Probe whether the source contains a video stream so we can copy it."""
    if src.suffix.lower() in AUDIO_EXTS:
        return False
    if not ffprobe:
        # No probe available — be conservative and assume audio-only so we
        # don't accidentally drop a video stream.
        return False
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0",
             str(src)],
            capture_output=True, text=True, timeout=20,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return proc.returncode == 0 and "video" in (proc.stdout or "")


def _run_one(src: Path, out_path: Path, filter_str: str, encode: str | None,
             ffmpeg: str, ffprobe: str | None) -> tuple[int, str | None]:
    """Run FFmpeg for a single input. Returns (rc, error_tail)."""
    cmd = [ffmpeg, "-y", "-i", str(src), "-af", filter_str]
    has_video = _is_video(src, ffprobe)
    if has_video:
        # Re-mux: copy video, only re-encode the filtered audio.
        cmd += ["-c:v", "copy"]
    if encode:
        codec, _ = ENCODE_TARGETS[encode]
        cmd += ["-c:a", codec]
        if encode == "mp3":
            cmd += ["-q:a", "2"]
        elif encode == "aac":
            cmd += ["-b:a", "192k"]
        elif encode == "opus":
            cmd += ["-b:a", "128k"]
    elif has_video:
        # Video container, no explicit encode requested — use AAC (broadly
        # compatible) so we don't end up with a stream the container can't carry.
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    # else: audio-only without --encode → FFmpeg picks the codec from the
    # output container extension, which preserves the original format when the
    # output extension matches input.
    cmd.append(str(out_path))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode == 0:
        return 0, None
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
    return proc.returncode, "; ".join(tail)


def op_compress(args: argparse.Namespace) -> int:
    err = _validate_params(args.threshold, args.ratio, args.attack, args.release,
                           args.makeup)
    if err:
        return fail("invalid_param", err)
    return _drive_files(args, args.threshold, args.ratio, args.attack, args.release,
                        args.makeup, suffix="compressed")


def op_preset(args: argparse.Namespace) -> int:
    if args.name not in PRESETS:
        return fail("unknown_preset",
                    f"Preset '{args.name}' unknown. Available: {sorted(PRESETS)}")
    p = PRESETS[args.name]
    return _drive_files(args, p["threshold"], p["ratio"], p["attack"], p["release"],
                        p["makeup"], suffix=args.name)


def _drive_files(args: argparse.Namespace, threshold: float, ratio: float,
                 attack: float, release: float, makeup: float, suffix: str) -> int:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found on PATH (set FFMPEG_PATH).")
    ffprobe = _find_ffprobe()  # optional

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss:
        return fail("missing_input", f"Audio file(s) not found: {miss}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    encode = args.encode if args.encode else None
    if encode and encode not in ENCODE_TARGETS:
        return fail("unknown_encode",
                    f"Unknown --encode '{encode}'. Available: {sorted(ENCODE_TARGETS)}")

    filter_str = _build_filter(threshold, ratio, attack, release, makeup)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="compressing", eta_seconds=None)

    failures = 0
    for i, src in enumerate(inputs):
        out_path = _resolve_output(src, out_dir, encode, suffix)
        rc, err_tail = _run_one(src, out_path, filter_str, encode, ffmpeg, ffprobe)
        if rc != 0:
            failures += 1
            if err_tail:
                emit("log", level="error", message=err_tail)
            emit("audio_compressed",
                 input=str(src), output=None,
                 size_bytes=None, source_bytes=src.stat().st_size,
                 threshold_db=threshold, ratio=ratio, attack_ms=attack,
                 release_ms=release, makeup_db=makeup,
                 success=False, error=f"ffmpeg_rc={rc}")
        else:
            try:
                out_bytes = out_path.stat().st_size
            except OSError:
                out_bytes = 0
            emit("audio_compressed",
                 input=str(src), output=str(out_path),
                 size_bytes=out_bytes, source_bytes=src.stat().st_size,
                 threshold_db=threshold, ratio=ratio, attack_ms=attack,
                 release_ms=release, makeup_db=makeup,
                 success=True)

        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1), stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    if failures == total:
        return fail("all_failed", f"All {total} input(s) failed; see log entries above.")

    emit("complete", output=str(out_dir), size_bytes=0, count=total - failures)
    return 0 if failures == 0 else 0  # partial success still exits 0; per-file event carries failure


def op_presets(_args: argparse.Namespace) -> int:
    """Enumerate built-in DRC presets so the UI can populate a dropdown."""
    for name, p in PRESETS.items():
        emit("preset", name=name,
             threshold_db=p["threshold"], ratio=p["ratio"],
             attack_ms=p["attack"], release_ms=p["release"],
             makeup_db=p["makeup"])
    emit("complete", output="", size_bytes=0, count=len(PRESETS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audio-compressor-sidecar",
        description="FFmpeg acompressor wrapper — dynamic-range compression for audio.",
    )
    sub = p.add_subparsers(dest="op", required=True)

    c = sub.add_parser("compress",
                       help="Apply explicit DRC parameters (threshold/ratio/attack/release/makeup).")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--threshold", type=float, default=-20.0,
                   help="Compression threshold in dB (negative). Default -20.")
    c.add_argument("--ratio", type=float, default=3.0,
                   help="Compression ratio :1. Default 3.")
    c.add_argument("--attack", type=float, default=10.0,
                   help="Attack in ms. Default 10.")
    c.add_argument("--release", type=float, default=200.0,
                   help="Release in ms. Default 200.")
    c.add_argument("--makeup", type=float, default=4.0,
                   help="Makeup gain in dB. Default 4.")
    c.add_argument("--encode", choices=sorted(ENCODE_TARGETS),
                   help="Re-encode output to this codec. Omit to preserve container+codec.")

    pr = sub.add_parser("preset", help="Apply a named DRC preset (light/medium/heavy/podcast/broadcast).")
    pr.add_argument("--name", required=True, choices=sorted(PRESETS))
    pr.add_argument("--input", nargs="+", required=True)
    pr.add_argument("--output-dir", required=True, dest="output_dir")
    pr.add_argument("--encode", choices=sorted(ENCODE_TARGETS),
                    help="Re-encode output to this codec. Omit to preserve container+codec.")

    sub.add_parser("presets", help="List built-in DRC presets (NDJSON output).")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "compress":
            return op_compress(args)
        if args.op == "preset":
            return op_preset(args)
        if args.op == "presets":
            return op_presets(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:  # noqa: BLE001 — surface unexpected errors as a single error event
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
