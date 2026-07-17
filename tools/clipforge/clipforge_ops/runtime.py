"""Shared runtime adapters for ClipForge operation modules."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_lib"))
from ucx_sidecar import (  # noqa: E402
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
    return shared_find_ffmpeg(Path(__file__).resolve().parent.parent)


def find_ffprobe() -> str | None:
    return shared_find_ffprobe(Path(__file__).resolve().parent.parent)


def probe(ffprobe: str, path: str) -> dict | None:
    return probe_media(ffprobe, path)
