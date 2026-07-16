"""Automatic audio-mastering sidecar.

Wraps Matchering 2.0 (sergree/matchering, GPL-3) -- the open-source automatic
mastering engine that takes a "target" track + a reference track ("master
this to sound like X") and produces a mastered version of the target.

Two modes:

  match     Master `--target` to sound like `--reference` (full pipeline).
  loudnorm  EBU R128 loudness normalization without a reference (preset-based).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def op_match(args: argparse.Namespace) -> int:
    try:
        import matchering as mg
    except ImportError as ex:
        return fail("missing_matchering",
                    f"matchering not installed: {ex}. `pip install matchering`.")

    target = Path(args.target)
    ref = Path(args.reference)
    if not target.is_file(): return fail("missing_input", f"Target not found: {target}")
    if not ref.is_file(): return fail("missing_input", f"Reference not found: {ref}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_24bit = out_dir / (target.stem + "_master_24bit.wav")
    out_16bit = out_dir / (target.stem + "_master_16bit.wav")
    out_mp3 = out_dir / (target.stem + "_master.mp3") if args.mp3 else None

    started = time.monotonic()
    emit("progress", percent=0, stage="matchering", eta_seconds=None)
    try:
        results = [
            mg.pcm24(str(out_24bit)),
            mg.pcm16(str(out_16bit)),
        ]
        if out_mp3 is not None:
            results.append(mg.Result(file=str(out_mp3), subtype="MP3"))
        mg.process(target=str(target), reference=str(ref), results=results)
    except Exception as ex:
        emit("log", level="error", message=str(ex))
        return fail("matchering_failed", str(ex))

    for op in (out_24bit, out_16bit, out_mp3):
        if op is None: continue
        if op.is_file():
            emit("master_audio",
                 input=str(target), reference=str(ref),
                 output=str(op),
                 size_bytes=op.stat().st_size,
                 format=op.suffix.lstrip("."))
    emit("progress", percent=100, stage="done",
         eta_seconds=int(time.monotonic() - started))
    emit("complete", output=str(out_dir), size_bytes=0,
         count=len([p for p in (out_24bit, out_16bit, out_mp3) if p is not None]))
    return 0


def op_loudnorm(args: argparse.Namespace) -> int:
    """Two-pass FFmpeg loudnorm (EBU R128) when no reference track is given."""
    import shutil
    import subprocess
    import tempfile
    ffmpeg = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found on PATH.")

    inputs = [Path(p) for p in args.input]
    miss = [str(p) for p in inputs if not p.is_file()]
    if miss: return fail("missing_input", f"Audio file(s) not found: {miss}")
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    target_lufs = float(args.lufs)
    target_tp = float(args.tp)
    target_lra = float(args.lra)

    total = len(inputs)
    started = time.monotonic()
    emit("progress", percent=0, stage="loudnorm", eta_seconds=None)

    for i, src in enumerate(inputs):
        # Pass 1 -- measure
        f1 = [ffmpeg, "-i", str(src),
              "-af", f"loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}:print_format=json",
              "-f", "null", "-"]
        proc = subprocess.run(f1, capture_output=True, text=True)
        stderr = proc.stderr or ""
        # Find the JSON block printed by loudnorm.
        s = stderr.rfind("{"); e = stderr.rfind("}")
        if s == -1 or e == -1:
            return fail("loudnorm_measure_failed",
                        "Could not parse loudnorm pass 1 output.")
        meas = json.loads(stderr[s:e + 1])
        # Pass 2 -- apply
        out_path = out_dir / (src.stem + "_loudnorm" + src.suffix)
        af = (
            f"loudnorm=I={target_lufs}:TP={target_tp}:LRA={target_lra}"
            f":measured_I={meas['input_i']}"
            f":measured_TP={meas['input_tp']}"
            f":measured_LRA={meas['input_lra']}"
            f":measured_thresh={meas['input_thresh']}"
            f":offset={meas['target_offset']}"
            f":linear=true:print_format=summary"
        )
        f2 = [ffmpeg, "-y", "-i", str(src), "-af", af, str(out_path)]
        proc = subprocess.run(f2, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            for ln in tail: emit("log", level="error", message=ln)
            return fail("loudnorm_failed", f"{src.name}: rc={proc.returncode}")

        emit("master_audio",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             format="loudnorm",
             target_lufs=target_lufs, target_tp=target_tp, target_lra=target_lra)
        pct = (i + 1) / total * 100
        elapsed = time.monotonic() - started
        eta = (elapsed / (pct / 100) - elapsed) if pct > 1 else None
        emit("progress", percent=round(pct, 1),
             stage=f"{i+1}/{total}",
             eta_seconds=int(eta) if eta and eta < 86400 else None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="audiomastering-sidecar",
                                description="Automatic audio mastering "
                                            "(Matchering 2.0 + FFmpeg loudnorm).")
    sub = p.add_subparsers(dest="op", required=True)

    m = sub.add_parser("match", help="Reference-based mastering (Matchering 2.0).")
    m.add_argument("--target", required=True, help="Track to be mastered.")
    m.add_argument("--reference", required=True, help="Reference track.")
    m.add_argument("--output-dir", required=True, dest="output_dir")
    m.add_argument("--mp3", action="store_true",
                   help="Also export an MP3 master (in addition to 16/24-bit WAV).")

    l = sub.add_parser("loudnorm", help="EBU R128 loudness normalization.")
    l.add_argument("--input", nargs="+", required=True)
    l.add_argument("--output-dir", required=True, dest="output_dir")
    l.add_argument("--lufs", default=-14.0,
                   help="Integrated loudness target (default -14 LUFS = streaming).")
    l.add_argument("--tp", default=-1.0, help="True peak ceiling in dBTP (default -1).")
    l.add_argument("--lra", default=11.0, help="Loudness range target (default 11).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "match":    return op_match(args)
        if args.op == "loudnorm": return op_loudnorm(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
