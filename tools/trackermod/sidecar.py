"""Tracker module sidecar -- MOD / IT / XM / S3M / MTM / OKT / MED / DBM / 669
plus 30+ niche formats -> WAV / FLAC via libopenmpt-python.

Falls back to `ffmpeg -i file.mod -f libopenmpt out.wav` when the python
bindings aren't installed but ffmpeg has libopenmpt support compiled in.
"""
from __future__ import annotations

import argparse
import json
try:
    import orjson
    def _dumps(obj):
        return orjson.dumps(obj).decode()
except ImportError:
    def _dumps(obj):
        return json.dumps(obj, ensure_ascii=False)
import os
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path


def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _try_libopenmpt():
    try:
        import libopenmpt as _  # newer wheels
        return ("libopenmpt", _)
    except ImportError:
        try:
            import pyopenmpt as _
            return ("pyopenmpt", _)
        except ImportError:
            return (None, None)


def _find_ffmpeg() -> str | None:
    here = Path(__file__).resolve().parent
    for c in (os.environ.get("FFMPEG_PATH"), shutil.which("ffmpeg"),
              str(here / "ffmpeg.exe"), str(here.parent / "_bin" / "ffmpeg.exe")):
        if c and Path(c).is_file(): return c
    return None


def op_render(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing: return fail("missing_input", f"Module(s) not found: {missing}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target = args.format.lower().lstrip(".")
    if target not in ("wav", "flac", "mp3", "ogg"):
        return fail("bad_format", f"Use wav | flac | mp3 | ogg (got '{target}').")

    backend, mod = _try_libopenmpt()
    ffmpeg = _find_ffmpeg()
    if backend is None and ffmpeg is None:
        return fail("missing_backend",
                    "Neither libopenmpt-python nor ffmpeg is available. "
                    "pip install libopenmpt OR install an ffmpeg build with libopenmpt.")

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="render", eta_seconds=None)

    for i, src in enumerate(inputs):
        out_path = out_dir / (src.stem + "." + target)

        if backend is not None and target == "wav":
            try:
                with src.open("rb") as fh:
                    raw = fh.read()
                # Older API: Module(bytes); newer: ModuleFile(stream).
                if hasattr(mod, "Module"):
                    m = mod.Module(raw)
                else:
                    import io as _io
                    m = mod.ModuleFile(_io.BytesIO(raw))
                sample_rate = int(args.sample_rate)
                # 16-bit stereo PCM.
                with wave.open(str(out_path), "wb") as w:
                    w.setnchannels(2); w.setsampwidth(2); w.setframerate(sample_rate)
                    chunk_frames = 2048
                    import struct
                    while True:
                        try:
                            data = m.read(sample_rate, chunk_frames)
                        except Exception:
                            break
                        # libopenmpt-py varies per version; assume float32 stereo or int16 stereo.
                        if not data: break
                        if isinstance(data, (bytes, bytearray)):
                            w.writeframes(bytes(data))
                        else:
                            # sequence of (left, right) floats; clamp + pack.
                            buf = bytearray()
                            for L, R in data:
                                il = max(-32768, min(32767, int(L * 32767)))
                                ir = max(-32768, min(32767, int(R * 32767)))
                                buf += struct.pack("<hh", il, ir)
                            w.writeframes(bytes(buf))
                emit("tracker_song",
                     input=str(src), output=str(out_path),
                     size_bytes=out_path.stat().st_size,
                     backend=backend)
            except Exception as ex:
                emit("log", level="warn", message=f"libopenmpt failed on {src.name}: {ex}")
                if ffmpeg is None:
                    return fail("render_failed", str(ex))
                # Fall through to ffmpeg.

        # ffmpeg fallback (also primary path for FLAC / MP3 / OGG even when libopenmpt is present).
        if ffmpeg is not None and not out_path.is_file():
            cmd = [ffmpeg, "-y", "-i", str(src),
                   "-ar", str(args.sample_rate), "-ac", "2", str(out_path)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout).splitlines()[-5:]
                for ln in tail: emit("log", level="error", message=ln)
                return fail("ffmpeg_failed", f"{src.name}: {proc.returncode}")
            emit("tracker_song",
                 input=str(src), output=str(out_path),
                 size_bytes=out_path.stat().st_size,
                 backend="ffmpeg")

        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trackermod-sidecar",
                                description="Tracker module renderer (libopenmpt + ffmpeg).")
    sub = p.add_subparsers(dest="op", required=True)
    r = sub.add_parser("render", help="Render MOD / IT / XM / S3M / etc. to audio.")
    r.add_argument("--input", nargs="+", required=True)
    r.add_argument("--output-dir", required=True, dest="output_dir")
    r.add_argument("--format", default="wav", help="wav | flac | mp3 | ogg")
    r.add_argument("--sample-rate", type=int, default=48000, dest="sample_rate")
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
