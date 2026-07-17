"""Shared, dependency-free primitives for UniversalConverterX sidecars."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Callable, Iterable

try:
    import orjson

    def _dumps(value: object) -> str:
        return orjson.dumps(value).decode()
except ImportError:
    def _dumps(value: object) -> str:
        return json.dumps(value, ensure_ascii=False)


EventEmitter = Callable[..., None]
_TIME_RE = re.compile(r"out_time_(?:us|ms)=(\d+)")
_PROGRESS_KEYS = (
    "frame=", "fps=", "stream_", "bitrate=", "total_size=", "out_time_",
    "out_time=", "dup_frames=", "drop_frames=", "speed=", "progress=",
)


def emit(event: str, **fields: object) -> None:
    """Write one UTF-8 NDJSON protocol event and flush it immediately."""
    sys.stdout.write(_dumps({"event": event, **fields}) + "\n")
    sys.stdout.flush()


def find_tool(
    name: str,
    *,
    env_var: str | None = None,
    anchor: str | Path | None = None,
    extra_directories: Iterable[str | Path] = (),
) -> str | None:
    """Resolve a managed/external CLI without mutating the process PATH."""
    candidates: list[str | None] = []
    if env_var:
        candidates.append(os.environ.get(env_var))

    candidates.extend([shutil.which(name), shutil.which(f"{name}.exe")])
    base = Path(anchor).resolve() if anchor is not None else None
    if base is not None:
        if base.is_file():
            base = base.parent
        candidates.extend([
            str(base / f"{name}.exe"),
            str(base / name),
            str(base.parent / "_bin" / f"{name}.exe"),
            str(base.parent / "_bin" / name),
            str(base.parent / name / f"{name}.exe"),
            str(base.parent / name / name),
        ])
    for directory in extra_directories:
        candidates.extend([
            str(Path(directory) / f"{name}.exe"),
            str(Path(directory) / name),
        ])

    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def find_ffmpeg(anchor: str | Path | None = None) -> str | None:
    return find_tool("ffmpeg", env_var="FFMPEG_PATH", anchor=anchor)


def find_ffprobe(anchor: str | Path | None = None) -> str | None:
    return find_tool("ffprobe", env_var="FFPROBE_PATH", anchor=anchor)


def probe_media(ffprobe: str, source: str | Path, timeout: int = 30) -> dict | None:
    """Return FFprobe format/stream JSON, or None for any probe failure."""
    try:
        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(source)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout)
        return payload if isinstance(payload, dict) else None
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return None


def run_ffmpeg(
    command: list[str],
    duration_seconds: float,
    stage: str,
    *,
    event_emitter: EventEmitter = emit,
    start_percent: float = 0.0,
    end_percent: float = 100.0,
    inject_progress_args: bool = True,
    completion_stage: str | None = None,
) -> int:
    """Run FFmpeg with bounded diagnostics and normalized NDJSON progress."""
    full_command = [*command]
    if inject_progress_args:
        full_command.extend(["-progress", "pipe:1", "-nostats"])

    process = subprocess.Popen(
        full_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    started = time.monotonic()
    last_percent = -1.0
    error_tail: deque[str] = deque(maxlen=20)
    assert process.stdout is not None
    try:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            match = _TIME_RE.search(line)
            if match and duration_seconds > 0:
                seconds = int(match.group(1)) / 1_000_000.0
                local = max(0.0, min(1.0, seconds / duration_seconds))
                percent = start_percent + (end_percent - start_percent) * local
                if percent - last_percent >= 0.5:
                    last_percent = percent
                    elapsed = time.monotonic() - started
                    eta = elapsed / local - elapsed if local > 0.01 else None
                    event_emitter(
                        "progress",
                        percent=round(percent, 1),
                        stage=stage,
                        eta_seconds=int(eta) if eta and eta < 86400 else None,
                    )
            elif line == "progress=end":
                event_emitter(
                    "progress", percent=round(end_percent, 1),
                    stage=completion_stage or stage, eta_seconds=0,
                )
            elif not line.startswith(_PROGRESS_KEYS):
                error_tail.append(line)
    finally:
        process.stdout.close()
        process.wait()

    if process.returncode != 0:
        for line in error_tail:
            event_emitter("log", level="error", message=line)
    return process.returncode


def safe_extract_path(dest: str | Path, name: str) -> Path:
    """Resolve ``name`` under ``dest``, raising ValueError if it escapes.

    Guards custom archive-extraction loops (e.g. Godot .pck tables) against
    path-traversal ("zip-slip") where a crafted entry name like ``../../x``
    would otherwise write outside the destination directory.
    """
    dest_root = Path(dest).resolve()
    target = (dest_root / name).resolve()
    if target != dest_root and dest_root not in target.parents:
        raise ValueError(f"unsafe archive entry rejected: {name!r}")
    return target


def safe_tar_extractall(tar, dest: str | Path) -> int:
    """Extract a tar archive, rejecting traversal and unsafe link members.

    ``tarfile.extractall`` performs no path validation, so a malicious archive
    can traverse out of ``dest`` or plant absolute/relative symlinks (tar-slip).
    Unlike ``zipfile`` — which strips ``..`` components — tar needs an explicit
    guard. Returns the number of members extracted.
    """
    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    dest_root = dest_path.resolve()
    members = tar.getmembers()
    for member in members:
        target = (dest_root / member.name).resolve()
        if target != dest_root and dest_root not in target.parents:
            raise ValueError(f"unsafe tar entry rejected: {member.name!r}")
        if member.issym() or member.islnk():
            link = (target.parent / member.linkname).resolve()
            if link != dest_root and dest_root not in link.parents:
                raise ValueError(f"unsafe tar link rejected: {member.name!r}")
    tar.extractall(str(dest_path), members=members)
    return len(members)
