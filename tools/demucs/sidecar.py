#!/usr/bin/env python3
"""
UCX Demucs Sidecar — headless NDJSON wrapper for demucs stem separation.

Usage:
    sidecar.py --input <path> --output-dir <dir> --model htdemucs_ft
               --stems vocals+drums+bass+other --format wav --shifts 0

NDJSON events emitted to stdout:
    {"event": "log",      "level": "info|warn|error", "message": "..."}
    {"event": "progress", "percent": 0-100, "stage": "...", "eta_seconds": N}
    {"event": "stem",     "name": "vocals|drums|bass|other", "path": "..."}
    {"event": "complete", "stems": [...], "output_dir": "..."}
    {"event": "error",    "code": "...", "message": "..."}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


def log(message: str, level: str = "info") -> None:
    emit({"event": "log", "level": level, "message": message})


def progress(percent: float, stage: str = "", eta: int = -1) -> None:
    emit({"event": "progress", "percent": round(percent, 1), "stage": stage, "eta_seconds": eta})


def error_exit(code: str, message: str) -> None:
    emit({"event": "error", "code": code, "message": message})
    sys.exit(1)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap() -> None:
    """Auto-install demucs and torch if not present."""
    # When frozen with PyInstaller, sys.executable is this sidecar exe — a pip
    # install would re-spawn this exe and fork-bomb the host. Bundle deps at
    # build time instead of relying on runtime install.
    if getattr(sys, "frozen", False):
        try:
            import demucs  # noqa: F401
            return
        except ImportError:
            error_exit("missing_dep",
                       "demucs is not bundled into this frozen sidecar. Rebuild "
                       "with PyInstaller after `pip install demucs torch`.")

    try:
        import demucs  # noqa: F401
        return
    except ImportError:
        pass

    log("demucs not found — installing (this may take a few minutes)...")
    progress(0.0, "Installing demucs...")

    # Try plain install first; fall back to --user
    for extra_args in [[], ["--user"]]:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "demucs>=4.0.1", "--quiet",
             *extra_args],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            log("demucs installed successfully.")
            return
        log(f"pip install attempt failed: {result.stderr.strip()}", "warn")

    # Last resort: --break-system-packages
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "demucs>=4.0.1", "--quiet",
         "--break-system-packages"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        error_exit("install_failed", f"Could not install demucs: {result.stderr.strip()}")

    log("demucs installed.")


# ---------------------------------------------------------------------------
# Stem selection helpers
# ---------------------------------------------------------------------------

_FOUR_STEM_MODELS = {"htdemucs", "htdemucs_ft", "htdemucs_6s", "mdx", "mdx_extra",
                     "mdx_q", "mdx_extra_q", "SIG"}


def resolve_stems(stems_arg: str, model: str) -> list[str]:
    if stems_arg == "2stem":
        return ["vocals", "no_vocals"]
    if stems_arg == "vocals":
        return ["vocals"]
    if stems_arg == "accompaniment":
        return ["no_vocals"]
    if stems_arg == "6stem":
        return ["vocals", "drums", "bass", "guitar", "piano", "other"]
    # 4stem or default: all stems for the model
    if "6s" in model:
        return ["vocals", "drums", "bass", "guitar", "piano", "other"]
    return ["vocals", "drums", "bass", "other"]


# ---------------------------------------------------------------------------
# Main separation logic
# ---------------------------------------------------------------------------

def separate(
    input_path: Path,
    output_dir: Path,
    model: str,
    stem_selection: str,
    fmt: str,
    shifts: int,
    mp3_bitrate: int,
    model_dir: Path | None,
) -> list[dict]:
    """Run demucs separation; return list of {name, path} dicts."""
    import torch  # noqa: F401 — imported after bootstrap confirms demucs/torch available

    output_dir.mkdir(parents=True, exist_ok=True)

    stems = resolve_stems(stem_selection, model)
    log(f"Model: {model}  Stems: {', '.join(stems)}  Format: {fmt}  Shifts: {shifts}")
    progress(2.0, "Loading model...")

    # demucs writes to <output_dir>/<model>/<track_name>/<stem>.wav by default
    stem_dir = output_dir / model / input_path.stem

    cmd = [
        sys.executable, "-m", "demucs",
        "--name", model,
        "--out", str(output_dir),
        "--shifts", str(shifts),
    ]

    if fmt == "mp3":
        cmd += ["--mp3", "--mp3-bitrate", str(mp3_bitrate)]
    elif fmt == "flac":
        cmd += ["--flac"]

    if model_dir:
        # demucs reads TORCH_HOME for cached model weights
        env_extra = {"TORCH_HOME": str(model_dir)}
    else:
        env_extra = {}

    # For 2-stem (vocals vs. accompaniment)
    if stem_selection in {"vocals", "2stem", "accompaniment"}:
        if stem_selection == "vocals":
            cmd += ["--two-stems", "vocals"]
        elif stem_selection == "accompaniment":
            cmd += ["--two-stems", "vocals"]  # demucs produces both halves anyway
        elif stem_selection == "2stem":
            cmd += ["--two-stems", "vocals"]

    cmd.append(str(input_path))

    env = os.environ.copy()
    env.update(env_extra)
    env["PYTHONUNBUFFERED"] = "1"

    log(f"Running: {' '.join(cmd)}")
    progress(5.0, "Starting separation...")

    start_time = time.time()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        bufsize=1,
    )

    # Parse demucs stderr progress lines like:
    #   100%|██████████| 220500/220500 [00:12<00:00, 17891.47it/s]
    #   Separating track  34%
    _pct_re = re.compile(r"(\d+)%")
    _seg_re = re.compile(r"Segment\s+(\d+)/(\d+)")

    last_pct = 5.0
    total_segments = None
    current_segment = 0

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue

        # Try segment progress first (more granular)
        seg_match = _seg_re.search(line)
        if seg_match:
            current_segment = int(seg_match.group(1))
            total_segments = int(seg_match.group(2))
            pct = 5.0 + 90.0 * (current_segment / max(total_segments, 1))
            elapsed = time.time() - start_time
            eta = int(elapsed / (pct / 100.0) * (1 - pct / 100.0)) if pct > 0 else -1
            progress(pct, f"Segment {current_segment}/{total_segments}", eta)
            last_pct = pct
            log(line, "info")
            continue

        # Fallback: % progress from tqdm
        pct_match = _pct_re.search(line)
        if pct_match:
            raw_pct = int(pct_match.group(1))
            pct = 5.0 + 90.0 * (raw_pct / 100.0)
            if pct > last_pct:
                elapsed = time.time() - start_time
                eta = int(elapsed / (pct / 100.0) * (1 - pct / 100.0)) if pct > 0 else -1
                progress(pct, f"Separating ({raw_pct}%)", eta)
                last_pct = pct
        else:
            log(line)

    proc.wait()
    if proc.returncode != 0:
        error_exit("demucs_failed", f"demucs exited with code {proc.returncode}")

    # Collect output stems
    progress(96.0, "Collecting stems...")
    produced: list[dict] = []

    if stem_dir.exists():
        for stem_file in sorted(stem_dir.iterdir()):
            if stem_file.is_file():
                produced.append({"name": stem_file.stem, "path": str(stem_file)})
                emit({"event": "stem", "name": stem_file.stem, "path": str(stem_file)})
                log(f"Stem ready: {stem_file.name}")
    else:
        # demucs may have written directly to output_dir
        ext = ".mp3" if fmt == "mp3" else (".flac" if fmt == "flac" else ".wav")
        for stem_file in sorted(output_dir.rglob(f"*{ext}")):
            produced.append({"name": stem_file.stem, "path": str(stem_file)})
            emit({"event": "stem", "name": stem_file.stem, "path": str(stem_file)})
            log(f"Stem ready: {stem_file.name}")

    return produced


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="UCX Demucs sidecar")
    parser.add_argument("--input", required=True, help="Input audio/video file")
    parser.add_argument("--output-dir", required=True, help="Output directory for stems")
    parser.add_argument("--model", default="htdemucs_ft",
                        choices=["htdemucs", "htdemucs_ft", "htdemucs_6s",
                                 "mdx_extra", "mdx_extra_q"],
                        help="Demucs model name")
    parser.add_argument("--stems", default="4stem",
                        help="Stem selection: 2stem | vocals | accompaniment | 4stem")
    parser.add_argument("--format", default="wav",
                        choices=["wav", "flac", "mp3"],
                        help="Output audio format")
    parser.add_argument("--shifts", type=int, default=0,
                        help="Number of random shifts for equivariant stabilization (0 = off)")
    parser.add_argument("--mp3-bitrate", type=int, default=320,
                        help="MP3 bitrate in kbps")
    parser.add_argument("--model-dir", default=None,
                        help="Directory for cached model weights (TORCH_HOME)")
    args = parser.parse_args()

    model_dir_env = os.environ.get("UCX_MODEL_DIR")
    model_dir = Path(args.model_dir) if args.model_dir else (
        Path(model_dir_env) if model_dir_env else None
    )

    input_path = Path(args.input)
    if not input_path.exists():
        error_exit("input_not_found", f"Input file not found: {input_path}")

    output_dir = Path(args.output_dir)

    bootstrap()
    progress(1.0, "Initializing...")

    stems = separate(
        input_path=input_path,
        output_dir=output_dir,
        model=args.model,
        stem_selection=args.stems,
        fmt=args.format,
        shifts=args.shifts,
        mp3_bitrate=args.mp3_bitrate,
        model_dir=model_dir,
    )

    progress(100.0, "Done")
    emit({
        "event": "complete",
        "stems": stems,
        "output_dir": str(output_dir),
    })


if __name__ == "__main__":
    main()
