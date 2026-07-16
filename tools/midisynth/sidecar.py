"""MIDI / SoundFont renderer -- .mid / .midi -> WAV / FLAC / MP3 / OGG via
FluidSynth + ffmpeg. Requires fluidsynth.exe on PATH and at least one .sf2
SoundFont file (path passed via --soundfont or auto-discovered).
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


def _find_fluidsynth() -> str | None:
    env = os.environ.get("FLUIDSYNTH_PATH")
    if env and Path(env).is_file(): return env
    for n in ("fluidsynth.exe", "fluidsynth"):
        hit = shutil.which(n)
        if hit: return hit
    for c in (r"C:\Program Files\FluidSynth\bin\fluidsynth.exe",
              r"C:\Tools\FluidSynth\bin\fluidsynth.exe"):
        if Path(c).is_file(): return c
    return None


def _find_ffmpeg() -> str | None:
    return shared_find_ffmpeg(Path(__file__).resolve().parent)


def _find_soundfont(hint: str | None) -> str | None:
    if hint and Path(hint).is_file(): return hint
    # Bundled location adjacent to the sidecar.
    here = Path(__file__).resolve().parent
    for cand in (here / "soundfont.sf2", here.parent / "_assets" / "soundfont.sf2"):
        if cand.is_file(): return str(cand)
    # Common Windows install of GeneralUser GS / FluidR3.
    for c in (r"C:\Program Files\FluidSynth\share\sf2\GeneralUser GS v1.471.sf2",
              r"C:\Program Files\Common Files\Microsoft Shared\MIDI\gm.dls"):
        if Path(c).is_file(): return c
    return None


def op_render(args: argparse.Namespace) -> int:
    fs = _find_fluidsynth()
    if not fs:
        return fail("missing_fluidsynth",
                    "fluidsynth.exe not found. Install FluidSynth or set FLUIDSYNTH_PATH.")

    sf = _find_soundfont(args.soundfont)
    if not sf:
        return fail("missing_soundfont",
                    "No .sf2 SoundFont found. Pass --soundfont path/to/file.sf2.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"MIDI file(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    if target not in ("wav", "flac", "mp3", "ogg"):
        return fail("bad_format", f"Use wav | flac | mp3 | ogg.")

    ffmpeg = _find_ffmpeg() if target != "wav" else None
    if target != "wav" and not ffmpeg:
        return fail("missing_ffmpeg", f"{target.upper()} requires ffmpeg.")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="render", eta_seconds=None)

    for i, src in enumerate(inputs):
        wav_path = out_dir / (src.stem + ".wav")
        cmd = [fs, "-ni", "-F", str(wav_path),
               "-r", str(args.sample_rate),
               "-g", str(args.gain),
               sf, str(src)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).splitlines()[-5:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("fluidsynth_failed", f"{src.name}: rc={proc.returncode}")
        emit("log", level="info", message=f"Rendered {src.name} -> WAV")

        out_path = wav_path
        if target != "wav":
            out_path = out_dir / (src.stem + "." + target)
            cmd_ff = [ffmpeg, "-y", "-i", str(wav_path), str(out_path)]
            proc2 = subprocess.run(cmd_ff, capture_output=True, text=True)
            try: wav_path.unlink()
            except OSError: pass
            if proc2.returncode != 0:
                return fail("ffmpeg_failed", f"{src.name}: rc={proc2.returncode}")

        emit("midi_render",
             input=str(src), output=str(out_path),
             soundfont=sf,
             size_bytes=out_path.stat().st_size)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="midisynth-sidecar",
                                description="MIDI -> audio via FluidSynth.")
    sub = p.add_subparsers(dest="op", required=True)
    r = sub.add_parser("render", help="Render MIDI files via SoundFont.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--output-dir", required=True, dest="output_dir")
    r.add_argument("--format", default="wav", help="wav | flac | mp3 | ogg")
    r.add_argument("--soundfont", help="Path to a .sf2 SoundFont (auto-discovers if omitted).")
    r.add_argument("--sample-rate", type=int, default=48000, dest="sample_rate")
    r.add_argument("--gain", type=float, default=0.5, help="Output gain (0.0 - 5.0). Default 0.5.")
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
