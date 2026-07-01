"""whisper.cpp GPU sidecar — NDJSON wrapper for whisper-cli.exe.

Secondary STT path alongside the primary `whisper-stt` (faster-whisper) sidecar.
Routes to the prebuilt whisper.cpp Windows binary which:
  - has zero Python dependency at runtime (single .exe + GGUF model)
  - supports Vulkan / CUDA / CoreML backends compiled in
  - integrates Silero VAD v6.2.0 (--vad flag) to skip silence

Subcommands:
  transcribe    one input → SRT/VTT/TXT/JSON transcript
  list-models   enumerate .bin GGUF models discoverable in tools/whisper-cpp/models/
  list-backends report which whisper-cli features are present (probed once)

Standard NDJSON contract: progress / log / complete / error / model / segment.
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
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# ── NDJSON helpers ───────────────────────────────────────────────────────────

def emit(event: str, **fields) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
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


# ── Discovery ────────────────────────────────────────────────────────────────

def _here() -> Path:
    return Path(__file__).resolve().parent


def find_whisper_cli() -> Path | None:
    """Search order: WHISPER_CPP_EXE → tools/whisper-cpp/bin/whisper-cli.exe →
    tools/whisper-cpp/bin/main.exe (legacy) → PATH."""
    here = _here()
    candidates = [
        os.environ.get("WHISPER_CPP_EXE"),
        str(here / "bin" / "whisper-cli.exe"),
        str(here / "bin" / "main.exe"),
        shutil.which("whisper-cli"),
        shutil.which("whisper.cpp"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


def find_ffmpeg() -> str | None:
    here = _here()
    for c in [
        os.environ.get("FFMPEG_PATH"),
        shutil.which("ffmpeg"),
        str(here / "ffmpeg.exe"),
        str(here.parent / "_bin" / "ffmpeg.exe"),
    ]:
        if c and Path(c).is_file():
            return c
    return None


def discover_models() -> list[dict]:
    """List ggml-*.bin GGUF model files in known locations."""
    locations: list[Path] = []
    here = _here()
    for d in [here / "bin" / "models", here / "models",
              Path(os.environ.get("UCX_MODEL_DIR") or "") / "whisper-cpp"]:
        if d and d.is_dir():
            locations.append(d)

    seen: dict[str, dict] = {}
    for loc in locations:
        for f in sorted(loc.glob("ggml-*.bin")):
            stem = f.stem
            if stem.lower() in seen:
                continue
            seen[stem.lower()] = {
                "name":  stem,
                "path":  str(f),
                "dir":   str(loc),
                "size_bytes": f.stat().st_size,
            }
    return list(seen.values())


# ── list-models ──────────────────────────────────────────────────────────────

def op_list_models(_: argparse.Namespace) -> int:
    found = discover_models()
    for m in found:
        emit("model", name=m["name"], path=m["path"], location=m["dir"],
             size_bytes=m["size_bytes"])
    emit("complete", count=len(found))
    return 0


# ── list-backends ────────────────────────────────────────────────────────────

def op_list_backends(_: argparse.Namespace) -> int:
    """Probe whisper-cli --help text for compiled-in feature flags."""
    exe = find_whisper_cli()
    if exe is None:
        emit("complete", available=False)
        return 0
    try:
        result = subprocess.run([str(exe), "--help"], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return fail("probe_failed", f"Could not run --help: {exc}")
    text = (result.stdout or "") + (result.stderr or "")
    flags = {
        "vulkan":  "vulkan" in text.lower(),
        "cuda":    "cuda" in text.lower() or "cublas" in text.lower(),
        "coreml":  "coreml" in text.lower(),
        "metal":   "metal" in text.lower(),
        "vad":     "--vad" in text,
        "silero":  "silero" in text.lower(),
    }
    emit("backend",
         available=True,
         exe=str(exe),
         **flags)
    emit("complete", available=True)
    return 0


# ── transcribe ───────────────────────────────────────────────────────────────

def _convert_to_wav16(ffmpeg: str, src: Path, work_dir: Path) -> Path | None:
    """whisper.cpp wants 16kHz mono PCM WAV."""
    wav = work_dir / "input.16k.wav"
    cmd = [
        ffmpeg, "-y", "-i", str(src),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(wav),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode != 0 or not wav.exists():
        log("error", f"ffmpeg WAV conversion failed: {res.stderr.strip()[-300:]}")
        return None
    return wav


_PROGRESS_RE = re.compile(r"progress\s*=\s*(\d+)%", re.IGNORECASE)
# whisper-cli prints lines like "[00:00:01.230 --> 00:00:04.560]   text..."
_SEGMENT_RE = re.compile(
    r"\[(\d+):(\d+):(\d+\.\d+)\s+-->\s+(\d+):(\d+):(\d+\.\d+)\]\s+(.+)"
)


def op_transcribe(args: argparse.Namespace) -> int:
    exe = find_whisper_cli()
    if exe is None:
        return fail("missing_exe",
                    "whisper-cli.exe not found. Run "
                    "`pwsh tools/whisper-cpp/build.ps1` to install the upstream "
                    "release into tools/whisper-cpp/bin/.")

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return fail("missing_ffmpeg",
                    "FFmpeg not on PATH; whisper.cpp needs it to resample to 16 kHz mono.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")

    # Resolve model: explicit --model path, or look up by name in discovered set.
    model_path: Path | None = None
    arg_model = args.model
    if arg_model and Path(arg_model).is_file():
        model_path = Path(arg_model)
    else:
        models = {m["name"].lower(): m for m in discover_models()}
        # accept either bare 'base' or 'ggml-base.en' style
        wanted = arg_model.lower() if arg_model else "ggml-base.en"
        if wanted in models:
            model_path = Path(models[wanted]["path"])
        elif f"ggml-{wanted}".lower() in models:
            model_path = Path(models[f"ggml-{wanted}".lower()]["path"])
        elif models:
            # take first available as last resort
            first = next(iter(models.values()))
            model_path = Path(first["path"])
            log("warn", f"Model {arg_model!r} not found; falling back to {first['name']}.")
    if model_path is None:
        return fail("missing_model",
                    "No GGUF model found. Run `pwsh tools/whisper-cpp/build.ps1` "
                    "or drop a ggml-*.bin file into tools/whisper-cpp/models/.")
    log("info", f"Model: {model_path.name}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_ext = out_path.suffix.lower().lstrip(".") or "srt"
    if out_ext not in {"srt", "vtt", "txt", "json"}:
        return fail("invalid_format",
                    f"Output extension must be one of srt|vtt|txt|json, got {out_ext!r}.")

    work = Path(tempfile.mkdtemp(prefix="ucx_whispercpp_"))
    try:
        # 1. Resample to 16 kHz mono PCM.
        progress(2.0, "resampling to 16 kHz mono")
        wav = _convert_to_wav16(ffmpeg, in_path, work)
        if wav is None:
            return fail("convert_failed", "Could not convert input to 16 kHz mono.")

        # 2. Run whisper-cli with the requested format.
        # We always ask for SRT (most universal) plus the explicit format if different.
        out_stem = work / "out"
        cmd = [
            str(exe),
            "-m", str(model_path),
            "-f", str(wav),
            "-of", str(out_stem),
            "-pp",                              # print progress
            "-l", args.language or "auto",
        ]
        if args.threads > 0:
            cmd += ["-t", str(args.threads)]
        if args.gpu_id >= 0:
            cmd += ["-dg", str(args.gpu_id)]
        if args.vad:
            cmd += ["--vad"]
        if args.word_timestamps:
            cmd += ["-ml", "1"]                 # max-len 1 char ≈ word-level
        # Output format flags. whisper-cli supports multiple at once.
        fmt_flags = {"srt": "-osrt", "vtt": "-ovtt", "txt": "-otxt", "json": "-oj"}
        cmd += [fmt_flags[out_ext]]

        log("info", f"whisper-cli command: {' '.join(c.split(chr(92))[-1] for c in cmd[:3])} ...")
        progress(5.0, f"loading {model_path.name}")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        last_pct = 5.0
        # whisper-cli writes progress + segment lines on stderr (merged into stdout above).
        # Drive a coarse 5–95% progress band; emit `segment` events as we see them.
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue

                m = _PROGRESS_RE.search(line)
                if m:
                    raw = int(m.group(1))
                    pct = 5.0 + 0.9 * raw
                    if pct - last_pct >= 0.5:
                        last_pct = pct
                        progress(pct, f"transcribing ({raw}%)", None)
                    continue

                m = _SEGMENT_RE.match(line)
                if m:
                    h0, mm0, s0, h1, mm1, s1, text = m.groups()
                    start = int(h0) * 3600 + int(mm0) * 60 + float(s0)
                    end   = int(h1) * 3600 + int(mm1) * 60 + float(s1)
                    emit("segment",
                         start=round(start, 3),
                         end=round(end, 3),
                         text=text.strip())
                    continue

                # everything else → log
                if line.lower().startswith(("ggml", "system_info", "whisper")):
                    log("info", line)
                else:
                    # noisy library logs stay at debug
                    log("debug", line[:200])
        finally:
            proc.wait()

        if proc.returncode != 0:
            return fail("whisper_failed", f"whisper-cli exited with code {proc.returncode}")

        # 3. Move generated <out_stem>.<ext> into the requested output path.
        produced = Path(str(out_stem) + "." + out_ext)
        if not produced.is_file():
            return fail("output_missing", f"whisper-cli did not produce {produced.name}")
        shutil.move(str(produced), str(out_path))
        progress(100.0, "done", 0)
        emit("complete",
             output=str(out_path),
             size_bytes=out_path.stat().st_size,
             model=model_path.name)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── argparse + main ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="whisper-cpp-sidecar",
        description="UCX whisper.cpp sidecar — Vulkan/CUDA STT via the prebuilt binary.",
    )
    sub = p.add_subparsers(dest="op", required=True)

    tx = sub.add_parser("transcribe", help="Transcribe one file")
    tx.add_argument("--input",  required=True)
    tx.add_argument("--output", required=True,
                    help="Output transcript path; extension drives format (.srt/.vtt/.txt/.json).")
    tx.add_argument("--model",  default="ggml-base.en",
                    help="GGUF model name (stem) or full path. Default: ggml-base.en.")
    tx.add_argument("--language", default="auto",
                    help="Language code or 'auto' (default: auto).")
    tx.add_argument("--threads", type=int, default=0,
                    help="CPU threads (0 = whisper-cli default).")
    tx.add_argument("--gpu-id", type=int, default=-1,
                    help="GPU device index (-1 = default / first available).")
    tx.add_argument("--vad", action="store_true",
                    help="Enable Silero VAD pre-filter (skip silence, reduce hallucinations).")
    tx.add_argument("--word-timestamps", action="store_true",
                    help="Approximate word-level timestamps via -ml 1.")

    sub.add_parser("list-models",   help="Enumerate available GGUF models")
    sub.add_parser("list-backends", help="Report compiled-in whisper-cli features")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "transcribe":
            return op_transcribe(args)
        if args.op == "list-models":
            return op_list_models(args)
        if args.op == "list-backends":
            return op_list_backends(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
