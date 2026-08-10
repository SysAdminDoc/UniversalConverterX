"""Retro / chiptune music sidecar.

Render legacy game-music files to modern audio (WAV / FLAC / MP3 / OGG)
via Game Music Emulator (gme) and SID/AHX/HVL helpers:

  * NSF / NSFE     Nintendo Entertainment System
  * SPC            Super Nintendo (Sony SPC700)
  * VGM / VGZ      multi-system VGM logs (Genesis / SMS / PCE / Neo Geo / etc.)
  * GBS            Game Boy / Game Boy Color
  * HES            PC Engine / TurboGrafx-16
  * KSS            MSX
  * GYM            Sega Genesis
  * AY             ZX Spectrum / Amstrad CPC
  * SID            Commodore 64 (sidplayfp)
  * AHX / HVL      Amiga AHX / HivelyTracker

Backed by `pyo3-rs/game-music-emu` Python wheels (gme), with sidplayfp +
hvl_player CLI shellouts for SID / AHX / HVL.
"""
from __future__ import annotations

import argparse
from functools import partial
import json
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg as shared_find_ffmpeg




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


GME_EXTS = {".nsf", ".nsfe", ".spc", ".vgm", ".vgz", ".gbs", ".hes",
            ".kss", ".gym", ".ay", ".sap"}


_find_ffmpeg = partial(shared_find_ffmpeg, Path(__file__).resolve().parent)


def _gme_render(src: Path, out_dir: Path, target: str,
                length_seconds: int, sample_rate: int) -> Path | None:
    """Render a GME-supported file to WAV, optionally transcode."""
    try:
        import gme  # game-music-emu Python binding
    except ImportError as ex:
        emit("error", code="missing_gme",
             message=f"game-music-emu not installed: {ex}. "
                     "`pip install game-music-emu` (or build pyo3 binding).")
        return None

    emu, info = gme.gme_open_file(str(src), sample_rate)
    try:
        track_count = gme.gme_track_count(emu)
        outputs: list[Path] = []
        for track in range(track_count):
            track_info = gme.gme_track_info(emu, track)
            gme.gme_start_track(emu, track)
            duration = min(length_seconds * 1000,
                           int(track_info.length or length_seconds * 1000))
            samples = int(sample_rate * (duration / 1000.0))
            buf = gme.gme_play(emu, samples * 2)  # stereo
            wav_path = out_dir / (src.stem + f"_t{track + 1:02d}.wav")
            with wave.open(str(wav_path), "wb") as w:
                w.setnchannels(2); w.setsampwidth(2); w.setframerate(sample_rate)
                w.writeframes(buf)
            if target == "wav":
                outputs.append(wav_path)
            else:
                ffmpeg = _find_ffmpeg()
                if not ffmpeg:
                    outputs.append(wav_path); continue
                final = wav_path.with_suffix("." + target)
                proc = subprocess.run(
                    [ffmpeg, "-y", "-i", str(wav_path), str(final)],
                    capture_output=True, text=True, timeout=600)
                if proc.returncode == 0:
                    wav_path.unlink(missing_ok=True)
                    outputs.append(final)
                else:
                    outputs.append(wav_path)
        return outputs[0] if outputs else None
    finally:
        gme.gme_delete(emu)


def _sid_render(src: Path, out_dir: Path, target: str,
                 length_seconds: int) -> Path | None:
    sidplayfp = shutil.which("sidplayfp") or shutil.which("sidplayfp.exe")
    if not sidplayfp:
        emit("error", code="missing_sidplayfp",
             message="sidplayfp not on PATH. `apt install sidplayfp`.")
        return None
    out_path = out_dir / (src.stem + ".wav")
    cmd = [sidplayfp, "-w" + str(out_path), "-t" + str(length_seconds),
           str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        emit("log", level="error",
             message=(proc.stderr or proc.stdout).strip()[:240])
        return None
    if target != "wav":
        ffmpeg = _find_ffmpeg()
        if ffmpeg:
            final = out_path.with_suffix("." + target)
            subprocess.run([ffmpeg, "-y", "-i", str(out_path), str(final)],
                            capture_output=True, text=True, timeout=600)
            if final.is_file():
                out_path.unlink(missing_ok=True); return final
    return out_path


def op_render(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Chiptune file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = args.format.lower().lstrip(".")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="chiptune", eta_seconds=None)

    for i, src in enumerate(inputs):
        ext = src.suffix.lower()
        out_path: Path | None = None
        if ext in GME_EXTS:
            out_path = _gme_render(src, out_dir, target,
                                    args.length, args.sample_rate)
        elif ext == ".sid":
            out_path = _sid_render(src, out_dir, target, args.length)
        elif ext in (".ahx", ".thx", ".hvl"):
            return fail("unsupported_yet",
                        f"{src.name}: AHX/HVL renderers not bundled. "
                        "Install hvl_player + place its CLI on PATH.")
        else:
            return fail("bad_format", f"Unsupported chiptune ext: {ext}")
        if out_path is None:
            return fail("render_failed", f"{src.name}: render produced no output.")

        emit("chiptune_audio",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format=target, source_ext=ext.lstrip("."),
             length_seconds=int(args.length))
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chiptune-sidecar",
                                description="Retro game-music renderer (NSF / SPC / VGM / GBS / HES / KSS / SID / AY).")
    sub = p.add_subparsers(dest="op", required=True)
    r = sub.add_parser("render", help="Render chiptune to audio.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--output-dir", required=True, dest="output_dir")
    r.add_argument("--format", default="wav",
                   help="wav | flac | mp3 | ogg | opus")
    r.add_argument("--length", type=int, default=180,
                   help="Cap track length in seconds (default 180).")
    r.add_argument("--sample-rate", type=int, default=44100, dest="sample_rate")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "render": return op_render(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
