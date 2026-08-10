#!/usr/bin/env python3
"""Video face enhancement sidecar.

Extracts frames with FFmpeg, sends frame batches through the existing
facerestore sidecar, then re-encodes the restored frames with source audio.
The sidecar owns orchestration only; model inference remains in facerestore.
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




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def log(level: str, message: str) -> None:
    emit("log", level=level, message=message)


def progress(percent: float, stage: str = "", eta_seconds: int | None = None) -> None:
    payload = {"percent": round(percent, 1), "stage": stage}
    if eta_seconds is not None:
        payload["eta_seconds"] = eta_seconds
    emit("progress", **payload)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def runtime_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


find_ffmpeg = partial(shared_find_ffmpeg, runtime_dir())


def _script_command(script: Path) -> list[str] | None:
    configured_python = os.environ.get("UCX_PYTHON")
    if configured_python:
        return [configured_python, str(script)]
    if not is_frozen():
        return [sys.executable, str(script)]
    return None


def find_facerestore_command() -> list[str] | None:
    override = os.environ.get("UCX_FACERESTORE_EXE")
    if override:
        path = Path(override)
        if path.is_file():
            if path.suffix.lower() == ".py":
                return _script_command(path)
            return [str(path)]

    here = runtime_dir()
    local_app = Path(os.environ.get("LOCALAPPDATA") or "") / "UniversalConverterX" / "tools"
    for exe in [
        here.parent / "facerestore" / "facerestore.exe",
        here / "facerestore.exe",
        local_app / "facerestore" / "facerestore.exe",
    ]:
        if exe.is_file():
            return [str(exe)]

    source = here.parent / "facerestore" / "sidecar.py"
    if source.is_file():
        return _script_command(source)
    return None


_TIME_RE = re.compile(r"out_time_ms=(\d+)")


def ffmpeg_progress(
    cmd: list[str],
    duration_sec: float,
    stage: str,
    base_pct: float,
    span_pct: float,
) -> int:
    progress_cmd = [cmd[0], "-hide_banner", "-nostats", "-progress", "pipe:1", *cmd[1:]]
    proc = subprocess.Popen(
        progress_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    started = time.monotonic()
    last = -1.0
    tail: list[str] = []
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            stripped = line.strip()
            if stripped:
                tail.append(stripped)
                tail = tail[-20:]
            match = _TIME_RE.search(stripped)
            if not match or duration_sec <= 0:
                continue
            current = int(match.group(1)) / 1_000_000
            local = max(0.0, min(1.0, current / duration_sec))
            pct = base_pct + span_pct * local
            if pct - last >= 0.5:
                last = pct
                eta = None
                if local > 0.01:
                    elapsed = time.monotonic() - started
                    eta = elapsed / local - elapsed
                progress(pct, stage, int(eta) if eta and eta < 86400 else None)
    finally:
        proc.wait()
        if proc.returncode != 0:
            for line in tail:
                log("error", line)
    return proc.returncode


def probe_video(ffmpeg: str, input_path: Path) -> tuple[float, float]:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(input_path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    stderr = proc.stderr or ""
    duration = 0.0
    match = re.search(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if match:
        duration = (
            float(match.group(1)) * 3600
            + float(match.group(2)) * 60
            + float(match.group(3))
        )

    fps = 30.0
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s+fps", stderr)
    if fps_match:
        fps = float(fps_match.group(1))
    return duration, fps


def chunks(items: list[Path], size: int) -> list[list[Path]]:
    size = max(1, size)
    return [items[i:i + size] for i in range(0, len(items), size)]


def forward_child_event(line: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    event = payload.get("event")
    if event == "log":
        log(str(payload.get("level") or "info"), str(payload.get("message") or ""))
    elif event == "face_restore":
        emit("face_restore", **{k: v for k, v in payload.items() if k != "event"})
    elif event == "error":
        return str(payload.get("code") or "face_restore_failed"), str(payload.get("message") or "")
    return None, None


def build_face_command(args: argparse.Namespace, frame_batch: list[Path], output_dir: Path) -> list[str]:
    command = find_facerestore_command()
    if command is None:
        raise FileNotFoundError(
            "facerestore sidecar not found. Build it with pwsh tools/facerestore/build.ps1."
        )

    base = [*command, args.backend, "--output-dir", str(output_dir)]
    if args.backend == "codeformer":
        base += ["--w", str(args.w), "--upscale", str(args.upscale)]
        if args.face_upsample:
            base.append("--face-upsample")
        if args.bg_enhance:
            base.append("--bg-enhance")
    else:
        base += ["--w", str(args.w), "--upscale", str(args.upscale)]
    base.append("--input")
    base.extend(str(path) for path in frame_batch)
    return base


def run_face_batches(
    args: argparse.Namespace,
    frames: list[Path],
    output_dir: Path,
) -> tuple[bool, str | None, str | None]:
    total = len(frames)
    done = 0
    for batch in chunks(frames, args.chunk_size):
        command = build_face_command(args, batch, output_dir)
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        child_error_code = None
        child_error_message = None
        assert proc.stdout is not None
        for line in proc.stdout:
            code, message = forward_child_event(line.strip())
            if code:
                child_error_code = code
                child_error_message = message
        _, stderr = proc.communicate()
        if proc.returncode != 0:
            for line in (stderr or "").splitlines()[-20:]:
                log("error", line)
            return (
                False,
                child_error_code or "face_restore_failed",
                child_error_message or f"facerestore exited {proc.returncode}",
            )
        done += len(batch)
        progress(30.0 + 50.0 * (done / total), f"enhancing frames {done}/{total}", None)
    return True, None, None


def op_probe(_: argparse.Namespace) -> int:
    emit(
        "complete",
        ffmpeg_found=find_ffmpeg() is not None,
        facerestore_found=find_facerestore_command() is not None,
    )
    return 0


def op_presets(_: argparse.Namespace) -> int:
    emit(
        "preset",
        name="CodeFormer face enhancement",
        backend="codeformer",
        description="Frame-by-frame CodeFormer restoration with audio passthrough.",
    )
    emit(
        "preset",
        name="GFPGAN face enhancement",
        backend="gfpgan",
        description="Frame-by-frame GFPGAN restoration with audio passthrough.",
    )
    emit("complete", count=2)
    return 0


def op_enhance(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return fail("missing_ffmpeg", "FFmpeg not found on PATH or under tools/_bin.")
    if find_facerestore_command() is None:
        return fail(
            "missing_facerestore",
            "facerestore sidecar not found. Build it with pwsh tools/facerestore/build.ps1.",
        )

    input_path = Path(args.input)
    if not input_path.is_file():
        return fail("missing_input", f"Input not found: {input_path}")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration, fps = probe_video(ffmpeg, input_path)
    work = Path(tempfile.mkdtemp(prefix="ucx_vface_"))
    try:
        frames_in = work / "frames-in"
        frames_out = work / "frames-out"
        frames_in.mkdir()
        frames_out.mkdir()

        progress(2.0, "extracting frames", None)
        rc = ffmpeg_progress(
            [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                "-vsync",
                "0",
                str(frames_in / "frame_%08d.png"),
            ],
            duration,
            "extracting frames",
            2.0,
            28.0,
        )
        if rc != 0:
            return fail("extract_failed", f"FFmpeg frame extraction exited {rc}")

        frames = sorted(frames_in.glob("frame_*.png"))
        if not frames:
            return fail("no_frames", "No video frames were extracted.")

        ok, code, message = run_face_batches(args, frames, frames_out)
        if not ok:
            return fail(code or "face_restore_failed", message or "Face restoration failed.")

        suffix = "_restored" if args.backend == "codeformer" else "_gfpgan"
        pattern = frames_out / f"frame_%08d{suffix}.png"
        if not any(frames_out.glob(f"frame_*{suffix}.png")):
            return fail("missing_restored_frames", "facerestore did not produce restored frames.")

        progress(82.0, "encoding video", None)
        rc = ffmpeg_progress(
            [
                ffmpeg,
                "-y",
                "-framerate",
                f"{fps:g}",
                "-i",
                str(pattern),
                "-i",
                str(input_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0?",
                "-c:v",
                args.codec,
                "-crf",
                str(args.crf),
                "-preset",
                args.encoder_preset,
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-c:a",
                "copy",
                str(output_path),
            ],
            duration,
            "encoding video",
            82.0,
            18.0,
        )
        if rc != 0:
            return fail("encode_failed", f"FFmpeg encode exited {rc}")
        if not output_path.is_file():
            return fail("output_missing", f"Output not produced: {output_path}")

        progress(100.0, "done", 0)
        emit(
            "complete",
            output=str(output_path),
            size_bytes=output_path.stat().st_size,
            backend=args.backend,
            frames=len(frames),
            fps=fps,
        )
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-face-enhance-sidecar",
        description="Frame-by-frame video face enhancement using the facerestore sidecar.",
    )
    sub = parser.add_subparsers(dest="op", required=True)

    enhance = sub.add_parser("enhance", help="Enhance faces in a video.")
    enhance.add_argument("--input", required=True)
    enhance.add_argument("--output", required=True)
    enhance.add_argument("--backend", choices=["codeformer", "gfpgan"], default="codeformer")
    enhance.add_argument("--w", type=float, default=0.65, help="Restoration weight passed to facerestore.")
    enhance.add_argument("--upscale", type=int, default=1, help="Face restore upscale factor.")
    enhance.add_argument("--face-upsample", action="store_true", help="Enable CodeFormer face upsample.")
    enhance.add_argument("--bg-enhance", action="store_true", help="Enable CodeFormer background enhance.")
    enhance.add_argument("--codec", default="libx264", help="Output video codec.")
    enhance.add_argument("--crf", type=int, default=18, help="Output CRF for x264/x265-style encoders.")
    enhance.add_argument("--encoder-preset", default="medium", help="FFmpeg encoder preset.")
    enhance.add_argument("--chunk-size", type=int, default=120, help="Frames per facerestore invocation.")

    sub.add_parser("presets", help="List built-in enhancement presets.")
    sub.add_parser("probe", help="Report dependency discovery state.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "enhance":
            return op_enhance(args)
        if args.op == "presets":
            return op_presets(args)
        if args.op == "probe":
            return op_probe(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except FileNotFoundError as ex:
        return fail("missing_dep", str(ex))
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:  # pylint: disable=broad-except
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
