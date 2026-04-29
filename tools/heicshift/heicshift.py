#!/usr/bin/env python3
"""
HEICShift v2.8.0 - High-performance universal image batch converter
Scans directories recursively and converts JPEG, PNG, HEIC, AVIF, WebP,
JPEG XL, RAW, TIFF, BMP, JPEG 2000, QOI, and ICO files to JPEG, PNG,
WebP, AVIF, or TIFF. Auto-detects optimal format: PNG for images with
transparency, JPEG for photos. Preserves EXIF metadata, ICC color
profiles, and XMP data. Supports CLI mode for headless/scripted operation.
"""

import sys, os, subprocess, importlib, platform, ctypes, argparse, shutil


# codex-branding:start
def _branding_icon_path() -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "icon.png")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "icon.png")
    current = Path(__file__).resolve()
    candidates.extend([current.parent / "icon.png", current.parent.parent / "icon.png", current.parent.parent.parent / "icon.png"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("icon.png")
# codex-branding:end


APP_VERSION = "2.8.0"

def _bootstrap():
    """Auto-install dependencies before imports."""
    required = {
        "PIL": "Pillow",
        "pillow_heif": "pillow-heif",
        "PyQt6": "PyQt6",
    }
    for module, package in required.items():
        try:
            importlib.import_module(module)
        except ImportError:
            for cmd_extra in [[], ["--user"], ["--break-system-packages"]]:
                try:
                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", package, "-q"] + cmd_extra,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    break
                except subprocess.CalledProcessError:
                    continue

    # Optional deps — best-effort install, graceful fallback
    optional = {
        "rawpy": "rawpy",
        "pillow_jxl": "pillow-jxl-plugin",
        "qoi": "qoi",
    }
    for module, package in optional.items():
        try:
            importlib.import_module(module)
        except ImportError:
            for cmd_extra in [[], ["--user"], ["--break-system-packages"]]:
                try:
                    subprocess.check_call(
                        [sys.executable, "-m", "pip", "install", package, "-q"] + cmd_extra,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    break
                except subprocess.CalledProcessError:
                    continue

_bootstrap()

import io
import time
import json
import traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageCms, ImageOps
import pillow_heif
from pillow_heif import register_heif_opener

register_heif_opener()

# Optional: JPEG XL plugin (registers into Pillow automatically on import)
HAS_JXL = False
try:
    import pillow_jxl  # noqa: F401
    HAS_JXL = True
except ImportError:
    pass

# Optional: RAW format support via rawpy (wraps libraw)
HAS_RAWPY = False
try:
    import rawpy
    HAS_RAWPY = True
except ImportError:
    pass

# Optional: QOI format support
HAS_QOI = False
try:
    import qoi as qoi_lib
    HAS_QOI = True
except ImportError:
    pass

from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSettings, QSize, QUrl,
)
from PyQt6.QtGui import (, QIcon
    QFont, QColor, QPalette, QIcon, QPixmap, QPainter, QAction,
    QDragEnterEvent, QDropEvent,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QComboBox, QSpinBox, QSlider,
    QProgressBar, QPlainTextEdit, QCheckBox, QGroupBox, QGridLayout,
    QFrame, QSplitter, QStatusBar, QMessageBox, QLineEdit, QStyle,
    QSystemTrayIcon, QMenu, QToolButton, QScrollArea,
)

# ── Catppuccin Mocha Palette ──────────────────────────────────────────────────
CAT = {
    "base":      "#1e1e2e", "mantle":   "#181825", "crust":    "#11111b",
    "surface0":  "#313244", "surface1": "#45475a", "surface2": "#585b70",
    "overlay0":  "#6c7086", "overlay1": "#7f849c",
    "text":      "#cdd6f4", "subtext0": "#a6adc8", "subtext1": "#bac2de",
    "lavender":  "#b4befe", "blue":     "#89b4fa", "sapphire": "#74c7ec",
    "sky":       "#89dceb", "teal":     "#94e2d5", "green":    "#a6e3a1",
    "yellow":    "#f9e2af", "peach":    "#fab387", "maroon":   "#eba0ac",
    "red":       "#f38ba8", "mauve":    "#cba6f7", "pink":     "#f5c2e7",
    "flamingo":  "#f2cdcd", "rosewater":"#f5e0dc",
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {CAT['base']};
    color: {CAT['text']};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QGroupBox {{
    background-color: {CAT['mantle']};
    border: 1px solid {CAT['surface1']};
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    font-size: 13px;
    color: {CAT['lavender']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 2px 10px;
    background-color: {CAT['mantle']};
    border-radius: 4px;
}}
QPushButton {{
    background-color: {CAT['surface0']};
    color: {CAT['text']};
    border: 1px solid {CAT['surface1']};
    border-radius: 6px;
    padding: 7px 18px;
    font-weight: 500;
    min-height: 20px;
}}
QPushButton:hover {{
    background-color: {CAT['surface1']};
    border-color: {CAT['lavender']};
}}
QPushButton:pressed {{
    background-color: {CAT['surface2']};
}}
QPushButton:disabled {{
    background-color: {CAT['crust']};
    color: {CAT['overlay0']};
    border-color: {CAT['surface0']};
}}
QPushButton#primaryBtn {{
    background-color: {CAT['blue']};
    color: {CAT['crust']};
    border: none;
    font-weight: 700;
    font-size: 14px;
    padding: 10px 28px;
}}
QPushButton#primaryBtn:hover {{
    background-color: {CAT['lavender']};
}}
QPushButton#primaryBtn:disabled {{
    background-color: {CAT['surface1']};
    color: {CAT['overlay0']};
}}
QPushButton#stopBtn {{
    background-color: {CAT['red']};
    color: {CAT['crust']};
    border: none;
    font-weight: 700;
}}
QPushButton#stopBtn:hover {{
    background-color: {CAT['maroon']};
}}
QLineEdit {{
    background-color: {CAT['surface0']};
    color: {CAT['text']};
    border: 1px solid {CAT['surface1']};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {CAT['blue']};
}}
QLineEdit:focus {{
    border-color: {CAT['lavender']};
}}
QComboBox {{
    background-color: {CAT['surface0']};
    color: {CAT['text']};
    border: 1px solid {CAT['surface1']};
    border-radius: 6px;
    padding: 6px 10px;
    min-width: 120px;
}}
QComboBox:hover {{
    border-color: {CAT['lavender']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {CAT['surface0']};
    color: {CAT['text']};
    border: 1px solid {CAT['surface1']};
    selection-background-color: {CAT['surface1']};
    selection-color: {CAT['lavender']};
}}
QSpinBox {{
    background-color: {CAT['surface0']};
    color: {CAT['text']};
    border: 1px solid {CAT['surface1']};
    border-radius: 6px;
    padding: 4px 8px;
}}
QSlider::groove:horizontal {{
    background: {CAT['surface0']};
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {CAT['lavender']};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background: {CAT['blue']};
    border-radius: 3px;
}}
QProgressBar {{
    background-color: {CAT['surface0']};
    border: 1px solid {CAT['surface1']};
    border-radius: 6px;
    text-align: center;
    color: {CAT['text']};
    font-weight: 600;
    min-height: 22px;
}}
QProgressBar::chunk {{
    background-color: {CAT['green']};
    border-radius: 5px;
}}
QPlainTextEdit {{
    background-color: {CAT['crust']};
    color: {CAT['subtext0']};
    border: 1px solid {CAT['surface0']};
    border-radius: 6px;
    padding: 8px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    selection-background-color: {CAT['surface1']};
}}
QCheckBox {{
    spacing: 8px;
    color: {CAT['text']};
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid {CAT['surface2']};
    background-color: {CAT['surface0']};
}}
QCheckBox::indicator:checked {{
    background-color: {CAT['blue']};
    border-color: {CAT['blue']};
}}
QLabel#dimLabel {{
    color: {CAT['overlay1']};
    font-size: 12px;
}}
QLabel#statValue {{
    color: {CAT['green']};
    font-size: 22px;
    font-weight: 700;
}}
QLabel#statLabel {{
    color: {CAT['overlay1']};
    font-size: 11px;
}}
QStatusBar {{
    background-color: {CAT['mantle']};
    color: {CAT['subtext0']};
    border-top: 1px solid {CAT['surface0']};
    font-size: 12px;
}}
QFrame#separator {{
    background-color: {CAT['surface1']};
    max-height: 1px;
}}
QScrollBar:vertical {{
    background: {CAT['mantle']};
    width: 10px;
    margin: 0;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {CAT['surface2']};
    min-height: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical:hover {{
    background: {CAT['overlay0']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background: {CAT['mantle']};
    height: 10px;
    margin: 0;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    background: {CAT['surface2']};
    min-width: 30px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {CAT['overlay0']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}
QToolButton {{
    background-color: {CAT['surface0']};
    color: {CAT['text']};
    border: 1px solid {CAT['surface1']};
    border-radius: 6px;
    padding: 6px;
}}
QToolButton:hover {{
    background-color: {CAT['surface1']};
    border-color: {CAT['lavender']};
}}
QToolButton::menu-indicator {{
    image: none;
}}
QMenu {{
    background-color: {CAT['surface0']};
    color: {CAT['text']};
    border: 1px solid {CAT['surface1']};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {CAT['surface1']};
    color: {CAT['lavender']};
}}
"""


# ── Supported Input Formats ───────────────────────────────────────────────────

# Always available (pillow-heif plugin)
HEIC_EXTS = {".heic", ".heif", ".hif"}
AVIF_EXTS = {".avif"}

# Always available (Pillow built-in)
JPEG_EXTS  = {".jpg", ".jpeg", ".jpe", ".jfif"}
PNG_EXTS   = {".png"}
WEBP_EXTS  = {".webp"}
TIFF_EXTS  = {".tif", ".tiff"}
BMP_EXTS   = {".bmp"}
JP2_EXTS   = {".jp2", ".j2k", ".jpx"}
ICO_EXTS   = {".ico", ".cur"}

# Conditional on optional deps
JXL_EXTS = {".jxl"}
RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf"}
QOI_EXTS = {".qoi"}

# Family name -> (extension set, availability flag)
FORMAT_FAMILIES = {
    "JPEG":        (JPEG_EXTS, True),
    "PNG":         (PNG_EXTS, True),
    "HEIC/HEIF":   (HEIC_EXTS, True),
    "AVIF":        (AVIF_EXTS, True),
    "WebP":        (WEBP_EXTS, True),
    "TIFF":        (TIFF_EXTS, True),
    "BMP":         (BMP_EXTS, True),
    "JPEG 2000":   (JP2_EXTS, True),
    "ICO/CUR":     (ICO_EXTS, True),
    "JPEG XL":     (JXL_EXTS, HAS_JXL),
    "Camera RAW":  (RAW_EXTS, HAS_RAWPY),
    "QOI":         (QOI_EXTS, HAS_QOI),
}


def get_supported_extensions() -> set[str]:
    """Return all input extensions we can currently decode."""
    exts = JPEG_EXTS | PNG_EXTS | HEIC_EXTS | AVIF_EXTS | WEBP_EXTS | TIFF_EXTS | BMP_EXTS | JP2_EXTS | ICO_EXTS
    if HAS_JXL:
        exts |= JXL_EXTS
    if HAS_RAWPY:
        exts |= RAW_EXTS
    if HAS_QOI:
        exts |= QOI_EXTS
    return exts


def get_format_support_summary() -> str:
    """Human-readable list of supported format families."""
    families = ["JPEG", "PNG", "HEIC/HEIF", "AVIF", "WebP", "TIFF", "BMP", "JPEG 2000", "ICO/CUR"]
    if HAS_JXL:
        families.append("JPEG XL")
    if HAS_RAWPY:
        families.append("Camera RAW")
    if HAS_QOI:
        families.append("QOI")
    return ", ".join(families)


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class ConvertResult:
    src: Path
    dst: Path | None = None
    success: bool = False
    skipped: bool = False
    error: str = ""
    size_before: int = 0
    size_after: int = 0
    elapsed: float = 0.0
    src_deleted: bool = False
    warnings: list[str] = field(default_factory=list)

@dataclass
class ScanResult:
    files: list[Path] = field(default_factory=list)
    total_size: int = 0
    elapsed: float = 0.0


# ── Conversion Engine ─────────────────────────────────────────────────────────

def scan_directory(root: Path, recursive: bool = True, extensions: set[str] | None = None, on_progress=None) -> ScanResult:
    """Find all supported image files in directory."""
    t0 = time.perf_counter()
    supported = extensions or get_supported_extensions()
    result = ScanResult()
    pattern = "**/*" if recursive else "*"
    current_dir = None
    dir_count = 0
    for p in root.glob(pattern):
        if p.is_file() and p.suffix.lower() in supported:
            result.files.append(p)
            result.total_size += p.stat().st_size
            if p.parent != current_dir:
                if on_progress and current_dir is not None:
                    on_progress(len(result.files), result.total_size, str(current_dir), dir_count)
                current_dir = p.parent
                dir_count = 1
            else:
                dir_count += 1
    if on_progress and current_dir is not None:
        on_progress(len(result.files), result.total_size, str(current_dir), dir_count)
    result.files.sort()
    result.elapsed = time.perf_counter() - t0
    return result


def has_transparency(img: Image.Image) -> bool:
    """Check if image has actual transparency data."""
    if img.mode in ("RGBA", "LA", "PA"):
        alpha = img.getchannel("A")
        extrema = alpha.getextrema()
        return extrema[0] < 255  # has non-opaque pixels
    return False


def _open_image(src: Path) -> tuple[Image.Image, dict]:
    """Open an image file, routing to the correct decoder.

    Returns (PIL Image, metadata_dict).
    metadata_dict contains 'exif', 'icc_profile', 'xmp' when available.
    """
    suffix = src.suffix.lower()
    meta = {}

    if suffix in RAW_EXTS and HAS_RAWPY:
        raw = rawpy.imread(str(src))
        rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
        raw.close()
        img = Image.fromarray(rgb)
        # RAW files don't carry EXIF through rawpy — metadata not available
        return img, meta

    if suffix in QOI_EXTS and HAS_QOI:
        arr = qoi_lib.read(str(src))
        img = Image.fromarray(arr)
        return img, meta

    # Everything else goes through Pillow (+ plugins: pillow-heif, pillow-jxl)
    img = Image.open(str(src))

    # Extract metadata from Pillow's info dict
    if exif := img.info.get("exif"):
        meta["exif"] = exif
    if icc := img.info.get("icc_profile"):
        meta["icc_profile"] = icc
    if xmp := img.info.get("xmp"):
        meta["xmp"] = xmp

    return img, meta


def convert_file(
    src: Path,
    output_dir: Path,
    fmt: str = "auto",
    jpeg_quality: int = 92,
    preserve_metadata: bool = True,
    preserve_structure: bool = False,
    base_dir: Path | None = None,
    in_place: bool = False,
    skip_existing: bool = False,
    resize_mode: str = "none",
    resize_value: int = 1920,
    prefix: str = "",
    suffix: str = "",
    lossless_webp: bool = False,
    progressive_jpeg: bool = False,
    chroma_subsampling: bool = False,
    convert_to_srgb: bool = False,
    tiff_compression: str = "none",
    png_compress_level: int = 6,
) -> ConvertResult:
    """Convert a single image file. Thread-safe."""
    t0 = time.perf_counter()
    result = ConvertResult(src=src, size_before=src.stat().st_size)
    img = None
    out_path = None
    temp_path = None

    try:
        img, meta = _open_image(src)

        # Warn when RAW files have no metadata to preserve
        if src.suffix.lower() in RAW_EXTS and not meta:
            result.warnings.append("RAW file: no EXIF/ICC metadata available after demosaic")

        # EXIF auto-rotate — apply orientation and strip the tag
        rotated = ImageOps.exif_transpose(img)
        if rotated is not None:
            img = rotated
            # Refresh EXIF from the transposed image (orientation tag removed)
            if "exif" in img.info:
                meta["exif"] = img.info["exif"]

        # sRGB color space conversion
        if convert_to_srgb and "icc_profile" in meta:
            try:
                src_profile = ImageCms.ImageCmsProfile(io.BytesIO(meta["icc_profile"]))
                dst_profile = ImageCms.createProfile("sRGB")
                img = ImageCms.profileToProfile(img, src_profile, dst_profile, outputMode="RGB")
                # Update ICC profile in metadata to sRGB
                srgb_profile = ImageCms.ImageCmsProfile(dst_profile)
                meta["icc_profile"] = srgb_profile.tobytes()
            except Exception as e:
                result.warnings.append(f"sRGB conversion failed: {e}")

        # Resize if requested
        if resize_mode == "max_dim" and resize_value > 0:
            w, h = img.size
            if max(w, h) > resize_value:
                if w >= h:
                    new_w = resize_value
                    new_h = max(1, int(h * (resize_value / w)))
                else:
                    new_h = resize_value
                    new_w = max(1, int(w * (resize_value / h)))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            else:
                result.warnings.append(f"Already smaller than {resize_value}px ({w}x{h}), resize skipped")
        elif resize_mode == "scale" and resize_value != 100:
            w, h = img.size
            factor = resize_value / 100
            new_w = max(1, int(w * factor))
            new_h = max(1, int(h * factor))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # Determine output format
        if fmt == "auto":
            out_fmt = "PNG" if has_transparency(img) else "JPEG"
        elif fmt == "jpeg":
            out_fmt = "JPEG"
        elif fmt == "png":
            out_fmt = "PNG"
        elif fmt == "webp":
            out_fmt = "WEBP"
        elif fmt == "tiff":
            out_fmt = "TIFF"
        elif fmt == "avif":
            out_fmt = "AVIF"
        elif fmt == "jxl":
            if not HAS_JXL:
                raise RuntimeError("JPEG XL output requires pillow-jxl-plugin (pip install pillow-jxl-plugin)")
            out_fmt = "JXL"
        else:
            out_fmt = "JPEG"

        # Same-format guard — skip if input is already the output format
        # and no processing (resize, sRGB, strip metadata) is requested
        src_ext = src.suffix.lower()
        same_fmt = (
            (out_fmt == "JPEG" and src_ext in JPEG_EXTS)
            or (out_fmt == "PNG" and src_ext in PNG_EXTS)
            or (out_fmt == "WEBP" and src_ext in WEBP_EXTS)
            or (out_fmt == "AVIF" and src_ext in AVIF_EXTS)
            or (out_fmt == "TIFF" and src_ext in TIFF_EXTS)
            or (out_fmt == "JXL" and src_ext in JXL_EXTS)
        )
        no_processing = (
            resize_mode == "none"
            and not convert_to_srgb
            and preserve_metadata
        )
        if same_fmt and no_processing:
            result.skipped = True
            result.warnings.append(f"Skipped: already {out_fmt} and no processing requested")
            result.elapsed = time.perf_counter() - t0
            return result

        ext_map = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "AVIF": ".avif", "TIFF": ".tiff", "JXL": ".jxl"}
        ext = ext_map.get(out_fmt, ".jpg")

        # Build output path — in-place writes next to the source file
        if in_place:
            dest_dir = src.parent
        elif preserve_structure and base_dir:
            rel = src.parent.relative_to(base_dir)
            dest_dir = output_dir / rel
        else:
            dest_dir = output_dir

        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = prefix + src.stem + suffix
        out_path = dest_dir / (stem + ext)

        # Skip if output already exists
        if skip_existing and out_path.exists():
            result.skipped = True
            result.dst = out_path
            result.size_after = out_path.stat().st_size
            result.elapsed = time.perf_counter() - t0
            return result

        # Handle name collisions
        counter = 1
        while out_path.exists():
            out_path = dest_dir / f"{stem}_{counter}{ext}"
            counter += 1

        # Gather metadata
        save_kwargs = {}
        if preserve_metadata and meta:
            if "exif" in meta:
                save_kwargs["exif"] = meta["exif"]
            if "icc_profile" in meta:
                save_kwargs["icc_profile"] = meta["icc_profile"]
            if "xmp" in meta and out_fmt in ("JPEG", "WEBP", "TIFF", "AVIF", "JXL"):
                save_kwargs["xmp"] = meta["xmp"]

        # Format-specific options
        if out_fmt == "JPEG":
            if img.mode in ("RGBA", "LA", "PA", "P"):
                img = img.convert("RGB")
            save_kwargs["quality"] = jpeg_quality
            save_kwargs["subsampling"] = 2 if chroma_subsampling else 0
            save_kwargs["optimize"] = True
            if progressive_jpeg:
                save_kwargs["progressive"] = True
        elif out_fmt == "PNG":
            save_kwargs["optimize"] = True
            save_kwargs["compress_level"] = png_compress_level
        elif out_fmt == "WEBP":
            if lossless_webp:
                save_kwargs["lossless"] = True
            else:
                save_kwargs["quality"] = jpeg_quality
            save_kwargs["method"] = 4
        elif out_fmt == "TIFF":
            if tiff_compression == "lzw":
                save_kwargs["compression"] = "tiff_lzw"
            elif tiff_compression == "deflate":
                save_kwargs["compression"] = "tiff_deflate"
        elif out_fmt == "AVIF":
            save_kwargs["quality"] = jpeg_quality
            save_kwargs["speed"] = 6
        elif out_fmt == "JXL":
            save_kwargs["quality"] = jpeg_quality
            save_kwargs["effort"] = 7

        # Atomic write: use temp file for in-place mode
        if in_place:
            temp_path = out_path.parent / (out_path.name + ".heicshift.tmp")
            img.save(str(temp_path), out_fmt, **save_kwargs)
        else:
            img.save(str(out_path), out_fmt, **save_kwargs)

        # Validate output file integrity
        check_path = temp_path if in_place else out_path
        if not check_path.exists() or check_path.stat().st_size == 0:
            raise RuntimeError(f"Output file missing or empty: {check_path.name}")
        try:
            with Image.open(str(check_path)) as verify_img:
                verify_img.verify()
        except Exception as ve:
            raise RuntimeError(f"Output validation failed: {ve}")

        # Atomic rename for in-place mode
        if in_place:
            os.replace(str(temp_path), str(out_path))
            temp_path = None  # Rename succeeded, no temp to clean

        result.dst = out_path
        result.size_after = out_path.stat().st_size
        result.success = True

        # In-place mode: delete the original after successful conversion
        if in_place and result.success:
            src.unlink()
            result.src_deleted = True

    except Exception as e:
        result.error = str(e)
        # Clean up temp file on failure
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        # Clean up partial output on failure
        if out_path and out_path.exists() and not result.success:
            try:
                out_path.unlink()
            except OSError:
                pass
    finally:
        if img is not None:
            try:
                img.close()
            except Exception:
                pass

    result.elapsed = time.perf_counter() - t0
    return result


# ── Worker Threads ───────────────────────────────────────────────────────────

class ConvertWorker(QThread):
    progress = pyqtSignal(int, int)       # current, total
    current_file = pyqtSignal(str)        # filename currently processing
    file_done = pyqtSignal(object)        # ConvertResult
    finished_all = pyqtSignal(list)        # list[ConvertResult]
    log = pyqtSignal(str)

    def __init__(self, files, output_dir, fmt, quality, preserve_meta,
                 preserve_structure, base_dir, workers, in_place=False,
                 skip_existing=False, resize_mode="none", resize_value=1920,
                 prefix="", suffix="", lossless_webp=False,
                 progressive_jpeg=False, chroma_subsampling=False,
                 convert_to_srgb=False, tiff_compression="none",
                 png_compress_level=6):
        super().__init__()
        self.files = files
        self.output_dir = Path(output_dir)
        self.fmt = fmt
        self.quality = quality
        self.preserve_meta = preserve_meta
        self.preserve_structure = preserve_structure
        self.base_dir = base_dir
        self.workers = workers
        self.in_place = in_place
        self.skip_existing = skip_existing
        self.resize_mode = resize_mode
        self.resize_value = resize_value
        self.prefix = prefix
        self.suffix = suffix
        self.lossless_webp = lossless_webp
        self.progressive_jpeg = progressive_jpeg
        self.chroma_subsampling = chroma_subsampling
        self.convert_to_srgb = convert_to_srgb
        self.tiff_compression = tiff_compression
        self.png_compress_level = png_compress_level
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        results = []
        total = len(self.files)
        done = 0

        self.log.emit(f"Starting conversion of {total} files with {self.workers} workers...")

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {}
            for f in self.files:
                if self._stop:
                    break
                fut = pool.submit(
                    convert_file, f, self.output_dir, self.fmt,
                    self.quality, self.preserve_meta,
                    self.preserve_structure, self.base_dir,
                    self.in_place, self.skip_existing,
                    self.resize_mode, self.resize_value,
                    self.prefix, self.suffix,
                    self.lossless_webp, self.progressive_jpeg,
                    self.chroma_subsampling, self.convert_to_srgb,
                    self.tiff_compression, self.png_compress_level,
                )
                futures[fut] = f

            for fut in as_completed(futures):
                if self._stop:
                    pool.shutdown(wait=False, cancel_futures=True)
                    self.log.emit("Conversion cancelled by user.")
                    break

                result = fut.result()
                results.append(result)
                done += 1
                self.progress.emit(done, total)
                self.current_file.emit(result.src.name)
                self.file_done.emit(result)

                if result.skipped:
                    self.log.emit(f"[SKIP] {result.src.name} — output already exists")
                elif result.success:
                    saved = result.size_before - result.size_after
                    pct = (saved / result.size_before * 100) if result.size_before else 0
                    deleted_tag = "  [source deleted]" if result.src_deleted else ""
                    self.log.emit(
                        f"[OK] {result.src.name} -> {result.dst.name}  "
                        f"({_fmt_size(result.size_before)} -> {_fmt_size(result.size_after)}, "
                        f"{pct:+.1f}%)  [{result.elapsed:.2f}s]{deleted_tag}"
                    )
                else:
                    self.log.emit(f"[FAIL] {result.src.name}: {result.error}")

                for warn in result.warnings:
                    self.log.emit(f"[WARN] {result.src.name}: {warn}")

        self.finished_all.emit(results)


class ScanWorker(QThread):
    finished = pyqtSignal(object)  # ScanResult
    log = pyqtSignal(str)
    scan_progress = pyqtSignal(int, int, str, int)  # total_count, total_bytes, dir_path, dir_file_count

    def __init__(self, directory, recursive, extensions=None):
        super().__init__()
        self.directory = Path(directory)
        self.recursive = recursive
        self.extensions = extensions

    def run(self):
        self.log.emit(f"Scanning {'recursively' if self.recursive else ''}: {self.directory}")
        result = scan_directory(
            self.directory, self.recursive, self.extensions,
            on_progress=lambda count, size, d, dc: self.scan_progress.emit(count, size, d, dc),
        )
        self.log.emit(
            f"Found {len(result.files)} supported files "
            f"({_fmt_size(result.total_size)}) in {result.elapsed:.2f}s"
        )
        self.finished.emit(result)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _fmt_eta(seconds: float) -> str:
    """Format seconds as human-readable ETA string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def _open_path(path: str):
    """Open a file/folder in the native file manager (cross-platform)."""
    if platform.system() == "Windows":
        os.startfile(path)
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _create_app_icon() -> QIcon:
    """Create a simple app icon programmatically."""
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(CAT["blue"]))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QColor(CAT["crust"]))
    f = QFont("Segoe UI", 30, QFont.Weight.Bold)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "H")
    p.end()
    return QIcon(pm)


# ── Conversion Presets ────────────────────────────────────────────────────────

PRESETS = {
    "Web Optimized": {
        "fmt": 1,              # JPEG
        "quality": 80,
        "progressive_jpeg": True,
        "chroma_subsampling": True,
        "convert_to_srgb": True,
        "resize_enabled": True,
        "resize_mode": 0,      # Max Dimension
        "resize_value": 1920,
    },
    "Archive Quality": {
        "fmt": 2,              # PNG
        "quality": 92,
        "png_compress_level": 6,
        "resize_enabled": False,
    },
    "Mobile Friendly": {
        "fmt": 3,              # WebP
        "quality": 75,
        "convert_to_srgb": True,
        "resize_enabled": True,
        "resize_mode": 0,      # Max Dimension
        "resize_value": 1080,
    },
    "Print / TIFF": {
        "fmt": 5,              # TIFF
        "tiff_compression": 1, # LZW
        "resize_enabled": False,
    },
}


# ── Disk Space Estimation ─────────────────────────────────────────────────────

SIZE_ESTIMATE_FACTORS = {"jpeg": 0.8, "auto": 0.8, "png": 1.2, "webp": 0.7, "avif": 0.5, "tiff": 1.5, "jxl": 0.45}


def _estimate_output_size(total_input_bytes: int, fmt: str) -> int:
    """Estimate total output size based on format and input size."""
    factor = SIZE_ESTIMATE_FACTORS.get(fmt, 1.0)
    return int(total_input_bytes * factor)


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"HEICShift v{APP_VERSION}")
        self.setMinimumSize(700, 520)
        self.resize(900, 800)
        self.setAcceptDrops(True)

        self._icon = _create_app_icon()
        self.setWindowIcon(self._icon)

        self.settings = QSettings("HEICShift", "HEICShift")
        self._scan_result: ScanResult | None = None
        self._worker: ConvertWorker | None = None
        self._results: list[ConvertResult] = []
        self._convert_start_time: float = 0.0
        self._last_ok_dst: Path | None = None

        # System tray for completion notifications
        self._tray = QSystemTrayIcon(self._icon, self)

        self._build_ui()
        self._apply_dark_titlebar()
        self._restore_state()
        self._log_startup()

    def _log_startup(self):
        """Log supported formats, dependency versions, and optional dep status on launch."""
        self._log(f"HEICShift v{APP_VERSION}")
        # Core dependency versions
        from PIL import __version__ as pil_ver
        from PyQt6.QtCore import PYQT_VERSION_STR
        heif_ver = getattr(pillow_heif, "__version__", "unknown")
        self._log(f"Pillow {pil_ver}, pillow-heif {heif_ver}, PyQt6 {PYQT_VERSION_STR}")
        # Optional dependency versions
        opt_vers = []
        if HAS_RAWPY:
            opt_vers.append(f"rawpy {getattr(rawpy, '__version__', '?')}")
        if HAS_JXL:
            opt_vers.append(f"pillow-jxl {getattr(pillow_jxl, '__version__', '?')}")
        if HAS_QOI:
            opt_vers.append(f"qoi {getattr(qoi_lib, '__version__', '?')}")
        if opt_vers:
            self._log(f"Optional: {', '.join(opt_vers)}")
        self._log(f"Supported input formats: {get_format_support_summary()}")
        missing = []
        if not HAS_JXL:
            missing.append("JPEG XL (pip install pillow-jxl-plugin)")
        if not HAS_RAWPY:
            missing.append("Camera RAW (pip install rawpy)")
        if not HAS_QOI:
            missing.append("QOI (pip install qoi)")
        if missing:
            self._log(f"Optional formats unavailable: {', '.join(missing)}")
        exts = sorted(get_supported_extensions())
        self._log(f"Scanning for: {' '.join(exts)}")
        self._log("")

    def _update_title(self, state: str = "base", **kwargs):
        """Update window title bar with contextual info."""
        base = f"HEICShift v{APP_VERSION}"
        if state == "scanned":
            count = kwargs.get("count", 0)
            self.setWindowTitle(f"{base} -- {count} files")
        elif state == "converting":
            current = kwargs.get("current", 0)
            total = kwargs.get("total", 0)
            self.setWindowTitle(f"{base} -- Converting {current}/{total}")
        elif state == "done":
            ok = kwargs.get("ok", 0)
            fail = kwargs.get("fail", 0)
            self.setWindowTitle(f"{base} -- Done ({ok} converted, {fail} failed)")
        else:
            self.setWindowTitle(base)

    def _apply_dark_titlebar(self):
        """Apply dark title bar on Windows 10 19041+ / Windows 11."""
        if platform.system() != "Windows":
            return
        try:
            hwnd = int(self.winId())
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
            )
        except Exception:
            pass

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(10)

        # ── Scroll area for controls ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)
        scroll.setWidget(scroll_widget)

        # ── Header ──
        hdr = QHBoxLayout()
        title = QLabel("HEICShift")
        title.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {CAT['lavender']};")
        ver = QLabel(f"v{APP_VERSION}")
        ver.setStyleSheet(f"color: {CAT['overlay0']}; font-size: 12px; margin-left: 6px;")
        hdr.addWidget(title)
        hdr.addWidget(ver)
        hdr.addStretch()
        desc = QLabel("Universal image batch converter with metadata preservation")
        desc.setObjectName("dimLabel")
        hdr.addWidget(desc)
        scroll_layout.addLayout(hdr)

        # ── Source / Output ──
        io_group = QGroupBox("Directories")
        io_grid = QGridLayout(io_group)
        io_grid.setColumnStretch(1, 1)

        io_grid.addWidget(QLabel("Source:"), 0, 0)
        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText("Select or drag & drop a directory containing image files...")
        io_grid.addWidget(self.src_edit, 0, 1)
        self.src_btn = QPushButton("Browse")
        self.src_btn.clicked.connect(self._browse_source)
        io_grid.addWidget(self.src_btn, 0, 2)

        self.recent_btn = QToolButton()
        self.recent_btn.setText("▾")
        self.recent_btn.setMinimumWidth(28)
        self.recent_btn.setToolTip("Recent directories")
        self._recent_menu = QMenu(self)
        self.recent_btn.setMenu(self._recent_menu)
        self.recent_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._recent_menu.aboutToShow.connect(self._populate_recent_menu)
        io_grid.addWidget(self.recent_btn, 0, 3)

        io_grid.addWidget(QLabel("Output:"), 1, 0)
        self.dst_edit = QLineEdit()
        self.dst_edit.setPlaceholderText("Converted files go here (default: source/converted)")
        io_grid.addWidget(self.dst_edit, 1, 1)
        self.dst_btn = QPushButton("Browse")
        self.dst_btn.clicked.connect(self._browse_output)
        io_grid.addWidget(self.dst_btn, 1, 2)

        self.recursive_chk = QCheckBox("Scan subdirectories")
        self.recursive_chk.setChecked(True)
        io_grid.addWidget(self.recursive_chk, 2, 1)

        self.structure_chk = QCheckBox("Preserve folder structure in output")
        self.structure_chk.setChecked(True)
        io_grid.addWidget(self.structure_chk, 2, 2)

        self.inplace_chk = QCheckBox("Convert in place (save next to original, delete source)")
        self.inplace_chk.setChecked(False)
        self.inplace_chk.setStyleSheet(f"color: {CAT['peach']};")
        self.inplace_chk.toggled.connect(self._on_inplace_toggled)
        io_grid.addWidget(self.inplace_chk, 3, 1, 1, 2)

        scroll_layout.addWidget(io_group)

        # ── Input Format Filter ──
        filter_group = QGroupBox("Input Format Filter")
        filter_layout = QGridLayout(filter_group)
        filter_layout.setSpacing(6)

        self._format_filters: dict[str, QCheckBox] = {}
        col = 0
        row = 0
        for name, (exts, available) in FORMAT_FAMILIES.items():
            chk = QCheckBox(name)
            chk.setChecked(available)
            chk.setEnabled(available)
            if not available:
                chk.setToolTip(f"{name} decoder not installed")
                chk.setStyleSheet(f"color: {CAT['overlay0']};")
            self._format_filters[name] = chk
            filter_layout.addWidget(chk, row, col)
            col += 1
            if col > 4:
                col = 0
                row += 1

        for c in range(5):
            filter_layout.setColumnStretch(c, 1)

        scroll_layout.addWidget(filter_group)

        # ── Conversion Options ──
        opt_group = QGroupBox("Conversion Settings")
        opt_grid = QGridLayout(opt_group)
        opt_grid.setColumnStretch(0, 0)
        opt_grid.setColumnStretch(1, 1)
        opt_grid.setColumnStretch(2, 0)
        opt_grid.setColumnStretch(3, 1)

        opt_grid.addWidget(QLabel("Output Format:"), 0, 0)
        self.fmt_combo = QComboBox()
        self.fmt_combo.addItems([
            "Auto (JPEG for photos, PNG for transparency)",
            "JPEG", "PNG", "WebP", "AVIF", "TIFF", "JPEG XL"
        ])
        self.fmt_combo.setItemData(0, "JPEG for photos, PNG when transparency exists", Qt.ItemDataRole.ToolTipRole)
        self.fmt_combo.setItemData(1, "Best for photographs, lossy compression", Qt.ItemDataRole.ToolTipRole)
        self.fmt_combo.setItemData(2, "Lossless, supports transparency", Qt.ItemDataRole.ToolTipRole)
        self.fmt_combo.setItemData(3, "Modern format, smaller files", Qt.ItemDataRole.ToolTipRole)
        self.fmt_combo.setItemData(4, "Next-gen AV1 codec, best compression ratio", Qt.ItemDataRole.ToolTipRole)
        self.fmt_combo.setItemData(5, "Lossless, professional workflows", Qt.ItemDataRole.ToolTipRole)
        if HAS_JXL:
            self.fmt_combo.setItemData(6, "Next-gen JPEG replacement, best quality-to-size ratio", Qt.ItemDataRole.ToolTipRole)
        else:
            model = self.fmt_combo.model()
            model.item(6).setEnabled(False)
            self.fmt_combo.setItemData(6, "Requires pillow-jxl-plugin (pip install pillow-jxl-plugin)", Qt.ItemDataRole.ToolTipRole)
        opt_grid.addWidget(self.fmt_combo, 0, 1, 1, 2)

        self._preset_btn = QToolButton()
        self._preset_btn.setText("Presets")
        self._preset_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._preset_btn.setToolTip("Apply a conversion preset")
        preset_menu = QMenu(self)
        for name in PRESETS:
            preset_menu.addAction(name, lambda n=name: self._apply_preset(n))
        self._preset_btn.setMenu(preset_menu)
        opt_grid.addWidget(self._preset_btn, 0, 3)

        self.quality_desc_label = QLabel("JPEG/WebP Quality:")
        opt_grid.addWidget(self.quality_desc_label, 1, 0)
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(50, 100)
        self.quality_slider.setValue(92)
        self.quality_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.quality_slider.setTickInterval(5)
        opt_grid.addWidget(self.quality_slider, 1, 1, 1, 2)
        self.quality_label = QLabel("92")
        self.quality_label.setStyleSheet(f"color: {CAT['blue']}; font-weight: 700; min-width: 30px;")
        self.quality_slider.valueChanged.connect(lambda v: self.quality_label.setText(str(v)))
        opt_grid.addWidget(self.quality_label, 1, 3)

        opt_grid.addWidget(QLabel("Parallel Workers:"), 2, 0)
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 32)
        cpu_count = os.cpu_count() or 4
        self.workers_spin.setValue(min(cpu_count, 8))
        opt_grid.addWidget(self.workers_spin, 2, 1)

        self.meta_chk = QCheckBox("Preserve metadata")
        self.meta_chk.setChecked(True)
        self.meta_chk.setToolTip("Preserve EXIF, ICC color profiles, and XMP metadata")
        self.meta_chk.toggled.connect(lambda checked: self.strip_meta_chk.setChecked(False) if checked else None)
        opt_grid.addWidget(self.meta_chk, 2, 2)

        self.strip_meta_chk = QCheckBox("Strip metadata")
        self.strip_meta_chk.setChecked(False)
        self.strip_meta_chk.setToolTip("Remove all EXIF, ICC, and XMP metadata from output files")
        self.strip_meta_chk.toggled.connect(lambda checked: self.meta_chk.setChecked(False) if checked else None)
        opt_grid.addWidget(self.strip_meta_chk, 2, 3)

        self.skip_existing_chk = QCheckBox("Skip files that already have output")
        self.skip_existing_chk.setChecked(False)
        self.skip_existing_chk.setToolTip("Resume interrupted batches — skip files where output already exists")
        opt_grid.addWidget(self.skip_existing_chk, 3, 0, 1, 2)

        self.progressive_jpeg_chk = QCheckBox("Progressive JPEG")
        self.progressive_jpeg_chk.setChecked(False)
        self.progressive_jpeg_chk.setToolTip("Save JPEGs as progressive (loads top-to-bottom in browsers)")
        opt_grid.addWidget(self.progressive_jpeg_chk, 3, 2)

        self.lossless_webp_chk = QCheckBox("Lossless WebP")
        self.lossless_webp_chk.setChecked(False)
        self.lossless_webp_chk.setToolTip("Save WebP files in lossless mode (larger files, no quality loss)")
        opt_grid.addWidget(self.lossless_webp_chk, 3, 3)

        # ── Resize ──
        self.resize_chk = QCheckBox("Resize")
        self.resize_chk.setChecked(False)
        self.resize_chk.toggled.connect(self._on_resize_toggled)
        opt_grid.addWidget(self.resize_chk, 4, 0)

        self.resize_combo = QComboBox()
        self.resize_combo.addItems(["Max Dimension", "Scale"])
        self.resize_combo.setEnabled(False)
        self.resize_combo.currentIndexChanged.connect(self._on_resize_mode_changed)
        opt_grid.addWidget(self.resize_combo, 4, 1)

        self.resize_spin = QSpinBox()
        self.resize_spin.setRange(100, 10000)
        self.resize_spin.setValue(1920)
        self.resize_spin.setSuffix(" px")
        self.resize_spin.setEnabled(False)
        opt_grid.addWidget(self.resize_spin, 4, 2, 1, 2)

        # ── Filename Prefix / Suffix ──
        opt_grid.addWidget(QLabel("Prefix:"), 5, 0)
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("e.g. converted_")
        opt_grid.addWidget(self.prefix_edit, 5, 1)

        opt_grid.addWidget(QLabel("Suffix:"), 5, 2)
        self.suffix_edit = QLineEdit()
        self.suffix_edit.setPlaceholderText("e.g. _web")
        opt_grid.addWidget(self.suffix_edit, 5, 3)

        # ── Chroma Subsampling + sRGB ──
        self.chroma_chk = QCheckBox("4:2:0 chroma (smaller JPEG files)")
        self.chroma_chk.setChecked(False)
        self.chroma_chk.setToolTip("Use 4:2:0 chroma subsampling instead of 4:4:4 for smaller JPEGs (slight color detail loss)")
        opt_grid.addWidget(self.chroma_chk, 6, 0, 1, 2)

        self.srgb_chk = QCheckBox("Convert colors to sRGB")
        self.srgb_chk.setChecked(False)
        self.srgb_chk.setToolTip("Convert embedded ICC profiles (e.g. Display P3) to sRGB for maximum compatibility")
        opt_grid.addWidget(self.srgb_chk, 6, 2, 1, 2)

        # ── TIFF Compression + PNG Compression Level ──
        self.tiff_comp_label = QLabel("TIFF Compression:")
        opt_grid.addWidget(self.tiff_comp_label, 7, 0)
        self.tiff_comp_combo = QComboBox()
        self.tiff_comp_combo.addItems(["None", "LZW", "Deflate"])
        opt_grid.addWidget(self.tiff_comp_combo, 7, 1)

        self.png_level_label = QLabel("PNG Compression:")
        opt_grid.addWidget(self.png_level_label, 7, 2)
        self.png_level_spin = QSpinBox()
        self.png_level_spin.setRange(1, 9)
        self.png_level_spin.setValue(6)
        self.png_level_spin.setToolTip("PNG compression level (1=fastest, 9=smallest)")
        opt_grid.addWidget(self.png_level_spin, 7, 3)

        # Show/hide TIFF and PNG controls based on format selection
        self.fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        self._on_format_changed(self.fmt_combo.currentIndex())

        scroll_layout.addWidget(opt_group)

        # ── Actions ──
        actions = QHBoxLayout()
        self.scan_btn = QPushButton("Scan Directory")
        self.scan_btn.setObjectName("primaryBtn")
        self.scan_btn.clicked.connect(self._scan)
        actions.addWidget(self.scan_btn)

        self.convert_btn = QPushButton("Convert All")
        self.convert_btn.setObjectName("primaryBtn")
        self.convert_btn.setEnabled(False)
        self.convert_btn.clicked.connect(self._convert)
        actions.addWidget(self.convert_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        actions.addWidget(self.stop_btn)

        actions.addStretch()

        self.auto_open_chk = QCheckBox("Auto-open output folder")
        self.auto_open_chk.setChecked(False)
        self.auto_open_chk.setToolTip("Automatically open the output folder when conversion finishes")
        actions.addWidget(self.auto_open_chk)

        self.open_output_btn = QPushButton("Open Output Folder")
        self.open_output_btn.setEnabled(False)
        self.open_output_btn.clicked.connect(self._open_output)
        actions.addWidget(self.open_output_btn)

        scroll_layout.addLayout(actions)

        # ── Stats bar ──
        stats_frame = QFrame()
        stats_frame.setStyleSheet(
            f"background-color: {CAT['mantle']}; border-radius: 8px; padding: 6px;"
        )
        stats_layout = QHBoxLayout(stats_frame)
        stats_layout.setContentsMargins(16, 8, 16, 8)

        self.stat_files = self._make_stat("0", "Files Found")
        self.stat_size = self._make_stat("0 B", "Total Size")
        self.stat_done = self._make_stat("0", "Converted")
        self.stat_skipped = self._make_stat("0", "Skipped")
        self.stat_failed = self._make_stat("0", "Failed")
        self.stat_saved = self._make_stat("0 B", "Space Saved")

        for w in [self.stat_files, self.stat_size, self.stat_done,
                  self.stat_skipped, self.stat_failed, self.stat_saved]:
            stats_layout.addWidget(w)

        scroll_layout.addWidget(stats_frame)

        # ── Progress ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)
        scroll_layout.addWidget(self.progress_bar)

        # ── Log + controls ──
        log_header = QHBoxLayout()
        log_label = QLabel("Log")
        log_label.setStyleSheet(f"color: {CAT['overlay1']}; font-weight: 600; font-size: 12px;")
        log_header.addWidget(log_label)
        log_header.addStretch()

        self.export_log_btn = QPushButton("Export Log")
        self.export_log_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self.export_log_btn.clicked.connect(self._export_log)
        log_header.addWidget(self.export_log_btn)

        self.export_csv_btn = QPushButton("Export CSV")
        self.export_csv_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self.export_csv_btn.setToolTip("Export conversion results as a CSV report")
        self.export_csv_btn.clicked.connect(self._export_csv)
        log_header.addWidget(self.export_csv_btn)

        self.clear_log_btn = QPushButton("Clear")
        self.clear_log_btn.setStyleSheet("font-size: 11px; padding: 2px 10px;")
        self.clear_log_btn.clicked.connect(self._clear_log)
        log_header.addWidget(self.clear_log_btn)

        log_container = QWidget()
        log_container_layout = QVBoxLayout(log_container)
        log_container_layout.setContentsMargins(0, 0, 0, 0)
        log_container_layout.setSpacing(4)
        log_container_layout.addLayout(log_header)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.log_view.customContextMenuRequested.connect(self._on_log_context_menu)
        log_container_layout.addWidget(self.log_view, 1)

        # ── Splitter: controls scroll area + log ──
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(scroll)
        splitter.addWidget(log_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # ── Status bar ──
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _make_stat(self, value: str, label: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val = QLabel(value)
        val.setObjectName("statValue")
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(label)
        lbl.setObjectName("statLabel")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(val)
        lay.addWidget(lbl)
        w._val = val
        return w

    def _log(self, msg: str):
        self.log_view.appendPlainText(msg)

    # ── Drag & Drop ──
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            supported = get_supported_extensions()
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    p = Path(url.toLocalFile())
                    if p.is_dir() or (p.is_file() and p.suffix.lower() in supported):
                        event.acceptProposedAction()
                        self.src_edit.setStyleSheet(f"border: 2px solid {CAT['lavender']};")
                        return

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.src_edit.setStyleSheet("")

    def dropEvent(self, event: QDropEvent):
        self.src_edit.setStyleSheet("")
        urls = event.mimeData().urls()

        # Check for directory drop first
        for url in urls:
            path = url.toLocalFile()
            if Path(path).is_dir():
                self.src_edit.setText(path)
                if not self.dst_edit.text() and not self.inplace_chk.isChecked():
                    self.dst_edit.setText(str(Path(path) / "converted"))
                self._add_recent_dir(path)
                self._log(f"Source set via drag & drop: {path}")
                event.acceptProposedAction()
                return

        # Handle individual file drops
        supported = get_supported_extensions()
        files = []
        for url in urls:
            p = Path(url.toLocalFile())
            if p.is_file() and p.suffix.lower() in supported:
                files.append(p)

        if files:
            files.sort()
            total_size = sum(f.stat().st_size for f in files)
            self._scan_result = ScanResult(files=files, total_size=total_size, elapsed=0)
            common_parent = str(Path(os.path.commonpath([str(f.parent) for f in files])))
            self.src_edit.setText(common_parent)
            if not self.dst_edit.text() and not self.inplace_chk.isChecked():
                self.dst_edit.setText(str(Path(common_parent) / "converted"))
            self.stat_files._val.setText(str(len(files)))
            self.stat_size._val.setText(_fmt_size(total_size))
            self.convert_btn.setEnabled(True)
            self._update_title("scanned", count=len(files))
            self._log(f"Added {len(files)} file{'s' if len(files) != 1 else ''} via drag & drop")
            event.acceptProposedAction()

    # ── Log context menu ──
    def _on_log_context_menu(self, pos):
        menu = QMenu(self)
        copy_sel = menu.addAction("Copy Selection")
        copy_sel.setEnabled(self.log_view.textCursor().hasSelection())
        copy_sel.triggered.connect(self.log_view.copy)

        copy_all = menu.addAction("Copy All")
        copy_all.triggered.connect(lambda: QApplication.clipboard().setText(self.log_view.toPlainText()))

        menu.addSeparator()

        open_loc = menu.addAction("Open File Location")
        open_loc.setEnabled(self._last_ok_dst is not None)
        open_loc.triggered.connect(
            lambda: _open_path(str(self._last_ok_dst.parent)) if self._last_ok_dst else None
        )

        menu.exec(self.log_view.mapToGlobal(pos))

    # ── Presets ──
    def _apply_preset(self, name: str):
        preset = PRESETS.get(name)
        if not preset:
            return
        if "fmt" in preset:
            self.fmt_combo.setCurrentIndex(preset["fmt"])
        if "quality" in preset:
            self.quality_slider.setValue(preset["quality"])
        if "progressive_jpeg" in preset:
            self.progressive_jpeg_chk.setChecked(preset["progressive_jpeg"])
        else:
            self.progressive_jpeg_chk.setChecked(False)
        if "lossless_webp" in preset:
            self.lossless_webp_chk.setChecked(preset["lossless_webp"])
        else:
            self.lossless_webp_chk.setChecked(False)
        if "chroma_subsampling" in preset:
            self.chroma_chk.setChecked(preset["chroma_subsampling"])
        else:
            self.chroma_chk.setChecked(False)
        if "convert_to_srgb" in preset:
            self.srgb_chk.setChecked(preset["convert_to_srgb"])
        else:
            self.srgb_chk.setChecked(False)
        if "resize_enabled" in preset:
            self.resize_chk.setChecked(preset["resize_enabled"])
            if preset["resize_enabled"]:
                if "resize_mode" in preset:
                    self.resize_combo.setCurrentIndex(preset["resize_mode"])
                if "resize_value" in preset:
                    self.resize_spin.setValue(preset["resize_value"])
        if "tiff_compression" in preset:
            self.tiff_comp_combo.setCurrentIndex(preset["tiff_compression"])
        if "png_compress_level" in preset:
            self.png_level_spin.setValue(preset["png_compress_level"])
        self._log(f"Preset applied: {name}")

    # ── In-place toggle ──
    def _on_inplace_toggled(self, checked: bool):
        self.dst_edit.setEnabled(not checked)
        self.dst_btn.setEnabled(not checked)
        self.structure_chk.setEnabled(not checked)
        if checked:
            self.dst_edit.setPlaceholderText("(disabled — output goes next to each source file)")
        else:
            self.dst_edit.setPlaceholderText("Converted files go here (default: source/converted)")

    # ── Browse ──
    def _browse_source(self):
        d = QFileDialog.getExistingDirectory(self, "Select Source Directory",
                                             self.src_edit.text() or str(Path.home()))
        if d:
            self.src_edit.setText(d)
            if not self.dst_edit.text():
                self.dst_edit.setText(str(Path(d) / "converted"))
            self._add_recent_dir(d)

    def _browse_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory",
                                             self.dst_edit.text() or str(Path.home()))
        if d:
            self.dst_edit.setText(d)

    # ── Format filter ──
    def _get_enabled_extensions(self) -> set[str]:
        """Build extension set from checked format filter checkboxes."""
        exts = set()
        for name, chk in self._format_filters.items():
            if chk.isChecked() and chk.isEnabled():
                family_exts, _ = FORMAT_FAMILIES[name]
                exts |= family_exts
        return exts

    # ── Recent directories ──
    def _add_recent_dir(self, path: str):
        """Add a directory to the recent list (max 10, deduplicated)."""
        recent = self._get_recent_dirs()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self.settings.setValue("recent_dirs", json.dumps(recent[:10]))

    def _get_recent_dirs(self) -> list[str]:
        raw = self.settings.value("recent_dirs", "[]")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    def _populate_recent_menu(self):
        self._recent_menu.clear()
        recent = self._get_recent_dirs()
        if not recent:
            action = self._recent_menu.addAction("No recent directories")
            action.setEnabled(False)
        else:
            for path in recent:
                action = self._recent_menu.addAction(path)
                action.triggered.connect(lambda checked, p=path: self._set_source_dir(p))

    def _set_source_dir(self, path: str):
        self.src_edit.setText(path)
        if not self.dst_edit.text() and not self.inplace_chk.isChecked():
            self.dst_edit.setText(str(Path(path) / "converted"))
        self._log(f"Source set from recent: {path}")

    # ── Format-dependent controls ──
    def _on_format_changed(self, idx: int):
        """Show/hide format-specific controls based on selected output format."""
        # idx: 0=Auto, 1=JPEG, 2=PNG, 3=WebP, 4=AVIF, 5=TIFF, 6=JPEG XL
        is_auto = idx == 0
        is_jpeg = idx == 1
        is_png = idx == 2
        is_webp = idx == 3
        is_avif = idx == 4
        is_tiff = idx == 5
        is_jxl = idx == 6

        # Quality slider: JPEG, WebP, AVIF, JXL, Auto
        show_quality = is_auto or is_jpeg or is_webp or is_avif or is_jxl
        self.quality_desc_label.setVisible(show_quality)
        self.quality_slider.setVisible(show_quality)
        self.quality_label.setVisible(show_quality)

        # Quality label text
        if is_jpeg:
            self.quality_desc_label.setText("JPEG Quality:")
        elif is_webp:
            self.quality_desc_label.setText("WebP Quality:")
        elif is_avif:
            self.quality_desc_label.setText("AVIF Quality:")
        elif is_jxl:
            self.quality_desc_label.setText("JXL Quality:")
        else:
            self.quality_desc_label.setText("JPEG/WebP Quality:")

        # Chroma subsampling: JPEG, Auto
        self.chroma_chk.setVisible(is_auto or is_jpeg)

        # Progressive JPEG: JPEG, Auto
        self.progressive_jpeg_chk.setVisible(is_auto or is_jpeg)

        # Lossless WebP: WebP, Auto
        self.lossless_webp_chk.setVisible(is_webp)

        # TIFF compression: TIFF only
        self.tiff_comp_label.setVisible(is_tiff)
        self.tiff_comp_combo.setVisible(is_tiff)

        # PNG compression: PNG only
        self.png_level_label.setVisible(is_png)
        self.png_level_spin.setVisible(is_png)

    # ── Resize controls ──
    def _on_resize_toggled(self, checked: bool):
        self.resize_combo.setEnabled(checked)
        self.resize_spin.setEnabled(checked)

    def _on_resize_mode_changed(self, idx: int):
        if idx == 0:  # Max Dimension
            self.resize_spin.setRange(100, 10000)
            self.resize_spin.setSuffix(" px")
            if self.resize_spin.value() < 100:
                self.resize_spin.setValue(1920)
        else:  # Scale
            self.resize_spin.setRange(1, 500)
            self.resize_spin.setSuffix(" %")
            if self.resize_spin.value() > 500:
                self.resize_spin.setValue(50)

    # ── Log controls ──
    def _export_log(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Log", str(Path.home() / "heicshift_log.txt"),
            "Text Files (*.txt);;All Files (*)"
        )
        if path:
            Path(path).write_text(self.log_view.toPlainText(), encoding="utf-8")
            self._log(f"Log exported to {path}")

    def _export_csv(self):
        """Export conversion results as a CSV report."""
        if not self._results:
            self._log("[ERROR] No conversion results to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV Report", str(Path.home() / "heicshift_report.csv"),
            "CSV Files (*.csv);;All Files (*)"
        )
        if path:
            import csv
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Source", "Output", "Status", "Size Before", "Size After",
                                 "Delta", "Elapsed (s)", "Warnings"])
                for r in self._results:
                    status = "OK" if r.success else ("SKIP" if r.skipped else "FAIL")
                    delta = r.size_before - r.size_after if r.success else 0
                    writer.writerow([
                        str(r.src), str(r.dst or ""), status,
                        r.size_before, r.size_after, delta,
                        f"{r.elapsed:.3f}",
                        "; ".join(r.warnings) if r.warnings else "",
                    ])
            self._log(f"CSV report exported to {path}")

    def _clear_log(self):
        self.log_view.clear()
        self._update_title()

    # ── Scan ──
    def _scan(self):
        src = self.src_edit.text().strip()
        if not src or not Path(src).is_dir():
            self._log("[ERROR] Please select a valid source directory.")
            return

        self._update_title()
        self.scan_btn.setEnabled(False)
        self.convert_btn.setEnabled(False)
        self.status_bar.showMessage("Scanning...")

        enabled_exts = self._get_enabled_extensions()
        if not enabled_exts:
            self._log("[ERROR] No input formats selected in the filter panel.")
            self.scan_btn.setEnabled(True)
            self.status_bar.showMessage("Ready")
            return

        self._scanner = ScanWorker(src, self.recursive_chk.isChecked(), enabled_exts)
        self._scanner.log.connect(self._log)
        self._scanner.scan_progress.connect(self._on_scan_progress)
        self._scanner.finished.connect(self._on_scan_done)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setFormat("Scanning...")
        self._scanner.start()

    def _on_scan_progress(self, count: int, total_size: int, directory: str, dir_count: int):
        try:
            rel = str(Path(directory).relative_to(self.src_edit.text().strip()))
            if rel == ".":
                rel = Path(directory).name
        except ValueError:
            rel = directory
        self.stat_files._val.setText(str(count))
        self.stat_size._val.setText(_fmt_size(total_size))
        self._log(f"  {rel}/ — {dir_count} file{'s' if dir_count != 1 else ''}")
        self.status_bar.showMessage(f"Scanning... {count} files found ({_fmt_size(total_size)})")

    def _on_scan_done(self, result: ScanResult):
        self._scan_result = result
        self.scan_btn.setEnabled(True)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")

        self.stat_files._val.setText(str(len(result.files)))
        self.stat_size._val.setText(_fmt_size(result.total_size))

        if result.files:
            self.convert_btn.setEnabled(True)
            self._update_title("scanned", count=len(result.files))
            # Count by format family
            ext_counts: dict[str, int] = {}
            for f in result.files:
                s = f.suffix.lower()
                if s in JPEG_EXTS:
                    ext_counts["JPEG"] = ext_counts.get("JPEG", 0) + 1
                elif s in PNG_EXTS:
                    ext_counts["PNG"] = ext_counts.get("PNG", 0) + 1
                elif s in HEIC_EXTS:
                    ext_counts["HEIC"] = ext_counts.get("HEIC", 0) + 1
                elif s in AVIF_EXTS:
                    ext_counts["AVIF"] = ext_counts.get("AVIF", 0) + 1
                elif s in WEBP_EXTS:
                    ext_counts["WebP"] = ext_counts.get("WebP", 0) + 1
                elif s in JXL_EXTS:
                    ext_counts["JXL"] = ext_counts.get("JXL", 0) + 1
                elif s in RAW_EXTS:
                    ext_counts["RAW"] = ext_counts.get("RAW", 0) + 1
                elif s in TIFF_EXTS:
                    ext_counts["TIFF"] = ext_counts.get("TIFF", 0) + 1
                elif s in BMP_EXTS:
                    ext_counts["BMP"] = ext_counts.get("BMP", 0) + 1
                elif s in JP2_EXTS:
                    ext_counts["JP2"] = ext_counts.get("JP2", 0) + 1
                elif s in QOI_EXTS:
                    ext_counts["QOI"] = ext_counts.get("QOI", 0) + 1
                elif s in ICO_EXTS:
                    ext_counts["ICO"] = ext_counts.get("ICO", 0) + 1
            breakdown = ", ".join(f"{v} {k}" for k, v in sorted(ext_counts.items(), key=lambda x: -x[1]))
            self._log(f"Breakdown: {breakdown}")
            self.status_bar.showMessage(
                f"Found {len(result.files)} files ({_fmt_size(result.total_size)}). Ready to convert."
            )
        else:
            self.status_bar.showMessage("No supported image files found.")

    # ── Convert ──
    def _convert(self):
        if not self._scan_result or not self._scan_result.files:
            return

        in_place = self.inplace_chk.isChecked()

        if in_place:
            dst = self.src_edit.text().strip()
        else:
            dst = self.dst_edit.text().strip()
            if not dst:
                src = self.src_edit.text().strip()
                dst = str(Path(src) / "converted")
                self.dst_edit.setText(dst)
            Path(dst).mkdir(parents=True, exist_ok=True)

        # Source/output overlap guard
        src_resolved = Path(self.src_edit.text().strip()).resolve()
        dst_resolved = Path(dst).resolve()
        if not in_place and dst_resolved == src_resolved:
            self._log("[ERROR] Output directory is the same as source directory. Use a subfolder or enable in-place mode.")
            self.scan_btn.setEnabled(True)
            self.convert_btn.setEnabled(True)
            return
        if not in_place and dst_resolved != src_resolved:
            try:
                if dst_resolved.is_relative_to(src_resolved):
                    self._log("[WARN] Output directory is inside the source directory. This is fine for most workflows.")
            except (ValueError, TypeError):
                pass

        fmt_map = {0: "auto", 1: "jpeg", 2: "png", 3: "webp", 4: "avif", 5: "tiff", 6: "jxl"}
        fmt = fmt_map.get(self.fmt_combo.currentIndex(), "auto")

        # Disk space pre-check
        try:
            estimated = _estimate_output_size(self._scan_result.total_size, fmt)
            disk = shutil.disk_usage(dst)
            if estimated > disk.free:
                self._log(
                    f"[ERROR] Not enough disk space. Estimated output: {_fmt_size(estimated)}, "
                    f"available: {_fmt_size(disk.free)}"
                )
                self.scan_btn.setEnabled(True)
                self.convert_btn.setEnabled(True)
                return
            if estimated > disk.free * 0.8:
                self._log(
                    f"[WARN] Estimated output ({_fmt_size(estimated)}) exceeds 80% of "
                    f"available disk space ({_fmt_size(disk.free)})"
                )
        except (OSError, ValueError):
            pass  # Network drives or unmounted paths may not support disk_usage

        resize_mode = "none"
        if self.resize_chk.isChecked():
            resize_mode = "max_dim" if self.resize_combo.currentIndex() == 0 else "scale"

        self._results = []
        self._convert_start_time = time.perf_counter()
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(self._scan_result.files))
        self.stat_done._val.setText("0")
        self.stat_skipped._val.setText("0")
        self.stat_failed._val.setText("0")
        self.stat_saved._val.setText("0 B")
        # Reset stat colors to default green for new batch
        default_stat_style = f"color: {CAT['green']}; font-size: 22px; font-weight: 700;"
        self.stat_done._val.setStyleSheet(default_stat_style)
        self.stat_skipped._val.setStyleSheet(default_stat_style)
        self.stat_failed._val.setStyleSheet(default_stat_style)
        self.stat_saved._val.setStyleSheet(default_stat_style)

        self.scan_btn.setEnabled(False)
        self.convert_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.open_output_btn.setEnabled(False)
        self.status_bar.showMessage("Converting...")

        if in_place:
            self._log("In-place mode: converted files saved next to originals, source files will be deleted")

        self._worker = ConvertWorker(
            files=self._scan_result.files,
            output_dir=Path(dst),
            fmt=fmt,
            quality=self.quality_slider.value(),
            preserve_meta=self.meta_chk.isChecked() and not self.strip_meta_chk.isChecked(),
            preserve_structure=self.structure_chk.isChecked(),
            base_dir=Path(self.src_edit.text().strip()),
            workers=self.workers_spin.value(),
            in_place=in_place,
            skip_existing=self.skip_existing_chk.isChecked(),
            resize_mode=resize_mode,
            resize_value=self.resize_spin.value(),
            prefix=self.prefix_edit.text(),
            suffix=self.suffix_edit.text(),
            lossless_webp=self.lossless_webp_chk.isChecked(),
            progressive_jpeg=self.progressive_jpeg_chk.isChecked(),
            chroma_subsampling=self.chroma_chk.isChecked(),
            convert_to_srgb=self.srgb_chk.isChecked(),
            tiff_compression=["none", "lzw", "deflate"][self.tiff_comp_combo.currentIndex()],
            png_compress_level=self.png_level_spin.value(),
        )
        self._worker.log.connect(self._log)
        self._worker.progress.connect(self._on_progress)
        self._worker.current_file.connect(self._on_current_file)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished_all.connect(self._on_convert_done)
        self._worker.start()

    def _on_progress(self, current, total):
        self.progress_bar.setValue(current)
        self._update_title("converting", current=current, total=total)
        elapsed = time.perf_counter() - self._convert_start_time
        if current > 0 and elapsed > 0 and current < total:
            speed = current / elapsed
            rate = elapsed / current
            remaining = (total - current) * rate
            self.status_bar.showMessage(
                f"Converting... {current}/{total} -- "
                f"{speed:.1f} files/sec -- "
                f"Elapsed: {_fmt_eta(elapsed)} -- "
                f"ETA: {_fmt_eta(remaining)}"
            )
        else:
            self.status_bar.showMessage(f"Converting... {current}/{total}")

    def _on_current_file(self, filename: str):
        self.progress_bar.setFormat(f"%p% — {filename}")

    def _on_file_done(self, result: ConvertResult):
        self._results.append(result)
        if result.success and result.dst:
            self._last_ok_dst = result.dst
        ok = sum(1 for r in self._results if r.success)
        skipped = sum(1 for r in self._results if r.skipped)
        fail = sum(1 for r in self._results if not r.success and not r.skipped)
        saved = sum(r.size_before - r.size_after for r in self._results if r.success)

        self.stat_done._val.setText(str(ok))
        self.stat_skipped._val.setText(str(skipped))
        if skipped:
            self.stat_skipped._val.setStyleSheet(f"color: {CAT['yellow']}; font-size: 22px; font-weight: 700;")
        self.stat_failed._val.setText(str(fail))
        if fail:
            self.stat_failed._val.setStyleSheet(f"color: {CAT['red']}; font-size: 22px; font-weight: 700;")
        self.stat_saved._val.setText(_fmt_size(abs(saved)))
        if saved >= 0:
            self.stat_saved._val.setStyleSheet(f"color: {CAT['green']}; font-size: 22px; font-weight: 700;")
        else:
            self.stat_saved._val.setStyleSheet(f"color: {CAT['peach']}; font-size: 22px; font-weight: 700;")

    def _play_completion_sound(self):
        """Play a platform-specific notification sound."""
        try:
            system = platform.system()
            if system == "Windows":
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            elif system == "Darwin":
                subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
            else:
                subprocess.Popen(["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"])
        except Exception:
            pass

    def _on_convert_done(self, results):
        self.scan_btn.setEnabled(True)
        self.convert_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.open_output_btn.setEnabled(True)
        self.progress_bar.setFormat("%p%")

        ok = sum(1 for r in results if r.success)
        skipped = sum(1 for r in results if r.skipped)
        fail = sum(1 for r in results if not r.success and not r.skipped)
        deleted = sum(1 for r in results if r.src_deleted)
        total_time = sum(r.elapsed for r in results)
        wall_time = time.perf_counter() - self._convert_start_time
        saved = sum(r.size_before - r.size_after for r in results if r.success)

        parts = [f"{ok} converted"]
        if skipped:
            parts.append(f"{skipped} skipped")
        if fail:
            parts.append(f"{fail} failed")
        if deleted:
            parts.append(f"{deleted} sources deleted")
        summary = (
            f"Done! {', '.join(parts)}. "
            f"Space {'saved' if saved >= 0 else 'added'}: {_fmt_size(abs(saved))}. "
            f"Wall time: {_fmt_eta(wall_time)} ({total_time:.1f}s processing)"
        )
        self._log(f"\n{'='*60}")
        self._log(summary)
        self._log(f"{'='*60}")
        self.status_bar.showMessage(summary)

        # System tray notification
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()
            self._tray.showMessage(
                "HEICShift — Conversion Complete",
                f"{ok} converted, {fail} failed" + (f", {skipped} skipped" if skipped else ""),
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
            QTimer.singleShot(6000, self._tray.hide)

        self._update_title("done", ok=ok, fail=fail)
        self._play_completion_sound()
        if self.auto_open_chk.isChecked():
            self._open_output()
        self._save_state()

    def _stop(self):
        if self._worker:
            self._worker.stop()
            self.stop_btn.setEnabled(False)
            self.status_bar.showMessage("Stopping...")

    def _open_output(self):
        if self.inplace_chk.isChecked():
            path = self.src_edit.text().strip()
        else:
            path = self.dst_edit.text().strip()
        if path and Path(path).exists():
            _open_path(path)

    # ── State persistence ──
    def _save_state(self):
        self.settings.setValue("src", self.src_edit.text())
        self.settings.setValue("dst", self.dst_edit.text())
        self.settings.setValue("fmt", self.fmt_combo.currentIndex())
        self.settings.setValue("quality", self.quality_slider.value())
        self.settings.setValue("workers", self.workers_spin.value())
        self.settings.setValue("recursive", self.recursive_chk.isChecked())
        self.settings.setValue("structure", self.structure_chk.isChecked())
        self.settings.setValue("metadata", self.meta_chk.isChecked())
        self.settings.setValue("inplace", self.inplace_chk.isChecked())
        self.settings.setValue("skip_existing", self.skip_existing_chk.isChecked())
        self.settings.setValue("progressive_jpeg", self.progressive_jpeg_chk.isChecked())
        self.settings.setValue("lossless_webp", self.lossless_webp_chk.isChecked())
        self.settings.setValue("resize_enabled", self.resize_chk.isChecked())
        self.settings.setValue("resize_mode", self.resize_combo.currentIndex())
        self.settings.setValue("resize_value", self.resize_spin.value())
        self.settings.setValue("prefix", self.prefix_edit.text())
        self.settings.setValue("suffix", self.suffix_edit.text())
        self.settings.setValue("chroma_subsampling", self.chroma_chk.isChecked())
        self.settings.setValue("convert_to_srgb", self.srgb_chk.isChecked())
        self.settings.setValue("tiff_compression", self.tiff_comp_combo.currentIndex())
        self.settings.setValue("png_compress_level", self.png_level_spin.value())
        self.settings.setValue("strip_metadata", self.strip_meta_chk.isChecked())
        self.settings.setValue("auto_open_output", self.auto_open_chk.isChecked())
        self.settings.setValue("geometry", self.saveGeometry())
        # Format filter states
        filter_state = {name: chk.isChecked() for name, chk in self._format_filters.items()}
        self.settings.setValue("format_filters", json.dumps(filter_state))

    def _restore_state(self):
        if v := self.settings.value("src"):
            self.src_edit.setText(v)
        if v := self.settings.value("dst"):
            self.dst_edit.setText(v)
        if (v := self.settings.value("fmt")) is not None:
            idx = int(v)
            if 0 <= idx < self.fmt_combo.count():
                self.fmt_combo.setCurrentIndex(idx)
        if (v := self.settings.value("quality")) is not None:
            self.quality_slider.setValue(int(v))
        if (v := self.settings.value("workers")) is not None:
            self.workers_spin.setValue(int(v))
        if (v := self.settings.value("recursive")) is not None:
            self.recursive_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("structure")) is not None:
            self.structure_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("metadata")) is not None:
            self.meta_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("inplace")) is not None:
            self.inplace_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("skip_existing")) is not None:
            self.skip_existing_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("progressive_jpeg")) is not None:
            self.progressive_jpeg_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("lossless_webp")) is not None:
            self.lossless_webp_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("resize_enabled")) is not None:
            self.resize_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("resize_mode")) is not None:
            self.resize_combo.blockSignals(True)
            self.resize_combo.setCurrentIndex(int(v))
            self.resize_combo.blockSignals(False)
            if int(v) == 0:
                self.resize_spin.setRange(100, 10000)
                self.resize_spin.setSuffix(" px")
            else:
                self.resize_spin.setRange(1, 500)
                self.resize_spin.setSuffix(" %")
        if (v := self.settings.value("resize_value")) is not None:
            self.resize_spin.setValue(int(v))
        if (v := self.settings.value("prefix")) is not None:
            self.prefix_edit.setText(v)
        if (v := self.settings.value("suffix")) is not None:
            self.suffix_edit.setText(v)
        if (v := self.settings.value("chroma_subsampling")) is not None:
            self.chroma_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("convert_to_srgb")) is not None:
            self.srgb_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("tiff_compression")) is not None:
            self.tiff_comp_combo.setCurrentIndex(int(v))
        if (v := self.settings.value("png_compress_level")) is not None:
            self.png_level_spin.setValue(int(v))
        if (v := self.settings.value("strip_metadata")) is not None:
            self.strip_meta_chk.setChecked(v == "true" or v is True)
        if (v := self.settings.value("auto_open_output")) is not None:
            self.auto_open_chk.setChecked(v == "true" or v is True)
        if v := self.settings.value("geometry"):
            self.restoreGeometry(v)
        # Restore format filter states
        if v := self.settings.value("format_filters"):
            try:
                saved = json.loads(v)
                for name, checked in saved.items():
                    if name in self._format_filters and self._format_filters[name].isEnabled():
                        self._format_filters[name].setChecked(checked)
            except (json.JSONDecodeError, TypeError):
                pass

    def closeEvent(self, event):
        self._save_state()
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(3000)
        self._tray.hide()
        super().closeEvent(event)


# ── CLI Mode ──────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    """Build argument parser for CLI mode."""
    p = argparse.ArgumentParser(
        prog="heicshift",
        description=f"HEICShift v{APP_VERSION} - High-performance image batch converter",
    )
    p.add_argument("--version", action="version", version=f"HEICShift v{APP_VERSION}")
    p.add_argument("-i", "--input", type=str, help="Source directory to scan")
    p.add_argument("-o", "--output", type=str, help="Output directory (default: <input>/converted)")
    p.add_argument("-f", "--format", type=str, default="auto",
                   choices=["auto", "jpeg", "png", "webp", "avif", "tiff", "jxl"],
                   help="Output format (default: auto)")
    p.add_argument("-q", "--quality", type=int, default=92, help="JPEG/WebP quality 50-100 (default: 92)")
    p.add_argument("-w", "--workers", type=int, default=min(os.cpu_count() or 4, 8),
                   help="Parallel worker count (default: min(cpu_count, 8))")
    p.add_argument("--in-place", action="store_true", help="Convert next to originals, delete source")
    p.add_argument("--recursive", action="store_true", default=True, dest="recursive",
                   help="Scan subdirectories (default)")
    p.add_argument("--no-recursive", action="store_false", dest="recursive",
                   help="Only scan top-level directory")
    p.add_argument("--dry-run", action="store_true", help="List files that would be converted, then exit")
    p.add_argument("--strip-metadata", action="store_true", help="Remove all metadata from output files")
    p.add_argument("--resize", type=str, default=None, metavar="MODE:VALUE",
                   help="Resize images, e.g. max_dim:1920 or scale:50")
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip files where output already exists")
    p.add_argument("--progressive", action="store_true",
                   help="Save JPEGs as progressive")
    p.add_argument("--chroma-420", action="store_true",
                   help="Use 4:2:0 chroma subsampling for JPEG")
    p.add_argument("--lossless", action="store_true",
                   help="Save WebP in lossless mode")
    p.add_argument("--srgb", action="store_true",
                   help="Convert embedded ICC profiles to sRGB")
    p.add_argument("--prefix", type=str, default="",
                   help="Prepend text to output filenames")
    p.add_argument("--suffix", type=str, default="",
                   help="Append text to output filenames")
    p.add_argument("--tiff-compression", type=str, default="none",
                   choices=["none", "lzw", "deflate"],
                   help="TIFF compression method (default: none)")
    p.add_argument("--png-level", type=int, default=6,
                   help="PNG compression level 1-9 (default: 6)")
    p.add_argument("--no-structure", action="store_true",
                   help="Flatten output (no subdirectory mirroring)")
    return p


def _log_dep_versions_cli():
    """Print dependency versions to stdout for CLI mode."""
    from PIL import __version__ as pil_ver
    heif_ver = getattr(pillow_heif, "__version__", "unknown")
    print(f"Pillow {pil_ver}, pillow-heif {heif_ver}")
    opt_vers = []
    if HAS_RAWPY:
        opt_vers.append(f"rawpy {getattr(rawpy, '__version__', '?')}")
    if HAS_JXL:
        opt_vers.append(f"pillow-jxl {getattr(pillow_jxl, '__version__', '?')}")
    if HAS_QOI:
        opt_vers.append(f"qoi {getattr(qoi_lib, '__version__', '?')}")
    if opt_vers:
        print(f"Optional: {', '.join(opt_vers)}")


def _run_cli(args):
    """Run headless CLI conversion."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    input_dir = Path(args.input).resolve()
    if not input_dir.is_dir():
        print(f"[ERROR] Not a directory: {input_dir}")
        sys.exit(2)

    if args.in_place:
        output_dir = input_dir
    elif args.output:
        output_dir = Path(args.output).resolve()
    else:
        output_dir = input_dir / "converted"

    print(f"HEICShift v{APP_VERSION} (CLI mode)")
    _log_dep_versions_cli()
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")
    print(f"Format: {args.format}  Quality: {args.quality}  Workers: {args.workers}")
    flags = []
    if args.skip_existing: flags.append("skip-existing")
    if args.progressive: flags.append("progressive")
    if args.chroma_420: flags.append("chroma-4:2:0")
    if args.lossless: flags.append("lossless")
    if args.srgb: flags.append("sRGB")
    if args.no_structure: flags.append("flatten")
    if args.tiff_compression != "none": flags.append(f"tiff-{args.tiff_compression}")
    if args.png_level != 6: flags.append(f"png-level:{args.png_level}")
    if flags:
        print(f"Options: {', '.join(flags)}")
    if args.prefix:
        print(f"Prefix: '{args.prefix}'")
    if args.suffix:
        print(f"Suffix: '{args.suffix}'")

    # Validate JXL dependency
    if args.format == "jxl" and not HAS_JXL:
        print("[ERROR] JPEG XL output requires pillow-jxl-plugin (pip install pillow-jxl-plugin)")
        sys.exit(2)

    # Validate PNG compression level
    if args.png_level < 1 or args.png_level > 9:
        print(f"[ERROR] PNG compression level must be 1-9, got {args.png_level}")
        sys.exit(2)

    # Parse resize
    resize_mode = "none"
    resize_value = 1920
    if args.resize:
        try:
            parts = args.resize.split(":")
            if len(parts) == 2 and parts[0] == "max_dim":
                resize_mode = "max_dim"
                resize_value = int(parts[1])
            elif len(parts) == 2 and parts[0] == "scale":
                resize_mode = "scale"
                resize_value = int(parts[1])
            else:
                print(f"[ERROR] Invalid resize format: {args.resize} (use max_dim:VALUE or scale:VALUE)")
                sys.exit(2)
        except ValueError:
            print(f"[ERROR] Invalid resize value: {args.resize}")
            sys.exit(2)

    # Scan
    print(f"\nScanning{'  recursively' if args.recursive else ''}...")
    scan = scan_directory(input_dir, args.recursive)
    print(f"Found {len(scan.files)} files ({_fmt_size(scan.total_size)}) in {scan.elapsed:.2f}s")

    if not scan.files:
        print("No supported files found.")
        sys.exit(0)

    # Dry run — list and exit
    if args.dry_run:
        print(f"\n[DRY RUN] Would convert {len(scan.files)} files:")
        for f in sorted(scan.files):
            print(f"  {f}")
        sys.exit(0)

    # Disk space check
    if not args.in_place:
        output_dir.mkdir(parents=True, exist_ok=True)
    try:
        estimated = _estimate_output_size(scan.total_size, args.format)
        disk = shutil.disk_usage(str(output_dir))
        if estimated > disk.free:
            print(
                f"[ERROR] Not enough disk space. Estimated output: {_fmt_size(estimated)}, "
                f"available: {_fmt_size(disk.free)}"
            )
            sys.exit(2)
        if estimated > disk.free * 0.8:
            print(
                f"[WARN] Estimated output ({_fmt_size(estimated)}) exceeds 80% of "
                f"available disk space ({_fmt_size(disk.free)})"
            )
    except (OSError, ValueError):
        pass

    # Convert
    preserve_meta = not args.strip_metadata
    ok_count = 0
    fail_count = 0
    skip_count = 0
    total = len(scan.files)
    done_count = 0

    print(f"\nConverting {total} files with {args.workers} workers...\n")

    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for f in scan.files:
            fut = pool.submit(
                convert_file, f, output_dir, args.format, args.quality,
                preserve_meta, not args.no_structure, input_dir, args.in_place,
                args.skip_existing, resize_mode, resize_value,
                args.prefix, args.suffix, args.lossless, args.progressive,
                args.chroma_420, args.srgb, args.tiff_compression, args.png_level,
            )
            futures[fut] = f

        for fut in as_completed(futures):
            result = fut.result()
            done_count += 1
            if result.skipped:
                skip_count += 1
                print(f"[SKIP] ({done_count}/{total}) {result.src.name}")
            elif result.success:
                ok_count += 1
                saved = result.size_before - result.size_after
                pct = (saved / result.size_before * 100) if result.size_before else 0
                deleted_tag = "  [source deleted]" if result.src_deleted else ""
                print(
                    f"[OK] ({done_count}/{total}) {result.src.name} -> {result.dst.name}  "
                    f"({_fmt_size(result.size_before)} -> {_fmt_size(result.size_after)}, "
                    f"{pct:+.1f}%)  [{result.elapsed:.2f}s]{deleted_tag}"
                )
            else:
                fail_count += 1
                print(f"[FAIL] ({done_count}/{total}) {result.src.name}: {result.error}")

            for warn in result.warnings:
                print(f"[WARN] {result.src.name}: {warn}")

    wall_time = time.perf_counter() - t0
    speed = ok_count / wall_time if wall_time > 0 else 0
    print(f"\nDone: {ok_count} converted, {fail_count} failed, {skip_count} skipped in {wall_time:.0f}s ({speed:.1f} files/sec)")

    if fail_count == total:
        sys.exit(2)
    elif fail_count > 0:
        sys.exit(1)
    sys.exit(0)


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    parser = _build_parser()
    args = parser.parse_args()

    # CLI mode if --input is provided
    if args.input:
        _run_cli(args)
        return

    app = QApplication(sys.argv)

    branding_icon = QIcon(str(_branding_icon_path()))

    app.setWindowIcon(branding_icon)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    # Dark palette fallback
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(CAT["base"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(CAT["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(CAT["crust"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(CAT["surface0"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(CAT["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(CAT["surface0"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(CAT["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(CAT["blue"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(CAT["crust"]))
    app.setPalette(palette)

    app.setWindowIcon(_create_app_icon())
    window = MainWindow()
    window.setWindowIcon(branding_icon)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
