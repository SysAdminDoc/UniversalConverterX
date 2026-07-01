#!/usr/bin/env python3
"""Slideshow Maker sidecar.

Builds a video slideshow from still images using FFmpeg. The default path
creates a Ken Burns-style zoom with cross-fade transitions, optional overlay
text, and optional background music. Output is NDJSON on stdout for the UCX
SidecarRunner.
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
import time
from pathlib import Path


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff",
    ".avif", ".heic", ".heif",
}

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
}

PRESETS = [
    {
        "name": "social-1080p",
        "description": "1920x1080 MP4, 3s slides, fade transition, Ken Burns motion.",
        "resolution": "1920x1080",
        "duration": 3.0,
        "transition": "fade",
        "motion": "kenburns",
        "fps": 30,
        "format": "mp4",
    },
    {
        "name": "square-feed",
        "description": "1080x1080 MP4 for square social posts.",
        "resolution": "1080x1080",
        "duration": 2.5,
        "transition": "zoom",
        "motion": "zoom-in",
        "fps": 30,
        "format": "mp4",
    },
    {
        "name": "presentation-4k",
        "description": "3840x2160 MP4 with slower 5s slide pacing.",
        "resolution": "3840x2160",
        "duration": 5.0,
        "transition": "fade",
        "motion": "kenburns",
        "fps": 30,
        "format": "mp4",
    },
]


def emit(event: str, **fields: object) -> None:
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def fail(code: str, message: str) -> int:
    emit("error", code=code, message=message)
    return 1


def find_ffmpeg() -> str | None:
    env = os.environ.get("FFMPEG_PATH")
    if env and Path(env).is_file():
        return env
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def natural_key(path: Path) -> list[object]:
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def collect_images(args: argparse.Namespace) -> list[Path]:
    images: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if not resolved.is_file():
            return
        if resolved.suffix.lower() not in IMAGE_EXTENSIONS:
            return
        key = os.path.normcase(str(resolved))
        if key in seen:
            return
        seen.add(key)
        images.append(resolved)

    if args.input_dir:
        root = Path(args.input_dir)
        iterator = root.rglob("*") if args.recursive else root.glob("*")
        for path in iterator:
            add(path)

    for raw in args.input or []:
        path = Path(raw)
        if path.is_dir():
            iterator = path.rglob("*") if args.recursive else path.glob("*")
            for child in iterator:
                add(child)
        else:
            add(path)

    return sorted(images, key=natural_key)


def parse_resolution(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d{2,5})\s*[xX]\s*(\d{2,5})\s*", value)
    if not match:
        raise ValueError("resolution must look like 1920x1080")
    width, height = int(match.group(1)), int(match.group(2))
    if width < 160 or height < 120 or width > 7680 or height > 4320:
        raise ValueError("resolution must be between 160x120 and 7680x4320")
    if width % 2 or height % 2:
        raise ValueError("resolution width and height must be even")
    return width, height


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for idx in range(1, 10_000):
        candidate = path.with_name(f"{stem} ({idx}){suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}-{int(time.time())}{suffix}")


def output_path(args: argparse.Namespace) -> Path:
    fmt = args.format.lower().lstrip(".")
    if args.output:
        target = Path(args.output).resolve()
        if not target.suffix:
            target = target.with_suffix(f".{fmt}")
    else:
        out_dir = Path(args.output_dir or os.getcwd()).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{args.name}.{fmt}"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target if args.overwrite else ensure_unique_path(target)


def ffmpeg_quote_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def zoom_expr(motion: str, frames: int) -> str:
    if motion == "none":
        return "1"
    if motion == "zoom-out":
        return "if(eq(on,0),1.12,max(1.0,zoom-0.0020))"
    if motion == "zoom-in":
        return "min(1.0+on*0.0020,1.14)"
    # Ken Burns defaults to a slow centered push-in.
    step = 0.14 / max(frames, 1)
    return f"min(1.0+on*{step:.7f},1.14)"


def build_filters(args: argparse.Namespace, image_count: int) -> tuple[str, str, float, str | None]:
    width, height = parse_resolution(args.resolution)
    fps = int(args.fps)
    duration = float(args.duration)
    frames = max(1, int(round(duration * fps)))
    transition_duration = 0.0 if args.transition == "cut" else min(float(args.transition_duration), duration - 0.05)

    filters: list[str] = []
    for idx in range(image_count):
        if args.fit == "contain":
            prep = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
        else:
            prep = (
                f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
                f"crop={width * 2}:{height * 2}"
            )

        z = zoom_expr(args.motion, frames)
        filters.append(
            f"[{idx}:v]{prep},setsar=1,"
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps={fps},"
            f"trim=duration={duration:.6f},setpts=N/{fps}/TB,format=yuv420p[v{idx}]"
        )

    if image_count == 1:
        current = "[v0]"
        total_duration = duration
    elif args.transition == "cut":
        inputs = "".join(f"[v{idx}]" for idx in range(image_count))
        filters.append(f"{inputs}concat=n={image_count}:v=1:a=0,format=yuv420p[vcat]")
        current = "[vcat]"
        total_duration = duration * image_count
    else:
        transition_name = {
            "fade": "fade",
            "wipe": "wipeleft",
            "zoom": "zoomin",
        }[args.transition]
        current = "[v0]"
        for idx in range(1, image_count):
            out = f"x{idx}"
            offset = idx * (duration - transition_duration)
            filters.append(
                f"{current}[v{idx}]xfade=transition={transition_name}:"
                f"duration={transition_duration:.6f}:offset={offset:.6f},"
                f"format=yuv420p[{out}]"
            )
            current = f"[{out}]"
        total_duration = duration * image_count - transition_duration * (image_count - 1)

    if args.overlay_text:
        safe_text = ffmpeg_quote_text(args.overlay_text)
        font_size = max(18, min(width // 24, 72))
        filters.append(
            f"{current}drawtext=text='{safe_text}':fontcolor=white:fontsize={font_size}:"
            f"box=1:boxcolor=black@0.48:boxborderw={max(8, font_size // 3)}:"
            f"x=(w-text_w)/2:y=h-text_h-{max(36, height // 18)}[vout]"
        )
        current = "[vout]"

    audio_label: str | None = None
    if args.music:
        music_index = image_count
        volume = max(0.0, min(float(args.music_volume), 2.0))
        filters.append(
            f"[{music_index}:a]volume={volume:.3f},"
            f"atrim=duration={total_duration:.6f},asetpts=PTS-STARTPTS[aout]"
        )
        audio_label = "[aout]"

    return ";".join(filters), current, max(total_duration, 0.1), audio_label


def output_encoding_args(fmt: str) -> list[str]:
    fmt = fmt.lower().lstrip(".")
    if fmt == "webm":
        return ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "31", "-row-mt", "1", "-pix_fmt", "yuv420p"]
    if fmt == "mov":
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def run_ffmpeg(cmd: list[str], total_duration: float) -> int:
    emit("progress", percent=3.0, stage="starting", eta_seconds=None)
    last_progress = 0.0
    tail: list[str] = []

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert proc.stderr is not None
    for raw in proc.stderr:
        line = raw.strip()
        if not line:
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            if key in {"out_time_ms", "out_time_us"}:
                try:
                    seconds = int(value) / 1_000_000.0
                except ValueError:
                    continue
                percent = min(98.0, 5.0 + (seconds / total_duration) * 92.0)
                if percent - last_progress >= 1.0:
                    emit("progress", percent=round(percent, 1), stage="encoding", eta_seconds=None)
                    last_progress = percent
            continue

        tail.append(line)
        tail = tail[-8:]

    rc = proc.wait()
    if rc != 0:
        for line in tail[-5:]:
            emit("log", level="error", message=line)
        return rc

    emit("progress", percent=100.0, stage="done", eta_seconds=0)
    return 0


def op_create(args: argparse.Namespace) -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return fail("missing_ffmpeg", "FFmpeg was not found on PATH or FFMPEG_PATH.")

    images = collect_images(args)
    if len(images) < 1:
        return fail("missing_input", "No supported images were found.")
    if len(images) > args.max_images:
        return fail("too_many_images", f"Refusing {len(images)} images; max is {args.max_images}.")

    try:
        parse_resolution(args.resolution)
    except ValueError as ex:
        return fail("bad_resolution", str(ex))

    if args.duration <= 0.25:
        return fail("bad_duration", "--duration must be greater than 0.25 seconds.")
    if args.fps < 1 or args.fps > 120:
        return fail("bad_fps", "--fps must be between 1 and 120.")

    if args.music:
        music = Path(args.music).resolve()
        if not music.is_file() or music.suffix.lower() not in AUDIO_EXTENSIONS:
            return fail("bad_music", "Background music must be an existing audio file.")
        args.music = str(music)

    out_path = output_path(args)

    try:
        filter_complex, video_label, total_duration, audio_label = build_filters(args, len(images))
    except ValueError as ex:
        return fail("bad_args", str(ex))

    cmd: list[str] = [ffmpeg, "-hide_banner"]
    cmd.append("-y" if args.overwrite else "-n")
    for image in images:
        cmd += ["-i", str(image)]
    if args.music:
        cmd += ["-stream_loop", "-1", "-i", args.music]

    cmd += ["-filter_complex", filter_complex, "-map", video_label]
    if audio_label:
        cmd += ["-map", audio_label, "-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-r", str(int(args.fps)), *output_encoding_args(args.format)]
    cmd += ["-progress", "pipe:2", "-nostats", str(out_path)]

    emit(
        "log",
        level="info",
        message=(
            f"Rendering {len(images)} images to {out_path.name} "
            f"({args.resolution}, {args.duration:g}s, {args.transition}, {args.motion})"
        ),
    )

    rc = run_ffmpeg(cmd, total_duration)
    if rc != 0:
        return fail("render_failed", f"FFmpeg exited with code {rc}.")

    size = out_path.stat().st_size if out_path.exists() else 0
    emit("complete", output=str(out_path), size_bytes=size, count=len(images))
    return 0


def op_presets(_args: argparse.Namespace) -> int:
    for preset in PRESETS:
        emit("preset", **preset)
    emit("complete", output="", size_bytes=0, count=len(PRESETS))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="slideshow-sidecar", description="Create video slideshows from images.")
    sub = parser.add_subparsers(dest="op", required=True)

    create = sub.add_parser("create", help="Image files or folder -> slideshow video.")
    create.add_argument("--input", nargs="*", default=[], help="Image file(s) or image folder(s).")
    create.add_argument("--input-dir", default=None, help="Folder of images, sorted naturally by filename.")
    create.add_argument("--recursive", action="store_true", help="Include images from child folders.")
    create.add_argument("--output", default=None, help="Exact output path.")
    create.add_argument("--output-dir", default=None, help="Output directory when --output is not supplied.")
    create.add_argument("--name", default="slideshow", help="Output basename when --output is not supplied.")
    create.add_argument("--format", choices=["mp4", "mov", "webm"], default="mp4")
    create.add_argument("--resolution", default="1920x1080")
    create.add_argument("--fps", type=int, default=30)
    create.add_argument("--duration", type=float, default=3.0, help="Seconds per slide.")
    create.add_argument("--transition", choices=["cut", "fade", "wipe", "zoom"], default="fade")
    create.add_argument("--transition-duration", type=float, default=0.6)
    create.add_argument("--motion", choices=["none", "kenburns", "zoom-in", "zoom-out"], default="kenburns")
    create.add_argument("--fit", choices=["cover", "contain"], default="cover")
    create.add_argument("--overlay-text", default="")
    create.add_argument("--music", default=None)
    create.add_argument("--music-volume", type=float, default=0.65)
    create.add_argument("--max-images", type=int, default=1000)
    create.add_argument("--overwrite", action="store_true")

    sub.add_parser("presets", help="Emit built-in slideshow presets.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.op == "create":
            return op_create(args)
        if args.op == "presets":
            return op_presets(args)
        return fail("unknown_op", f"Unknown op: {args.op}")
    except KeyboardInterrupt:
        return fail("cancelled", "Cancelled by user.")
    except Exception as ex:
        return fail("internal", f"{type(ex).__name__}: {ex}")


if __name__ == "__main__":
    raise SystemExit(main())
