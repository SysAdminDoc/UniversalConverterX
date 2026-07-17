"""Offline UCX bridge for a user-installed Av1an encoding toolchain."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg, find_tool


ENCODERS: dict[str, tuple[str, ...]] = {
    "aom": ("aomenc",),
    "svt-av1": ("SvtAv1EncApp", "svtav1encapp"),
    "rav1e": ("rav1e",),
    "vpx": ("vpxenc",),
    "x264": ("x264",),
    "x265": ("x265",),
}
TARGET_METRICS = (
    "vmaf", "ssimulacra2", "butteraugli-inf", "butteraugli-3",
    "xpsnr", "xpsnr-weighted",
)
SPLIT_METHODS = ("av-scenechange", "none")
CHUNK_METHODS = ("hybrid", "select", "segment", "lsmash", "ffms2", "bestsource", "dgdecnv")
CONCAT_METHODS = ("ffmpeg", "mkvmerge", "ivf")
_PERCENT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
MINIMUM_VERSION = (0, 5, 2)


def _here() -> Path:
    return Path(__file__).resolve().parent


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_av1an() -> str | None:
    return find_tool("av1an", env_var="AV1AN_PATH", anchor=_here())


def _find_vspipe() -> str | None:
    return find_tool("vspipe", env_var="VSPIPE_PATH", anchor=_here())


def _find_encoder(name: str) -> str | None:
    env_name = "UCX_" + name.upper().replace("-", "_") + "_PATH"
    for executable in ENCODERS[name]:
        found = find_tool(executable, env_var=env_name, anchor=_here())
        if found:
            return found
    return None


def _version(executable: str | None) -> str | None:
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True,
            timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr or "").strip()
    return text.splitlines()[0][:300] if result.returncode == 0 and text else None


def _supported_version(version: str | None) -> bool:
    match = _VERSION_RE.search(version or "")
    return bool(match and tuple(int(part) for part in match.groups()) >= MINIMUM_VERSION)


def runtime_status() -> dict[str, object]:
    av1an = _find_av1an()
    ffmpeg = find_ffmpeg(_here())
    vspipe = _find_vspipe()
    encoders = {name: _find_encoder(name) for name in ENCODERS}
    version = _version(av1an)
    version_supported = _supported_version(version)
    available = bool(av1an and version_supported and ffmpeg and vspipe and any(encoders.values()))
    return {
        "available": available,
        "av1an": av1an,
        "version": version,
        "version_supported": version_supported,
        "ffmpeg": ffmpeg,
        "vspipe": vspipe,
        "encoders": encoders,
    }


def op_probe(_: argparse.Namespace) -> int:
    status = runtime_status()
    emit("backend", **status)
    emit("complete", output="", size_bytes=0, available=status["available"])
    return 0 if status["available"] else 1


def _validate_runtime(encoder: str) -> tuple[str, str] | None:
    av1an = _find_av1an()
    version = _version(av1an)
    if not av1an or not version:
        fail("missing_av1an", "Av1an was not found or did not answer --version. Install the current Windows runtime and set AV1AN_PATH if needed.")
        return None
    if not _supported_version(version):
        fail("outdated_av1an", f"Av1an 0.5.2 or newer is required; detected: {version}")
        return None
    if not find_ffmpeg(_here()):
        fail("missing_ffmpeg", "FFmpeg was not found.")
        return None
    if not _find_vspipe():
        fail("missing_vapoursynth", "VapourSynth/vspipe was not found. Current Av1an requires the VapourSynth runtime.")
        return None
    encoder_executable = _find_encoder(encoder)
    if not encoder_executable:
        expected = " or ".join(ENCODERS[encoder])
        fail("missing_encoder", f"Encoder executable {expected} was not found for --encoder {encoder}.")
        return None
    return av1an, encoder_executable


def build_encode_command(args: argparse.Namespace, av1an: str, staged_output: Path) -> list[str]:
    command = [
        av1an,
        "-i", str(Path(args.input).resolve()),
        "-o", str(staged_output),
        "--encoder", args.encoder,
        "--workers", str(args.workers),
        "--split-method", args.split_method,
        "--chunk-method", args.chunk_method,
        "--concat", args.concat_method,
        "--min-scene-len", str(args.min_scene_len),
        "--extra-split-sec", str(args.extra_split_sec),
    ]
    if args.video_params:
        command.extend(["--video-params", args.video_params])
    if args.audio_params:
        command.extend(["--audio-params", args.audio_params])
    if args.scenes:
        command.extend(["--scenes", str(Path(args.scenes).resolve())])
    if args.target_quality is not None:
        command.extend([
            "--target-metric", args.target_metric,
            "--target-quality", str(args.target_quality),
            "--probes", str(args.probes),
        ])
    if args.temp:
        command.extend(["--temp", str(Path(args.temp).resolve())])
    if args.resume:
        command.append("--resume")
    if args.keep_temp:
        command.append("--keep")
    if args.overwrite:
        command.append("--overwrite")
    return command


def _run(command: list[str], stage: str) -> tuple[int, list[str]]:
    emit("progress", percent=0, stage=stage, eta_seconds=None)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tail: deque[str] = deque(maxlen=20)
    last_percent = -1.0
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.strip()
        if not line:
            continue
        tail.append(line[:1000])
        match = _PERCENT_RE.search(line)
        if match:
            percent = min(99.5, max(0.0, float(match.group(1))))
            if percent >= last_percent + 0.5:
                last_percent = percent
                emit("progress", percent=percent, stage=stage, eta_seconds=None)
        else:
            emit("log", level="info", message=line[:1000])
    return process.wait(), list(tail)


def _staged_path(output: Path, label: str) -> Path:
    return output.with_name(f".{output.stem}.ucx-{label}{output.suffix}")


def _promote(staged: Path, output: Path) -> None:
    if not staged.is_file() or staged.stat().st_size == 0:
        raise RuntimeError(f"Expected output was not produced: {staged}")
    os.replace(staged, output)


def op_encode(args: argparse.Namespace) -> int:
    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input not found: {source}")
    output = Path(args.output).resolve()
    if source.resolve() == output:
        return fail("invalid_output", "Input and output paths must differ.")
    if output.exists() and not args.overwrite:
        return fail("output_exists", f"Output already exists: {output}")
    if args.target_quality is not None and args.target_quality < 0:
        return fail("invalid_quality", "Target quality cannot be negative.")
    if args.target_metric in {"vmaf", "ssimulacra2"} and args.target_quality is not None and args.target_quality > 100:
        return fail("invalid_quality", f"{args.target_metric} target quality must be between 0 and 100.")
    runtime = _validate_runtime(args.encoder)
    if runtime is None:
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    staged = _staged_path(output, "av1an")
    if staged.exists():
        staged.unlink()
    command = build_encode_command(args, runtime[0], staged)
    emit("log", level="info", message=f"Av1an per-scene encode with {args.encoder} and {args.workers or 'automatic'} workers")
    rc, tail = _run(command, "av1an-encode")
    if rc != 0:
        if staged.exists():
            staged.unlink()
        detail = " | ".join(tail[-5:])
        return fail("av1an_failed", f"Av1an exited with code {rc}" + (f": {detail}" if detail else ""))
    try:
        _promote(staged, output)
    except (OSError, RuntimeError) as ex:
        return fail("output_failed", str(ex))
    emit("progress", percent=100, stage="av1an-encode", eta_seconds=0)
    emit(
        "complete", output=str(output), size_bytes=output.stat().st_size,
        encoder=args.encoder, workers=args.workers, target_quality=args.target_quality,
    )
    return 0


def op_scenes(args: argparse.Namespace) -> int:
    source = Path(args.input)
    if not source.is_file():
        return fail("missing_input", f"Input not found: {source}")
    av1an = _find_av1an()
    if not av1an or not _version(av1an):
        return fail("missing_av1an", "Av1an was not found or did not answer --version.")
    if not find_ffmpeg(_here()) or not _find_vspipe():
        return fail("missing_runtime", "Scene detection requires FFmpeg and VapourSynth/vspipe.")
    output = Path(args.output).resolve()
    if output.suffix.lower() != ".json":
        return fail("invalid_output", "Scene-list output must use the .json extension.")
    if output.exists() and not args.overwrite:
        return fail("output_exists", f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = _staged_path(output, "scenes")
    if staged.exists():
        staged.unlink()
    command = [
        av1an, "-i", str(source.resolve()), "--sc-only", "--scenes", str(staged),
        "--split-method", args.split_method,
        "--min-scene-len", str(args.min_scene_len),
        "--extra-split-sec", str(args.extra_split_sec),
    ]
    rc, tail = _run(command, "av1an-scenes")
    if rc != 0:
        if staged.exists():
            staged.unlink()
        detail = " | ".join(tail[-5:])
        return fail("av1an_failed", f"Av1an scene detection exited with code {rc}" + (f": {detail}" if detail else ""))
    try:
        _promote(staged, output)
    except (OSError, RuntimeError) as ex:
        return fail("output_failed", str(ex))
    emit("progress", percent=100, stage="av1an-scenes", eta_seconds=0)
    emit("complete", output=str(output), size_bytes=output.stat().st_size)
    return 0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def _workers(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 256:
        raise argparse.ArgumentTypeError("workers must be between 0 (automatic) and 256")
    return parsed


def _add_scene_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--split-method", choices=SPLIT_METHODS, default="av-scenechange")
    parser.add_argument("--min-scene-len", type=_positive_int, default=24)
    parser.add_argument("--extra-split-sec", type=_positive_int, default=10)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="av1an-sidecar",
        description="Offline per-scene parallel encoding through a user-installed Av1an toolchain.",
    )
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("probe", help="Report Av1an, VapourSynth, FFmpeg, and encoder readiness.")

    encode = sub.add_parser("encode", help="Encode one video with atomic output promotion.")
    encode.add_argument("--input", required=True)
    encode.add_argument("--output", required=True)
    encode.add_argument("--encoder", choices=tuple(ENCODERS), default="svt-av1")
    encode.add_argument("--workers", type=_workers, default=0, help="Parallel workers; zero lets Av1an choose.")
    encode.add_argument("--chunk-method", choices=CHUNK_METHODS, default="hybrid")
    encode.add_argument("--concat-method", choices=CONCAT_METHODS, default="ffmpeg")
    encode.add_argument("--video-params", help="One encoder-parameter string passed directly as one Av1an argument.")
    encode.add_argument("--audio-params", default="-c:a copy", help="One FFmpeg audio-parameter string.")
    encode.add_argument("--scenes", help="Reuse or write an Av1an scene JSON file.")
    encode.add_argument("--target-quality", type=float)
    encode.add_argument("--target-metric", choices=TARGET_METRICS, default="vmaf")
    encode.add_argument("--probes", type=_positive_int, default=4)
    encode.add_argument("--temp", help="Persistent chunk directory used for resume.")
    resume = encode.add_mutually_exclusive_group()
    resume.add_argument("--resume", dest="resume", action="store_true")
    resume.add_argument("--no-resume", dest="resume", action="store_false")
    encode.set_defaults(resume=True)
    encode.add_argument("--keep-temp", action="store_true")
    encode.add_argument("--overwrite", action="store_true")
    _add_scene_options(encode)

    scenes = sub.add_parser("scenes", help="Write a reusable Av1an scene list without encoding.")
    scenes.add_argument("--input", required=True)
    scenes.add_argument("--output", required=True)
    scenes.add_argument("--overwrite", action="store_true")
    _add_scene_options(scenes)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":
            return op_probe(args)
        if args.op == "encode":
            return op_encode(args)
        if args.op == "scenes":
            return op_scenes(args)
        return fail("unknown_op", f"Unknown operation: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
