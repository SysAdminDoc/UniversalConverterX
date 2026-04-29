"""Download Integrity Verification — post-download ffprobe check (F65).

Verifies that downloaded media files are valid containers with expected
duration. Reports: verified (green), warning (yellow), failed (red).

Usage::

    worker = VerifyWorker(media_path, expected_duration=3600)
    worker.verified.connect(on_result)  # (path, status, details)
    worker.start()
"""

import json
import os
import subprocess

from PyQt6.QtCore import QThread, pyqtSignal

from .paths import _CREATE_NO_WINDOW

# Status constants
STATUS_OK = "verified"
STATUS_WARN = "warning"
STATUS_FAIL = "failed"


def _parse_numeric_probe_value(value, cast):
    try:
        parsed = cast(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed


def verify_media(media_path, expected_duration=0):
    """Verify a media file's integrity via ffprobe.

    Returns ``(status, details)`` where status is one of
    ``STATUS_OK``, ``STATUS_WARN``, ``STATUS_FAIL``.
    """
    if not media_path or not os.path.isfile(media_path):
        return STATUS_FAIL, "File not found"

    file_size = os.path.getsize(media_path)
    if file_size == 0:
        return STATUS_FAIL, "File is empty (0 bytes)"

    # Run ffprobe
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,size,nb_streams",
        "-of", "json",
        media_path,
    ]
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=30,
            creationflags=_CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return STATUS_FAIL, f"ffprobe error: {e}"

    if r.returncode != 0:
        stderr = r.stderr.decode("utf-8", errors="replace")[:200]
        return STATUS_FAIL, f"ffprobe failed: {stderr}"

    try:
        data = json.loads(r.stdout.decode("utf-8", errors="replace"))
        fmt = data.get("format", {})
    except (json.JSONDecodeError, ValueError):
        return STATUS_FAIL, "ffprobe returned invalid JSON"

    actual_duration = _parse_numeric_probe_value(fmt.get("duration", 0), float)
    nb_streams = _parse_numeric_probe_value(fmt.get("nb_streams", 0), int)
    if actual_duration is None or nb_streams is None:
        return STATUS_FAIL, "ffprobe returned invalid numeric metadata"

    # Check for corruption signatures
    if actual_duration <= 0:
        return STATUS_FAIL, "Duration is 0 (corrupted or incomplete)"

    if nb_streams < 1:
        return STATUS_FAIL, "No media streams found"

    # Compare against expected duration (if provided)
    if expected_duration and expected_duration > 0:
        ratio = actual_duration / expected_duration
        if ratio < 0.5:
            return STATUS_FAIL, (
                f"Duration {actual_duration:.0f}s is <50% of expected "
                f"{expected_duration:.0f}s (truncated)"
            )
        if ratio < 0.95:
            return STATUS_WARN, (
                f"Duration {actual_duration:.0f}s is {ratio*100:.0f}% of "
                f"expected {expected_duration:.0f}s (minor discrepancy)"
            )
        if ratio > 1.05:
            return STATUS_WARN, (
                f"Duration {actual_duration:.0f}s exceeds expected "
                f"{expected_duration:.0f}s by {(ratio-1)*100:.0f}%"
            )

    # All checks passed
    return STATUS_OK, (
        f"Valid ({actual_duration:.0f}s, {nb_streams} stream(s), "
        f"{file_size / 1024 / 1024:.1f} MB)"
    )


def verify_recording_dir(recording_dir, expected_duration=0):
    """Verify the first media file in a recording directory.

    Returns ``(status, details, media_path)``.
    """
    if not recording_dir or not os.path.isdir(recording_dir):
        return STATUS_FAIL, "Directory not found", ""

    media = ""
    for fn in sorted(os.listdir(recording_dir)):
        if fn.lower().endswith((".mp4", ".mkv", ".ts", ".webm", ".flv")) and not fn.startswith("."):
            media = os.path.join(recording_dir, fn)
            break

    if not media:
        return STATUS_FAIL, "No media file found", ""

    status, details = verify_media(media, expected_duration)
    return status, details, media


class VerifyWorker(QThread):
    """Run integrity verification in background."""

    verified = pyqtSignal(str, str, str)  # path, status, details

    def __init__(self, media_path, expected_duration=0):
        super().__init__()
        self._path = media_path
        self._expected = expected_duration

    def run(self):
        status, details = verify_media(self._path, self._expected)
        self.verified.emit(self._path, status, details)
