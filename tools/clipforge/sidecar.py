"""ClipForge sidecar — NDJSON CLI shim for the UCX Editor module.

Supported ops:
  trim      Trim a clip by start/end seconds (lossless stream-copy or re-encode).
  crop      Crop video to W:H:X:Y via -vf crop.
  crop-meta Set H.264/H.265 SPS display-crop metadata without decoding frames.
  aspect-override Set container display aspect ratio without changing packets.
  rotate    Rotate/flip video via -vf transpose / hflip / vflip.
  loudnorm  EBU R128 loudness normalisation via -af loudnorm.
  rewrap    Change container without re-encoding (-c copy stream copy).
  rife      Interpolate frames to a higher target FPS with the pinned Vulkan runtime.
  rife-status  Report managed RIFE and Vulkan readiness metadata.

Contract: see ../README.md (sidecar contract) and ../../README.md (parent).
"""
from __future__ import annotations

import argparse
import json
import os
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SIDECAR_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SIDECAR_DIR))
sys.path.insert(0, str(SIDECAR_DIR.parent / "_lib"))
from ucx_sidecar import (
    emit,
    find_ffmpeg as shared_find_ffmpeg,
    find_ffprobe as shared_find_ffprobe,
    probe_media,
    run_ffmpeg,
)




def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_ffmpeg() -> str | None:
    return shared_find_ffmpeg(Path(__file__).resolve().parent)


def find_ffprobe() -> str | None:
    return shared_find_ffprobe(Path(__file__).resolve().parent)


def probe(ffprobe: str, path: str) -> dict | None:
    return probe_media(ffprobe, path)


_RIFE_EXECUTABLE = "rife-ncnn-vulkan"
_RIFE_MODEL = "rife-v4.6"
_RIFE_MAX_FPS = 240.0
_RIFE_PERCENT_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*%")


def find_rife() -> str | None:
    """Find the managed RIFE ncnn-vulkan runtime.

    The host prepends its managed ``tools/bin`` directory to PATH for every
    sidecar launch.  The explicit environment override and sidecar-local
    fallbacks keep the operation usable from the CLI and preserve the legacy
    ClipForge layout without allowing an arbitrary command string.
    """
    candidates = [
        os.environ.get("UCX_RIFE_PATH"),
        os.environ.get("RIFE_NCNN_PATH"),
        shutil.which(_RIFE_EXECUTABLE),
        shutil.which(f"{_RIFE_EXECUTABLE}.exe"),
    ]
    here = Path(__file__).resolve().parent
    candidates.extend([
        str(here / f"{_RIFE_EXECUTABLE}.exe"),
        str(here / _RIFE_EXECUTABLE),
        str(here / "bin" / f"{_RIFE_EXECUTABLE}.exe"),
        str(here / "bin" / _RIFE_EXECUTABLE),
        str(here.parent / "_bin" / f"{_RIFE_EXECUTABLE}.exe"),
        str(here.parent / "_bin" / _RIFE_EXECUTABLE),
    ])
    managed_bin = os.environ.get("UCX_TOOLS_BIN")
    if managed_bin:
        candidates.extend([
            str(Path(managed_bin) / f"{_RIFE_EXECUTABLE}.exe"),
            str(Path(managed_bin) / _RIFE_EXECUTABLE),
        ])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def _stream_fps(info: dict) -> float | None:
    streams = info.get("streams", []) if isinstance(info, dict) else []
    video = next((item for item in streams
                  if isinstance(item, dict) and item.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        return None
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = video.get(key)
        if not isinstance(value, str) or not value or value == "0/0":
            continue
        try:
            if "/" in value:
                numerator, denominator = value.split("/", 1)
                rate = float(numerator) / float(denominator)
            else:
                rate = float(value)
        except (ValueError, ZeroDivisionError):
            continue
        if math.isfinite(rate) and rate > 0:
            return rate
    return None


def _concat_file_line(path: Path) -> str:
    # concat's safe=0 mode accepts absolute paths.  Keep the line quoted even
    # for ordinary paths so spaces and apostrophes cannot change the command.
    escaped = str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'"


def _rife_runtime_status(rife: str) -> dict[str, object]:
    path = Path(rife)
    return {
        "runtime": _RIFE_EXECUTABLE,
        "runtime_version": _RIFE_MODEL,
        "model": _RIFE_MODEL,
        "path": str(path),
        "managed": bool(os.environ.get("UCX_TOOLS_BIN")) or path.parent.name in {"bin", "_bin"},
        "gpu": "vulkan",
    }


def op_rife_status(_args: argparse.Namespace) -> int:
    rife = find_rife()
    if not rife:
        return fail(
            "missing_rife",
            "The pinned RIFE ncnn-vulkan runtime was not found. Install the managed "
            "runtime as rife-ncnn-vulkan.exe in UCX tools/bin, ClipForge/bin, or the sidecar directory.",
        )
    emit("capability", name="rife", status="ready", **_rife_runtime_status(rife))
    emit("complete", output=rife, size_bytes=Path(rife).stat().st_size,
         source_preserving=True, gpu="vulkan", model=_RIFE_MODEL)
    return 0


def op_rife(args: argparse.Namespace) -> int:
    """Interpolate a video to a higher target frame rate through RIFE.

    Frames and the final encode are staged beside the requested destination.
    The source is never used as an output target, and its size/mtime are
    checked again before the staged artifact is atomically promoted.
    """
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    rife = find_rife()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install the managed FFmpeg runtime first.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install the managed FFmpeg runtime first.")
    if not rife:
        return fail(
            "missing_rife",
            "The pinned RIFE ncnn-vulkan runtime was not found. Install rife-ncnn-vulkan.exe in the managed UCX tools folder.",
        )

    source = Path(args.input)
    output = Path(args.output)
    if not source.is_file():
        return fail("missing_input", f"Input file does not exist: {source}")
    try:
        source_resolved = source.resolve()
        output_resolved = output.resolve()
    except OSError as exc:
        return fail("invalid_path", f"Could not resolve the source or destination path: {exc}")
    if source_resolved == output_resolved:
        return fail("output_same_as_input", "RIFE output must be a different path from the source file.")
    if not math.isfinite(args.target_fps) or not 1.0 <= args.target_fps <= _RIFE_MAX_FPS:
        return fail("invalid_target_fps", f"Target FPS must be between 1 and {_RIFE_MAX_FPS:g}.")

    try:
        source_stat = source.stat()
    except OSError as exc:
        return fail("input_unreadable", f"Could not inspect the input file: {exc}")

    info = probe(ffprobe, str(source))
    if not info:
        return fail("probe_failed", "Could not read input video metadata.")
    source_fps = _stream_fps(info)
    if source_fps is None:
        return fail("probe_failed", "Could not determine the source video frame rate.")
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    if not math.isfinite(duration) or duration <= 0:
        return fail("probe_failed", "Could not determine the source video duration.")
    if args.target_fps + 0.001 < source_fps:
        return fail(
            "target_below_source",
            f"Target FPS ({args.target_fps:g}) must be at least the source FPS ({source_fps:g}).",
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    ratio = args.target_fps / source_fps
    workspace = Path(tempfile.mkdtemp(prefix=".ucx-rife-", dir=str(output.parent)))
    staged_output: Path | None = None
    rife_process: subprocess.Popen[str] | None = None
    try:
        frames_dir = workspace / "frames"
        interpolated_dir = workspace / "interpolated"
        frames_dir.mkdir()
        interpolated_dir.mkdir()
        extract_pattern = str(frames_dir / "frame_%08d.png")

        emit("capability", name="rife", status="ready", **_rife_runtime_status(rife))
        emit("log", level="info", message=(
            f"RIFE {_RIFE_MODEL}: {source_fps:g} -> {args.target_fps:g} FPS "
            f"(managed Vulkan runtime {Path(rife).name})"))
        emit("progress", percent=0, stage="extracting source frames", eta_seconds=None)
        extract_cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source), "-vsync", "0", "-q:v", "2", extract_pattern,
        ]
        rc = run_ffmpeg(extract_cmd, duration, "extracting source frames",
                        start_percent=0, end_percent=20)
        if rc != 0:
            return fail("ffmpeg_failed", f"FFmpeg exited with code {rc} while extracting frames.")
        source_frames = sorted(path for path in frames_dir.iterdir()
                               if path.is_file() and path.suffix.lower() == ".png")
        if not source_frames:
            return fail("no_frames", "FFmpeg produced no source frames for RIFE.")

        expected_frames = max(2, math.ceil(len(source_frames) * ratio))
        emit("log", level="info", message=f"Interpolating {len(source_frames)} -> {expected_frames} frames.")
        emit("progress", percent=20, stage="RIFE Vulkan interpolation", eta_seconds=None)
        hidden_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        rife_cmd = [
            rife, "-i", str(frames_dir), "-o", str(interpolated_dir),
            "-m", args.model, "-n", str(expected_frames),
        ]
        rife_process = subprocess.Popen(
            rife_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=hidden_flags,
        )
        assert rife_process.stdout is not None
        try:
            for raw_line in rife_process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                match = _RIFE_PERCENT_RE.search(line)
                if match:
                    local = max(0.0, min(100.0, float(match.group(1))))
                    emit("progress", percent=round(20 + local * 0.6, 1),
                         stage="RIFE Vulkan interpolation", eta_seconds=None)
                else:
                    emit("log", level="debug", message=line[:4096])
        finally:
            rife_process.stdout.close()
            rife_process.wait()
        if rife_process.returncode != 0:
            return fail("rife_failed", f"RIFE exited with code {rife_process.returncode}.")

        interpolated_frames = sorted(
            path for path in interpolated_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})
        if not interpolated_frames:
            return fail("rife_no_frames", "RIFE completed without producing interpolated frames.")
        emit("log", level="info", message=f"RIFE produced {len(interpolated_frames)} frames.")

        concat_list = workspace / "frames.ffconcat"
        concat_list.write_text(
            "ffconcat version 1.0\n" + "\n".join(_concat_file_line(path) for path in interpolated_frames) + "\n",
            encoding="utf-8",
        )
        fd, staged_name = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".part", dir=str(output.parent))
        os.close(fd)
        staged_output = Path(staged_name)
        reassemble_cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(source), "-map", "0:v:0", "-map", "1:a?",
            "-r", f"{args.target_fps:g}", "-c:v", args.codec,
            "-crf", str(args.crf), "-preset", args.preset,
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", f"{args.audio_bitrate}k",
            "-map_metadata", "1", "-movflags", "+faststart", "-shortest", str(staged_output),
        ]
        emit("progress", percent=80, stage="reassembling source-preserving video", eta_seconds=None)
        rc = run_ffmpeg(reassemble_cmd, duration, "reassembling source-preserving video",
                        start_percent=80, end_percent=98)
        if rc != 0:
            return fail("ffmpeg_failed", f"FFmpeg exited with code {rc} while reassembling the video.")
        if not staged_output.is_file() or staged_output.stat().st_size <= 0:
            return fail("output_missing", "RIFE did not produce a non-empty staged output.")

        output_info = probe(ffprobe, str(staged_output))
        output_fps = _stream_fps(output_info or {})
        if output_fps is None or abs(output_fps - args.target_fps) > 0.5:
            return fail(
                "output_validation_failed",
                f"Output FPS validation failed: expected {args.target_fps:g}, got "
                f"{output_fps:g}" if output_fps is not None else
                f"Output FPS validation failed: expected {args.target_fps:g}, but the staged file has no video rate.",
            )

        current_stat = source.stat()
        if current_stat.st_size != source_stat.st_size or current_stat.st_mtime_ns != source_stat.st_mtime_ns:
            return fail("source_changed", "The source file changed while RIFE was running; staged output was discarded.")
        os.replace(staged_output, output)
        staged_output = None
        size_bytes = output.stat().st_size
        emit("progress", percent=100, stage="RIFE output validated", eta_seconds=0)
        emit(
            "complete",
            output=str(output),
            size_bytes=size_bytes,
            source=str(source),
            source_fps=source_fps,
            target_fps=args.target_fps,
            frames_in=len(source_frames),
            frames_out=len(interpolated_frames),
            runtime=_RIFE_EXECUTABLE,
            runtime_version=_RIFE_MODEL,
            model=args.model,
            gpu="vulkan",
            source_preserving=True,
            artifact_manifest={
                "source": str(source),
                "output": str(output),
                "source_preserved": True,
                "target_fps": args.target_fps,
            },
        )
        return 0
    except KeyboardInterrupt:
        if rife_process is not None:
            try:
                if rife_process.poll() is None:
                    rife_process.kill()
            except OSError:
                pass
        raise
    finally:
        if staged_output is not None:
            try:
                staged_output.unlink(missing_ok=True)
            except OSError:
                pass
        shutil.rmtree(workspace, ignore_errors=True)


def op_trim(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    src_dur = float(info.get("format", {}).get("duration", 0))
    if src_dur <= 0:
        return fail("probe_failed", "Could not determine input duration.")

    start = max(0.0, args.start)
    end = args.end if args.end is not None and args.end > 0 else src_dur
    end = min(end, src_dur)
    if end <= start:
        return fail("invalid_range", f"Trim end ({end:.2f}) must be greater than start ({start:.2f}).")
    span = end - start

    emit("log", level="info", message=f"Trim {start:.2f}-{end:.2f} ({span:.2f}s) of {src_dur:.2f}s")

    if args.lossless:
        # Stream-copy trim — fast but only cuts on keyframes; output may be slightly off.
        cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", str(in_path), "-c", "copy",
               "-map_metadata", "0", "-movflags", "+faststart", str(out_path)]
        emit("progress", percent=0, stage="trim (lossless)", eta_seconds=None)
        rc = run_ffmpeg(cmd, span, "trim (lossless)")
    else:
        cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", str(in_path),
               "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset]
        if args.audio_codec == "an":
            cmd += ["-an"]
        elif args.audio_codec == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", args.audio_codec, "-b:a", f"{args.audio_bitrate}k"]
        cmd += ["-movflags", "+faststart", str(out_path)]
        emit("progress", percent=0, stage="trim (re-encode)", eta_seconds=None)
        rc = run_ffmpeg(cmd, span, "trim (re-encode)")

    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_crop(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    crop_filter = f"crop={args.width}:{args.height}:{args.x}:{args.y}"
    emit("log", level="info", message=f"Crop filter: {crop_filter}")

    cmd = [ffmpeg, "-y", "-i", str(in_path),
           "-vf", crop_filter,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy",
           "-movflags", "+faststart", str(out_path)]
    emit("progress", percent=0, stage="crop", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "crop")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


from clipforge_ops.metadata import (
    _ROTATE_FILTERS,
    _first_video_stream,
    _parse_aspect_ratio,
    _stream_copy_command,
    op_aspect_override,
    op_crop_meta,
    op_loudnorm,
    op_rotate,
)


from clipforge_ops.tracks import (
    op_track_add,
    op_track_edit,
    op_track_extract,
    op_track_list,
    op_track_remove,
)


from clipforge_ops.video import op_deinterlace


from clipforge_ops.analysis import (
    op_keyframes,
    op_proxy,
    op_timeline,
    op_vmaf,
)



def op_rewrap(args: argparse.Namespace) -> int:
    """Stream-copy into a new container — no re-encode, instant remux."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg not found. Install FFmpeg or set FFMPEG_PATH.")
    if not ffprobe:
        return fail("missing_ffprobe", "FFprobe not found. Install FFmpeg or set FFPROBE_PATH.")

    in_path = Path(args.input)
    if not in_path.is_file():
        return fail("missing_input", f"Input file does not exist: {args.input}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(in_path))
    if not info:
        return fail("probe_failed", "Could not read input metadata.")
    duration = float(info.get("format", {}).get("duration", 0))

    in_ext = in_path.suffix.lower()
    out_ext = out_path.suffix.lower()
    emit("log", level="info", message=f"Rewrap {in_ext} -> {out_ext} (stream copy)")

    cmd = [ffmpeg, "-y", "-i", str(in_path),
           "-c", "copy",
           "-map_metadata", "0"]
    if out_ext in (".mp4", ".m4v", ".mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(str(out_path))

    emit("progress", percent=0, stage="rewrap", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "rewrap")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_concat(args: argparse.Namespace) -> int:
    """Stream-copy concatenate via ffmpeg's concat demuxer when codecs match;
    fall back to filter_complex concat for mixed sources."""
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")

    inputs = [Path(p) for p in args.input]
    missing = [str(p) for p in inputs if not p.is_file()]
    if missing:
        return fail("missing_input", f"Input(s) not found: {missing}")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Probe codecs to decide stream-copy vs re-encode.
    codecs = []
    total_dur = 0.0
    for p in inputs:
        info = probe(ffprobe, str(p))
        if info:
            v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
            codecs.append(v.get("codec_name", ""))
            total_dur += float(info.get("format", {}).get("duration", 0))
    can_copy = len(set(codecs)) == 1 and not args.reencode

    if can_copy:
        # Concat demuxer: needs a list file with one "file 'path'" per line.
        list_path = Path(out_path.parent / f".concat_{os.getpid()}.txt")
        list_path.write_text(
            "\n".join(f"file '{str(p).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
                      for p in inputs),
            encoding="utf-8")
        try:
            cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0",
                   "-i", str(list_path), "-c", "copy", str(out_path)]
            emit("log", level="info", message=f"Concat (stream copy) of {len(inputs)} clip(s)")
            emit("progress", percent=0, stage="concat", eta_seconds=None)
            rc = run_ffmpeg(cmd, total_dur, "concat")
        finally:
            try: list_path.unlink()
            except OSError: pass
    else:
        # filter_complex concat -- normalises to one resolution / codec.
        emit("log", level="info", message=f"Concat (re-encode) of {len(inputs)} clip(s)")
        cmd = [ffmpeg, "-y"]
        for p in inputs: cmd += ["-i", str(p)]
        n = len(inputs)
        filter_str = "".join(f"[{i}:v:0][{i}:a:0?]" for i in range(n)) \
                   + f"concat=n={n}:v=1:a=1[v][a]"
        cmd += ["-filter_complex", filter_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-crf", "20", "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k", str(out_path)]
        emit("progress", percent=0, stage="concat", eta_seconds=None)
        rc = run_ffmpeg(cmd, total_dur, "concat")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited with code {rc}")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size,
         input_count=len(inputs))
    return 0


def op_speed(args: argparse.Namespace) -> int:
    """Speed-up / slow-down a clip via setpts (video) + atempo (audio)."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))
    factor = float(args.factor)
    if factor <= 0: return fail("bad_factor", "--factor must be > 0")

    # Video: setpts=PTS/factor (factor>1 = speed up, <1 = slow down).
    # Audio: atempo accepts 0.5-100; chain multiple stages for extreme factors.
    def _atempo_chain(f: float) -> str:
        chain = []
        while f > 100:
            chain.append("atempo=100"); f /= 100
        while f < 0.5:
            chain.append("atempo=0.5"); f /= 0.5
        chain.append(f"atempo={f}")
        return ",".join(chain)

    streams = info.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    if not has_video and not has_audio:
        return fail("no_streams", "Input has no video or audio streams.")

    if has_video and has_audio:
        fc = f"[0:v]setpts=PTS/{factor}[v];[0:a]{_atempo_chain(factor)}[a]"
        maps = ["-map", "[v]", "-map", "[a]"]
        codecs = ["-c:v", "libx264", "-crf", "20", "-preset", "medium",
                  "-c:a", "aac", "-b:a", "192k"]
    elif has_video:
        fc = f"[0:v]setpts=PTS/{factor}[v]"
        maps = ["-map", "[v]"]
        codecs = ["-c:v", "libx264", "-crf", "20", "-preset", "medium"]
    else:
        fc = f"[0:a]{_atempo_chain(factor)}[a]"
        maps = ["-map", "[a]"]
        codecs = ["-c:a", "aac", "-b:a", "192k"]

    cmd = [ffmpeg, "-y", "-i", str(src),
           "-filter_complex", fc, *maps, *codecs, str(out_path)]
    emit("progress", percent=0, stage=f"speed x{factor}", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration / factor, f"speed x{factor}")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_reverse(args: argparse.Namespace) -> int:
    """Reverse video and (optionally) audio."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    streams = info.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    cmd = [ffmpeg, "-y", "-i", str(src)]
    if has_video:
        cmd += ["-vf", "reverse", "-c:v", "libx264", "-crf", "20", "-preset", "medium"]
    if has_audio:
        cmd += ["-af", "areverse" if args.reverse_audio else "anull",
                "-c:a", "aac", "-b:a", "192k"]
    elif not has_video:
        return fail("no_streams", "Input has no video or audio streams.")
    cmd.append(str(out_path))
    emit("progress", percent=0, stage="reverse", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "reverse")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


def op_lut(args: argparse.Namespace) -> int:
    """Apply a 3D LUT (.cube) to a video via ffmpeg's lut3d filter."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input); lut = Path(args.lut)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    if not lut.is_file(): return fail("missing_lut", f"LUT file not found: {args.lut}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    safe_lut = str(lut).replace("\\", "/").replace(":", "\\:")
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", f"lut3d='{safe_lut}'",
           "-c:v", "libx264", "-crf", "20", "-preset", "medium",
           "-c:a", "copy", str(out_path)]
    emit("progress", percent=0, stage="lut3d", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "lut3d")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


_TONEMAP_OPERATORS = {"hable", "reinhard", "mobius", "clip", "linear", "gamma"}


def op_hdr_to_sdr(args: argparse.Namespace) -> int:
    """Tone-map HDR (BT.2020 / HLG / PQ) to SDR (BT.709) via FFmpeg's
    `zscale` -> `tonemap` -> `zscale` filter chain. The tonemap operator is
    user-selectable (Item 17): hable / reinhard / mobius are the three most
    commonly recommended for SDR delivery; clip / linear / gamma are kept as
    debug-style escape hatches."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file(): return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    operator = (getattr(args, "operator", None) or "hable").lower()
    if operator not in _TONEMAP_OPERATORS:
        return fail("invalid_args",
                    f"Unknown tonemap operator: {operator}. "
                    f"Use one of {sorted(_TONEMAP_OPERATORS)}.")
    desat = max(0.0, min(1.0, getattr(args, "desat", 0.0) or 0.0))
    peak = getattr(args, "peak_nits", None) or 100
    crf = getattr(args, "crf", None) or 20

    # zscale path is the most portable across ffmpeg builds. tonemap accepts
    # an optional desat=… arg to control colour-saturation falloff in highlights.
    vf = (f"zscale=t=linear:npl={peak},format=gbrpf32le,"
          f"zscale=p=bt709,tonemap=tonemap={operator}:desat={desat},"
          f"zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", vf,
           "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
           "-c:a", "copy", str(out_path)]
    emit("log", level="info",
         message=f"hdr->sdr operator={operator} desat={desat} peak={peak} crf={crf}")
    emit("progress", percent=0, stage="hdr->sdr", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "hdr->sdr")
    if rc != 0: return fail("ffmpeg_failed", f"FFmpeg exited {rc} (zscale not built? Try a "
                                              "newer ffmpeg with --enable-libzimg).")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Intro/outro editor (Item 36) ────────────────────────────────────────────

def op_intro_outro(args: argparse.Namespace) -> int:
    """Prepend an intro and/or append an outro to the primary --input video.
    Thin wrapper over op_concat: builds the [intro?, primary, outro?] list,
    delegates to the existing concat machinery (stream-copy when codecs match,
    filter_complex when not), and produces a single output. Keeps the
    intro/outro UX clean for callers who don't want to think about `nargs="+"`."""
    primary = Path(args.input)
    if not primary.is_file():
        return fail("missing_input", f"Primary input not found: {args.input}")
    pieces: list[Path] = []
    if args.intro:
        ip = Path(args.intro)
        if not ip.is_file():
            return fail("missing_intro", f"Intro file not found: {args.intro}")
        pieces.append(ip)
    pieces.append(primary)
    if args.outro:
        op = Path(args.outro)
        if not op.is_file():
            return fail("missing_outro", f"Outro file not found: {args.outro}")
        pieces.append(op)

    if len(pieces) == 1:
        return fail("nothing_to_concat",
                    "intro-outro requires at least one --intro or --outro file.")

    # Synthesise the args namespace op_concat expects.
    concat_args = argparse.Namespace(
        input=[str(p) for p in pieces],
        output=args.output,
        reencode=bool(args.reencode))
    return op_concat(concat_args)


# ─── 360° / VR projection (Item 38) ──────────────────────────────────────────

_V360_INPUT_PROJECTIONS = {"e", "equirect", "c3x2", "c6x1", "c1x6", "fisheye", "flat", "dfisheye", "barrel", "cube"}
_V360_OUTPUT_PROJECTIONS = {"e", "equirect", "c3x2", "c6x1", "c1x6", "fisheye", "flat", "dfisheye", "barrel", "cube"}


def op_v360(args: argparse.Namespace) -> int:
    """Convert between 360° / VR projections via FFmpeg's `v360` filter.
    Common moves: equirectangular -> rectilinear (flat) viewport, equirect
    -> 6x1 cubemap for game-engine import, fisheye -> equirect, etc."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    src_proj = (args.input_projection or "equirect").lower()
    dst_proj = (args.output_projection or "flat").lower()
    if src_proj not in _V360_INPUT_PROJECTIONS:
        return fail("invalid_args",
                    f"Unknown --input-projection: {src_proj}. "
                    f"Known: {sorted(_V360_INPUT_PROJECTIONS)}.")
    if dst_proj not in _V360_OUTPUT_PROJECTIONS:
        return fail("invalid_args",
                    f"Unknown --output-projection: {dst_proj}. "
                    f"Known: {sorted(_V360_OUTPUT_PROJECTIONS)}.")

    parts = [f"v360={src_proj}:{dst_proj}",
             f"yaw={args.yaw}", f"pitch={args.pitch}", f"roll={args.roll}"]
    if args.h_fov: parts.append(f"h_fov={args.h_fov}")
    if args.v_fov: parts.append(f"v_fov={args.v_fov}")
    if args.width and args.height:
        parts.append(f"w={args.width}")
        parts.append(f"h={args.height}")
    vf = ":".join(parts)

    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", vf,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
    emit("log", level="info", message=f"v360 {src_proj} -> {dst_proj}")
    emit("progress", percent=0, stage="v360", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "v360")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during v360 conversion.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Lens correction (Item 24) ───────────────────────────────────────────────

def op_lens_correct(args: argparse.Namespace) -> int:
    """Apply FFmpeg's `lenscorrection` filter for barrel / pincushion
    distortion correction. Useful for action cam / wide-angle footage where
    a vendor lens-distortion model is unavailable. K1 < 0 = pincushion
    correction; K1 > 0 = barrel correction. Cx/Cy default to centre."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    cx = max(0.0, min(1.0, args.cx))
    cy = max(0.0, min(1.0, args.cy))
    vf = f"lenscorrection=cx={cx}:cy={cy}:k1={args.k1}:k2={args.k2}"
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", vf,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
    emit("log", level="info", message=f"lenscorrection k1={args.k1} k2={args.k2}")
    emit("progress", percent=0, stage="lens-correct", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "lens-correct")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during lens correction.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Watermark overlay (Item 31) ─────────────────────────────────────────────

# 9-point grid -> FFmpeg overlay x/y expressions. Anchors derived from main
# video dimensions (W,H) and overlay dimensions (w,h).
_WATERMARK_POSITIONS = {
    "tl": ("(M)", "(M)"),
    "tc": ("(W-w)/2", "(M)"),
    "tr": ("W-w-(M)", "(M)"),
    "ml": ("(M)", "(H-h)/2"),
    "mc": ("(W-w)/2", "(H-h)/2"),
    "mr": ("W-w-(M)", "(H-h)/2"),
    "bl": ("(M)", "H-h-(M)"),
    "bc": ("(W-w)/2", "H-h-(M)"),
    "br": ("W-w-(M)", "H-h-(M)"),
}


def op_watermark(args: argparse.Namespace) -> int:
    """Stamp a PNG/JPEG logo onto the video via FFmpeg's `overlay` filter.
    9-point position grid + opacity (0..1) + scale (% of frame width).
    The overlay is alpha-pre-multiplied via the `format=rgba,colorchannelmixer`
    chain so users can dial opacity without baking it into the source PNG."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    overlay = Path(args.overlay)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    if not overlay.is_file():
        return fail("missing_overlay", f"Overlay image not found: {args.overlay}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    pos = (args.position or "br").lower()
    coords = _WATERMARK_POSITIONS.get(pos)
    if coords is None:
        return fail("invalid_args", f"Unknown position: {pos}. "
                                     f"Use one of {sorted(_WATERMARK_POSITIONS)}.")
    margin = max(0, args.margin)
    x_expr = coords[0].replace("(M)", str(margin))
    y_expr = coords[1].replace("(M)", str(margin))

    opacity = max(0.0, min(1.0, args.opacity))
    scale_pct = max(1.0, min(100.0, args.scale))
    # scale2ref pegs the overlay width to the main video width % so the stamp
    # stays proportional regardless of source resolution.
    fc = (
        f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wm0];"
        f"[wm0][0:v]scale2ref=w=main_w*{scale_pct/100.0}:h=ow/iw*ih[wm][bg];"
        f"[bg][wm]overlay={x_expr}:{y_expr}"
    )
    cmd = [ffmpeg, "-y", "-i", str(src), "-i", str(overlay),
           "-filter_complex", fc,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
    emit("log", level="info",
         message=f"watermark {overlay.name} pos={pos} opacity={opacity} scale={scale_pct}%")
    emit("progress", percent=0, stage="watermark", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "watermark")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during watermark overlay.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Subtitle burn-in (Item 14) ──────────────────────────────────────────────

# 9-point grid -> ASS \an alignment (libass numbering: 1=BL, 2=BC, 3=BR,
# 4=ML, 5=MC, 6=MR, 7=TL, 8=TC, 9=TR).
_BURN_POSITION_TO_AN = {
    "tl": 7, "tc": 8, "tr": 9,
    "ml": 4, "mc": 5, "mr": 6,
    "bl": 1, "bc": 2, "br": 3,
}


def _ffmpeg_subfile_arg(path: Path) -> str:
    """Escape a Windows path so FFmpeg's `subtitles=` filter parses it."""
    s = str(path).replace("\\", "/")
    s = s.replace("'", "\\'")
    s = s.replace(":", "\\:")
    s = s.replace("[", "\\[").replace("]", "\\]")
    s = s.replace(";", "\\;")
    return s


import re as _re
_SAFE_FONT_RE = _re.compile(r"^[A-Za-z0-9 \-_.']+$")
_SAFE_HEX_RE = _re.compile(r"^[0-9A-Fa-f]{6,8}$")


def op_subtitle_burn(args: argparse.Namespace) -> int:
    """Burn an external subtitle file (.srt / .ass / .ssa / .vtt) into the
    video using FFmpeg's `subtitles=` filter. Honours user font / size /
    colour / outline / position controls via libass `force_style` overrides."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    sub = Path(args.subtitles)
    if not sub.is_file():
        return fail("missing_subtitles", f"Subtitle file not found: {args.subtitles}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    pos = (args.position or "bc").lower()
    alignment = _BURN_POSITION_TO_AN.get(pos)
    if alignment is None:
        return fail("invalid_args", f"Unknown position: {pos}. "
                                     f"Use one of {sorted(_BURN_POSITION_TO_AN)}.")

    font = args.font
    if not _SAFE_FONT_RE.match(font):
        font = _re.sub(r"[^A-Za-z0-9 \-_.]", "", font) or "Arial"
    for color_name in ("color", "outline_color", "shadow_color"):
        val = getattr(args, color_name, "")
        if val and not _SAFE_HEX_RE.match(val):
            return fail("invalid_args", f"--{color_name.replace('_', '-')} must be a hex color (e.g. FFFFFF)")

    style_pairs = [
        f"FontName={font}",
        f"FontSize={args.size}",
        f"PrimaryColour=&H{args.color}",
        f"OutlineColour=&H{args.outline_color}",
        f"BackColour=&H{args.shadow_color}",
        f"BorderStyle={args.border_style}",
        f"Outline={args.outline}",
        f"Shadow={args.shadow}",
        f"MarginV={args.margin_v}",
        f"Alignment={alignment}",
    ]
    if args.bold:   style_pairs.append("Bold=-1")
    if args.italic: style_pairs.append("Italic=-1")
    style = ",".join(style_pairs)

    sub_arg = _ffmpeg_subfile_arg(sub)
    vf = f"subtitles='{sub_arg}':force_style='{style}'"
    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", vf,
           "-c:v", "libx264", "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy",
           "-movflags", "+faststart", str(out_path)]
    emit("log", level="info", message=f"burn subtitles {sub.name} -> {out_path.name}")
    emit("progress", percent=0, stage="burn-in", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "burn-in")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during subtitle burn-in.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Auto-crop (Item 23) ─────────────────────────────────────────────────────

_CROPDETECT_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def _detect_crop(ffmpeg: str, src: Path, sample_seconds: float, threshold: int) -> str | None:
    """Run a short cropdetect pass over the first <sample_seconds> seconds
    and return the most-frequently observed `crop=W:H:X:Y` rectangle. Returns
    None when no rectangle could be detected."""
    cmd = [ffmpeg, "-y",
           "-t", f"{max(1.0, sample_seconds):.1f}",
           "-i", str(src),
           "-vf", f"cropdetect={threshold}:16:0",
           "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    counts: dict[str, int] = {}
    for ln in (proc.stderr or "").splitlines():
        m = _CROPDETECT_RE.search(ln)
        if not m:
            continue
        key = m.group(0)  # "crop=W:H:X:Y"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.__getitem__)


def op_auto_crop(args: argparse.Namespace) -> int:
    """Detect black borders via FFmpeg's cropdetect filter and apply the
    detected rectangle. Useful for letterboxed / pillarboxed content
    captured from broadcast or DVD."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    emit("progress", percent=0, stage="cropdetect", eta_seconds=None)
    sample = min(args.sample_seconds, max(1.0, duration))
    crop = _detect_crop(ffmpeg, src, sample, args.threshold)
    if crop is None:
        return fail("crop_undetected",
                    "cropdetect did not return a stable rectangle. "
                    "Try --threshold higher (e.g. 36) or a longer --sample-seconds.")
    emit("log", level="info", message=f"detected {crop}")

    if args.detect_only:
        # Probe-only mode — print the detected rectangle and exit successfully
        # without producing an output file.
        m = _CROPDETECT_RE.search(crop)
        if m:
            emit("complete", output=None,
                 detected={"width": int(m.group(1)), "height": int(m.group(2)),
                           "x": int(m.group(3)), "y": int(m.group(4))})
        return 0

    cmd = [ffmpeg, "-y", "-i", str(src),
           "-vf", crop,
           "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
           "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
    emit("progress", percent=0, stage="auto-crop", eta_seconds=None)
    rc = run_ffmpeg(cmd, duration, "auto-crop")
    if rc != 0:
        return fail("ffmpeg_failed", f"FFmpeg exited {rc} during auto-crop.")
    if not out_path.is_file():
        return fail("output_missing", f"Output not produced: {out_path}")
    emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
    return 0


# ─── Video stabilization (Item 19) ───────────────────────────────────────────

def op_stabilize(args: argparse.Namespace) -> int:
    """Two-pass video stabilization via FFmpeg's vidstab filters.

    Pass 1 runs `vidstabdetect` writing motion vectors to a temp `.trf` file.
    Pass 2 runs `vidstabtransform` consuming that file and crops or fills
    the borders introduced by the warp."""
    ffmpeg = find_ffmpeg(); ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        return fail("missing_ffmpeg", "FFmpeg/FFprobe not found.")
    src = Path(args.input)
    if not src.is_file():
        return fail("missing_input", f"Input not found: {args.input}")
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe(ffprobe, str(src)) or {}
    duration = float(info.get("format", {}).get("duration", 0))

    border = (args.border or "keep").lower()
    if border not in ("keep", "black", "crop"):
        return fail("invalid_args",
                    f"Unknown --border: {border}. Use keep, black, or crop.")
    shakiness = max(1, min(10, args.shakiness))
    smoothing = max(1, min(60, args.smoothing))

    transforms = out_path.parent / f"{src.stem}_{os.getpid()}.trf"
    try:
        # Pass 1: detect.
        detect_filter = f"vidstabdetect=shakiness={shakiness}:result={_ffmpeg_subfile_arg(transforms)}"
        cmd1 = [ffmpeg, "-y", "-i", str(src),
                "-vf", detect_filter,
                "-f", "null", "-"]
        emit("log", level="info",
             message=f"stabilize pass1 shakiness={shakiness} -> {transforms.name}")
        emit("progress", percent=0, stage="stabilize-detect", eta_seconds=None)
        rc = run_ffmpeg(cmd1, duration, "stabilize-detect")
        if rc != 0:
            return fail("vidstab_missing",
                        f"FFmpeg exited {rc}. The vidstab filter requires a "
                        "build with --enable-libvidstab. BtbN's "
                        "ffmpeg-master-latest-win64-gpl includes it.")

        # Pass 2: transform.
        if border == "crop":
            transform_filter = (
                f"vidstabtransform=smoothing={smoothing}:input={_ffmpeg_subfile_arg(transforms)}"
                f":crop=keep,unsharp=5:5:0.8:3:3:0.4")
        else:
            crop_arg = "black" if border == "black" else "keep"
            transform_filter = (
                f"vidstabtransform=smoothing={smoothing}:input={_ffmpeg_subfile_arg(transforms)}"
                f":crop={crop_arg},unsharp=5:5:0.8:3:3:0.4")
        cmd2 = [ffmpeg, "-y", "-i", str(src),
                "-vf", transform_filter,
                "-c:v", args.codec, "-crf", str(args.crf), "-preset", args.preset,
                "-c:a", "copy", "-movflags", "+faststart", str(out_path)]
        emit("log", level="info",
             message=f"stabilize pass2 smoothing={smoothing} border={border}")
        emit("progress", percent=0, stage="stabilize-transform", eta_seconds=None)
        rc = run_ffmpeg(cmd2, duration, "stabilize-transform")
        if rc != 0:
            return fail("ffmpeg_failed",
                        f"FFmpeg exited {rc} during vidstabtransform pass.")
        if not out_path.is_file():
            return fail("output_missing", f"Output not produced: {out_path}")
        emit("complete", output=str(out_path), size_bytes=out_path.stat().st_size)
        return 0
    finally:
        try: transforms.unlink(missing_ok=True)
        except OSError: pass

from clipforge_ops.privacy import (
    _blur_face_regions,
    _expand_face_box,
    _load_face_detector,
    op_face_blur,
)



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clipforge-sidecar",
                                description="UCX ClipForge sidecar — video editor operations with NDJSON progress.")
    sub = p.add_subparsers(dest="op", required=True)

    # ── trim ──────────────────────────────────────────────────────────────────
    trim = sub.add_parser("trim", help="Trim a video clip")
    trim.add_argument("--input", required=True)
    trim.add_argument("--output", required=True)
    trim.add_argument("--start", type=float, default=0.0, help="Start time (seconds)")
    trim.add_argument("--end", type=float, help="End time (seconds); omit or 0 for end of clip")
    trim.add_argument("--lossless", action="store_true",
                      help="Stream-copy mode (fast, keyframe-bounded). Skips re-encode.")
    trim.add_argument("--codec", default="libx264", help="Video codec when re-encoding")
    trim.add_argument("--crf", type=int, default=18, help="CRF when re-encoding")
    trim.add_argument("--preset", default="medium", help="FFmpeg encoder preset")
    trim.add_argument("--audio-codec", default="aac")
    trim.add_argument("--audio-bitrate", type=int, default=192)

    # ── crop ──────────────────────────────────────────────────────────────────
    crop = sub.add_parser("crop", help="Crop video to a rectangle")
    crop.add_argument("--input", required=True)
    crop.add_argument("--output", required=True)
    crop.add_argument("--width", type=int, required=True, help="Output width in pixels")
    crop.add_argument("--height", type=int, required=True, help="Output height in pixels")
    crop.add_argument("--x", type=int, default=0, help="Left edge of crop (pixels from left)")
    crop.add_argument("--y", type=int, default=0, help="Top edge of crop (pixels from top)")
    crop.add_argument("--codec", default="libx264")
    crop.add_argument("--crf", type=int, default=18)
    crop.add_argument("--preset", default="medium")

    # ── RIFE frame interpolation ────────────────────────────────────────────
    rife_status = sub.add_parser(
        "rife-status",
        help="Check the pinned managed RIFE ncnn-vulkan runtime")

    rife = sub.add_parser(
        "rife",
        help="Interpolate a video to a higher target frame rate with RIFE Vulkan")
    rife.add_argument("--input", required=True)
    rife.add_argument("--output", required=True)
    rife.add_argument("--target-fps", type=float, required=True,
                      help="Target frame rate, from 1 through 240 FPS")
    rife.add_argument("--model", choices=[_RIFE_MODEL], default=_RIFE_MODEL,
                      help="Pinned RIFE model (default: rife-v4.6)")
    rife.add_argument("--codec", choices=["libx264", "libx265"], default="libx264")
    rife.add_argument("--crf", type=int, choices=range(0, 52), default=18)
    rife.add_argument("--preset", default="medium")
    rife.add_argument("--audio-bitrate", type=int, default=192)

    crop_meta = sub.add_parser(
        "crop-meta",
        help="Set H.264/H.265 display-crop metadata without re-encoding")
    crop_meta.add_argument("--input", required=True)
    crop_meta.add_argument("--output", required=True)
    crop_meta.add_argument("--left", type=int, default=0)
    crop_meta.add_argument("--right", type=int, default=0)
    crop_meta.add_argument("--top", type=int, default=0)
    crop_meta.add_argument("--bottom", type=int, default=0)

    aspect_override = sub.add_parser(
        "aspect-override",
        help="Override display aspect ratio with packet stream-copy")
    aspect_override.add_argument("--input", required=True)
    aspect_override.add_argument("--output", required=True)
    aspect_override.add_argument(
        "--aspect", required=True,
        help="Display aspect ratio, for example 16:9 or 4/3")

    # ── rotate ────────────────────────────────────────────────────────────────
    rotate = sub.add_parser("rotate", help="Rotate or flip video")
    rotate.add_argument("--input", required=True)
    rotate.add_argument("--output", required=True)
    rotate.add_argument("--angle", required=True,
                        choices=list(_ROTATE_FILTERS.keys()),
                        help="90 | 180 | 270 | flip_h | flip_v")
    rotate.add_argument("--codec", default="libx264")
    rotate.add_argument("--crf", type=int, default=18)
    rotate.add_argument("--preset", default="medium")

    # ── loudnorm ──────────────────────────────────────────────────────────────
    loudnorm = sub.add_parser("loudnorm", help="EBU R128 loudness normalisation")
    loudnorm.add_argument("--input", required=True)
    loudnorm.add_argument("--output", required=True)
    loudnorm.add_argument("--integrated-lufs", type=float, default=-14.0,
                          dest="integrated_lufs",
                          help="Target integrated loudness in LUFS (default: -14)")
    loudnorm.add_argument("--true-peak", type=float, default=-1.5, dest="true_peak",
                          help="Max true peak in dBTP (default: -1.5)")
    loudnorm.add_argument("--lra", type=float, default=11.0,
                          help="Loudness range target in LU (default: 11)")
    loudnorm.add_argument("--audio-codec", default="aac", dest="audio_codec")
    loudnorm.add_argument("--audio-bitrate", type=int, default=192, dest="audio_bitrate")

    # ── rewrap ────────────────────────────────────────────────────────────────
    rewrap = sub.add_parser("rewrap", help="Remux into a different container without re-encoding")
    rewrap.add_argument("--input", required=True)
    rewrap.add_argument("--output", required=True)

    # ── tracks ────────────────────────────────────────────────────────────────
    track_list = sub.add_parser("track-list",
                                help="Enumerate every stream in a container")
    track_list.add_argument("--input", required=True)

    track_remove = sub.add_parser("track-remove",
                                  help="Remove specific streams without re-encoding")
    track_remove.add_argument("--input", required=True)
    track_remove.add_argument("--output", required=True)
    track_remove.add_argument("--remove", required=True,
                              help="Comma-separated list of stream indices to drop, e.g. '1,3'")

    track_edit = sub.add_parser(
        "track-edit",
        help="Remove streams and apply per-audio-stream timestamp offsets without re-encoding")
    track_edit.add_argument("--input", required=True)
    track_edit.add_argument("--output", required=True)
    track_edit.add_argument("--remove", default="",
                            help="Optional comma-separated stream indices to drop")
    track_edit.add_argument("--delays", default="",
                            help="Optional stream=milliseconds pairs, e.g. '1=250,2=-80'")

    track_add = sub.add_parser("track-add",
                               help="Add an external audio/subtitle file as a new track")
    track_add.add_argument("--input", required=True)
    track_add.add_argument("--extra", required=True,
                           help="Audio (.mp3/.aac/.flac/...) or subtitle (.srt/.ass) file to attach")
    track_add.add_argument("--output", required=True)
    track_add.add_argument("--language",
                           help="Optional ISO-639 language code for the new track (e.g. 'eng', 'jpn')")
    track_add.add_argument("--title",
                           help="Optional title metadata for the new track")

    track_extract = sub.add_parser(
        "track-extract",
        help="Export a single subtitle stream from the container to a standalone file")
    track_extract.add_argument("--input", required=True)
    track_extract.add_argument("--stream", required=True,
                               help="Container-level stream index (as reported by track-list)")
    track_extract.add_argument("--output", required=True,
                               help="Output path; extension drives the target format "
                                    "(.srt / .vtt / .ass / .ssa / .lrc / .sup)")

    deinterlace = sub.add_parser(
        "deinterlace",
        help="Auto-detect interlaced video and produce progressive output")
    deinterlace.add_argument("--input", required=True)
    deinterlace.add_argument("--output", required=True)
    deinterlace.add_argument("--filter", choices=["bwdif", "yadif"], default="bwdif")
    deinterlace.add_argument("--rate", choices=["double", "single"], default="double",
                             help="One frame per field (double) or per input frame (single)")
    deinterlace.add_argument("--codec", default="libx264")
    deinterlace.add_argument("--crf", type=int, choices=range(0, 52), default=18)
    deinterlace.add_argument("--preset", default="medium")

    # ── concat ────────────────────────────────────────────────────────────────
    concat = sub.add_parser("concat", help="Concatenate clips (stream-copy when codecs match, re-encode otherwise)")
    concat.add_argument("--input", nargs="+", required=True)
    concat.add_argument("--output", required=True)
    concat.add_argument("--reencode", action="store_true",
                        help="Force re-encode via filter_complex concat.")

    # ── speed ─────────────────────────────────────────────────────────────────
    speed = sub.add_parser("speed", help="Speed up / slow down (factor > 1 speeds up; < 1 slows)")
    speed.add_argument("--input", required=True)
    speed.add_argument("--output", required=True)
    speed.add_argument("--factor", required=True, help="0.25 = quarter speed, 2 = double speed")

    # ── reverse ───────────────────────────────────────────────────────────────
    reverse = sub.add_parser("reverse", help="Play video backwards")
    reverse.add_argument("--input", required=True)
    reverse.add_argument("--output", required=True)
    reverse.add_argument("--reverse-audio", action="store_true", dest="reverse_audio",
                         help="Also reverse the audio (default keeps audio forward).")

    # ── lut3d ─────────────────────────────────────────────────────────────────
    lut = sub.add_parser("lut3d", help="Apply a 3D LUT (.cube) for colour grading")
    lut.add_argument("--input", required=True)
    lut.add_argument("--output", required=True)
    lut.add_argument("--lut", required=True, help="Path to a .cube LUT file")

    # ── hdr-to-sdr ────────────────────────────────────────────────────────────
    h2s = sub.add_parser("hdr-to-sdr", help="Tone-map HDR (BT.2020/HLG/PQ) -> SDR (BT.709)")
    h2s.add_argument("--input", required=True)
    h2s.add_argument("--output", required=True)
    h2s.add_argument("--operator", default="hable",
                     help="Tonemap operator: hable, reinhard, mobius, clip, linear, gamma. "
                          "Default 'hable' is the safest default for general SDR delivery.")
    h2s.add_argument("--desat", type=float, default=0.0,
                     help="Highlight desaturation 0.0..1.0 (default 0).")
    h2s.add_argument("--peak-nits", type=int, default=100, dest="peak_nits",
                     help="Reference SDR peak in nits passed to zscale (default 100).")
    h2s.add_argument("--crf", type=int, default=20,
                     help="CRF for the libx264 output (default 20).")

    # ── subtitle-burn ─────────────────────────────────────────────────────────
    burn = sub.add_parser("subtitle-burn",
                          help="Burn an external subtitle file into the video (libass)")
    burn.add_argument("--input", required=True)
    burn.add_argument("--output", required=True)
    burn.add_argument("--subtitles", required=True,
                      help="Path to .srt / .ass / .ssa / .vtt subtitle file")
    burn.add_argument("--font", default="Arial", help="Font family name (default Arial)")
    burn.add_argument("--size", type=int, default=24, help="Font size px (default 24)")
    burn.add_argument("--color", default="00FFFFFF",
                      help="Primary fill colour as ASS BBGGRR or AABBGGRR hex (default 00FFFFFF = white).")
    burn.add_argument("--outline-color", dest="outline_color", default="00000000",
                      help="Outline colour as ASS hex (default 00000000 = black).")
    burn.add_argument("--shadow-color", dest="shadow_color", default="80000000",
                      help="Shadow colour as ASS hex (default 80000000 = 50%% black).")
    burn.add_argument("--border-style", dest="border_style", type=int, default=1,
                      help="Border style: 1=outline+shadow, 3=opaque box (default 1).")
    burn.add_argument("--outline", type=float, default=2.0,
                      help="Outline thickness in pixels (default 2.0).")
    burn.add_argument("--shadow", type=float, default=0.0,
                      help="Drop-shadow offset in pixels (default 0).")
    burn.add_argument("--margin-v", dest="margin_v", type=int, default=24,
                      help="Vertical margin from edge in pixels (default 24).")
    burn.add_argument("--position", default="bc",
                      help="9-point grid: tl tc tr ml mc mr bl bc br (default bc).")
    burn.add_argument("--bold", action="store_true")
    burn.add_argument("--italic", action="store_true")
    burn.add_argument("--codec", default="libx264")
    burn.add_argument("--crf", type=int, default=20)
    burn.add_argument("--preset", default="medium")

    # ── auto-crop ─────────────────────────────────────────────────────────────
    autocrop = sub.add_parser("auto-crop",
                              help="Detect black borders via cropdetect and apply the rectangle")
    autocrop.add_argument("--input", required=True)
    autocrop.add_argument("--output", required=True)
    autocrop.add_argument("--threshold", type=int, default=24,
                          help="cropdetect black-pixel threshold (default 24).")
    autocrop.add_argument("--sample-seconds", dest="sample_seconds", type=float, default=10.0,
                          help="Seconds of source to sample for detection (default 10).")
    autocrop.add_argument("--detect-only", dest="detect_only", action="store_true",
                          help="Detect and report the rectangle without producing an output file.")
    autocrop.add_argument("--codec", default="libx264")
    autocrop.add_argument("--crf", type=int, default=20)
    autocrop.add_argument("--preset", default="medium")

    # ── intro-outro ───────────────────────────────────────────────────────────
    io_p = sub.add_parser("intro-outro",
                          help="Prepend an intro and/or append an outro to the primary input")
    io_p.add_argument("--input", required=True, help="Primary video file")
    io_p.add_argument("--output", required=True)
    io_p.add_argument("--intro", help="Optional pre-clip prepended to the primary video")
    io_p.add_argument("--outro", help="Optional post-clip appended to the primary video")
    io_p.add_argument("--reencode", action="store_true",
                      help="Force a filter_complex re-encode even when codecs match.")

    # ── v360 ──────────────────────────────────────────────────────────────────
    v360 = sub.add_parser("v360",
                          help="Reproject 360°/VR video between equirectangular, cubemap, fisheye, flat (FFmpeg v360 filter)")
    v360.add_argument("--input", required=True)
    v360.add_argument("--output", required=True)
    v360.add_argument("--input-projection", dest="input_projection", default="equirect",
                      help=f"Source projection. Default 'equirect'. Known: {sorted(_V360_INPUT_PROJECTIONS)}.")
    v360.add_argument("--output-projection", dest="output_projection", default="flat",
                      help=f"Target projection. Default 'flat' (rectilinear viewport).")
    v360.add_argument("--yaw", type=float, default=0.0, help="Yaw rotation in degrees (default 0).")
    v360.add_argument("--pitch", type=float, default=0.0, help="Pitch rotation in degrees (default 0).")
    v360.add_argument("--roll", type=float, default=0.0, help="Roll rotation in degrees (default 0).")
    v360.add_argument("--h-fov", dest="h_fov", type=float, default=0.0,
                      help="Horizontal FOV (degrees) for output projection (0 = filter default).")
    v360.add_argument("--v-fov", dest="v_fov", type=float, default=0.0,
                      help="Vertical FOV (degrees) for output projection (0 = filter default).")
    v360.add_argument("--width", type=int, default=0, help="Output width in pixels (0 = source).")
    v360.add_argument("--height", type=int, default=0, help="Output height in pixels (0 = source).")
    v360.add_argument("--codec", default="libx264")
    v360.add_argument("--crf", type=int, default=20)
    v360.add_argument("--preset", default="medium")

    # ── lens-correct ──────────────────────────────────────────────────────────
    lensc = sub.add_parser("lens-correct",
                           help="Barrel/pincushion correction via FFmpeg lenscorrection filter")
    lensc.add_argument("--input", required=True)
    lensc.add_argument("--output", required=True)
    lensc.add_argument("--k1", type=float, default=-0.2,
                       help="Quadratic correction. <0 = pincushion correction (default -0.2 for action cams).")
    lensc.add_argument("--k2", type=float, default=0.0,
                       help="Quartic correction (default 0).")
    lensc.add_argument("--cx", type=float, default=0.5, help="Optical centre X (0..1, default 0.5).")
    lensc.add_argument("--cy", type=float, default=0.5, help="Optical centre Y (0..1, default 0.5).")
    lensc.add_argument("--codec", default="libx264")
    lensc.add_argument("--crf", type=int, default=20)
    lensc.add_argument("--preset", default="medium")

    # ── watermark ─────────────────────────────────────────────────────────────
    wm = sub.add_parser("watermark",
                        help="Overlay a PNG/JPEG logo with 9-point positioning, opacity, and scale")
    wm.add_argument("--input", required=True)
    wm.add_argument("--output", required=True)
    wm.add_argument("--overlay", required=True,
                    help="Path to a PNG (with alpha) or JPEG logo file")
    wm.add_argument("--position", default="br",
                    help="9-point grid: tl tc tr ml mc mr bl bc br (default br).")
    wm.add_argument("--opacity", type=float, default=0.7,
                    help="Overlay opacity 0..1 (default 0.7).")
    wm.add_argument("--scale", type=float, default=15.0,
                    help="Overlay width as percent of frame width (default 15).")
    wm.add_argument("--margin", type=int, default=24,
                    help="Edge margin in pixels (default 24).")
    wm.add_argument("--codec", default="libx264")
    wm.add_argument("--crf", type=int, default=20)
    wm.add_argument("--preset", default="medium")

    # ── stabilize ─────────────────────────────────────────────────────────────
    stab = sub.add_parser("stabilize",
                          help="Two-pass video stabilization via vidstabdetect + vidstabtransform")
    stab.add_argument("--input", required=True)
    stab.add_argument("--output", required=True)
    stab.add_argument("--shakiness", type=int, default=5,
                      help="Detection shakiness 1..10 (default 5).")
    stab.add_argument("--smoothing", type=int, default=15,
                      help="Smoothing window in frames 1..60 (default 15).")
    stab.add_argument("--border", default="keep",
                      help="Border handling: keep | black | crop (default keep).")
    stab.add_argument("--codec", default="libx264")
    stab.add_argument("--crf", type=int, default=20)
    stab.add_argument("--preset", default="medium")

    # ── face blur ────────────────────────────────────────────────────────────
    face_blur = sub.add_parser(
        "face-blur",
        help="Detect and irreversibly blur frontal faces in every frame")
    face_blur.add_argument("--input", required=True)
    face_blur.add_argument("--output", required=True)
    face_blur.add_argument("--strength", type=int, default=70,
                           help="Blur/pixelation strength 1..100 (default 70).")
    face_blur.add_argument("--padding", type=int, default=20,
                           help="Expand each detected face box by this percent (default 20).")
    face_blur.add_argument("--scale-factor", dest="scale_factor", type=float, default=1.1,
                           help="OpenCV cascade scale factor 1.01..2.0 (default 1.1).")
    face_blur.add_argument("--min-neighbors", dest="min_neighbors", type=int, default=5,
                           help="Cascade consensus threshold 1..20 (default 5).")
    face_blur.add_argument("--min-face", dest="min_face", type=int, default=24,
                           help="Smallest detected face in pixels (default 24).")
    face_blur.add_argument(
        "--hw-decode",
        action="store_true",
        help="Opt in to NVDEC frame decoding when CUDA/PyAV are available.")
    face_blur.add_argument("--codec", choices=("libx264", "libx265"), default="libx264")
    face_blur.add_argument("--crf", type=int, choices=range(0, 52), default=18)
    face_blur.add_argument("--preset", default="medium")

    # ── timeline ──────────────────────────────────────────────────────────────
    timeline = sub.add_parser("timeline",
                              help="Extract a thumbnail strip + waveform image for the UI scrub bar")
    timeline.add_argument("--input", required=True)
    timeline.add_argument("--output-dir", required=True, dest="output_dir")
    timeline.add_argument("--thumb-fps", type=float, default=1.0, dest="thumb_fps",
                          help="Thumbnails per second (default 1.0).")
    timeline.add_argument("--thumb-height", type=int, default=72, dest="thumb_height",
                          help="Thumbnail height in pixels (default 72).")
    timeline.add_argument("--waveform-width", type=int, default=2400, dest="waveform_width",
                          help="Waveform image width in pixels (default 2400).")
    timeline.add_argument("--waveform-height", type=int, default=80, dest="waveform_height",
                          help="Waveform image height in pixels (default 80).")
    timeline.add_argument("--waveform-color", default="0x6dd3ff", dest="waveform_color",
                          help="Waveform fill colour (default brand cyan).")

    # ── keyframes ─────────────────────────────────────────────────────────────
    keyframes = sub.add_parser(
        "keyframes",
        help="List video keyframe timestamps for lossless-cut snapping")
    keyframes.add_argument("--input", required=True)

    proxy = sub.add_parser(
        "proxy",
        help="Generate a fast low-resolution preview proxy (default 480p / 5 Mbps)")
    proxy.add_argument("--input", required=True)
    proxy.add_argument("--output", required=True)
    proxy.add_argument("--height", type=int, default=480,
                       help="Proxy height in pixels (default 480; width auto).")
    proxy.add_argument("--bitrate", default="5000k",
                       help="Target video bitrate, e.g. 5000k (default).")

    # ── vmaf ──────────────────────────────────────────────────────────────────
    vmaf = sub.add_parser("vmaf",
                          help="VMAF quality comparison: distorted vs. reference (libvmaf)")
    vmaf.add_argument("--reference", required=True,
                      help="Reference (high-quality master) video.")
    vmaf.add_argument("--distorted", required=True,
                      help="Distorted (compressed / re-encoded) video to score.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "trim":
            return op_trim(args)
        if args.op == "crop":
            return op_crop(args)
        if args.op == "rife-status":
            return op_rife_status(args)
        if args.op == "rife":
            return op_rife(args)
        if args.op == "crop-meta":
            return op_crop_meta(args)
        if args.op == "aspect-override":
            return op_aspect_override(args)
        if args.op == "rotate":
            return op_rotate(args)
        if args.op == "loudnorm":
            return op_loudnorm(args)
        if args.op == "rewrap":
            return op_rewrap(args)
        if args.op == "vmaf":
            return op_vmaf(args)
        if args.op == "timeline":
            return op_timeline(args)
        if args.op == "keyframes":
            return op_keyframes(args)
        if args.op == "proxy":
            return op_proxy(args)
        if args.op == "track-list":
            return op_track_list(args)
        if args.op == "track-remove":
            return op_track_remove(args)
        if args.op == "track-edit":
            return op_track_edit(args)
        if args.op == "track-add":
            return op_track_add(args)
        if args.op == "track-extract":
            return op_track_extract(args)
        if args.op == "deinterlace":
            return op_deinterlace(args)
        if args.op == "concat":
            return op_concat(args)
        if args.op == "speed":
            return op_speed(args)
        if args.op == "reverse":
            return op_reverse(args)
        if args.op == "lut3d":
            return op_lut(args)
        if args.op == "hdr-to-sdr":
            return op_hdr_to_sdr(args)
        if args.op == "subtitle-burn":
            return op_subtitle_burn(args)
        if args.op == "auto-crop":
            return op_auto_crop(args)
        if args.op == "stabilize":
            return op_stabilize(args)
        if args.op == "face-blur":
            return op_face_blur(args)
        if args.op == "lens-correct":
            return op_lens_correct(args)
        if args.op == "watermark":
            return op_watermark(args)
        if args.op == "v360":
            return op_v360(args)
        if args.op == "intro-outro":
            return op_intro_outro(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        emit("error", code="cancelled", message="Cancelled by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", code="unhandled", message=f"{type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
