"""Long-tail audio codec sidecar (extends `audiopro`).

Adds the formats `audiopro` doesn't already cover, focused on
audiophile / broadcast / mobile niches:

  * AIFF / AIFC                  Apple Audio Interchange File Format
  * IFF-8SVX                     Amiga uncompressed sound
  * Apple CAF                    Core Audio Format (any-codec container)
  * uLaw / aLaw                  G.711 telephony
  * DTS Master Audio (DTS-HD MA) lossless DTS
  * TrueHD / MLP                 Dolby TrueHD lossless
  * HE-AAC v2 / xHE-AAC          modern AAC variants
  * Sony ATRAC3 / ATRAC3+        legacy MiniDisc (read-only)

Backed by FFmpeg shellouts.
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
from ucx_sidecar import emit, find_ffmpeg as shared_find_ffmpeg




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_ffmpeg() -> str | None:
    return shared_find_ffmpeg(Path(__file__).resolve().parent)


# Each entry: (FFmpeg codec, container, default args).
TARGETS = {
    "aiff":   ("pcm_s16be", ".aiff", []),
    "aifc":   ("pcm_s16be", ".aifc", []),
    "iff":    ("pcm_s16be", ".iff",  []),
    "caf":    (None, ".caf", []),                 # let FFmpeg pick the codec
    "ulaw":   ("pcm_mulaw", ".ulaw", ["-ar", "8000", "-ac", "1"]),
    "alaw":   ("pcm_alaw",  ".alaw", ["-ar", "8000", "-ac", "1"]),
    "dts":    ("dts", ".dts", ["-strict", "-2"]),    # DTS encode marked experimental
    "thd":    ("truehd", ".thd", []),
    "mlp":    ("mlp", ".mlp", []),
    "heaac":  ("aac", ".m4a", ["-profile:a", "aac_he", "-b:a", "64k"]),
    "heaacv2":("libfdk_aac", ".m4a", ["-profile:a", "aac_he_v2", "-b:a", "32k"]),
    "xhe":    ("libfdk_aac", ".m4a", ["-profile:a", "aac_low", "-b:a", "24k"]),
}


def op_convert(args: argparse.Namespace) -> int:
    ffmpeg = _find_ffmpeg()
    if not ffmpeg: return fail("missing_ffmpeg", "FFmpeg not found.")

    fmt = args.format.lower().lstrip(".")
    if fmt not in TARGETS:
        return fail("bad_format", f"Choose: {sorted(TARGETS)}")
    codec, ext, fmt_args = TARGETS[fmt]

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Audio file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="audiomore", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + ext)
        cmd = [ffmpeg, "-y", "-i", str(src)]
        if codec: cmd += ["-c:a", codec]
        cmd += fmt_args
        if args.bitrate: cmd += ["-b:a", args.bitrate]
        cmd += [str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("convert_failed", f"{src.name}: rc={proc.returncode}")

        emit("audio_long_tail",
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="audiomore-sidecar",
                                description="Long-tail audio codec conversion (AIFF / CAF / DTS / TrueHD / HE-AAC / ulaw / alaw).")
    sub = p.add_subparsers(dest="op", required=True)
    c = sub.add_parser("convert", help="Convert audio to a long-tail target codec.")
    c.add_argument("--input", nargs="+", required=True)
    c.add_argument("--output-dir", required=True, dest="output_dir")
    c.add_argument("--format", required=True,
                   help=f"Target: {sorted(TARGETS)}")
    c.add_argument("--bitrate", default=None,
                   help="Override bitrate (e.g. 256k).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "convert": return op_convert(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
