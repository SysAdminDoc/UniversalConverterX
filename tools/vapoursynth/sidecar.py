"""Explicit-trust bridge for local VapourSynth scripts and vspipe R76+."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "_lib"))
from ucx_sidecar import emit, find_ffmpeg, find_tool


_SCRIPT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_FRAME_PROGRESS_RE = re.compile(r"(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)")
_PROGRESS_LINE_RE = re.compile(
    r"^(?:frame|fps|stream_.+|bitrate|total_size|out_time(?:_us|_ms)?|dup_frames|drop_frames|speed|progress)="
)
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".mov", ".webm", ".avi"}
CODECS = ("h264", "hevc", "av1", "prores", "ffv1")


def _here() -> Path:
    return Path(__file__).resolve().parent


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def _find_vspipe() -> str | None:
    return find_tool("vspipe", env_var="VSPIPE_PATH", anchor=_here())


def _version(vspipe: str | None) -> str | None:
    if not vspipe:
        return None
    try:
        result = subprocess.run(
            [vspipe, "--version"], capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr or "").strip()
    return " | ".join(text.splitlines()[:8])[:500] if result.returncode == 0 and text else None


def _supported_version(version: str | None) -> bool:
    match = re.search(r"\b(?:Core\s+)?R(\d+)\b", version or "", re.IGNORECASE)
    return bool(match and int(match.group(1)) >= 76)


def op_probe(_: argparse.Namespace) -> int:
    vspipe = _find_vspipe()
    version = _version(vspipe)
    ffmpeg = find_ffmpeg(_here())
    version_supported = _supported_version(version)
    available = bool(vspipe and version_supported and ffmpeg)
    emit("backend", available=available, vspipe=vspipe, version=version, version_supported=version_supported, ffmpeg=ffmpeg)
    emit("complete", output="", size_bytes=0, available=available)
    return 0 if available else 1


def _trusted_script(args: argparse.Namespace) -> Path | None:
    if not args.acknowledge_script_code:
        fail(
            "script_trust_required",
            "A .vpy file is executable Python code. Re-run with --acknowledge-script-code only after reviewing and trusting the local script.",
        )
        return None
    script = Path(args.input)
    if script.suffix.lower() != ".vpy":
        fail("invalid_script", "VapourSynth scripts must use the .vpy extension.")
        return None
    if not script.is_file():
        fail("missing_script", f"Script not found: {script}")
        return None
    return script.resolve()


def _script_arguments(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if "=" not in value:
            raise ValueError(f"Script argument must be key=value: {value}")
        key, argument = value.split("=", 1)
        if not _SCRIPT_KEY_RE.fullmatch(key):
            raise ValueError(f"Invalid script argument key: {key}")
        if key.casefold() in seen:
            raise ValueError(f"Duplicate script argument key: {key}")
        if len(argument) > 4096 or "\x00" in argument:
            raise ValueError(f"Script argument value is invalid or too long: {key}")
        seen.add(key.casefold())
        result.extend(["--arg", f"{key}={argument}"])
    return result


def build_vspipe_command(
    vspipe: str,
    script: Path,
    outfile: str | Path,
    args: argparse.Namespace,
    *,
    operation: str,
) -> list[str]:
    command = [vspipe]
    if operation == "info":
        command.append("--info")
    elif operation == "graph":
        command.extend(["--graph", args.graph_level])
    elif operation == "render":
        command.extend(["--container", "y4m", "--progress"])
    else:
        raise ValueError(f"Unknown vspipe operation: {operation}")
    command.extend(_script_arguments(args.script_arg))
    if args.output_index != 0:
        command.extend(["--outputindex", str(args.output_index)])
    if getattr(args, "start_frame", None) is not None:
        command.extend(["--start", str(args.start_frame)])
    if getattr(args, "end_frame", None) is not None:
        command.extend(["--end", str(args.end_frame)])
    if getattr(args, "requests", None) is not None:
        command.extend(["--requests", str(args.requests)])
    command.extend([str(script), str(outfile)])
    return command


def _run_capture(command: list[str], timeout: int = 120) -> tuple[int, str]:
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.returncode, ((result.stdout or "") + (result.stderr or "")).strip()


def _base_args(args: argparse.Namespace) -> tuple[Path, str] | None:
    script = _trusted_script(args)
    if script is None:
        return None
    vspipe = _find_vspipe()
    version = _version(vspipe)
    if not vspipe or not version:
        fail("missing_vspipe", "VapourSynth/vspipe was not found or did not answer --version.")
        return None
    if not _supported_version(version):
        fail("outdated_vspipe", f"VapourSynth R76 or newer is required; detected: {version}")
        return None
    try:
        _script_arguments(args.script_arg)
    except ValueError as ex:
        fail("invalid_script_argument", str(ex))
        return None
    return script, vspipe


def op_info(args: argparse.Namespace) -> int:
    base = _base_args(args)
    if base is None:
        return 1
    command = build_vspipe_command(base[1], base[0], "-", args, operation="info")
    emit("progress", percent=0, stage="vapoursynth-info", eta_seconds=None)
    try:
        rc, text = _run_capture(command)
    except subprocess.TimeoutExpired:
        return fail("vspipe_timeout", "VSPipe script inspection timed out after 120 seconds.")
    if rc != 0:
        return fail("vspipe_failed", f"VSPipe exited with code {rc}: {text[-2000:]}")
    for line in text.splitlines():
        emit("log", level="info", message=line[:1000])
    emit("complete", output=str(base[0]), size_bytes=base[0].stat().st_size, details=text[:16000])
    return 0


def _staged_path(output: Path, label: str) -> Path:
    return output.with_name(f".{output.stem}.ucx-{label}{output.suffix}")


def _promote(staged: Path, output: Path) -> None:
    if not staged.is_file() or staged.stat().st_size == 0:
        raise RuntimeError(f"Expected output was not produced: {staged}")
    os.replace(staged, output)


def op_graph(args: argparse.Namespace) -> int:
    base = _base_args(args)
    if base is None:
        return 1
    output = Path(args.output).resolve()
    if output.suffix.lower() not in {".dot", ".gv"}:
        return fail("invalid_output", "Filter graphs must use the .dot or .gv extension.")
    if output.exists() and not args.overwrite:
        return fail("output_exists", f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = _staged_path(output, "graph")
    if staged.exists():
        staged.unlink()
    command = build_vspipe_command(base[1], base[0], staged, args, operation="graph")
    emit("progress", percent=0, stage="vapoursynth-graph", eta_seconds=None)
    try:
        rc, text = _run_capture(command)
    except subprocess.TimeoutExpired:
        return fail("vspipe_timeout", "VSPipe graph export timed out after 120 seconds.")
    if rc != 0:
        if staged.exists():
            staged.unlink()
        return fail("vspipe_failed", f"VSPipe exited with code {rc}: {text[-2000:]}")
    try:
        _promote(staged, output)
    except (OSError, RuntimeError) as ex:
        return fail("output_failed", str(ex))
    emit("progress", percent=100, stage="vapoursynth-graph", eta_seconds=0)
    emit("complete", output=str(output), size_bytes=output.stat().st_size, graph_level=args.graph_level)
    return 0


def _video_encoding(codec: str, crf: int | None) -> list[str]:
    if codec == "h264":
        return ["-c:v", "libx264", "-crf", str(18 if crf is None else crf), "-preset", "medium"]
    if codec == "hevc":
        return ["-c:v", "libx265", "-crf", str(20 if crf is None else crf), "-preset", "medium"]
    if codec == "av1":
        return ["-c:v", "libsvtav1", "-crf", str(30 if crf is None else crf), "-preset", "6"]
    if codec == "prores":
        return ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]
    if codec == "ffv1":
        return ["-c:v", "ffv1", "-level", "3", "-g", "1"]
    raise ValueError(f"Unsupported codec: {codec}")


def build_ffmpeg_command(args: argparse.Namespace, ffmpeg: str, staged: Path) -> list[str]:
    command = [ffmpeg, "-y", "-f", "yuv4mpegpipe", "-i", "pipe:0"]
    if args.audio_source:
        command.extend(["-i", str(Path(args.audio_source).resolve())])
    command.extend(["-map", "0:v:0"])
    if args.audio_source and args.audio_mode != "none":
        command.extend(["-map", "1:a?"])
    command.extend(_video_encoding(args.codec, args.crf))
    if not args.audio_source or args.audio_mode == "none":
        command.append("-an")
    elif args.audio_mode == "copy":
        command.extend(["-c:a", "copy"])
    elif args.audio_mode == "aac":
        command.extend(["-c:a", "aac", "-b:a", "192k"])
    else:
        command.extend(["-c:a", "libopus", "-b:a", "160k"])
    command.extend(["-progress", "pipe:1", "-nostats", str(staged)])
    return command


def _run_pipeline(vspipe_command: list[str], ffmpeg_command: list[str]) -> tuple[int, int, list[str]]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    vspipe = subprocess.Popen(
        vspipe_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    assert vspipe.stdout is not None and vspipe.stderr is not None
    ffmpeg = subprocess.Popen(
        ffmpeg_command, stdin=vspipe.stdout, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        bufsize=1, creationflags=creationflags,
    )
    vspipe.stdout.close()
    tail: deque[str] = deque(maxlen=30)
    last_percent = -1.0

    def drain_vspipe() -> None:
        nonlocal last_percent
        for raw in vspipe.stderr:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            tail.append("vspipe: " + line[:1000])
            match = _FRAME_PROGRESS_RE.search(line)
            if match and int(match.group(2)) > 0:
                percent = min(99.5, 100 * int(match.group(1)) / int(match.group(2)))
                if percent >= last_percent + 0.5:
                    last_percent = percent
                    emit("progress", percent=round(percent, 1), stage="vapoursynth-render", eta_seconds=None)
            else:
                emit("log", level="info", message=line[:1000])

    drain = threading.Thread(target=drain_vspipe, name="ucx-vspipe-log", daemon=True)
    drain.start()
    assert ffmpeg.stdout is not None
    for raw in ffmpeg.stdout:
        line = raw.strip()
        if not line:
            continue
        tail.append("ffmpeg: " + line[:1000])
        if not _PROGRESS_LINE_RE.match(line):
            emit("log", level="info", message=line[:1000])
    ffmpeg_rc = ffmpeg.wait()
    if ffmpeg_rc != 0 and vspipe.poll() is None:
        vspipe.terminate()
    vspipe_rc = vspipe.wait()
    drain.join(timeout=5)
    return vspipe_rc, ffmpeg_rc, list(tail)


def op_render(args: argparse.Namespace) -> int:
    base = _base_args(args)
    if base is None:
        return 1
    ffmpeg = find_ffmpeg(_here())
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg was not found.")
    output = Path(args.output).resolve()
    if output.suffix.lower() not in VIDEO_EXTENSIONS:
        return fail("invalid_output", "Rendered video must use mkv, mp4, mov, webm, or avi.")
    if base[0] == output:
        return fail("invalid_output", "Script and output paths must differ.")
    if output.exists() and not args.overwrite:
        return fail("output_exists", f"Output already exists: {output}")
    if args.end_frame is not None and args.start_frame is not None and args.end_frame < args.start_frame:
        return fail("invalid_range", "End frame must be greater than or equal to start frame.")
    if args.crf is not None and not 0 <= args.crf <= 63:
        return fail("invalid_crf", "CRF must be between 0 and 63.")
    if args.audio_source and not Path(args.audio_source).is_file():
        return fail("missing_audio_source", f"Audio source not found: {args.audio_source}")

    output.parent.mkdir(parents=True, exist_ok=True)
    staged = _staged_path(output, "vapoursynth")
    if staged.exists():
        staged.unlink()
    vspipe_command = build_vspipe_command(base[1], base[0], "-", args, operation="render")
    ffmpeg_command = build_ffmpeg_command(args, ffmpeg, staged)
    emit("log", level="warning", message="Executing a user-trusted local .vpy Python script through VSPipe.")
    emit("progress", percent=0, stage="vapoursynth-render", eta_seconds=None)
    vspipe_rc, ffmpeg_rc, tail = _run_pipeline(vspipe_command, ffmpeg_command)
    if vspipe_rc != 0 or ffmpeg_rc != 0:
        if staged.exists():
            staged.unlink()
        detail = " | ".join(tail[-6:])
        return fail(
            "render_failed",
            f"VSPipe exited {vspipe_rc}; FFmpeg exited {ffmpeg_rc}" + (f": {detail}" if detail else ""),
        )
    try:
        _promote(staged, output)
    except (OSError, RuntimeError) as ex:
        return fail("output_failed", str(ex))
    emit("progress", percent=100, stage="vapoursynth-render", eta_seconds=0)
    emit(
        "complete", output=str(output), size_bytes=output.stat().st_size,
        codec=args.codec, output_index=args.output_index,
    )
    return 0


def _nonnegative(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def _positive(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least one")
    return parsed


def _add_script_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True, help="Reviewed local .vpy script.")
    parser.add_argument("--acknowledge-script-code", action="store_true", help="Confirm the script is trusted executable Python code.")
    parser.add_argument("--script-arg", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--output-index", type=_nonnegative, default=0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vapoursynth-sidecar",
        description="Inspect and render explicitly trusted local VapourSynth scripts.",
    )
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("probe", help="Report VSPipe and FFmpeg readiness.")

    info = sub.add_parser("info", help="Execute a trusted script and report its output metadata.")
    _add_script_options(info)

    graph = sub.add_parser("graph", help="Export the trusted script's filter graph as DOT.")
    _add_script_options(graph)
    graph.add_argument("--output", required=True)
    graph.add_argument("--graph-level", choices=("simple", "full"), default="simple")
    graph.add_argument("--overwrite", action="store_true")

    render = sub.add_parser("render", help="Pipe the trusted script's video output to FFmpeg.")
    _add_script_options(render)
    render.add_argument("--output", required=True)
    render.add_argument("--codec", choices=CODECS, default="h264")
    render.add_argument("--crf", type=int)
    render.add_argument("--start-frame", type=_nonnegative)
    render.add_argument("--end-frame", type=_nonnegative)
    render.add_argument("--requests", type=_positive)
    render.add_argument("--audio-source", help="Optional media file whose audio tracks are remuxed or encoded.")
    render.add_argument("--audio-mode", choices=("copy", "aac", "opus", "none"), default="copy")
    render.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "probe":
            return op_probe(args)
        if args.op == "info":
            return op_info(args)
        if args.op == "graph":
            return op_graph(args)
        if args.op == "render":
            return op_render(args)
        return fail("unknown_op", f"Unknown operation: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
