"""Persistent crash log that survives the frozen-build stderr drop.

PyInstaller one-file builds capture ``sys.stderr`` into a handle that is
discarded after process exit — any ``print(..., file=sys.stderr)`` during
shutdown is effectively lost. That's where the most interesting
late-binding warnings live (worker threads that refuse to join, partial
output unlinks, finaliser exceptions), so we need a durable sink.

This module appends short human-readable lines to a file in the OS
user-data directory. Never raises — every operation is wrapped so a
broken filesystem path or ENOSPC can't turn "we wanted to log a warning"
into "we crashed the app harder".

Path selection (first match wins):
    $VERTIGO_CRASH_LOG           explicit override (tests, CI, users)
    %LOCALAPPDATA%\\Vertigo\\crash.log   Windows
    ~/Library/Logs/Vertigo/crash.log     macOS
    $XDG_STATE_HOME/vertigo/crash.log    Linux (XDG base dir spec)
    ~/.local/state/vertigo/crash.log     Linux fallback

PyInstaller's ``_MEIPASS`` staging dir is explicitly never used — it's
read-only in one-file builds and wiped on exit anyway, so logging there
would defeat the whole point.
"""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


_LOCK = threading.Lock()
_MAX_BYTES = 256 * 1024  # cap at 256 KiB — one ring-buffer rotation


def crash_log_path() -> Path:
    """Resolve the platform-appropriate crash log path.

    Honours ``$VERTIGO_CRASH_LOG`` first so tests can pin a tmp path.
    Never returns a path inside the PyInstaller ``_MEIPASS`` staging
    dir — that directory is read-only in one-file builds and wiped on
    exit, so logging there would defeat the whole point.
    """
    candidate = _resolve_candidate()
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and _is_under(candidate, Path(meipass)):
        # User misconfigured an env var to point at the PyInstaller stage
        # — fall back to the home-relative default so we never silently
        # write into a volume that disappears after shutdown.
        return Path.home() / ".vertigo" / "crash.log"
    return candidate


def _resolve_candidate() -> Path:
    """Platform-appropriate crash log path.

    Aligned 1:1 with :func:`vertigo._log_dir` so the bootstrap-layer
    fatal-error log and the runtime breadcrumb log land in the same
    file. Divergence here used to send Linux users to two separate
    files (``vertigo/`` from this module, ``Vertigo/`` from the
    bootstrap) and nobody would ever realise their history was split.
    """
    override = os.environ.get("VERTIGO_CRASH_LOG")
    if override:
        return Path(override)

    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or (Path.home() / "AppData" / "Local")
        )
        return base / "Vertigo" / "crash.log"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "Vertigo" / "crash.log"
    # Linux / other POSIX — follow XDG base-dir spec. Directory is
    # "Vertigo" (capitalised) to match vertigo.py::_log_dir exactly.
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".local" / "state")
    return base / "Vertigo" / "crash.log"


def _is_under(candidate: Path, ancestor: Path) -> bool:
    """Resolve both sides enough to compare without following missing parents."""
    try:
        candidate_abs = candidate.expanduser().resolve(strict=False)
        ancestor_abs = ancestor.expanduser().resolve(strict=False)
    except Exception:
        return False
    try:
        candidate_abs.relative_to(ancestor_abs)
        return True
    except ValueError:
        return False


def _rotate_if_needed(path: Path) -> None:
    """Truncate to tail if the file has grown past the cap.

    A single 256 KiB window is plenty for forensic work; anything older
    than that on a tool this size is noise. Rotation keeps the last
    ``_MAX_BYTES / 2`` so there is always headroom before the next
    rotation fires. Write-rename via ``os.replace`` so a crash between
    read and write can never leave a truncated file.

    All failures are swallowed — a broken rotation must never turn a
    routine append into a crash.
    """
    try:
        if not path.exists():
            return
        size = path.stat().st_size
        if size <= _MAX_BYTES:
            return
        with path.open("rb") as f:
            # Halving is deliberate: keeps 128 KiB so the next rotation
            # doesn't fire on the very next append.
            f.seek(-_MAX_BYTES // 2, os.SEEK_END)
            tail = f.read()
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with tmp.open("wb") as f:
                f.write(b"# crash.log rotated\n")
                f.write(tail)
            os.replace(tmp, path)
        except Exception:
            # Windows AV / tail -f can hold an exclusive handle on the
            # log file, turning os.replace into PermissionError. Clean
            # up the tmp so the orphan doesn't sit between rotations.
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def _temp_fallback() -> Path:
    """Best-effort writable path when the preferred dir fails to mkdir.

    Matches the ``vertigo.py::_log_dir`` escape hatch so a sandboxed
    environment (read-only ``$HOME``, wiped ``$XDG_STATE_HOME``) still
    leaves breadcrumbs somewhere.
    """
    base = Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp")
    return base / "Vertigo-crash.log"


def append(message: str) -> Path | None:
    """Append a single timestamped line to the crash log. Never raises.

    Returns the resolved path on success so tests can inspect it, or
    ``None`` if both the preferred path and the TEMP fallback failed.
    """
    path = crash_log_path()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{stamp} {message}\n"
    for candidate in (path, _temp_fallback()):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with _LOCK:
                _rotate_if_needed(candidate)
                with candidate.open("a", encoding="utf-8") as f:
                    f.write(line)
            return candidate
        except Exception:
            continue
    return None
