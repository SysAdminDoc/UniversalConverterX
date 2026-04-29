#!/usr/bin/env python3
"""Vertigo v0.12.3 — vertical video studio for short-form creators.

From the Latin *vertere*, "to turn." Turns raw footage of any shape into
polished 9:16 for YouTube Shorts, TikTok, and Instagram Reels.

Turnkey entry: bootstraps dependencies on first run, then launches the GUI.
"""

from __future__ import annotations

# ---------------------------------------------------------------- CRITICAL
# multiprocessing.freeze_support() MUST be the very first thing that runs in
# the entry point of a frozen (PyInstaller) build on Windows. Without it,
# any library that uses Python's multiprocessing module (mediapipe, cv2,
# torch-ish backends) will call sys.executable to spawn a worker — and
# sys.executable is Vertigo.exe itself, causing the whole app to relaunch
# recursively (the "PyInstaller fork bomb"). It is a no-op at first call
# in the parent; it prevents re-execution of main() in each child.
# ----------------------------------------------------------------
import multiprocessing
multiprocessing.freeze_support()

import os
import shutil
import subprocess
import sys
from pathlib import Path

__version__ = "0.12.3"
APP_NAME = "Vertigo"

_REQUIRED = [
    ("PyQt6",        "PyQt6>=6.7.0"),
    ("cv2",          "opencv-python>=4.10.0"),
    ("numpy",        "numpy>=1.26.0"),
    ("PIL",          "Pillow>=10.3.0"),
    ("mediapipe",    "mediapipe>=0.10.14"),
    ("scenedetect",  "scenedetect>=0.6.5"),
    ("scipy",        "scipy>=1.11.0"),
]


def _is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


# ---------------------------------------------------------------- reporting

def _log_dir() -> Path:
    """Writable log directory that survives PyInstaller temp-extract churn."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Logs")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    path = Path(base) / APP_NAME
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        return Path(os.environ.get("TEMP") or "/tmp")
    return path


def _safe_write(stream, text: str) -> None:
    """sys.stderr / sys.stdout are None in Windows GUI PyInstaller builds."""
    if stream is None:
        return
    try:
        stream.write(text)
        stream.flush()
    except Exception:
        pass


def _fatal(title: str, body: str, exit_code: int = 1) -> None:
    """Report a fatal error without ever crashing on stderr=None.

    Writes to %LOCALAPPDATA%\\Vertigo\\crash.log, echoes to stderr when
    available, and pops a native MessageBox on Windows GUI builds so the
    user actually sees the failure. Then exits.
    """
    message = f"[{APP_NAME}] {title}\n{body}\n"

    log_path = _log_dir() / "crash.log"
    try:
        import time
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n---- {time.strftime('%Y-%m-%d %H:%M:%S')} ----\n{message}")
    except Exception:
        log_path = None

    _safe_write(sys.stderr, message)

    if sys.platform == "win32":
        try:
            import ctypes
            MB_ICONERROR = 0x00000010
            suffix = f"\n\nDetails logged to:\n{log_path}" if log_path else ""
            ctypes.windll.user32.MessageBoxW(
                None,
                body + suffix,
                f"{APP_NAME} — {title}",
                MB_ICONERROR,
            )
        except Exception:
            pass

    sys.exit(exit_code)


# ---------------------------------------------------------------- bootstrap

def _pip_install(spec: str) -> bool:
    """Try three install strategies. Return True on success.

    This must never run in a frozen build — sys.executable is the app
    itself, which would recursively relaunch the GUI instead of pip.
    """
    if _is_frozen():
        return False

    bases = [
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", spec],
        [sys.executable, "-m", "pip", "install", "--user", "--disable-pip-version-check", spec],
        [sys.executable, "-m", "pip", "install", "--break-system-packages", "--disable-pip-version-check", spec],
    ]
    for cmd in bases:
        try:
            rc = subprocess.call(cmd)
            if rc == 0:
                return True
        except Exception:
            continue
    return False


def _bootstrap() -> None:
    """Import each required module; pip-install any that's missing.

    In a frozen build we never try to pip-install. If an import fails
    there, the bundle is broken and we surface a clear error (MessageBox
    + crash log) instead of silently relaunching ourselves or dying on
    a None stderr.
    """
    if _is_frozen():
        missing: list[tuple[str, str]] = []
        for mod, _spec in _REQUIRED:
            try:
                __import__(mod)
            except Exception as e:     # catch ImportError AND any init-time crash
                missing.append((mod, f"{type(e).__name__}: {e}"))
        if missing:
            lines = "\n".join(f"  - {mod}: {err}" for mod, err in missing)
            _fatal(
                "bundled import failed",
                (
                    f"The following modules could not be loaded from the bundle:\n\n{lines}\n\n"
                    f"This binary is incomplete. Please download a fresh copy of {APP_NAME}."
                ),
                exit_code=4,
            )
        return

    missing_specs: list[str] = []
    for mod, spec in _REQUIRED:
        try:
            __import__(mod)
        except ImportError:
            missing_specs.append(spec)

    if missing_specs:
        _safe_write(sys.stdout, f"[{APP_NAME}] bootstrapping: {', '.join(missing_specs)}\n")
        for spec in missing_specs:
            if not _pip_install(spec):
                _fatal(
                    "bootstrap failed",
                    f"Could not install: {spec}\nRun manually:\n  pip install {spec}",
                    exit_code=2,
                )
        _safe_write(sys.stdout, f"[{APP_NAME}] bootstrap complete.\n")


def _check_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        _fatal(
            "FFmpeg not found",
            (
                "FFmpeg and ffprobe must be installed and on your PATH.\n\n"
                "Windows:   winget install Gyan.FFmpeg\n"
                "macOS:     brew install ffmpeg\n"
                "Linux:     sudo apt install ffmpeg"
            ),
            exit_code=3,
        )


def _load_saved_theme(QSettings) -> str:
    """Chained fallback: Vertigo → Kiln → ReelForge → 'system'.

    Carries theme preference through every historical project name so
    long-time users keep their chosen appearance across renames.
    """
    for org, app in (("Vertigo", "Vertigo"), ("Kiln", "Kiln"), ("ReelForge", "ReelForge")):
        value = QSettings(org, app).value("theme", None)
        if value is not None:
            return str(value)
    return "system"


# ---------------------------------------------------------------- main

def main() -> int:
    _bootstrap()
    _check_ffmpeg()

    # late imports so bootstrap can install them first
    if not _is_frozen():
        sys.path.insert(0, str(Path(__file__).parent))

    from PyQt6.QtCore import Qt, QSettings
    from PyQt6.QtGui import QFont, QIcon
    from PyQt6.QtWidgets import QApplication

    from ui.assets import icon_path
    from ui.main_window import MainWindow
    from ui.theme import apply_app_theme, sanitize_theme_preference

    if sys.platform == "win32":
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))

    icon = QIcon(str(icon_path()))
    if not icon.isNull():
        app.setWindowIcon(icon)

    theme_pref = sanitize_theme_preference(_load_saved_theme(QSettings))
    apply_app_theme(app, theme_pref)

    win = MainWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()
    return app.exec()


def _entry() -> int:
    """Wrap main() so a late-import / Qt-init crash still surfaces a MessageBox
    instead of silently closing the GUI process."""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException as e:
        import traceback
        _fatal(
            f"startup error ({type(e).__name__})",
            f"{e}\n\n{traceback.format_exc()}",
            exit_code=10,
        )
        return 10


if __name__ == "__main__":
    raise SystemExit(_entry())
