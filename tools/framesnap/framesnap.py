#!/usr/bin/env python3
"""
FrameSnap v2.1.0
Browse any video, mark frames, and export screenshots — all formats, all features.
"""

import sys
import os
import json
import subprocess
import math
from pathlib import Path


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


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def _bootstrap():
    import importlib
    to_install = []
    for mod, pkg in [
        ("cv2",   "opencv-python"),
        ("numpy", "numpy"),
        ("PIL",   "Pillow"),
    ]:
        try:
            importlib.import_module(mod)
        except ImportError:
            to_install.append(pkg)
    try:
        importlib.import_module("PyQt6")
    except ImportError:
        to_install.append("PyQt6")
    if to_install:
        print(f"Installing: {', '.join(to_install)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install",
             "--break-system-packages"] + to_install,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


_bootstrap()

import cv2
import numpy as np
from PIL import Image as PilImage
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QListWidget, QListWidgetItem,
    QFileDialog, QLineEdit, QGroupBox, QSizePolicy, QFrame, QSplitter,
    QMenu, QComboBox, QSpinBox, QInputDialog, QMessageBox,
    QStyle, QStyleOptionSlider, QTabWidget, QAbstractItemView,
)
from PyQt6.QtCore import (
    Qt, QTimer, QThread, QMutex, QWaitCondition, pyqtSignal,
    QPoint, QSize, QRect,
)
from PyQt6.QtGui import (, QIcon
    QPixmap, QImage, QIcon, QPainter, QColor, QFont, QAction,
    QDragEnterEvent, QDropEvent,
)


# ── Palette ───────────────────────────────────────────────────────────────────

BASE     = "#1e1e2e"
MANTLE   = "#181825"
CRUST    = "#11111b"
SURFACE0 = "#313244"
SURFACE1 = "#45475a"
SURFACE2 = "#585b70"
TEXT     = "#cdd6f4"
SUBTEXT0 = "#a6adc8"
OVERLAY0 = "#6c7086"
MAUVE    = "#cba6f7"
LAVENDER = "#b4befe"
BLUE     = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
PEACH    = "#fab387"
YELLOW   = "#f9e2af"
TEAL     = "#94e2d5"
SAPPHIRE = "#74c7ec"

MARK_COLORS: dict[str, str] = {
    "Default": MAUVE,
    "Red":     RED,
    "Green":   GREEN,
    "Blue":    BLUE,
    "Orange":  PEACH,
    "Yellow":  YELLOW,
    "Teal":    TEAL,
}

# All extensions cv2 / FFmpeg can typically handle
SUPPORTED_EXTS = (
    ".mp4", ".m4v", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".ts",  ".mts", ".m2ts", ".m2t", ".m2v", ".mpg", ".mpeg", ".mpe",
    ".mxf", ".ogv", ".ogg", ".3gp", ".3g2", ".asf", ".vob", ".divx",
    ".rm",  ".rmvb", ".f4v", ".dv",  ".y4m", ".yuv", ".hevc", ".h264",
    ".h265",".bik",  ".smk", ".nut", ".roq", ".rv",  ".swf",  ".gif",
    ".amv", ".mpv",  ".mj2", ".mjpeg",
)
_ext_glob = " ".join(f"*{e}" for e in SUPPORTED_EXTS)
VIDEO_FILTER = f"Video Files ({_ext_glob});;All Files (*)"

STYLESHEET = f"""
QMainWindow, QDialog, QWidget {{
    background-color: {BASE};
    color: {TEXT};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QLabel {{ color: {TEXT}; background: transparent; }}
QMenuBar {{
    background-color: {MANTLE};
    color: {TEXT};
    border-bottom: 1px solid {SURFACE0};
    padding: 2px 4px;
}}
QMenuBar::item:selected {{ background-color: {SURFACE0}; border-radius: 4px; }}
QMenu {{
    background-color: {MANTLE};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 5px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {SURFACE1}; color: {MAUVE}; }}
QMenu::separator {{ height: 1px; background: {SURFACE1}; margin: 4px 10px; }}
QPushButton {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background-color: {SURFACE1}; border-color: {MAUVE}; color: {MAUVE}; }}
QPushButton:pressed {{ background-color: {SURFACE2}; }}
QPushButton:disabled {{ color: {OVERLAY0}; border-color: {SURFACE0}; background-color: {MANTLE}; }}
QPushButton#markBtn {{
    background-color: {MAUVE}; color: {CRUST};
    font-weight: bold; border: none; font-size: 14px;
    padding: 8px 22px; border-radius: 8px;
}}
QPushButton#markBtn:hover {{ background-color: {LAVENDER}; }}
QPushButton#markBtn:disabled {{ background-color: {SURFACE1}; color: {OVERLAY0}; }}
QPushButton#exportBtn {{
    background-color: {GREEN}; color: {CRUST};
    font-weight: bold; border: none;
    padding: 8px 16px; border-radius: 8px;
}}
QPushButton#exportBtn:hover {{ background-color: #b9f1b5; }}
QPushButton#exportBtn:disabled {{ background-color: {SURFACE1}; color: {OVERLAY0}; }}
QPushButton#sheetBtn {{
    background-color: {TEAL}; color: {CRUST};
    font-weight: bold; border: none;
    padding: 8px 16px; border-radius: 8px;
}}
QPushButton#sheetBtn:hover {{ background-color: #a7f0e8; }}
QPushButton#sheetBtn:disabled {{ background-color: {SURFACE1}; color: {OVERLAY0}; }}
QPushButton#copyBtn {{
    background-color: {BLUE}; color: {CRUST};
    font-weight: bold; border: none;
    padding: 8px 16px; border-radius: 8px;
}}
QPushButton#copyBtn:hover {{ background-color: {LAVENDER}; }}
QPushButton#copyBtn:disabled {{ background-color: {SURFACE1}; color: {OVERLAY0}; }}
QPushButton#loopBtn {{
    background-color: {SURFACE0}; color: {TEXT};
    border: 1px solid {SURFACE1}; border-radius: 6px; padding: 6px 12px;
}}
QPushButton#loopBtn[active="true"] {{
    background-color: {SAPPHIRE}; color: {CRUST};
    border: none; font-weight: bold;
}}
QPushButton#dangerBtn {{
    background-color: {SURFACE0}; color: {RED};
    border: 1px solid {SURFACE1}; border-radius: 6px; padding: 6px 12px;
}}
QPushButton#dangerBtn:hover {{ background-color: {RED}; color: {CRUST}; border-color: {RED}; }}
QSlider::groove:horizontal {{
    height: 6px; background-color: {SURFACE0}; border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background-color: {MAUVE}; width: 16px; height: 16px;
    margin: -5px 0; border-radius: 8px; border: 2px solid {CRUST};
}}
QSlider::sub-page:horizontal {{ background-color: {MAUVE}; border-radius: 3px; }}
QSlider::handle:horizontal:disabled {{ background-color: {SURFACE2}; }}
QSlider::sub-page:horizontal:disabled {{ background-color: {SURFACE1}; }}
QListWidget {{
    background-color: {MANTLE}; border: 1px solid {SURFACE0};
    border-radius: 8px; padding: 4px; outline: none;
}}
QListWidget::item {{ border-radius: 6px; padding: 2px; border: 1px solid transparent; }}
QListWidget::item:selected {{ background-color: {SURFACE1}; border: 1px solid {SURFACE2}; }}
QListWidget::item:hover {{ background-color: {SURFACE0}; }}
QScrollBar:vertical {{
    background-color: {MANTLE}; width: 8px; border-radius: 4px; margin: 0;
}}
QScrollBar::handle:vertical {{ background-color: {SURFACE2}; border-radius: 4px; min-height: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QLineEdit {{
    background-color: {MANTLE}; border: 1px solid {SURFACE1};
    border-radius: 6px; padding: 5px 10px; color: {TEXT};
}}
QLineEdit:focus {{ border-color: {MAUVE}; }}
QComboBox {{
    background-color: {SURFACE0}; color: {TEXT};
    border: 1px solid {SURFACE1}; border-radius: 6px;
    padding: 5px 10px; min-width: 72px;
}}
QComboBox:hover {{ border-color: {MAUVE}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background-color: {MANTLE}; color: {TEXT};
    border: 1px solid {SURFACE1}; border-radius: 6px;
    selection-background-color: {SURFACE1};
    selection-color: {MAUVE};
    outline: none;
}}
QSpinBox {{
    background-color: {SURFACE0}; color: {TEXT};
    border: 1px solid {SURFACE1}; border-radius: 6px; padding: 5px 8px;
}}
QSpinBox:focus {{ border-color: {MAUVE}; }}
QGroupBox {{
    border: 1px solid {SURFACE1}; border-radius: 10px;
    margin-top: 14px; padding: 10px 8px 8px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px;
    padding: 0 6px; color: {MAUVE}; font-weight: bold; font-size: 12px;
}}
QTabWidget::pane {{
    border: 1px solid {SURFACE1}; border-radius: 8px;
    background: {MANTLE}; top: -1px;
}}
QTabBar::tab {{
    background: {SURFACE0}; color: {SUBTEXT0};
    border-radius: 6px 6px 0 0; padding: 7px 18px; margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {MAUVE}; color: {CRUST}; font-weight: bold; }}
QTabBar::tab:hover:!selected {{ background: {SURFACE1}; color: {TEXT}; }}
QSplitter::handle {{ background-color: {SURFACE0}; width: 2px; }}
QFrame[frameShape="4"] {{ color: {SURFACE1}; }}
"""

CONFIG_PATH     = Path.home() / ".framesnap_config.json"
MAX_RECENT      = 10
DEFAULT_TEMPLATE = "{stem}_{frame}_{ts}"


# ── Utilities ─────────────────────────────────────────────────────────────────

def ms_to_ts(ms: float) -> str:
    total_s = int(ms) // 1000
    millis  = int(ms) % 1000
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{millis:03d}"


def frame_to_ms(idx: int, fps: float) -> float:
    return (idx / fps) * 1000.0 if fps > 0 else 0.0


def bgr_to_pixmap(bgr: np.ndarray) -> QPixmap:
    """Convert a BGR numpy frame to QPixmap safely (copies buffer)."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    # Use bytes() to own the data — avoids QImage holding a dangling pointer
    return QPixmap.fromImage(
        QImage(bytes(rgb), w, h, ch * w, QImage.Format.Format_RGB888)
    )


def make_thumb(bgr: np.ndarray, tw: int = 96, th: int = 54) -> QPixmap:
    return bgr_to_pixmap(bgr).scaled(
        tw, th,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def sizeof_fmt(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def safe_filename(name: str) -> str:
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip(". ") or "frame"


def apply_template(template: str, stem: str, frame_idx: int,
                   fps: float, label: str, n: int) -> str:
    ts  = ms_to_ts(frame_to_ms(frame_idx, fps)).replace(":", "-").replace(".", "-")
    lbl = label.strip() or "mark"
    try:
        result = template.format(
            stem=stem, frame=f"{frame_idx:06d}",
            ts=ts, label=lbl, n=f"{n:03d}",
        )
    except (KeyError, ValueError):
        result = f"{stem}_{frame_idx:06d}_{ts}"
    return safe_filename(result)


def open_cap(path: str) -> cv2.VideoCapture | None:
    """Try FFmpeg backend first, fall back to OS default."""
    for backend in (cv2.CAP_FFMPEG, cv2.CAP_ANY):
        cap = cv2.VideoCapture(path, backend)
        if cap.isOpened():
            return cap
        cap.release()
    return None


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    defaults = {
        "recent": [],
        "last_output_dir": str(Path.home() / "Desktop"),
        "export_format": "PNG",
        "export_quality": 90,
        "export_scale": "100%",
        "naming_template": DEFAULT_TEMPLATE,
        "show_overlay": True,
        "speed": "1x",
    }
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            defaults.update(data)
        except Exception:
            pass
    return defaults


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Frame Cache ───────────────────────────────────────────────────────────────

class FrameCache:
    def __init__(self, maxsize: int = 40):
        self._cache: dict[int, np.ndarray] = {}
        self._order: list[int] = []
        self._maxsize = maxsize

    def get(self, idx: int) -> np.ndarray | None:
        return self._cache.get(idx)

    def put(self, idx: int, frame: np.ndarray) -> None:
        if idx in self._cache:
            self._order.remove(idx)
        elif len(self._order) >= self._maxsize:
            del self._cache[self._order.pop(0)]
        self._cache[idx] = frame
        self._order.append(idx)

    def clear(self) -> None:
        self._cache.clear()
        self._order.clear()


# ── Preview Thread ────────────────────────────────────────────────────────────

class PreviewThread(QThread):
    """Decodes single frames in background for hover-scrubber preview."""
    preview_ready = pyqtSignal(int, object)   # frame_idx, ndarray

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap   = None
        self._mutex = QMutex()
        self._cond  = QWaitCondition()
        self._pending_frame: int = -1
        self._pending_path: str | None = None
        self._running = True

    def open_video(self, path: str) -> None:
        self._mutex.lock()
        self._pending_path = path
        self._mutex.unlock()
        self._cond.wakeOne()

    def request(self, frame_idx: int) -> None:
        self._mutex.lock()
        self._pending_frame = frame_idx   # overwrites previous; only latest matters
        self._mutex.unlock()
        self._cond.wakeOne()

    def stop(self) -> None:
        self._mutex.lock()
        self._running = False
        self._mutex.unlock()
        self._cond.wakeOne()
        self.wait(3000)

    def run(self) -> None:
        while True:
            self._mutex.lock()
            while (self._running
                   and self._pending_frame < 0
                   and self._pending_path is None):
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            path  = self._pending_path
            idx   = self._pending_frame
            self._pending_path  = None
            self._pending_frame = -1
            self._mutex.unlock()

            if path is not None:
                if self._cap:
                    self._cap.release()
                self._cap = open_cap(path)

            if idx >= 0 and self._cap and self._cap.isOpened():
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = self._cap.read()
                if ret:
                    self.preview_ready.emit(idx, frame.copy())

        if self._cap:
            self._cap.release()


# ── Mark Slider ───────────────────────────────────────────────────────────────

class MarkSlider(QSlider):
    """QSlider that paints mark ticks and emits hover frame index."""
    hovered_frame = pyqtSignal(int, QPoint)
    hover_left    = pyqtSignal()

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._marks: dict[int, str] = {}   # frame_idx -> color hex
        self.setMouseTracking(True)

    def set_marks(self, marks: dict[int, str]) -> None:
        self._marks = marks
        self.update()

    def _groove_rect(self) -> QRect:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self,
        )

    def _frame_to_x(self, idx: int) -> int:
        gr = self._groove_rect()
        pos = QStyle.sliderPositionFromValue(
            self.minimum(), self.maximum(), idx, gr.width()
        )
        return gr.x() + pos

    def _x_to_frame(self, x: int) -> int:
        gr = self._groove_rect()
        rel = max(0, min(x - gr.x(), gr.width()))
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), rel, gr.width()
        )

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.maximum() > 0:
            self.hovered_frame.emit(
                self._x_to_frame(event.pos().x()),
                self.mapToGlobal(event.pos()),
            )

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.hover_left.emit()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._marks or self.maximum() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() // 2
        painter.setPen(Qt.PenStyle.NoPen)
        for idx, color_hex in self._marks.items():
            col = QColor(color_hex)
            col.setAlpha(215)
            painter.setBrush(col)
            x = self._frame_to_x(idx)
            painter.drawRoundedRect(x - 1, cy - 7, 3, 14, 1, 1)


# ── Video Display ─────────────────────────────────────────────────────────────

class VideoDisplay(QLabel):
    wheel_delta  = pyqtSignal(int)
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)
        self._bgr: np.ndarray | None = None
        self._overlay_text = ""
        self._show_overlay = True
        self._placeholder()

    def _placeholder(self):
        self.setStyleSheet(
            f"background-color: {CRUST}; border-radius: 10px; "
            f"color: {SUBTEXT0}; font-size: 16px;"
        )
        self.setText("Open a video file or drop one here")

    def show_frame(self, bgr: np.ndarray):
        self._bgr = bgr
        self.setStyleSheet(f"background-color: {CRUST}; border-radius: 10px;")
        self._refresh()

    def set_overlay(self, text: str):
        self._overlay_text = text
        self.update()

    def set_show_overlay(self, val: bool):
        self._show_overlay = val
        self.update()

    def _refresh(self):
        if self._bgr is None:
            return
        self.setPixmap(
            bgr_to_pixmap(self._bgr).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._show_overlay or not self._overlay_text or self._bgr is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont("Consolas", 10))
        fm  = painter.fontMetrics()
        tw  = fm.horizontalAdvance(self._overlay_text)
        th  = fm.height()
        pad, mg = 6, 8
        rx = self.width()  - tw - mg - pad * 2
        ry = self.height() - th - mg - pad * 2
        bg = QColor(CRUST)
        bg.setAlpha(185)
        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rx, ry, tw + pad * 2, th + pad * 2, 4, 4)
        painter.setPen(QColor(MAUVE))
        painter.drawText(rx + pad, ry + pad + fm.ascent(), self._overlay_text)

    def wheelEvent(self, event):
        d = event.angleDelta().y()
        if d > 0:   self.wheel_delta.emit(-1)
        elif d < 0: self.wheel_delta.emit(1)

    def dragEnterEvent(self, event: QDragEnterEvent):
        # Accept any file — let cv2 decide if it's valid
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            self.file_dropped.emit(urls[0].toLocalFile())


# ── Frame Item Widget ─────────────────────────────────────────────────────────

class FrameItemWidget(QWidget):
    remove_requested = pyqtSignal(int)
    jump_requested   = pyqtSignal(int)

    def __init__(self, frame_idx: int, fps: float,
                 thumb: QPixmap | None, label: str = "",
                 color: str = MAUVE, parent=None):
        super().__init__(parent)
        self.frame_idx = frame_idx
        self.fps       = fps
        self.setFixedHeight(72)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 6, 0)
        root.setSpacing(0)

        # Color bar
        self._color_bar = QFrame()
        self._color_bar.setFixedWidth(4)
        root.addWidget(self._color_bar)

        inner = QHBoxLayout()
        inner.setContentsMargins(8, 4, 0, 4)
        inner.setSpacing(10)
        root.addLayout(inner)

        # Thumbnail
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(96, 54)
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setStyleSheet(
            f"border: 1px solid {SURFACE1}; border-radius: 4px; background: {CRUST};"
        )
        if thumb:
            thumb_lbl.setPixmap(thumb)
        inner.addWidget(thumb_lbl)

        # Info
        info = QVBoxLayout()
        info.setSpacing(1)
        ms = frame_to_ms(frame_idx, fps)
        self._ts_lbl    = QLabel(ms_to_ts(ms))
        self._ts_lbl.setStyleSheet(f"color: {TEXT}; font-weight: bold; font-size: 13px;")
        self._frame_lbl = QLabel(f"Frame {frame_idx:,}")
        self._frame_lbl.setStyleSheet(f"color: {SUBTEXT0}; font-size: 11px;")
        self._label_lbl = QLabel(label)
        self._label_lbl.setStyleSheet(f"color: {PEACH}; font-size: 11px; font-style: italic;")
        self._label_lbl.setVisible(bool(label))
        info.addWidget(self._ts_lbl)
        info.addWidget(self._frame_lbl)
        info.addWidget(self._label_lbl)
        inner.addLayout(info)
        inner.addStretch()

        jump_btn = QPushButton("Go")
        jump_btn.setFixedSize(36, 28)
        jump_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BLUE}; color: {CRUST};
                border: none; border-radius: 5px; font-size: 11px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {LAVENDER}; }}
        """)
        jump_btn.clicked.connect(lambda: self.jump_requested.emit(self.frame_idx))

        del_btn = QPushButton("x")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {SURFACE0}; color: {RED};
                border: 1px solid {SURFACE1}; border-radius: 14px;
                font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {RED}; color: {CRUST}; border-color: {RED}; }}
        """)
        del_btn.clicked.connect(lambda: self.remove_requested.emit(self.frame_idx))

        inner.addWidget(jump_btn)
        inner.addWidget(del_btn)

        self.set_color(color)

    def set_color(self, color_hex: str):
        self._color_bar.setStyleSheet(
            f"background: {color_hex}; border-radius: 2px;"
        )

    def update_label(self, label: str):
        self._label_lbl.setText(label)
        self._label_lbl.setVisible(bool(label))


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FrameSnap v2.1.0")
        self.setMinimumSize(1100, 680)
        self.resize(1380, 860)
        self.setAcceptDrops(True)

        self._cfg = load_config()

        # Video state
        self.cap: cv2.VideoCapture | None = None
        self._video_path = ""
        self.total_frames = 0       # 0 means unknown
        self.fps          = 30.0
        self.current_frame = 0
        self.is_playing   = False
        self._loop_mode   = False
        self._speed       = 1.0
        self._slider_held = False
        self._last_bgr: np.ndarray | None = None
        self._cache = FrameCache(40)

        # Marks: frame_idx -> {item, widget, label, color}
        self.marked: dict[int, dict] = {}

        self._preview_thread = PreviewThread(self)
        self._preview_thread.preview_ready.connect(self._on_preview_ready)
        self._preview_thread.start()
        self._pending_hover_pos = QPoint()

        self._build_menu()
        self._build_ui()
        self._build_timer()
        self._build_hover_popup()
        self._apply_config()

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        self._recent_menu = QMenu("Recent Files", self)
        file_menu.addAction(self._make_act("Open Video...", self.open_video))
        file_menu.addSeparator()
        file_menu.addMenu(self._recent_menu)
        file_menu.addSeparator()
        file_menu.addAction(self._make_act("Save Session...", self.save_session))
        file_menu.addAction(self._make_act("Load Session...", self.load_session))
        file_menu.addSeparator()
        file_menu.addAction(self._make_act("Exit", self.close))

        edit_menu = mb.addMenu("Edit")
        edit_menu.addAction(self._make_act("Mark Current Frame", self.mark_frame))
        edit_menu.addAction(self._make_act("Clear All Marks",    self.clear_marks))
        edit_menu.addSeparator()
        edit_menu.addAction(self._make_act("Copy Current Frame to Clipboard",
                                            self.copy_frame_clipboard))

        view_menu = mb.addMenu("View")
        self._act_overlay = self._make_act("Frame Overlay", self._toggle_overlay,
                                            checkable=True,
                                            checked=self._cfg.get("show_overlay", True))
        view_menu.addAction(self._act_overlay)

        self._refresh_recent_menu()

    def _make_act(self, label: str, slot, checkable=False, checked=False) -> QAction:
        act = QAction(label, self)
        if checkable:
            act.setCheckable(True)
            act.setChecked(checked)
            act.triggered.connect(slot)
        else:
            act.triggered.connect(slot)
        return act

    def _refresh_recent_menu(self):
        self._recent_menu.clear()
        recents = self._cfg.get("recent", [])
        if not recents:
            no_act = QAction("(none)", self)
            no_act.setEnabled(False)
            self._recent_menu.addAction(no_act)
            return
        for path in recents:
            act = QAction(Path(path).name, self)
            act.setToolTip(path)
            act.triggered.connect(lambda _, p=path: self._open_path(p))
            self._recent_menu.addAction(act)

    def _push_recent(self, path: str):
        recents = self._cfg.get("recent", [])
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self._cfg["recent"] = recents[:MAX_RECENT]
        save_config(self._cfg)
        self._refresh_recent_menu()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Left ──────────────────────────────────────────────────────────────
        left_w = QWidget()
        left   = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)

        top_bar = QHBoxLayout()
        open_btn = QPushButton("Open Video...")
        open_btn.setFixedHeight(34)
        open_btn.clicked.connect(self.open_video)
        self._file_lbl = QLabel("No file loaded")
        self._file_lbl.setStyleSheet(f"color: {SUBTEXT0}; font-size: 12px;")
        top_bar.addWidget(open_btn)
        top_bar.addWidget(self._file_lbl, 1)
        left.addLayout(top_bar)

        self._info_bar = QLabel("")
        self._info_bar.setStyleSheet(f"color: {OVERLAY0}; font-size: 11px; padding: 2px 0;")
        self._info_bar.hide()
        left.addWidget(self._info_bar)

        self.display = VideoDisplay()
        self.display.wheel_delta.connect(self.step)
        self.display.file_dropped.connect(self._open_path)
        left.addWidget(self.display, 1)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        left.addWidget(div)

        # Scrubber
        scrub = QHBoxLayout()
        self._pos_lbl = QLabel("00:00:00.000")
        self._pos_lbl.setStyleSheet(
            f"color: {MAUVE}; font-family: Consolas, monospace; "
            f"font-size: 13px; min-width: 105px;"
        )
        self.slider = MarkSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self._slider_press)
        self.slider.sliderReleased.connect(self._slider_release)
        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.hovered_frame.connect(self._slider_hovered)
        self.slider.hover_left.connect(self._slider_hover_left)
        self._dur_lbl = QLabel("00:00:00.000")
        self._dur_lbl.setStyleSheet(
            f"color: {SUBTEXT0}; font-family: Consolas, monospace; "
            f"font-size: 13px; min-width: 105px;"
        )
        self._dur_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scrub.addWidget(self._pos_lbl)
        scrub.addWidget(self.slider, 1)
        scrub.addWidget(self._dur_lbl)
        left.addLayout(scrub)

        # Controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)

        self._btn_p10  = QPushButton("-10")
        self._btn_p1   = QPushButton("-1")
        self._btn_play = QPushButton("Play")
        self._btn_n1   = QPushButton("+1")
        self._btn_n10  = QPushButton("+10")
        for b in (self._btn_p10, self._btn_p1, self._btn_play, self._btn_n1, self._btn_n10):
            b.setEnabled(False)
            b.setFixedHeight(32)
            ctrl.addWidget(b)
        self._btn_p10.clicked.connect(lambda: self.step(-10))
        self._btn_p1.clicked.connect(lambda: self.step(-1))
        self._btn_play.clicked.connect(self.toggle_play)
        self._btn_n1.clicked.connect(lambda: self.step(1))
        self._btn_n10.clicked.connect(lambda: self.step(10))

        # Speed combo
        self._speed_combo = QComboBox()
        self._speed_combo.addItems(["0.25x", "0.5x", "1x", "2x", "4x"])
        self._speed_combo.setCurrentText("1x")
        self._speed_combo.setFixedHeight(32)
        self._speed_combo.currentTextChanged.connect(self._speed_changed)
        ctrl.addWidget(self._speed_combo)

        # Loop button
        self._loop_btn = QPushButton("Loop")
        self._loop_btn.setObjectName("loopBtn")
        self._loop_btn.setFixedHeight(32)
        self._loop_btn.setCheckable(True)
        self._loop_btn.toggled.connect(self._loop_toggled)
        ctrl.addWidget(self._loop_btn)

        ctrl.addStretch()

        self._btn_prev_mark = QPushButton("< Prev")
        self._btn_prev_mark.setEnabled(False)
        self._btn_prev_mark.setFixedHeight(32)
        self._btn_prev_mark.clicked.connect(self.jump_prev_mark)

        self._btn_next_mark = QPushButton("Next >")
        self._btn_next_mark.setEnabled(False)
        self._btn_next_mark.setFixedHeight(32)
        self._btn_next_mark.clicked.connect(self.jump_next_mark)

        self._copy_btn = QPushButton("Copy Frame")
        self._copy_btn.setObjectName("copyBtn")
        self._copy_btn.setEnabled(False)
        self._copy_btn.setFixedHeight(38)
        self._copy_btn.clicked.connect(self.copy_frame_clipboard)

        self._mark_btn = QPushButton("Mark Frame")
        self._mark_btn.setObjectName("markBtn")
        self._mark_btn.setEnabled(False)
        self._mark_btn.setFixedHeight(38)
        self._mark_btn.clicked.connect(self.mark_frame)

        ctrl.addWidget(self._btn_prev_mark)
        ctrl.addWidget(self._btn_next_mark)
        ctrl.addSpacing(8)
        ctrl.addWidget(self._copy_btn)
        ctrl.addWidget(self._mark_btn)
        left.addLayout(ctrl)

        # ── Right ─────────────────────────────────────────────────────────────
        right_w = QWidget()
        right_w.setMinimumWidth(320)
        right_w.setMaximumWidth(430)
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        self._tabs = QTabWidget()
        right.addWidget(self._tabs)

        # Tab 1: Marks
        marks_tab = QWidget()
        ml = QVBoxLayout(marks_tab)
        ml.setContentsMargins(8, 8, 8, 8)
        ml.setSpacing(6)

        self._marks_list = QListWidget()
        self._marks_list.setSpacing(2)
        self._marks_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._marks_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._marks_list.customContextMenuRequested.connect(self._marks_context_menu)
        self._marks_list.itemDoubleClicked.connect(
            lambda item: self._jump_to(item.data(Qt.ItemDataRole.UserRole))
        )
        ml.addWidget(self._marks_list, 1)

        nav_row = QHBoxLayout()
        self._count_lbl = QLabel("0 frames marked")
        self._count_lbl.setStyleSheet(f"color: {SUBTEXT0}; font-size: 11px;")
        sel_all = QPushButton("All")
        sel_all.setFixedHeight(28)
        sel_all.clicked.connect(self._marks_list.selectAll)
        self._del_sel_btn = QPushButton("Del Sel")
        self._del_sel_btn.setObjectName("dangerBtn")
        self._del_sel_btn.setFixedHeight(28)
        self._del_sel_btn.setEnabled(False)
        self._del_sel_btn.clicked.connect(self._delete_selected)
        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setObjectName("dangerBtn")
        self._clear_btn.setFixedHeight(28)
        self._clear_btn.setEnabled(False)
        self._clear_btn.clicked.connect(self.clear_marks)
        nav_row.addWidget(self._count_lbl)
        nav_row.addStretch()
        nav_row.addWidget(sel_all)
        nav_row.addWidget(self._del_sel_btn)
        nav_row.addWidget(self._clear_btn)
        ml.addLayout(nav_row)
        self._tabs.addTab(marks_tab, "Marks (0)")

        # Tab 2: Export
        export_tab = QWidget()
        el = QVBoxLayout(export_tab)
        el.setContentsMargins(10, 10, 10, 10)
        el.setSpacing(10)

        # Format
        fmt_g = QGroupBox("Format")
        fi = QVBoxLayout(fmt_g)
        fi.setSpacing(6)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(["PNG", "JPEG", "WebP", "TIFF", "BMP", "GIF"])
        self._fmt_combo.currentTextChanged.connect(self._fmt_changed)
        fmt_row.addWidget(self._fmt_combo)
        fmt_row.addStretch()
        fi.addLayout(fmt_row)
        qual_row = QHBoxLayout()
        self._qual_lbl_l = QLabel("Quality:")
        self._qual_spin  = QSpinBox()
        self._qual_spin.setRange(1, 100)
        self._qual_spin.setValue(90)
        self._qual_spin.setSuffix("%")
        self._qual_spin.setFixedWidth(75)
        self._qual_lbl_l.setEnabled(False)
        self._qual_spin.setEnabled(False)
        qual_row.addWidget(self._qual_lbl_l)
        qual_row.addWidget(self._qual_spin)
        qual_row.addStretch()
        fi.addLayout(qual_row)
        el.addWidget(fmt_g)

        # Scale
        scale_g = QGroupBox("Scale")
        si = QVBoxLayout(scale_g)
        si.setSpacing(6)
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Scale:"))
        self._scale_combo = QComboBox()
        self._scale_combo.addItems(["100%", "75%", "50%", "25%", "Custom"])
        self._scale_combo.currentTextChanged.connect(self._scale_changed)
        scale_row.addWidget(self._scale_combo)
        scale_row.addStretch()
        si.addLayout(scale_row)
        cust_row = QHBoxLayout()
        self._cust_lbl  = QLabel("Width px:")
        self._cust_spin = QSpinBox()
        self._cust_spin.setRange(1, 7680)
        self._cust_spin.setValue(1280)
        self._cust_spin.setSingleStep(10)
        self._cust_lbl.setVisible(False)
        self._cust_spin.setVisible(False)
        cust_row.addWidget(self._cust_lbl)
        cust_row.addWidget(self._cust_spin)
        cust_row.addStretch()
        si.addLayout(cust_row)
        el.addWidget(scale_g)

        # Naming
        name_g = QGroupBox("Filename Template")
        ni = QVBoxLayout(name_g)
        ni.setSpacing(4)
        self._name_edit = QLineEdit(DEFAULT_TEMPLATE)
        self._name_edit.setPlaceholderText("{stem}_{frame}_{ts}")
        ni.addWidget(self._name_edit)
        hint = QLabel("Variables: {stem}  {frame}  {ts}  {label}  {n}")
        hint.setStyleSheet(f"color: {OVERLAY0}; font-size: 10px;")
        ni.addWidget(hint)
        el.addWidget(name_g)

        # Output
        out_g = QGroupBox("Output Folder")
        oi = QVBoxLayout(out_g)
        oi.setSpacing(6)
        dir_row = QHBoxLayout()
        self._dir_edit = QLineEdit(self._cfg.get("last_output_dir", ""))
        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedHeight(30)
        browse_btn.clicked.connect(self.browse_dir)
        dir_row.addWidget(self._dir_edit, 1)
        dir_row.addWidget(browse_btn)
        oi.addLayout(dir_row)

        export_row = QHBoxLayout()
        self._export_btn = QPushButton("Export All Frames")
        self._export_btn.setObjectName("exportBtn")
        self._export_btn.setEnabled(False)
        self._export_btn.setFixedHeight(38)
        self._export_btn.clicked.connect(self.export_frames)
        self._open_dir_btn = QPushButton("Open Folder")
        self._open_dir_btn.setFixedHeight(38)
        self._open_dir_btn.clicked.connect(self.open_export_dir)
        export_row.addWidget(self._export_btn, 1)
        export_row.addWidget(self._open_dir_btn)
        oi.addLayout(export_row)

        self._sheet_btn = QPushButton("Contact Sheet...")
        self._sheet_btn.setObjectName("sheetBtn")
        self._sheet_btn.setEnabled(False)
        self._sheet_btn.setFixedHeight(34)
        self._sheet_btn.clicked.connect(self.export_contact_sheet)
        oi.addWidget(self._sheet_btn)
        el.addWidget(out_g)

        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
        self._status_lbl.setWordWrap(True)
        el.addWidget(self._status_lbl)
        el.addStretch()
        self._tabs.addTab(export_tab, "Export")

        splitter.addWidget(left_w)
        splitter.addWidget(right_w)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

    def _build_timer(self):
        self._timer = QTimer()
        self._timer.timeout.connect(self._advance)

    def _build_hover_popup(self):
        self._hover_popup = QWidget(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._hover_popup.setFixedSize(192, 130)
        self._hover_popup.setStyleSheet(
            f"background: {CRUST}; border: 1px solid {SURFACE1}; border-radius: 6px;"
        )
        pl = QVBoxLayout(self._hover_popup)
        pl.setContentsMargins(4, 4, 4, 4)
        pl.setSpacing(3)
        self._hover_thumb_lbl = QLabel()
        self._hover_thumb_lbl.setFixedSize(184, 104)
        self._hover_thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hover_thumb_lbl.setStyleSheet(f"background: {MANTLE}; border-radius: 4px;")
        self._hover_ts_lbl = QLabel("")
        self._hover_ts_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hover_ts_lbl.setStyleSheet(
            f"color: {MAUVE}; font-family: Consolas, monospace; font-size: 11px;"
        )
        pl.addWidget(self._hover_thumb_lbl)
        pl.addWidget(self._hover_ts_lbl)
        self._hover_popup.hide()

    def _apply_config(self):
        cfg = self._cfg
        self._fmt_combo.setCurrentText(cfg.get("export_format", "PNG"))
        self._qual_spin.setValue(cfg.get("export_quality", 90))
        self._scale_combo.setCurrentText(cfg.get("export_scale", "100%"))
        self._name_edit.setText(cfg.get("naming_template", DEFAULT_TEMPLATE))
        self._speed_combo.setCurrentText(cfg.get("speed", "1x"))
        overlay_on = cfg.get("show_overlay", True)
        self._act_overlay.setChecked(overlay_on)
        self.display.set_show_overlay(overlay_on)

    # ── Video loading ─────────────────────────────────────────────────────────

    def open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "", VIDEO_FILTER
        )
        if path:
            self._open_path(path)

    def _open_path(self, path: str):
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Not Found", f"File not found:\n{path}")
            return

        # BUG FIX: stop timer BEFORE releasing old cap
        self._timer.stop()
        self.is_playing = False
        self._btn_play.setText("Play")

        if self.cap:
            self.cap.release()
            self.cap = None

        cap = open_cap(path)
        if cap is None or not cap.isOpened():
            QMessageBox.critical(self, "Error",
                                 f"Cannot open video:\n{path}\n\n"
                                 "File may be unsupported or missing codec.")
            return

        self.cap = cap
        self._video_path = path

        # BUG FIX: handle formats where FRAME_COUNT is 0 or -1
        raw_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if raw_count > 0:
            self.total_frames = raw_count
        else:
            # Estimate from duration property (seconds)
            dur_s = cap.get(cv2.CAP_PROP_POS_AVI_RATIO)
            self.total_frames = 0   # unknown; slider will be disabled

        self.current_frame = 0
        self._cache.clear()

        # BUG FIX: clear stale marks from previous video
        self.clear_marks()

        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, self.total_frames - 1))
        self.slider.setValue(0)
        self.slider.setEnabled(self.total_frames > 0)
        self.slider.blockSignals(False)

        if self.total_frames > 0:
            self._dur_lbl.setText(ms_to_ts(frame_to_ms(self.total_frames, self.fps)))
        else:
            self._dur_lbl.setText("--:--:--.---")

        self._file_lbl.setText(Path(path).name)

        vw  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        vh  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        sz  = os.path.getsize(path)
        tf  = f"{self.total_frames:,}" if self.total_frames else "unknown"
        self._info_bar.setText(
            f"  {vw}x{vh}  |  {self.fps:.3f} fps  |  "
            f"{ms_to_ts(frame_to_ms(self.total_frames or 0, self.fps))}  |  "
            f"{tf} frames  |  {sizeof_fmt(sz)}"
        )
        self._info_bar.show()

        for b in (self._btn_p10, self._btn_p1, self._btn_play,
                  self._btn_n1, self._btn_n10,
                  self._mark_btn, self._copy_btn):
            b.setEnabled(True)

        self._preview_thread.open_video(path)
        self._show(0)
        self._push_recent(path)

    # ── Playback ──────────────────────────────────────────────────────────────

    def _show(self, idx: int):
        if not self.cap:
            return
        if self.total_frames > 0:
            idx = max(0, min(idx, self.total_frames - 1))
        else:
            idx = max(0, idx)

        cached = self._cache.get(idx)
        if cached is not None:
            frame = cached
            # Only sync cap position when playing so _advance reads correctly
            if self.is_playing:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx + 1)
        else:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = self.cap.read()
            if not ret:
                return
            self._cache.put(idx, frame)

        self.current_frame = idx
        self._last_bgr     = frame
        self.display.show_frame(frame)
        ms = frame_to_ms(idx, self.fps)
        self._pos_lbl.setText(ms_to_ts(ms))
        tf  = f" / {self.total_frames:,}" if self.total_frames else ""
        self.display.set_overlay(f"Frame {idx:,}{tf}  |  {ms_to_ts(ms)}")

        if not self._slider_held and self.total_frames > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(idx)
            self.slider.blockSignals(False)

    def _advance(self):
        if not self.cap:
            return
        nxt = self.current_frame + 1

        # BUG FIX: total_frames == 0 means unknown — don't stop based on it
        if self.total_frames > 0 and nxt >= self.total_frames:
            if self._loop_mode:
                self._show(0)
                # Restart timer so cap position is correct
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 1)
            else:
                self.toggle_play()
            return

        ret, frame = self.cap.read()
        if not ret:
            # BUG FIX: resync cap on failure rather than silently drifting
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, nxt)
            ret, frame = self.cap.read()
            if not ret:
                self.toggle_play()
                return

        self._cache.put(nxt, frame)
        self.current_frame = nxt
        self._last_bgr     = frame
        self.display.show_frame(frame)
        ms = frame_to_ms(nxt, self.fps)
        self._pos_lbl.setText(ms_to_ts(ms))
        tf = f" / {self.total_frames:,}" if self.total_frames else ""
        self.display.set_overlay(f"Frame {nxt:,}{tf}  |  {ms_to_ts(ms)}")

        if not self._slider_held and self.total_frames > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(nxt)
            self.slider.blockSignals(False)

    def toggle_play(self):
        if not self.cap:
            return
        self.is_playing = not self.is_playing
        if self.is_playing:
            self._btn_play.setText("Pause")
            interval = max(1, int(1000.0 / (self.fps * self._speed)))
            self._timer.start(interval)
        else:
            self._btn_play.setText("Play")
            self._timer.stop()

    def step(self, delta: int):
        if not self.cap:
            return
        if self.is_playing:
            self.toggle_play()
        self._show(self.current_frame + delta)

    def _slider_press(self):
        self._slider_held = True
        if self.is_playing:
            self._timer.stop()

    def _slider_release(self):
        self._slider_held = False
        self._show(self.slider.value())
        if self.is_playing:
            interval = max(1, int(1000.0 / (self.fps * self._speed)))
            self._timer.start(interval)

    def _slider_changed(self, val: int):
        if self._slider_held:
            self._show(val)

    def _speed_changed(self, text: str):
        try:
            self._speed = float(text.rstrip("x"))
        except ValueError:
            self._speed = 1.0
        if self.is_playing:
            interval = max(1, int(1000.0 / (self.fps * self._speed)))
            self._timer.setInterval(interval)
        self._cfg["speed"] = text
        save_config(self._cfg)

    def _loop_toggled(self, checked: bool):
        self._loop_mode = checked
        self._loop_btn.setProperty("active", "true" if checked else "false")
        self._loop_btn.style().unpolish(self._loop_btn)
        self._loop_btn.style().polish(self._loop_btn)

    # ── Hover preview ─────────────────────────────────────────────────────────

    def _slider_hovered(self, frame_idx: int, global_pos: QPoint):
        if not self.cap:
            return
        self._pending_hover_pos = global_pos
        self._preview_thread.request(frame_idx)

    def _slider_hover_left(self):
        self._hover_popup.hide()

    def _on_preview_ready(self, frame_idx: int, bgr: np.ndarray):
        px = bgr_to_pixmap(bgr).scaled(
            184, 104,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._hover_thumb_lbl.setPixmap(px)
        self._hover_ts_lbl.setText(ms_to_ts(frame_to_ms(frame_idx, self.fps)))
        gp = self._pending_hover_pos
        x, y = gp.x() - 96, gp.y() - 148
        screen = QApplication.primaryScreen().availableGeometry()
        x = max(screen.left(), min(x, screen.right()  - 192))
        y = max(screen.top(),  min(y, screen.bottom() - 130))
        self._hover_popup.move(x, y)
        self._hover_popup.show()

    # ── Marking ───────────────────────────────────────────────────────────────

    def mark_frame(self):
        if not self.cap:
            return
        if self.is_playing:
            self.toggle_play()
        idx = self.current_frame
        if idx in self.marked:
            self._marks_list.setCurrentItem(self.marked[idx]["item"])
            self._set_status(f"Already marked: {ms_to_ts(frame_to_ms(idx, self.fps))}", YELLOW)
            return

        thumb  = make_thumb(self._last_bgr) if self._last_bgr is not None else None
        color  = MAUVE
        widget = FrameItemWidget(idx, self.fps, thumb, color=color)
        widget.remove_requested.connect(self._remove_mark)
        widget.jump_requested.connect(self._jump_to)

        list_item = QListWidgetItem()
        list_item.setSizeHint(QSize(0, 72))
        list_item.setData(Qt.ItemDataRole.UserRole, idx)

        pos = self._marks_list.count()
        for i in range(self._marks_list.count()):
            if self._marks_list.item(i).data(Qt.ItemDataRole.UserRole) > idx:
                pos = i
                break
        self._marks_list.insertItem(pos, list_item)
        self._marks_list.setItemWidget(list_item, widget)
        self.marked[idx] = {"item": list_item, "widget": widget, "label": "", "color": color}

        self.slider.set_marks({k: v["color"] for k, v in self.marked.items()})
        self._update_marks_ui()
        self._set_status(f"Marked: {ms_to_ts(frame_to_ms(idx, self.fps))}", GREEN)
        self._tabs.setCurrentIndex(0)

    def _remove_mark(self, idx: int):
        if idx not in self.marked:
            return
        item = self.marked.pop(idx)["item"]
        self._marks_list.takeItem(self._marks_list.row(item))
        self.slider.set_marks({k: v["color"] for k, v in self.marked.items()})
        self._update_marks_ui()

    def _delete_selected(self):
        for item in list(self._marks_list.selectedItems()):
            idx = item.data(Qt.ItemDataRole.UserRole)
            if idx in self.marked:
                self.marked.pop(idx)
                self._marks_list.takeItem(self._marks_list.row(item))
        self.slider.set_marks({k: v["color"] for k, v in self.marked.items()})
        self._update_marks_ui()

    def clear_marks(self):
        self._marks_list.clear()
        self.marked.clear()
        self.slider.set_marks({})
        self._update_marks_ui()

    def _update_marks_ui(self):
        n   = len(self.marked)
        self._count_lbl.setText(f"{n} frame{'s' if n != 1 else ''} marked")
        self._tabs.setTabText(0, f"Marks ({n})")
        has = n > 0
        self._export_btn.setEnabled(has)
        self._sheet_btn.setEnabled(has)
        self._clear_btn.setEnabled(has)
        self._del_sel_btn.setEnabled(has)
        self._btn_prev_mark.setEnabled(has)
        self._btn_next_mark.setEnabled(has)

    def _marks_context_menu(self, pos):
        item = self._marks_list.itemAt(pos)
        if not item:
            return
        idx  = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        act_jump  = menu.addAction("Jump to Frame")
        act_copy  = menu.addAction("Copy Frame to Clipboard")
        menu.addSeparator()
        act_label = menu.addAction("Edit Label...")
        # Color submenu
        color_menu = menu.addMenu("Set Color")
        color_acts = {}
        for name, hex_val in MARK_COLORS.items():
            ca = color_menu.addAction(name)
            color_acts[ca] = (name, hex_val)
        menu.addSeparator()
        act_del = menu.addAction("Remove")

        chosen = menu.exec(self._marks_list.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_jump:
            self._jump_to(idx)
        elif chosen == act_copy:
            self._copy_mark_frame(idx)
        elif chosen == act_label:
            self._edit_label(idx)
        elif chosen == act_del:
            self._remove_mark(idx)
        elif chosen in color_acts:
            _, hex_val = color_acts[chosen]
            self._set_mark_color(idx, hex_val)

    def _set_mark_color(self, idx: int, color_hex: str):
        if idx not in self.marked:
            return
        self.marked[idx]["color"] = color_hex
        self.marked[idx]["widget"].set_color(color_hex)
        self.slider.set_marks({k: v["color"] for k, v in self.marked.items()})

    def _jump_to(self, idx: int):
        if self.is_playing:
            self.toggle_play()
        self._show(idx)

    def jump_prev_mark(self):
        keys = sorted(k for k in self.marked if k < self.current_frame)
        if keys:
            self._jump_to(keys[-1])

    def jump_next_mark(self):
        keys = sorted(k for k in self.marked if k > self.current_frame)
        if keys:
            self._jump_to(keys[0])

    def _edit_label(self, idx: int):
        if idx not in self.marked:
            return
        text, ok = QInputDialog.getText(
            self, "Edit Label", "Label for this mark:",
            text=self.marked[idx]["label"],
        )
        if ok:
            self.marked[idx]["label"] = text
            self.marked[idx]["widget"].update_label(text)

    # ── Clipboard ─────────────────────────────────────────────────────────────

    def copy_frame_clipboard(self):
        if self._last_bgr is None:
            return
        QApplication.clipboard().setPixmap(bgr_to_pixmap(self._last_bgr))
        self._set_status("Frame copied to clipboard.", BLUE)

    def _copy_mark_frame(self, idx: int):
        if not self.cap:
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = self.cap.read()
        # BUG FIX: restore cap position regardless of read success
        self._show(self.current_frame)
        if ret:
            QApplication.clipboard().setPixmap(bgr_to_pixmap(frame))
            self._set_status("Mark frame copied to clipboard.", BLUE)

    # ── Export ────────────────────────────────────────────────────────────────

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self._dir_edit.text()
        )
        if d:
            self._dir_edit.setText(d)

    def open_export_dir(self):
        d = self._dir_edit.text().strip()
        if not d or not os.path.isdir(d):
            return
        if sys.platform == "win32":
            os.startfile(d)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])

    def _collect_frames(self) -> list[tuple[int, np.ndarray, str]]:
        """Seek and read each marked frame. Returns [(idx, bgr, label), ...]."""
        results = []
        for idx in sorted(self.marked):
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = self.cap.read()
            if ret:
                results.append((idx, frame, self.marked[idx]["label"]))
        self._show(self.current_frame)
        return results

    def _apply_scale(self, frame: np.ndarray, scale: str) -> np.ndarray:
        scale_map = {"100%": 1.0, "75%": 0.75, "50%": 0.5, "25%": 0.25}
        f = scale_map.get(scale)
        if f and f != 1.0:
            h, w = frame.shape[:2]
            return cv2.resize(frame, (int(w * f), int(h * f)),
                              interpolation=cv2.INTER_LANCZOS4)
        if scale == "Custom":
            cw = self._cust_spin.value()
            h, w = frame.shape[:2]
            return cv2.resize(frame, (cw, int(h * cw / w)),
                              interpolation=cv2.INTER_LANCZOS4)
        return frame

    def export_frames(self):
        if not self.cap or not self.marked:
            return
        out_dir  = self._dir_edit.text().strip() or str(Path.home() / "Desktop")
        fmt      = self._fmt_combo.currentText()
        quality  = self._qual_spin.value()
        scale    = self._scale_combo.currentText()
        template = self._name_edit.text().strip() or DEFAULT_TEMPLATE
        stem     = Path(self._video_path).stem
        os.makedirs(out_dir, exist_ok=True)

        ext_map  = {"PNG": ".png", "JPEG": ".jpg", "WebP": ".webp",
                    "TIFF": ".tif", "BMP": ".bmp", "GIF": ".gif"}
        ext      = ext_map.get(fmt, ".png")
        enc_flags: list = []
        if fmt == "JPEG":
            enc_flags = [cv2.IMWRITE_JPEG_QUALITY, quality]
        elif fmt == "WebP":
            enc_flags = [cv2.IMWRITE_WEBP_QUALITY, quality]

        frames_data = self._collect_frames()
        exported, errors = 0, 0

        if fmt == "GIF":
            # Export all marks as separate GIFs (one frame each) or an animated GIF
            self._export_gif(frames_data, out_dir, stem, scale, quality)
            self._update_export_config(out_dir, fmt, quality, scale, template)
            return

        for n, (idx, frame, label) in enumerate(frames_data, start=1):
            frame = self._apply_scale(frame, scale)
            fname = apply_template(template, stem, idx, self.fps, label, n) + ext
            ok = cv2.imwrite(os.path.join(out_dir, fname), frame, enc_flags)
            if ok:
                exported += 1
            else:
                errors += 1

        self._update_export_config(out_dir, fmt, quality, scale, template)
        color = YELLOW if errors else GREEN
        self._set_status(
            f"Exported {exported} frame{'s' if exported != 1 else ''}"
            + (f" ({errors} failed)" if errors else "") + f"\n{out_dir}", color
        )
        self._tabs.setCurrentIndex(1)

    def _export_gif(self, frames_data: list, out_dir: str, stem: str,
                    scale: str, quality: int):
        if not frames_data:
            return
        pil_frames = []
        for _, bgr, _ in frames_data:
            bgr = self._apply_scale(bgr, scale)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            pil_frames.append(PilImage.fromarray(rgb).convert("P", palette=PilImage.ADAPTIVE,
                                                               dither=0))
        out_path = os.path.join(out_dir, f"{safe_filename(stem)}_marks.gif")
        pil_frames[0].save(
            out_path, save_all=True,
            append_images=pil_frames[1:],
            duration=500, loop=0, optimize=True,
        )
        self._set_status(f"Exported animated GIF ({len(pil_frames)} frames)\n{out_dir}", GREEN)
        self._tabs.setCurrentIndex(1)

    def export_contact_sheet(self):
        if not self.cap or not self.marked:
            return
        out_dir = self._dir_edit.text().strip() or str(Path.home() / "Desktop")
        os.makedirs(out_dir, exist_ok=True)

        n    = len(self.marked)
        cols = max(2, min(6, math.ceil(math.sqrt(n))))
        rows = math.ceil(n / cols)

        cell_w, cell_h, label_h = 320, 180, 26
        pad_c = [int(c * 0.9) for c in [30, 30, 46]]   # BASE in BGR

        sheet_w = cols * cell_w
        sheet_h = rows * (cell_h + label_h)
        sheet   = np.full((sheet_h, sheet_w, 3), pad_c, dtype=np.uint8)

        frames_data = self._collect_frames()
        for i, (idx, frame, label) in enumerate(frames_data):
            r, c = divmod(i, cols)
            x = c * cell_w
            y = r * (cell_h + label_h)
            # Fit frame into cell
            fh, fw = frame.shape[:2]
            scale_f = min(cell_w / fw, cell_h / fh)
            nw, nh  = int(fw * scale_f), int(fh * scale_f)
            resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
            ox = (cell_w - nw) // 2
            oy = (cell_h - nh) // 2
            sheet[y + oy:y + oy + nh, x + ox:x + ox + nw] = resized
            # Timestamp + label
            ts  = ms_to_ts(frame_to_ms(idx, self.fps))
            txt = f"{ts}" + (f"  {label}" if label else "")
            cv2.putText(sheet, txt, (x + 4, y + cell_h + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (203, 166, 247), 1, cv2.LINE_AA)

        stem     = Path(self._video_path).stem
        out_path = os.path.join(out_dir, f"{safe_filename(stem)}_contact_sheet.png")
        cv2.imwrite(out_path, sheet)
        self._set_status(f"Contact sheet saved ({n} frames)\n{out_path}", TEAL)
        self._tabs.setCurrentIndex(1)

    def _update_export_config(self, out_dir, fmt, quality, scale, template):
        self._cfg.update({
            "last_output_dir": out_dir,
            "export_format":   fmt,
            "export_quality":  quality,
            "export_scale":    scale,
            "naming_template": template,
        })
        save_config(self._cfg)

    # ── Session ───────────────────────────────────────────────────────────────

    def save_session(self):
        if not self._video_path:
            QMessageBox.warning(self, "No Video", "Open a video before saving a session.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session", "", "FrameSnap Session (*.fsnap)"
        )
        if not path:
            return
        if not path.endswith(".fsnap"):
            path += ".fsnap"
        data = {
            "version":     "2.1",
            "video_path":  self._video_path,
            "position":    self.current_frame,
            "marks": [
                {"frame": idx, "label": m["label"], "color": m["color"]}
                for idx, m in sorted(self.marked.items())
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._set_status(f"Session saved: {Path(path).name}", GREEN)

    def load_session(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Session", "", "FrameSnap Session (*.fsnap)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not read session:\n{e}")
            return

        video = data.get("video_path", "")
        if video and video != self._video_path:
            self._open_path(video)
            if not self.cap:
                return

        self.clear_marks()
        for entry in data.get("marks", []):
            fidx  = entry.get("frame", 0)
            label = entry.get("label", "")
            color = entry.get("color", MAUVE)
            if 0 <= fidx < max(self.total_frames, fidx + 1):
                # Temporarily set current_frame so mark_frame() uses it
                self.current_frame = fidx
                cached = self._cache.get(fidx)
                if cached is None:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
                    ret, frame = self.cap.read()
                    if ret:
                        self._last_bgr = frame
                        self._cache.put(fidx, frame)
                else:
                    self._last_bgr = cached
                self.mark_frame()
                if fidx in self.marked:
                    if label:
                        self.marked[fidx]["label"] = label
                        self.marked[fidx]["widget"].update_label(label)
                    self._set_mark_color(fidx, color)

        pos = data.get("position", 0)
        self._show(min(pos, max(0, self.total_frames - 1)) if self.total_frames else pos)
        self._set_status(f"Session loaded: {len(self.marked)} marks.", GREEN)

    # ── View toggles ──────────────────────────────────────────────────────────

    def _toggle_overlay(self, checked: bool):
        self.display.set_show_overlay(checked)
        self._cfg["show_overlay"] = checked
        save_config(self._cfg)

    def _fmt_changed(self, fmt: str):
        lossy = fmt in ("JPEG", "WebP")
        self._qual_lbl_l.setEnabled(lossy)
        self._qual_spin.setEnabled(lossy)

    def _scale_changed(self, scale: str):
        custom = scale == "Custom"
        self._cust_lbl.setVisible(custom)
        self._cust_spin.setVisible(custom)

    # ── Status ────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, color: str = GREEN):
        self._status_lbl.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._status_lbl.setText(msg)
        QTimer.singleShot(6000, lambda: self._status_lbl.setText(""))

    # ── Window drag-drop ──────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            self._open_path(urls[0].toLocalFile())

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._timer.stop()
        self._hover_popup.hide()
        self._preview_thread.stop()
        if self.cap:
            self.cap.release()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    branding_icon = QIcon(str(_branding_icon_path()))
    app.setWindowIcon(branding_icon)
    app.setApplicationName("FrameSnap")
    app.setApplicationVersion("2.1.0")
    app.setStyleSheet(STYLESHEET)

    icon_path = Path(__file__).parent / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    win = MainWindow()

    win.setWindowIcon(branding_icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
