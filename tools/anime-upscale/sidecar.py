"""anime-upscale sidecar — Real-ESRGAN and Anime4K GLSL animation upscaling.

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
  shader-status     Verify the optional mpv runtime and Anime4K shaders.
  download-shaders  Install the pinned, verified Anime4K shader pack.

Standard NDJSON contract: progress / log / complete / error events on stdout.
"""
from __future__ import annotations

import argparse
from functools import partial
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import (
    emit,
    find_ffmpeg as shared_find_ffmpeg,
    find_ffprobe as shared_find_ffprobe,
)


# ── NDJSON helpers ───────────────────────────────────────────────────────────

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

_ANIME4K_VERSION = "4.0.1"
_ANIME4K_LICENSE = "MIT"
_ANIME4K_ARCHIVE_URL = (
    "https://github.com/bloc97/Anime4K/releases/download/"
    "v4.0.1/Anime4K_v4.0.zip"
)
_ANIME4K_ARCHIVE_SHA256 = (
    "139cd282086457c5adc79caf7b75b8b825091d71c9b54958c18745fea62d7ed7"
)
_ANIME4K_ARCHIVE_BYTES = 776_303
_ANIME4K_CHAINS = {
    "a": (
        "Anime4K_Clamp_Highlights.glsl",
        "Anime4K_Restore_CNN_VL.glsl",
        "Anime4K_Upscale_CNN_x2_VL.glsl",
        "Anime4K_AutoDownscalePre_x2.glsl",
        "Anime4K_AutoDownscalePre_x4.glsl",
        "Anime4K_Upscale_CNN_x2_M.glsl",
    ),
    "b": (
        "Anime4K_Clamp_Highlights.glsl",
        "Anime4K_Restore_CNN_Soft_VL.glsl",
        "Anime4K_Upscale_CNN_x2_VL.glsl",
        "Anime4K_AutoDownscalePre_x2.glsl",
        "Anime4K_AutoDownscalePre_x4.glsl",
        "Anime4K_Upscale_CNN_x2_M.glsl",
    ),
    "c": (
        "Anime4K_Clamp_Highlights.glsl",
        "Anime4K_Upscale_Denoise_CNN_x2_VL.glsl",
        "Anime4K_AutoDownscalePre_x2.glsl",
        "Anime4K_AutoDownscalePre_x4.glsl",
        "Anime4K_Upscale_CNN_x2_M.glsl",
    ),
}
_ANIME4K_REQUIRED_FILES = tuple(sorted({
    name for chain in _ANIME4K_CHAINS.values() for name in chain
}))


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


_find_ffmpeg = partial(shared_find_ffmpeg, Path(__file__).resolve().parent)


_find_ffprobe = partial(shared_find_ffprobe, Path(__file__).resolve().parent)


def _find_mpv() -> str | None:
    configured = os.environ.get("UCX_MPV_PATH")
    here = Path(__file__).resolve().parent
    candidates = (
        configured,
        shutil.which("mpv.exe"),
        shutil.which("mpv"),
        str(here / "mpv.exe"),
        str(here.parent / "_bin" / "mpv.exe"),
    )
    return next((item for item in candidates if item and Path(item).is_file()), None)


def _shader_dir() -> Path:
    configured = os.environ.get("UCX_ANIME4K_SHADERS")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return base / "UniversalConverterX" / "models" / "anime4k" / _ANIME4K_VERSION


def _missing_shaders(root: Path | None = None) -> list[str]:
    shader_root = root or _shader_dir()
    return [name for name in _ANIME4K_REQUIRED_FILES
            if not (shader_root / name).is_file()
            or (shader_root / name).stat().st_size == 0]


def _install_shader_archive(archive: Path, destination: Path) -> None:
    staging = destination.parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
    backup = destination.parent / f".{destination.name}.backup-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    promoted = False
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = [item for item in bundle.infolist() if not item.is_dir()]
            for name in _ANIME4K_REQUIRED_FILES:
                matches = [item for item in entries if Path(item.filename).name == name]
                if len(matches) != 1:
                    raise ValueError(f"Shader archive must contain exactly one {name}.")
                target = staging / name
                with bundle.open(matches[0]) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if target.stat().st_size == 0:
                    raise ValueError(f"Shader archive contains an empty {name}.")
        metadata = {
            "version": _ANIME4K_VERSION,
            "license": _ANIME4K_LICENSE,
            "archiveSha256": _ANIME4K_ARCHIVE_SHA256,
            "source": _ANIME4K_ARCHIVE_URL,
        }
        (staging / "pack.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            os.replace(destination, backup)
        os.replace(staging, destination)
        promoted = True
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if promoted and destination.exists():
            shutil.rmtree(destination)
        if backup.exists():
            os.replace(backup, destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _download_shader_archive(destination: Path) -> None:
    request = urllib.request.Request(
        _ANIME4K_ARCHIVE_URL,
        headers={"User-Agent": "UniversalConverterX-Anime4K/1"},
    )
    digest = hashlib.sha256()
    received = 0
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            output.write(block)
            digest.update(block)
            received += len(block)
            emit("progress", percent=min(99.0, received * 100 / _ANIME4K_ARCHIVE_BYTES),
                 stage="downloading Anime4K shaders", eta_seconds=None)
    if received != _ANIME4K_ARCHIVE_BYTES:
        raise ValueError(
            f"Anime4K archive size mismatch: expected {_ANIME4K_ARCHIVE_BYTES}, got {received}.")
    actual = digest.hexdigest()
    if actual != _ANIME4K_ARCHIVE_SHA256:
        raise ValueError(
            f"Anime4K archive SHA-256 mismatch: expected {_ANIME4K_ARCHIVE_SHA256}, got {actual}.")


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
             ffmpeg_path=_find_ffmpeg(), mpv_path=_find_mpv(),
             anime4k_shader_path=str(_shader_dir()),
             anime4k_ready=not _missing_shaders())
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
         ffmpeg_path=_find_ffmpeg(), mpv_path=_find_mpv(),
         anime4k_shader_path=str(_shader_dir()),
         anime4k_ready=not _missing_shaders())
    return 0


def op_shader_status(_args: argparse.Namespace) -> int:
    mpv = _find_mpv()
    if not mpv:
        return fail(
            "missing_mpv",
            "mpv not found. Put mpv.exe beside the anime-upscale sidecar, under "
            "tools/_bin, on PATH, or set UCX_MPV_PATH.",
        )
    missing = _missing_shaders()
    if missing:
        return fail(
            "missing_shaders",
            "Anime4K v4.0.1 shader pack is not installed. Use download-shaders "
            "with explicit MIT license acceptance.",
        )
    emit("complete", output=str(_shader_dir()), size_bytes=0,
         version=_ANIME4K_VERSION, license=_ANIME4K_LICENSE,
         mpv_path=mpv, profiles=sorted(_ANIME4K_CHAINS))
    return 0


def op_download_shaders(args: argparse.Namespace) -> int:
    if not args.accept_license:
        return fail(
            "license_not_accepted",
            "Anime4K is MIT-licensed. Re-run with --accept-license after reviewing "
            "https://github.com/bloc97/Anime4K/blob/v4.0.1/LICENSE.",
        )
    shader_root = _shader_dir()
    if not _missing_shaders(shader_root):
        emit("complete", output=str(shader_root), size_bytes=0,
             version=_ANIME4K_VERSION, license=_ANIME4K_LICENSE, already_present=True)
        return 0
    with tempfile.TemporaryDirectory(prefix="ucx-anime4k-download-") as temp:
        archive = Path(temp) / "Anime4K_v4.0.zip"
        try:
            _download_shader_archive(archive)
            emit("progress", percent=99, stage="verifying Anime4K shaders", eta_seconds=None)
            _install_shader_archive(archive, shader_root)
        except Exception as exc:
            return fail("shader_download_failed", str(exc))
    missing = _missing_shaders(shader_root)
    if missing:
        return fail("shader_install_failed", f"Installed pack is missing: {missing}")
    emit("progress", percent=100, stage="Anime4K shaders ready", eta_seconds=0)
    emit("complete", output=str(shader_root), size_bytes=0,
         version=_ANIME4K_VERSION, license=_ANIME4K_LICENSE)
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

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
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
_MPV_PERCENT_RE = re.compile(r"\((\d{1,3})%\)")


def _probe_video_dimensions(ffprobe: str, source: Path) -> tuple[int, int] | None:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(source)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        stream = json.loads(result.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        return (width, height) if width > 0 and height > 0 else None
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _anime4k_command(
    mpv: str,
    source: Path,
    output: Path,
    profile: str,
    width: int,
    height: int,
    crf: int,
) -> list[str]:
    command = [
        mpv,
        "--no-config",
        "--no-sub",
        "--no-osc",
        "--no-input-default-bindings",
    ]
    if os.name == "nt":
        command.append("--gpu-api=d3d11")
    shader_root = _shader_dir()
    for name in _ANIME4K_CHAINS[profile]:
        command.append(f"--glsl-shader={shader_root / name}")
    command += [
        f"--vf=gpu=w={width * 2}:h={height * 2}",
        "--ovc=libx264",
        f"--ovcopts-add=crf={crf}",
        "--ovcopts-add=preset=medium",
        "--oac=aac",
        f"--o={output}",
        str(source),
    ]
    return command


def op_video_anime4k(args: argparse.Namespace) -> int:
    if args.scale != 2:
        return fail("bad_arg", "Anime4K GLSL export currently supports exactly --scale 2.")
    mpv = _find_mpv()
    if not mpv:
        return fail("missing_mpv", "mpv not found. Install the optional mpv runtime first.")
    missing = _missing_shaders()
    if missing:
        return fail("missing_shaders", "Anime4K v4.0.1 shader pack is not installed.")
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found on PATH.")
    source = Path(args.input).resolve()
    if not source.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    dimensions = _probe_video_dimensions(ffprobe, source)
    if dimensions is None:
        return fail("probe_failed", "Could not determine the input video dimensions.")
    width, height = dimensions
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.stem}.partial-{uuid.uuid4().hex}{output.suffix or '.mp4'}")
    command = _anime4k_command(
        mpv, source, partial, args.profile, width, height, args.crf)
    emit("progress", percent=0, stage=f"Anime4K Mode {args.profile.upper()}", eta_seconds=None)
    log("info", f"Anime4K v{_ANIME4K_VERSION} Mode {args.profile.upper()} via mpv")
    last_percent = -1
    tail: list[str] = []
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.strip()
            if clean:
                tail.append(clean)
                tail = tail[-30:]
            match = _MPV_PERCENT_RE.search(line)
            if match:
                percent = min(99, int(match.group(1)))
                if percent >= last_percent + 2:
                    emit("progress", percent=percent,
                         stage=f"Anime4K Mode {args.profile.upper()}", eta_seconds=None)
                    last_percent = percent
        return_code = process.wait()
        if return_code != 0:
            for line in tail[-12:]:
                log("error", line)
            return fail("anime4k_failed", f"mpv exited {return_code} during Anime4K export.")
        if not partial.is_file() or partial.stat().st_size == 0:
            return fail("output_missing", "mpv completed without a non-empty output file.")
        os.replace(partial, output)
    finally:
        if partial.exists():
            partial.unlink()
    emit("progress", percent=100, stage="complete", eta_seconds=0)
    emit("complete", output=str(output), size_bytes=output.stat().st_size,
         scale=2, backend="anime4k", profile=args.profile,
         width=width * 2, height=height * 2)
    return 0


def op_video(args: argparse.Namespace) -> int:
    if args.backend == "anime4k":
        return op_video_anime4k(args)
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
            capture_output=True, text=True, timeout=600).returncode
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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            for ln in (proc.stderr or proc.stdout or "").splitlines()[-15:]:
                log("error", ln)
            return fail("upscale_failed", f"realesrgan exited {proc.returncode}")

        # Probe input fps via ffmpeg.
        probe = subprocess.run(
            [ffmpeg, "-i", str(src)],
            capture_output=True, text=True, timeout=600)
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
            capture_output=True, text=True, timeout=600).returncode
        if rc != 0:
            return fail("encode_failed", f"FFmpeg encode exited {rc}")

    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         scale=scale, model=model)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anime-upscale-sidecar",
                                description="Real-ESRGAN or Anime4K GLSL anime/animation upscaling.")
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
    vid.add_argument("--backend", choices=("realesrgan", "anime4k"),
                     default="realesrgan",
                     help="Upscale backend (default realesrgan).")
    vid.add_argument("--profile", choices=tuple(_ANIME4K_CHAINS), default="a",
                     help="Anime4K profile: a=line restoration, b=soft, c=denoise.")
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
    sub.add_parser("shader-status",
                   help="Verify the pinned Anime4K shader pack and optional mpv runtime.")
    shaders = sub.add_parser("download-shaders",
                             help="Download the pinned SHA-256-verified Anime4K shader pack.")
    shaders.add_argument("--accept-license", action="store_true",
                         help="Acknowledge the Anime4K MIT license before downloading.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "image":  return op_image(args)
        if args.op == "video":  return op_video(args)
        if args.op == "models": return op_models(args)
        if args.op == "probe":  return op_probe(args)
        if args.op == "shader-status": return op_shader_status(args)
        if args.op == "download-shaders": return op_download_shaders(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
