"""Shared paths and platform-specific constants.

Separated from `config` so modules that just need the config directory
don't have to import the whole persistence layer.

Portable mode (F43): if ``portable.txt`` exists next to the main script
or frozen exe, all config/data goes into a ``data/`` subdirectory alongside
the executable instead of ``%APPDATA%\\StreamKeep``.
"""

import os
import sys
import subprocess
from pathlib import Path

# Windows-only: hide console windows that subprocess would otherwise spawn
_CREATE_NO_WINDOW = (
    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
)

# ── Portable mode detection (F43) ──────────────────────────────────
# Check for a ``portable.txt`` marker next to the exe/script.
_exe_dir = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.argv[0] or "."))).resolve()
# For PyInstaller one-file builds, _MEIPASS is a temp dir — use the exe's
# actual location instead.
if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
PORTABLE = (_exe_dir / "portable.txt").is_file()

if PORTABLE:
    CONFIG_DIR = _exe_dir / "data"
else:
    CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "StreamKeep"

CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "streamkeep.log"
LOG_FILE_BACKUP = CONFIG_DIR / "streamkeep.log.1"
LOG_FILE_MAX_BYTES = 2_000_000  # rotate at ~2 MB
CRASH_LOG = CONFIG_DIR / "crash.log"
