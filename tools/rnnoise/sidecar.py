"""RNNoise sidecar — NDJSON broadband speech denoiser for the UCX Noise Remover module.

Uses FFmpeg's `arnndn` filter (Recurrent Neural Network Noise Suppression),
present since FFmpeg 4.4. No Python ML dependencies — just FFmpeg + a pretrained
RNNoise model file (.rnnn).

Subcommands:
  denoise     run the denoiser on one input file
  list-models emit any *.rnnn files discoverable under tools/rnnoise/models/

Model resolution order (for `denoise`):
  1. --model <path>          explicit override
  2. RNNOISE_MODEL env var
  3. UCX_MODEL_DIR/rnnoise/*.rnnn    shared cache (set by SidecarRunner)
  4. tools/rnnoise/models/*.rnnn     bundled / user-dropped

Standard NDJSON contract: progress / log / complete / error / model events.
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


# ── NDJSON helpers ───────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


def progress(percent: float, stage: str = "", eta: int | None = None) -> None:
    payload: dict = {"percent": round(percent, 1), "stage": stage}
    if eta is not None:
        payload["eta_seconds"] = eta
    emit("progress", **payload)


# ── ffmpeg discovery ─────────────────────────────────────────────────────────

def find_ffmpeg() -> str | None:
    here = Path(__file__).resolve().parent
    for candidate in [
        os.environ.get("FFMPEG_PATH"),
        shutil.which("ffmpeg"),
        str(here / "ffmpeg.exe"),
        str(here.parent / "_bin" / "ffmpeg.exe"),
    ]:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def probe_duration(ffmpeg: str, path: Path) -> float:
    try:
        result = subprocess.run(
            [ffmpeg, "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=15,
        )
        m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", result.stderr)
        if m:
            h, mm, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return h * 3600 + mm * 60 + s
    except Exception:
        pass
    return 0.0


# ── Model discovery ──────────────────────────────────────────────────────────

def _models_dir_local() -> Path:
    return Path(__file__).resolve().parent / "models"


def _models_dir_shared() -> Path | None:
    base = os.environ.get("UCX_MODEL_DIR")
    if not base:
        return None
    return Path(base) / "rnnoise"


def discover_models() -> list[Path]:
    found: list[Path] = []
    for d in [_models_dir_shared(), _models_dir_local()]:
        if d is None:
            continue
        if d.is_dir():
            found.extend(sorted(d.glob("*.rnnn")))
    # de-dup by name, prefer shared cache
    seen: dict[str, Path] = {}
    for p in found:
        seen.setdefault(p.name.lower(), p)
    return list(seen.values())


def resolve_model(arg_path: str | None) -> Path | None:
    if arg_path:
        p = Path(arg_path)
        return p if p.is_file() else None

    env = os.environ.get("RNNOISE_MODEL")
    if env:
        p = Path(env)
        if p.is_file():
            return p

    candidates = discover_models()
    if candidates:
        # Prefer 'cb.rnnn' if present (broadband-conservative default).
        for p in candidates:
            if p.name.lower() == "cb.rnnn":
                return p
        return candidates[0]

    return None


# ── ffmpeg progress parser ───────────────────────────────────────────────────

_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def run_ffmpeg(cmd: list[str], duration_sec: float, stage: str) -> int:
    proc = subprocess.Popen(
        cmd + ["-progress", "pipe:1", "-nostats"],
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
                current = int(m.group(1)) / 1_000_000
                pct = max(0.0, min(100.0, current / duration_sec * 100.0))
                if pct - last_pct >= 0.5:
                    last_pct = pct
                    elapsed = time.monotonic() - started
                    local = pct / 100.0
                    eta = (elapsed / local - elapsed) if local > 0.01 else None
                    progress(pct, stage,
                             int(eta) if eta and eta < 86400 else None)
            elif line.startswith("progress=end"):
                progress(100, stage, 0)
    finally:
        proc.wait()
        if proc.returncode != 0 and proc.stderr is not None:
            for ln in proc.stderr.read().splitlines()[-20:]:
                log("error", ln)
    return proc.returncode


# ── denoise ──────────────────────────────────────────────────────────────────

def op_denoise(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")

    model = resolve_model(args.model)
    if model is None:
        return fail(
            "missing_model",
            "No RNNoise model (.rnnn) found. Pass --model <path>, set "
            "RNNOISE_MODEL, or drop a .rnnn file under "
            "tools/rnnoise/models/. The cb.rnnn model from "
            "github.com/GregorR/rnnoise-models is a good general-purpose "
            "broadband default.",
        )
    log("info", f"Model: {model.name}")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    duration = probe_duration(ffmpeg, in_path)
    log("info", f"Duration: {duration:.1f}s") if duration > 0 else None

    # Build the FFmpeg filter graph.
    # arnndn: RNNoise filter — input must be 48 kHz mono per filter spec; we
    # let FFmpeg resample on the way in.
    # Escape the model path for the filter graph: forward slashes only and
    # single-quote any embedded single quotes per FFmpeg's filter syntax.
    model_str = str(model).replace("\\", "/")
    model_str = model_str.replace("'", "'\\''")
    mix = "aformat=sample_rates=48000:channel_layouts=mono"
    nn = f"arnndn=m='{model_str}'"
    rejoin = "aformat=sample_rates=48000"
    af = f"{mix},{nn},{rejoin}"

    # Output codec routing — keep video stream unchanged, denoise audio only.
    # Pure-audio inputs: let FFmpeg pick from the output extension.
    out_ext = out_path.suffix.lower().lstrip(".")
    audio_codec = ["-c:a", _audio_codec_for(out_ext)]
    audio_bitrate = _audio_bitrate_for(out_ext)
    if audio_bitrate:
        audio_codec += audio_bitrate

    cmd: list[str] = [ffmpeg, "-y", "-i", str(in_path), "-vn"] if args.audio_only else [ffmpeg, "-y", "-i", str(in_path)]
    if not args.audio_only:
        cmd += ["-map", "0", "-c:v", "copy"]
    cmd += ["-af", af, *audio_codec, str(out_path)]

    progress(2.0, "loading model", None)
    log("info", f"FFmpeg command: {' '.join(cmd[:3])} ... {out_path.name}")

    rc = run_ffmpeg(cmd, duration, "denoising")
    if rc != 0:
        return fail("denoise_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")

    emit("complete",
         output=str(out_path),
         size_bytes=out_path.stat().st_size,
         model=model.name)
    return 0


def _audio_codec_for(ext: str) -> str:
    # Conservative defaults — reuse common UCX audio outputs.
    return {
        "mp3":  "libmp3lame",
        "m4a":  "aac",
        "aac":  "aac",
        "ogg":  "libvorbis",
        "opus": "libopus",
        "flac": "flac",
        "wav":  "pcm_s16le",
    }.get(ext, "aac")


def _audio_bitrate_for(ext: str) -> list[str]:
    return {
        "mp3":  ["-b:a", "192k"],
        "m4a":  ["-b:a", "192k"],
        "aac":  ["-b:a", "192k"],
        "ogg":  ["-q:a", "5"],
        "opus": ["-b:a", "96k"],
    }.get(ext, [])


# ── list-models ──────────────────────────────────────────────────────────────

def op_list_models(_: argparse.Namespace) -> int:
    found = discover_models()
    for p in found:
        emit("model", name=p.name, path=str(p), size_bytes=p.stat().st_size,
             location="shared" if _models_dir_shared() and str(p).startswith(str(_models_dir_shared())) else "local")
    emit("complete", count=len(found))
    return 0


# ── argparse + main ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rnnoise-sidecar",
        description="UCX RNNoise sidecar — FFmpeg arnndn broadband denoiser.",
    )
    sub = p.add_subparsers(dest="op", required=True)

    den = sub.add_parser("denoise", help="Denoise one audio or video file")
    den.add_argument("--input",  required=True)
    den.add_argument("--output", required=True,
                     help="Output path; extension drives audio codec selection.")
    den.add_argument("--model",  default=None,
                     help="Path to a .rnnn model. Defaults to cb.rnnn from "
                          "tools/rnnoise/models/ if unset.")
    den.add_argument("--audio-only", action="store_true",
                     help="Drop video stream entirely (output audio only).")

    sub.add_parser("list-models", help="Emit available .rnnn models as NDJSON")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "denoise":
            return op_denoise(args)
        if args.op == "list-models":
            return op_list_models(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
