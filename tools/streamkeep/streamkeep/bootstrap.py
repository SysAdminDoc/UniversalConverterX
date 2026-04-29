"""Dependency auto-install. Must run before any PyQt6 imports.

Kept as a standalone module so `__main__.py` can call `bootstrap()`
before importing anything that depends on PyQt6.

CRITICAL: `sys.executable` in a PyInstaller-frozen exe is the exe
itself, NOT python. If we called
    subprocess.check_call([sys.executable, "-m", "pip", "install", ...])
from inside StreamKeep.exe, the bootloader would ignore `-m pip` and
just re-run `main()` — which calls `bootstrap()` again — which spawns
another StreamKeep.exe — forever. That's exactly the fork bomb we hit
in v4.12.0 on the shipped exe. `bootstrap()` MUST be a no-op in frozen
mode; dependencies are expected to be bundled at build time.
"""

import sys
import subprocess


def _is_frozen():
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def bootstrap():
    """Auto-install dependencies on first run (source-checkout only)."""
    # In a PyInstaller/Nuitka/cx_Freeze exe, all deps are baked in. Any
    # ImportError at this point is a build-time bug and must NOT trigger
    # a pip install — see the module docstring for the history here.
    if _is_frozen():
        return

    required = {"PyQt6": "PyQt6"}
    # yt_dlp is genuinely optional (used as an external CLI via subprocess
    # elsewhere, not as a Python import). playwright is an optional page
    # scraper. `deno` was a bogus entry — the user-space tool is a native
    # binary, not a pip package — and attempting to install it was one of
    # the fork-bomb triggers. send2trash powers storage-manager + retention
    # recycle-bin deletion; optional so the app still launches without it
    # (features degrade to a warning, never silent permanent delete).
    optional = {
        "yt_dlp": "yt-dlp",
        "playwright": "playwright",
        "send2trash": "send2trash",
        # Live Kick chat rides on Pusher WebSocket — degrades gracefully
        # to "not supported" when missing, so it's optional, not required.
        "websocket": "websocket-client",
    }
    import importlib

    for mod, pkg in required.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            for cmd in (
                [sys.executable, "-m", "pip", "install", pkg],
                [sys.executable, "-m", "pip", "install", "--user", pkg],
                [sys.executable, "-m", "pip", "install", "--break-system-packages", pkg],
            ):
                try:
                    subprocess.check_call(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    break
                except Exception:
                    continue

    for mod, pkg in optional.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass  # optional deps — graceful fallback
