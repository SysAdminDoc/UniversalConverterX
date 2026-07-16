#!/usr/bin/env python3
"""Opt-in CUDA SeedVR2 video-restoration sidecar.

The inference command never downloads code or weights.  ``download-model`` is
the only networked operation and requires explicit Apache-2.0 acceptance.  It
installs immutable, SHA-256 verified snapshots of the Windows-capable SeedVR2
standalone runtime and its 3B FP8 model pack.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import multiprocessing
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit as shared_emit, find_ffmpeg  # noqa: E402


MODEL_REPO = "numz/SeedVR2_comfyUI"
MODEL_REVISION = "09ced71023636e9bc8cdf9cdecfb2625d1e691e8"
MODEL_LICENSE = "Apache-2.0"
MODEL_NAME = "seedvr2_ema_3b_fp8_e4m3fn.safetensors"
VAE_NAME = "ema_vae_fp16.safetensors"
RUNTIME_REPO = "numz/ComfyUI-SeedVR2_VideoUpscaler"
RUNTIME_REVISION = "4490bd1f482e026674543386bb2a4d176da245b9"
RUNTIME_ARCHIVE_SHA256 = "04c61842bc00fd8673e6bc9a3b1b1935955461f363791070ed14d67d2a2e77fb"
PACK_SLUG = "seedvr2"
MARKER_NAME = ".ucx-pack.json"
MODEL_ASSETS = (
    (
        MODEL_NAME,
        3_391_544_696,
        "3bf1e43ebedd570e7e7a0b1b60d6a02e105978f505c8128a241cde99a8240cff",
    ),
    (
        VAE_NAME,
        501_324_814,
        "20678548f420d98d26f11442d3528f8b8c94e57ee046ef93dbb7633da8612ca1",
    ),
)
RUNTIME_ARCHIVE_SIZE = 4_864_981
TOTAL_DOWNLOAD_BYTES = RUNTIME_ARCHIVE_SIZE + sum(item[1] for item in MODEL_ASSETS)
_PROTOCOL_STDOUT = sys.stdout
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class _ProtocolWriter:
    """Keep the shared emitter on the NDJSON stream during upstream redirects."""

    def write(self, value: str) -> int:
        try:
            return _PROTOCOL_STDOUT.write(value)
        except UnicodeEncodeError:
            escaped = value.encode("ascii", "backslashreplace").decode("ascii")
            return _PROTOCOL_STDOUT.write(escaped)

    def flush(self) -> None:
        _PROTOCOL_STDOUT.flush()


def protocol_event(event: str, **fields: object) -> None:
    with contextlib.redirect_stdout(_ProtocolWriter()):
        shared_emit(event, **fields)


emit = protocol_event


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def resolve_pack_dir(root: str | Path | None = None) -> Path:
    configured = root or os.environ.get("UCX_MODEL_DIR")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.name.lower() == PACK_SLUG or (candidate / MARKER_NAME).is_file():
            return candidate.resolve()
        return (candidate / PACK_SLUG).resolve()
    anchor = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent
    return (anchor / "models" / PACK_SLUG).resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    immutable_files = (
        item for item in root.rglob("*")
        if item.is_file()
        and "__pycache__" not in item.relative_to(root).parts
        and item.suffix.lower() not in {".pyc", ".pyo"}
    )
    for path in sorted(immutable_files, key=lambda p: p.as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def safe_extract_runtime(archive: Path, destination: Path) -> None:
    """Extract a single-root GitHub zip without traversal or link entries."""
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise ValueError(f"Unsafe runtime archive member: {info.filename}")
            if len(member.parts) < 2:
                if info.is_dir():
                    continue
                raise ValueError(f"Unsafe runtime archive member: {info.filename}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"Runtime archive contains a symbolic link: {info.filename}")
            relative = Path(*member.parts[1:])
            if not relative.parts:
                continue
            target = (destination / relative).resolve()
            if os.path.commonpath((str(destination_root), str(target))) != str(destination_root):
                raise ValueError(f"Runtime archive escapes its destination: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def validate_pack(pack: Path, *, verify_hashes: bool) -> list[str]:
    problems: list[str] = []
    marker_path = pack / MARKER_NAME
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"missing or invalid {MARKER_NAME}"]
    if marker.get("model_revision") != MODEL_REVISION:
        problems.append("model revision marker does not match the pinned revision")
    if marker.get("runtime_revision") != RUNTIME_REVISION:
        problems.append("runtime revision marker does not match the pinned revision")

    runtime = pack / "runtime"
    cli = runtime / "inference_cli.py"
    if not cli.is_file() or cli.is_symlink():
        problems.append("runtime/inference_cli.py is missing or unsafe")
    models = pack / "models"
    for name, expected_size, expected_hash in MODEL_ASSETS:
        path = models / name
        if not path.is_file() or path.is_symlink():
            problems.append(f"models/{name} is missing or unsafe")
            continue
        if path.stat().st_size != expected_size:
            problems.append(f"models/{name} has the wrong size")
        elif verify_hashes and sha256_file(path) != expected_hash:
            problems.append(f"models/{name} failed SHA-256 verification")
    if verify_hashes and runtime.is_dir():
        expected_tree = marker.get("runtime_tree_sha256")
        if not expected_tree or tree_sha256(runtime) != expected_tree:
            problems.append("the pinned runtime failed directory verification")
    return problems


def _download(url: str, destination: Path, *, offset: int, total: int, stage: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "UniversalConverterX/SeedVR2"})
    digest = hashlib.sha256()
    downloaded = 0
    last_event = 0.0
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(8 * 1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            downloaded += len(chunk)
            now = time.monotonic()
            if now - last_event >= 1.5:
                last_event = now
                emit(
                    "progress",
                    percent=round((offset + downloaded) / total * 92.0, 1),
                    stage=stage,
                    eta_seconds=None,
                )
    destination.with_suffix(destination.suffix + ".sha256").write_text(
        digest.hexdigest(), encoding="ascii")


def _promote_stage(stage: Path, target: Path) -> None:
    backup = target.with_name(target.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        os.replace(target, backup)
    try:
        os.replace(stage, target)
    except Exception:
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def download_model(args: argparse.Namespace) -> int:
    if not args.accept_license:
        return fail(
            "license_acceptance_required",
            f"SeedVR2 is licensed under {MODEL_LICENSE}. Re-run the explicit download "
            "action after accepting that license.",
        )

    target = resolve_pack_dir(args.model_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(target.parent).free < TOTAL_DOWNLOAD_BYTES + 1_073_741_824:
        return fail(
            "insufficient_disk_space",
            "SeedVR2 needs approximately 5 GB of free space to stage and verify its optional pack.",
        )
    stage = Path(tempfile.mkdtemp(prefix=".seedvr2-", dir=target.parent))
    offset = 0
    try:
        runtime_zip = stage / "runtime.zip"
        _download(
            f"https://codeload.github.com/{RUNTIME_REPO}/zip/{RUNTIME_REVISION}",
            runtime_zip,
            offset=offset,
            total=TOTAL_DOWNLOAD_BYTES,
            stage="Downloading pinned SeedVR2 runtime",
        )
        if runtime_zip.stat().st_size != RUNTIME_ARCHIVE_SIZE or sha256_file(runtime_zip) != RUNTIME_ARCHIVE_SHA256:
            raise RuntimeError("Pinned SeedVR2 runtime archive failed SHA-256 verification")
        offset += RUNTIME_ARCHIVE_SIZE
        safe_extract_runtime(runtime_zip, stage / "runtime")
        runtime_zip.unlink()
        runtime_zip.with_suffix(runtime_zip.suffix + ".sha256").unlink(missing_ok=True)

        models = stage / "models"
        models.mkdir()
        for name, expected_size, expected_hash in MODEL_ASSETS:
            destination = models / name
            _download(
                f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}?download=true",
                destination,
                offset=offset,
                total=TOTAL_DOWNLOAD_BYTES,
                stage=f"Downloading {name}",
            )
            if destination.stat().st_size != expected_size or sha256_file(destination) != expected_hash:
                raise RuntimeError(f"{name} failed pinned SHA-256 verification")
            destination.with_suffix(destination.suffix + ".sha256").unlink(missing_ok=True)
            offset += expected_size

        emit("progress", percent=96.0, stage="Validating optional model pack", eta_seconds=None)
        marker = {
            "license": MODEL_LICENSE,
            "model_repo": MODEL_REPO,
            "model_revision": MODEL_REVISION,
            "runtime_repo": RUNTIME_REPO,
            "runtime_revision": RUNTIME_REVISION,
            "runtime_tree_sha256": tree_sha256(stage / "runtime"),
            "models": {name: {"size": size, "sha256": digest} for name, size, digest in MODEL_ASSETS},
        }
        (stage / MARKER_NAME).write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
        problems = validate_pack(stage, verify_hashes=True)
        if problems:
            raise RuntimeError("; ".join(problems))
        _promote_stage(stage, target)
    except Exception as exc:
        shutil.rmtree(stage, ignore_errors=True)
        return fail("model_download_failed", str(exc))

    emit("progress", percent=100.0, stage="SeedVR2 model ready", eta_seconds=0)
    emit("complete", output=str(target), size_bytes=sum(item[1] for item in MODEL_ASSETS))
    return 0


def model_status(args: argparse.Namespace) -> int:
    pack = resolve_pack_dir(args.model_dir)
    problems = validate_pack(pack, verify_hashes=args.verify)
    emit(
        "model",
        name="SeedVR2 3B FP8",
        path=str(pack),
        ready=not problems,
        revision=MODEL_REVISION,
        runtime_revision=RUNTIME_REVISION,
        license=MODEL_LICENSE,
        size_bytes=sum(item[1] for item in MODEL_ASSETS),
    )
    if problems:
        return fail(
            "model_not_installed",
            "SeedVR2's verified optional pack is not ready: " + "; ".join(problems),
        )
    emit("complete", output=str(pack), size_bytes=sum(item[1] for item in MODEL_ASSETS))
    return 0


@dataclass
class DeviceInfo:
    name: str
    vram_bytes: int


def cuda_device() -> tuple[DeviceInfo | None, str | None]:
    try:
        import torch
    except ImportError as exc:
        return None, f"SeedVR2 CUDA runtime is not bundled: {exc}"
    if not torch.cuda.is_available():
        return None, "SeedVR2 requires an NVIDIA CUDA GPU; no CUDA device is available."
    try:
        props = torch.cuda.get_device_properties(0)
        return DeviceInfo(str(props.name), int(props.total_memory)), None
    except Exception as exc:
        return None, f"CUDA device 0 could not be queried: {exc}"


class _UpstreamLogSink:
    def __init__(self) -> None:
        self.buffer = ""
        self.last_stage = ""

    def write(self, value: str) -> int:
        self.buffer += value.replace("\r", "\n")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self._line(line)
        return len(value)

    def flush(self) -> None:
        if self.buffer.strip():
            self._line(self.buffer)
        self.buffer = ""

    def _line(self, line: str) -> None:
        clean = _ANSI_RE.sub("", line).strip()
        if not clean:
            return
        stage_map = (
            ("Phase 1", 12.0, "Encoding frames"),
            ("Phase 2", 35.0, "Restoring with SeedVR2"),
            ("Phase 3", 72.0, "Decoding restored frames"),
            ("Phase 4", 88.0, "Applying color correction"),
            ("Output saved", 97.0, "Writing restored video"),
        )
        for token, percent, stage in stage_map:
            if token.lower() in clean.lower() and stage != self.last_stage:
                self.last_stage = stage
                emit("progress", percent=percent, stage=stage, eta_seconds=None)
                break
        emit("log", level="info", message=clean[:1200])


def _run_upstream(pack: Path, argv: list[str]) -> int:
    cli = pack / "runtime" / "inference_cli.py"
    spec = importlib.util.spec_from_file_location("ucx_seedvr2_runtime", cli)
    if spec is None or spec.loader is None:
        raise RuntimeError("Pinned SeedVR2 CLI could not be loaded")
    module = importlib.util.module_from_spec(spec)
    old_argv = sys.argv
    runtime_path = str(cli.parent)
    sys.path.insert(0, runtime_path)
    sink = _UpstreamLogSink()
    try:
        sys.argv = [str(cli), *argv]
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            spec.loader.exec_module(module)
            # The pack was fully verified above. Replacing this downloader is
            # the hard network boundary for restore: upstream may only read the
            # exact local weight files UCX passed in.
            module.download_weight = lambda **_: True
            module.main()
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)
    finally:
        sink.flush()
        sys.argv = old_argv
        if runtime_path in sys.path:
            sys.path.remove(runtime_path)


def remux_source_audio(ffmpeg: str, source: Path, restored_video: Path, output: Path) -> tuple[bool, str]:
    base = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(restored_video), "-i", str(source),
        "-map", "0:v:0", "-map", "1:a?", "-map_metadata", "1",
        "-c:v", "copy",
    ]
    attempts = (
        [*base, "-c:a", "copy", "-movflags", "+faststart", "-shortest", str(output)],
        [*base, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(output)],
    )
    diagnostic = ""
    for command in attempts:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0 and output.is_file() and output.stat().st_size > 0:
            return True, ""
        diagnostic = (result.stderr or result.stdout or f"FFmpeg exited {result.returncode}").strip()
        output.unlink(missing_ok=True)
    return False, diagnostic[-4000:]


def restore(args: argparse.Namespace) -> int:
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    if not source.is_file():
        return fail("input_not_found", f"Input video not found: {source}")
    if source == output:
        return fail("unsafe_output", "Output must not overwrite the input video.")
    if output.suffix.lower() != ".mp4":
        return fail("unsupported_output", "SeedVR2 video restoration outputs an MP4 file.")

    pack = resolve_pack_dir(args.model_dir)
    emit("progress", percent=1.0, stage="Verifying pinned SeedVR2 pack", eta_seconds=None)
    problems = validate_pack(pack, verify_hashes=True)
    if problems:
        return fail(
            "model_not_installed",
            "SeedVR2 never downloads during restoration. Use Review & download model first: "
            + "; ".join(problems),
        )
    device, device_error = cuda_device()
    if device is None:
        return fail("cuda_required", device_error or "SeedVR2 requires CUDA.")
    if device.vram_bytes < 10 * 1024**3:
        return fail(
            "insufficient_vram",
            f"{device.name} has {device.vram_bytes / 1024**3:.1f} GB VRAM. "
            "The selected FP8 pack requires at least 10 GB for a reliable low-resolution run.",
        )
    emit("device", backend="cuda", name=device.name, vram_bytes=device.vram_bytes)

    ffmpeg = find_ffmpeg(Path(__file__).resolve().parent)
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg is required for SeedVR2 video output.")
    output.parent.mkdir(parents=True, exist_ok=True)
    env_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(Path(ffmpeg).resolve().parent) + os.pathsep + env_path
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"

    command = [
        str(source),
        "--output", str(output.with_name(f".{output.stem}.seedvr2-{os.getpid()}.mp4")),
        "--output_format", "mp4",
        "--video_backend", "ffmpeg",
        "--model_dir", str(pack / "models"),
        "--dit_model", MODEL_NAME,
        "--resolution", str(args.resolution),
        "--max_resolution", str(args.max_resolution),
        "--batch_size", "5",
        "--uniform_batch_size",
        "--chunk_size", "165",
        "--temporal_overlap", "1",
        "--cuda_device", str(args.gpu_id),
        "--dit_offload_device", "cpu",
        "--vae_offload_device", "cpu",
        "--tensor_offload_device", "cpu",
        "--blocks_to_swap", str(args.blocks_to_swap),
        "--swap_io_components",
        "--vae_encode_tiled",
        "--vae_decode_tiled",
        "--attention_mode", "sdpa",
    ]
    restored_video = Path(command[command.index("--output") + 1])
    emit("progress", percent=5.0, stage="Loading SeedVR2 CUDA runtime", eta_seconds=None)
    try:
        exit_code = _run_upstream(pack, command)
    except Exception as exc:
        return fail("seedvr2_failed", str(exc))
    finally:
        os.environ["PATH"] = env_path
    if exit_code != 0:
        restored_video.unlink(missing_ok=True)
        return fail("seedvr2_failed", f"SeedVR2 runtime exited with code {exit_code}.")
    if not restored_video.is_file() or restored_video.stat().st_size <= 0:
        return fail("output_missing", f"SeedVR2 did not produce its staged video: {restored_video}")
    emit("progress", percent=98.0, stage="Preserving source audio", eta_seconds=None)
    try:
        try:
            remuxed, diagnostic = remux_source_audio(ffmpeg, source, restored_video, output)
        except Exception as exc:
            remuxed, diagnostic = False, str(exc)
    finally:
        restored_video.unlink(missing_ok=True)
    if not remuxed:
        return fail("ffmpeg_failed", diagnostic or "FFmpeg could not preserve the source audio.")
    emit("progress", percent=100.0, stage="Done", eta_seconds=0)
    emit(
        "complete",
        output=str(output),
        size_bytes=output.stat().st_size,
        model="SeedVR2 3B FP8",
        resolution=args.resolution,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seedvr2")
    commands = parser.add_subparsers(dest="command", required=True)

    status_parser = commands.add_parser("model-status")
    status_parser.add_argument("--model-dir")
    status_parser.add_argument("--verify", action="store_true")
    status_parser.set_defaults(handler=model_status)

    download_parser = commands.add_parser("download-model")
    download_parser.add_argument("--model-dir")
    download_parser.add_argument("--accept-license", action="store_true")
    download_parser.set_defaults(handler=download_model)

    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("--input", required=True)
    restore_parser.add_argument("--output", required=True)
    restore_parser.add_argument("--model-dir")
    restore_parser.add_argument("--resolution", type=int, choices=(540, 720, 1080), default=720)
    restore_parser.add_argument("--max-resolution", type=int, default=1920)
    restore_parser.add_argument("--blocks-to-swap", type=int, choices=range(0, 33), default=24)
    restore_parser.add_argument("--gpu-id", type=int, choices=range(0, 16), default=0)
    restore_parser.set_defaults(handler=restore)
    return parser


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
