"""Asset resolution — finds files in the repo or in a PyInstaller bundle."""

from __future__ import annotations

import sys
from pathlib import Path


def asset_root() -> Path:
    """Directory containing bundled assets (icon, logos, etc.)."""
    if getattr(sys, "frozen", False):
        # PyInstaller --onefile unpacks to sys._MEIPASS; --onedir uses the exe dir.
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for candidate in (base / "assets", base):
            if (candidate / "icon.png").exists():
                return candidate
        return base

    return Path(__file__).resolve().parent.parent / "assets"


def asset(name: str) -> Path:
    return asset_root() / name


def icon_path() -> Path:
    root = asset_root()
    for name in ("icon.ico", "icon.png", "icon_256.png", "icon.svg"):
        p = root / name
        if p.exists():
            return p
    return root / "icon.png"
