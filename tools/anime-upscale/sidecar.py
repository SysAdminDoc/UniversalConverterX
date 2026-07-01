"""anime-upscale sidecar — Real-ESRGAN ncnn-vulkan wrapper for animation.

ROADMAP Item 95. Wraps the upstream `realesrgan-ncnn-vulkan` Windows binary,
which runs Real-ESRGAN on Intel / AMD / Nvidia GPUs via the Vulkan SDK
(no CUDA dependency). Distinct from the photo-oriented `superres` sidecar:
this one defaults to the `realesr-animevideov3` and `realesrgan-x4plus-anime`
models that preserve line art and flat colour without the photo-style
texture hallucination.

Subcommands:
  image      Upscale a single image or batch of images.
  video      Upscale a video frame-by-frame (extracts → upscales → re-muxes).
  models     Enumerate models available next to the binary.
  probe      Report whether the ncnn-vulkan binary is on disk and its version.

Standard NDJSON contract: progress / log / complete / error events on stdout.
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


# ── Binary discovery ─────────────────────────────────────────────────────────

# realesrgan-ncnn-vulkan ships as a single .exe with a `models/` folder
# alongside it; we recognise the nested layout AND a flat models-next-to-exe.
_REALESRGAN_BINARY_NAMES = ("realesrgan-ncnn-vulkan.exe", "realesrgan-ncnn-vulkan")
_DEFAULT_MODELS = (
    "realesr-animevideov3",        # animation video model (default)
    "realesrgan-x4plus-anime",     # 4x anime stills
    "realesrgan-x4plus",           # general 4x photo
    "realesrnet-x4plus",           # less-aggressive 4x
)


def _find_realesrgan() -> str | None:
    candidates: list[str | None] = [
        os.environ.get("REALESRGAN_NCNN_PATH"),
    ]
    for name in _REALESRGAN_BINARY_NAMES:
        candidates.append(shutil.which(name))
    here = Path(__file__).resolve().parent
    for name in _REALESRGAN_BINARY_NAMES:
        candidates += [
            str(here / name),
            str(here.parent / "_bin" / name),
        ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def _find_ffmpeg() -> str | None:
    return os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")


def _binary_models_dir(binary: str) -> Path | None:
    parent = Path(binary).resolve().parent
    for candidate in (parent / "models", parent):
        if candidate.is_dir():
            param_files = list(candidate.glob("*.param"))
            if param_files:
                return candidate
    return None


# ── Ops ──────────────────────────────────────────────────────────────────────

def op_models(_args: argparse.Namespace) -> int:
    binary = _find_realesrgan()
    if not binary:
        log("warn", "realesrgan-ncnn-vulkan not found; reporting curated default list.")
        for name in _DEFAULT_MODELS:
            emit("model", name=name, path=None, available=False)
        emit("complete", output="", size_bytes=0,
             count=len(_DEFAULT_MODELS), available=0)
        return 0
    models_dir = _binary_models_dir(binary)
    if models_dir is None:
        log("warn", f"No .param files found near {binary}.")
        for name in _DEFAULT_MODELS:
            emit("model", name=name, path=None, available=False)
        emit("complete", output="", size_bytes=0,
             count=len(_DEFAULT_MODELS), available=0)
        return 0

    found: dict[str, Path] = {}
    for param in models_dir.glob("*.param"):
        # The bin file name is the same stem; we only record the param path.
        found[param.stem] = param.resolve()

    # Emit curated names first (with availability), then any extras the user
    # has dropped into the folder.
    emitted: set[str] = set()
    for name in _DEFAULT_MODELS:
        present = name in found
        emit("model", name=name,
             path=str(found[name]) if present else None,
             available=present)
        emitted.add(name)
    for name, path in sorted(found.items()):
        if name in emitted:
            continue
        emit("model", name=name, path=str(path), available=True)
        emitted.add(name)
    available_count = sum(1 for p in found.values() if p.is_file())
    emit("complete", output=str(models_dir), size_bytes=0,
         count=len(emitted), available=available_count)
    return 0


def op_probe(_args: argparse.Namespace) -> int:
    binary = _find_realesrgan()
    if not binary:
        log("warn", "realesrgan-ncnn-vulkan not found on PATH or in tools/.")
        emit("complete", output="", size_bytes=0,
             realesrgan_path=None, realesrgan_version=None,
             ffmpeg_path=_find_ffmpeg())
        return 0
    try:
        # The binary doesn't ship a clean --version flag; -h returns banner +
        # version on the first line. Capture it for diagnostic use.
        result = subprocess.run([binary, "-h"], capture_output=True, text=True, timeout=15)
        first_line = (result.stdout or result.stderr or "").splitlines()[0:1]
        version = first_line[0].strip() if first_line else "unknown"
    except Exception as ex:
        version = f"probe-failed: {type(ex).__name__}"
    log("info", f"realesrgan-ncnn-vulkan at {binary} ({version})")
    emit("complete", output=binary, size_bytes=0,
         realesrgan_path=binary, realesrgan_version=version,
         ffmpeg_path=_find_ffmpeg())
    return 0


def _resolve_model(model: str | None) -> str:
    if not model: return "realesr-animevideov3"
    return model


def op_image(args: argparse.Namespace) -> int:
    binary = _find_realesrgan()
    if not binary:
        return fail("missing_realesrgan",
                    "realesrgan-ncnn-vulkan not installed. Drop the binary "
                    "next to this sidecar (with its models/ folder) or under "
                    "tools/_bin/. Source: github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases.")
    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Image(s) not found: {missing}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = max(2, min(int(args.scale), 4))
    model = _resolve_model(args.model)
    fmt = (args.format or "png").lower().lstrip(".")
    if fmt not in ("png", "jpg", "webp"):
        return fail("bad_arg", f"--format must be png|jpg|webp, got '{fmt}'.")

    total = len(inputs)
    emit("progress", percent=0, stage="anime-upscale", eta_seconds=None)
    for i, src in enumerate(inputs):
        out_path = out_dir / f"{src.stem}_x{scale}_{model}.{fmt}"
        cmd = [binary, "-i", str(src), "-o", str(out_path),
               "-s", str(scale), "-n", model, "-f", fmt]
        if args.tile_size is not None:
            cmd += ["-t", str(args.tile_size)]
        if args.gpu_id is not None:
            cmd += ["-g", str(args.gpu_id)]

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            for ln in (proc.stderr or proc.stdout or "").splitlines()[-15:]:
                log("error", ln)
            return fail("upscale_failed", f"{src.name}: rc={proc.returncode}")
        if not out_path.is_file():
            return fail("output_missing", f"Output not produced: {out_path}")

        emit("upscale_image",
             input=str(src), output=str(out_path),
             size_bytes=out_path.stat().st_size,
             scale=scale, model=model)
        pct = (i + 1) / total * 100
        emit("progress", percent=round(pct, 1),
             stage=f"image {i+1}/{total}", eta_seconds=None)

    emit("complete", output=str(out_dir), size_bytes=0, count=total)
    return 0


_FFMPEG_FRAME_RE = re.compile(r"frame=\s*(\d+)")


def op_video(args: argparse.Namespace) -> int:
    binary = _find_realesrgan()
    if not binary:
        return fail("missing_realesrgan",
                    "realesrgan-ncnn-vulkan not installed.")
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found on PATH.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    scale = max(2, min(int(args.scale), 4))
    model = _resolve_model(args.model)
    crf = args.crf
    target_codec = args.codec or "libx264"

    with tempfile.TemporaryDirectory(prefix="anime-upscale-") as tmp:
        tmp_path = Path(tmp)
        frames_in = tmp_path / "in"
        frames_out = tmp_path / "out"
        frames_in.mkdir(); frames_out.mkdir()

        # Extract frames as PNGs.
        emit("progress", percent=0, stage="extract frames", eta_seconds=None)
        log("info", f"Extracting frames to {frames_in}")
        rc = subprocess.run(
            [ffmpeg, "-y", "-i", str(src),
             "-qscale:v", "1", "-qmin", "1", "-qmax", "1",
             str(frames_in / "%08d.png")],
            capture_output=True, text=True).returncode
        if rc != 0:
            return fail("extract_failed", f"FFmpeg extract exited {rc}")

        # Upscale via realesrgan in batch (-i / -o accept directories).
        emit("progress", percent=10, stage="upscale frames", eta_seconds=None)
        log("info", f"Upscaling frames with model {model} x{scale}")
        cmd = [binary, "-i", str(frames_in), "-o", str(frames_out),
               "-s", str(scale), "-n", model, "-f", "png"]
        if args.tile_size is not None:
            cmd += ["-t", str(args.tile_size)]
        if args.gpu_id is not None:
            cmd += ["-g", str(args.gpu_id)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            for ln in (proc.stderr or proc.stdout or "").splitlines()[-15:]:
                log("error", ln)
            return fail("upscale_failed", f"realesrgan exited {proc.returncode}")

        # Probe input fps via ffmpeg.
        probe = subprocess.run(
            [ffmpeg, "-i", str(src)],
            capture_output=True, text=True)
        fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", probe.stderr or "")
        fps = float(fps_match.group(1)) if fps_match else 30.0

        # Re-mux: combine upscaled PNGs with the source audio.
        emit("progress", percent=80, stage="encode video", eta_seconds=None)
        log("info", f"Encoding output at {fps} fps with codec {target_codec}")
        rc = subprocess.run(
            [ffmpeg, "-y",
             "-framerate", str(fps), "-i", str(frames_out / "%08d.png"),
             "-i", str(src),
             "-map", "0:v:0", "-map", "1:a:0?",
             "-c:v", target_codec, "-crf", str(crf), "-preset", "medium",
             "-c:a", "copy", "-pix_fmt", "yuv420p",
             str(out_path)],
            capture_output=True, text=True).returncode
        if rc != 0:
            return fail("encode_failed", f"FFmpeg encode exited {rc}")

    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         scale=scale, model=model)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anime-upscale-sidecar",
                                description="Real-ESRGAN ncnn-vulkan wrapper for anime/animation upscaling.")
    sub = p.add_subparsers(dest="op", required=True)

    img = sub.add_parser("image", help="Upscale one or more still images.")
    img.add_argument("--input", nargs="+", required=True)
    img.add_argument("--output-dir", required=True, dest="output_dir")
    img.add_argument("--scale", type=int, default=4,
                     help="Upscale factor: 2, 3, or 4 (default 4).")
    img.add_argument("--model", default=None,
                     help=f"Model name (default realesr-animevideov3). "
                          f"Curated: {list(_DEFAULT_MODELS)}.")
    img.add_argument("--format", default="png",
                     help="Output format: png (default) / jpg / webp.")
    img.add_argument("--tile-size", type=int, default=None, dest="tile_size",
                     help="Tile size in pixels (0 = auto). Lower = less VRAM.")
    img.add_argument("--gpu-id", type=int, default=None, dest="gpu_id",
                     help="GPU index for multi-GPU setups (default 0 / first).")

    vid = sub.add_parser("video",
                         help="Upscale a video frame-by-frame and re-mux audio.")
    vid.add_argument("--input", required=True)
    vid.add_argument("--output", required=True)
    vid.add_argument("--scale", type=int, default=2,
                     help="Upscale factor: 2 (default), 3, or 4. "
                          "Use 2 for video — 4x video is rarely worth the encode time.")
    vid.add_argument("--model", default=None,
                     help=f"Model (default realesr-animevideov3). Curated: {list(_DEFAULT_MODELS)}.")
    vid.add_argument("--codec", default="libx264",
                     help="Output video codec (default libx264).")
    vid.add_argument("--crf", type=int, default=18,
                     help="CRF for the output encode (default 18 — visually lossless).")
    vid.add_argument("--tile-size", type=int, default=None, dest="tile_size")
    vid.add_argument("--gpu-id", type=int, default=None, dest="gpu_id")

    sub.add_parser("models",
                   help="Enumerate models available next to the binary.")
    sub.add_parser("probe",
                   help="Report whether the ncnn-vulkan binary is on disk and its version.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "image":  return op_image(args)
        if args.op == "video":  return op_video(args)
        if args.op == "models": return op_models(args)
        if args.op == "probe":  return op_probe(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
