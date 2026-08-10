"""Real-ESRGAN sidecar — NDJSON 4× image / video upscaler.

Wraps the portable `realesrgan-ncnn-vulkan.exe` (xinntao/Real-ESRGAN, BSD-3),
which runs Real-ESRGAN inference on Intel/AMD/NVIDIA GPUs via Vulkan with no
Python or PyTorch runtime. Models bundled into the same directory.

Subcommands:
  upscale-image    one image in, one image out (any RGB-bearing format)
  upscale-video    extract frames → upscale each → re-encode (slow but works)
  list-models      enumerate available .bin / .param model pairs

Standard NDJSON contract: progress / log / complete / error / model events.
"""
from __future__ import annotations

import argparse
from functools import partial
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg as shared_find_ffmpeg


# ── NDJSON helpers ───────────────────────────────────────────────────────────



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


# ── Binary + model discovery ─────────────────────────────────────────────────

def _here() -> Path:
    return Path(__file__).resolve().parent


def find_realesrgan_exe() -> Path | None:
    """Return path to realesrgan-ncnn-vulkan.exe.

    Search order:
      1. REALESRGAN_EXE env var
      2. tools/realesrgan/bin/realesrgan-ncnn-vulkan.exe
      3. tools/realesrgan/realesrgan-ncnn-vulkan.exe (legacy flat layout)
      4. PATH lookup
    """
    here = _here()
    for cand in [
        os.environ.get("REALESRGAN_EXE"),
        str(here / "bin" / "realesrgan-ncnn-vulkan.exe"),
        str(here / "realesrgan-ncnn-vulkan.exe"),
        shutil.which("realesrgan-ncnn-vulkan"),
    ]:
        if cand and Path(cand).is_file():
            return Path(cand)
    return None


def discover_models() -> list[dict]:
    """List <name>.bin / <name>.param model pairs in known locations.

    A "model" is a (.bin, .param) pair sharing a stem. ncnn-vulkan picks the
    pair via its `-n <stem>` flag.
    """
    locations: list[Path] = []
    here = _here()
    for d in [here / "bin" / "models", here / "models",
              Path(os.environ.get("UCX_MODEL_DIR") or "") / "realesrgan"]:
        if d and d.is_dir():
            locations.append(d)

    seen: dict[str, dict] = {}
    for loc in locations:
        for bin_file in sorted(loc.glob("*.bin")):
            stem = bin_file.stem
            if stem.lower() in seen:
                continue
            param = bin_file.with_suffix(".param")
            if not param.exists():
                continue
            seen[stem.lower()] = {
                "name":  stem,
                "dir":   str(loc),
                "bin":   str(bin_file),
                "param": str(param),
                "size_bytes": bin_file.stat().st_size,
            }
    return list(seen.values())


find_ffmpeg = partial(shared_find_ffmpeg, _here())


# ── list-models ──────────────────────────────────────────────────────────────

def op_list_models(_: argparse.Namespace) -> int:
    found = discover_models()
    for m in found:
        emit("model",
             name=m["name"],
             path=m["bin"],
             location=m["dir"],
             size_bytes=m["size_bytes"])
    emit("complete", count=len(found))
    return 0


# ── upscale-image ────────────────────────────────────────────────────────────

def op_upscale_image(args: argparse.Namespace) -> int:
    exe = find_realesrgan_exe()
    if exe is None:
        return fail("missing_exe",
                    "realesrgan-ncnn-vulkan.exe not found. Run "
                    "`pwsh tools/realesrgan/build.ps1` to download the upstream "
                    "release into tools/realesrgan/bin/.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Validate the requested model is discoverable so we can give a clean error
    # before invoking the exe (which would otherwise cryptically fail).
    models = {m["name"].lower(): m for m in discover_models()}
    model_lc = args.model.lower()
    if model_lc not in models:
        return fail(
            "missing_model",
            f"Model {args.model!r} not found. Available: "
            f"{', '.join(sorted(m['name'] for m in models.values())) or '(none)'}. "
            f"Run `pwsh tools/realesrgan/build.ps1` to fetch the default set.",
        )
    chosen = models[model_lc]
    log("info", f"Model: {chosen['name']} (from {chosen['dir']})")

    scale = max(2, min(args.scale, 4))
    fmt = (args.format or out_path.suffix.lstrip(".") or "png").lower()

    cmd = [
        str(exe),
        "-i", str(in_path),
        "-o", str(out_path),
        "-n", chosen["name"],
        "-s", str(scale),
        "-f", fmt,
    ]
    if args.tta:
        cmd += ["-x"]
    if args.tile_size > 0:
        cmd += ["-t", str(args.tile_size)]
    if args.gpu_id >= 0:
        cmd += ["-g", str(args.gpu_id)]

    log("info", f"Upscaling {in_path.name} ×{scale} → {out_path.name}")
    progress(2.0, "loading model", None)

    # ncnn-vulkan writes a single line per image to stderr (no real progress).
    # We tick a coarse 50% on launch and 100% on success to keep the watchdog fed.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    progress(50.0, "upscaling", None)

    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        for ln in (stderr or "").splitlines()[-20:]:
            log("error", ln)
        return fail("ncnn_failed", f"realesrgan-ncnn-vulkan exited with code {proc.returncode}")

    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")

    progress(100.0, "done", 0)
    emit("complete",
         output=str(out_path),
         size_bytes=out_path.stat().st_size,
         model=chosen["name"],
         scale=scale)
    return 0


# ── upscale-video ────────────────────────────────────────────────────────────

_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def _ffmpeg_progress(cmd: list[str], duration_sec: float, stage: str,
                     base_pct: float, span_pct: float) -> int:
    proc = subprocess.Popen(
        cmd + ["-progress", "pipe:1", "-nostats"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    started = time.monotonic()
    last = -1.0
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            m = _TIME_RE.search(line)
            if m and duration_sec > 0:
                cur = int(m.group(1)) / 1_000_000
                local = max(0.0, min(1.0, cur / duration_sec))
                pct = base_pct + span_pct * local
                if pct - last >= 0.5:
                    last = pct
                    elapsed = time.monotonic() - started
                    eta = (elapsed / local - elapsed) if local > 0.01 else None
                    progress(pct, stage,
                             int(eta) if eta and eta < 86400 else None)
    finally:
        proc.wait()
        if proc.returncode != 0 and proc.stderr is not None:
            for ln in proc.stderr.read().splitlines()[-20:]:
                log("error", ln)
    return proc.returncode


def op_upscale_video(args: argparse.Namespace) -> int:
    """Frame-by-frame video upscale: extract → ncnn-vulkan → re-encode.

    This is intentionally simple. ncnn-vulkan has a video mode (`-i in.mp4 -o
    out.mp4`) but it bypasses progress reporting and audio handling; the
    extract-and-encode path gives real progress + audio passthrough.
    """
    exe = find_realesrgan_exe()
    if exe is None:
        return fail("missing_exe",
                    "realesrgan-ncnn-vulkan.exe not found. Run "
                    "`pwsh tools/realesrgan/build.ps1` to install.")

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return fail("missing_ffmpeg", "FFmpeg not on PATH; required for video upscale.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input not found: {in_path}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    models = {m["name"].lower(): m for m in discover_models()}
    if args.model.lower() not in models:
        return fail("missing_model",
                    f"Model {args.model!r} not found. Available: "
                    f"{', '.join(sorted(m['name'] for m in models.values())) or '(none)'}.")
    chosen = models[args.model.lower()]
    scale = max(2, min(args.scale, 4))

    # Probe duration for progress maths.
    probe = subprocess.run([ffmpeg, "-i", str(in_path), "-f", "null", "-"],
                           capture_output=True, text=True, timeout=20)
    m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", probe.stderr)
    duration = 0.0
    if m:
        duration = float(m.group(1)) * 3600 + float(m.group(2)) * 60 + float(m.group(3))

    work = Path(tempfile.mkdtemp(prefix="ucx_realesrgan_"))
    try:
        in_dir  = work / "in";  in_dir.mkdir()
        out_dir = work / "out"; out_dir.mkdir()

        # 1. Extract frames as PNG (lossless input to ncnn-vulkan).
        progress(2.0, "extracting frames", None)
        rc = _ffmpeg_progress(
            [ffmpeg, "-y", "-i", str(in_path),
             "-vsync", "0", str(in_dir / "f_%06d.png")],
            duration, "extracting frames", base_pct=2.0, span_pct=28.0,
        )
        if rc != 0:
            return fail("extract_failed", f"FFmpeg frame-extract exited {rc}")

        # 2. Upscale every frame in one ncnn-vulkan invocation (folder mode).
        progress(30.0, "upscaling frames", None)
        cmd = [str(exe),
               "-i", str(in_dir),
               "-o", str(out_dir),
               "-n", chosen["name"],
               "-s", str(scale),
               "-f", "png"]
        if args.tta:        cmd += ["-x"]
        if args.tile_size > 0: cmd += ["-t", str(args.tile_size)]
        if args.gpu_id >= 0:   cmd += ["-g", str(args.gpu_id)]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1)
        # ncnn-vulkan emits per-frame lines on stderr like "f_000123.png done".
        # We use that to drive progress in the 30-85% band.
        total_frames = len(list(in_dir.glob("*.png")))
        done = 0
        try:
            assert proc.stderr is not None
            for line in proc.stderr:
                if "done" in line:
                    done += 1
                    if total_frames > 0:
                        pct = 30.0 + 55.0 * (done / total_frames)
                        progress(pct, f"upscaling frame {done}/{total_frames}", None)
        finally:
            proc.wait()
        if proc.returncode != 0:
            return fail("ncnn_failed", f"ncnn-vulkan exited {proc.returncode}")

        # 3. Re-encode PNG sequence + original audio to the target video.
        progress(85.0, "encoding video", None)
        # Get source frame rate.
        m = re.search(r"(\d+(?:\.\d+)?)\s+fps", probe.stderr)
        fps = float(m.group(1)) if m else 30.0

        cmd = [
            ffmpeg, "-y",
            "-framerate", str(fps),
            "-i", str(out_dir / "f_%06d.png"),
            "-i", str(in_path),
            "-map", "0:v", "-map", "1:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "copy",
            str(out_path),
        ]
        rc = _ffmpeg_progress(cmd, duration, "encoding video", base_pct=85.0, span_pct=15.0)
        if rc != 0:
            return fail("encode_failed", f"FFmpeg encode exited {rc}")

        if not out_path.is_file():
            return fail("output_missing", f"Output not produced: {out_path}")

        emit("complete",
             output=str(out_path),
             size_bytes=out_path.stat().st_size,
             model=chosen["name"],
             scale=scale,
             frames=total_frames)
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── argparse + main ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="realesrgan-sidecar",
        description="UCX Real-ESRGAN sidecar — ncnn-vulkan upscaler.",
    )
    sub = p.add_subparsers(dest="op", required=True)

    img = sub.add_parser("upscale-image", help="Upscale one image")
    img.add_argument("--input",  required=True)
    img.add_argument("--output", required=True)
    img.add_argument("--model",  default="realesrgan-x4plus",
                     help="Model name (stem of .bin/.param pair). "
                          "Default: realesrgan-x4plus.")
    img.add_argument("--scale",  type=int, default=4,
                     help="Upscale factor 2/3/4 (default 4).")
    img.add_argument("--format", default=None,
                     help="Output image format override (png/jpg/webp).")
    img.add_argument("--tile-size", type=int, default=0,
                     help="ncnn-vulkan -t tile size (0 = auto).")
    img.add_argument("--gpu-id", type=int, default=-1,
                     help="GPU index (-1 = auto).")
    img.add_argument("--tta", action="store_true",
                     help="Test-time augmentation (slower, slightly higher quality).")

    vid = sub.add_parser("upscale-video", help="Frame-by-frame video upscale (slow)")
    vid.add_argument("--input",  required=True)
    vid.add_argument("--output", required=True)
    vid.add_argument("--model",  default="realesr-animevideov3",
                     help="Default: realesr-animevideov3 (anime/footage); "
                          "use realesrgan-x4plus for live-action photos.")
    vid.add_argument("--scale",  type=int, default=2,
                     help="Upscale factor 2/3/4 (default 2 for video — bigger "
                          "factors take longer and need more VRAM).")
    vid.add_argument("--crf",    type=int, default=20,
                     help="x264 CRF for the re-encode (default 20).")
    vid.add_argument("--tile-size", type=int, default=0)
    vid.add_argument("--gpu-id", type=int, default=-1)
    vid.add_argument("--tta", action="store_true")

    sub.add_parser("list-models", help="Enumerate available models")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "upscale-image":
            return op_upscale_image(args)
        if args.op == "upscale-video":
            return op_upscale_video(args)
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
