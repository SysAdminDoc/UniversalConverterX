"""Clip / Trim dialog — visual scrubber + lossless (or re-encode) range cut.

Filmstrip of 20 ffmpeg-generated thumbnails with two draggable handles
(start / end) layered over them. A live preview image shows the current
playhead frame. HH:MM:SS text fields stay in sync with the handles and
accept manual entry.

Stream-copy (default) is keyframe-aligned (fast, can be off by up to one
GOP). Re-encode is frame-accurate (slower) and exposes the existing video
codec picker.

An audio waveform strip (F34) sits below the filmstrip, showing a filled
amplitude envelope extracted from the source audio. Peaks are cached as
`.waveform.bin` alongside the video so re-opens are instant.
"""

import os
import struct
import subprocess

from PyQt6.QtCore import Qt, QRectF, QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QProgressBar, QPushButton, QScrollArea,
    QSlider, QTextEdit, QVBoxLayout, QWidget,
)

from ..paths import _CREATE_NO_WINDOW
from ..theme import CAT
from ..postprocess import ClipWorker, HighlightWorker, ThumbWorker, probe_duration
from ..postprocess.codecs import VIDEO_CODECS
from ..utils import fmt_duration
from .widgets import (
    make_dialog_hero,
    make_dialog_section,
    make_status_banner,
    update_status_banner,
)

THUMB_COUNT = 20
THUMB_W = 120
THUMB_H = 68     # 16:9-ish placeholder height when thumbs are missing
STRIP_PAD = 6

# Social clip export presets (F31)
SOCIAL_PRESETS = [
    ("", "Original (no crop)"),
    ("tiktok", "TikTok \u2014 9:16, 1080\u00d71920, max 10m"),
    ("shorts", "YouTube Shorts \u2014 9:16, 1080\u00d71920, max 60s"),
    ("reels", "Instagram Reels \u2014 9:16, 1080\u00d71920, max 90s"),
    ("twitter", "Twitter/X \u2014 16:9, 1920\u00d71080, max 2:20"),
]
SOCIAL_SPECS = {
    "tiktok": {"w": 1080, "h": 1920, "max_secs": 600},
    "shorts": {"w": 1080, "h": 1920, "max_secs": 60},
    "reels":  {"w": 1080, "h": 1920, "max_secs": 90},
    "twitter": {"w": 1920, "h": 1080, "max_secs": 140},
}
_VERTICAL_PRESETS = {"tiktok", "shorts", "reels"}


def parse_hhmmss(text, fallback=0.0):
    """Parse 'HH:MM:SS', 'MM:SS', 'SSSS', or '12.5' into seconds."""
    text = (text or "").strip()
    if not text:
        return fallback
    if ":" in text:
        parts = text.split(":")
        try:
            parts = [float(p) for p in parts]
        except ValueError:
            return fallback
        total = 0.0
        for p in parts:
            total = total * 60.0 + p
        return total
    try:
        return float(text)
    except ValueError:
        return fallback


def format_hhmmss(secs):
    secs = max(0.0, float(secs))
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = secs - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


class ScrubberView(QGraphicsView):
    """QGraphicsView that lays out N thumbnails horizontally and overlays
    two draggable handles. Emits `handles_changed(start, end)` as a ratio
    of total duration.
    """

    handles_changed = pyqtSignal(float, float)   # start_ratio, end_ratio
    preview_requested = pyqtSignal(float)        # playhead_ratio

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(self.renderHints())
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(THUMB_H + 30)
        self.setStyleSheet("background: transparent;")
        self._thumb_items = []
        self._start_ratio = 0.0
        self._end_ratio = 1.0
        self._drag_target = None   # "start" | "end" | None
        self._strip_width = THUMB_COUNT * THUMB_W
        self._build_strip()

    def _build_strip(self):
        scene = self.scene()
        scene.clear()
        self._thumb_items = []
        # Placeholder rectangles so the layout is stable before thumbs land.
        for i in range(THUMB_COUNT):
            x = i * THUMB_W
            placeholder = QGraphicsRectItem(QRectF(x, 0, THUMB_W - 1, THUMB_H))
            placeholder.setPen(QPen(QColor(69, 71, 90)))
            placeholder.setBrush(QBrush(QColor(30, 30, 46)))
            scene.addItem(placeholder)
            pix_item = QGraphicsPixmapItem()
            pix_item.setPos(x, 0)
            scene.addItem(pix_item)
            self._thumb_items.append(pix_item)
        # Selection mask — dimmed overlay over the out-of-range region.
        self._dim_left = QGraphicsRectItem()
        self._dim_left.setBrush(QBrush(QColor(0, 0, 0, 160)))
        self._dim_left.setPen(QPen(Qt.PenStyle.NoPen))
        scene.addItem(self._dim_left)
        self._dim_right = QGraphicsRectItem()
        self._dim_right.setBrush(QBrush(QColor(0, 0, 0, 160)))
        self._dim_right.setPen(QPen(Qt.PenStyle.NoPen))
        scene.addItem(self._dim_right)
        # Handles: tall narrow rectangles at start/end.
        self._start_handle = QGraphicsRectItem()
        self._start_handle.setBrush(QBrush(QColor(137, 180, 250)))   # CAT blue
        self._start_handle.setPen(QPen(QColor(137, 180, 250)))
        self._start_handle.setZValue(5)
        scene.addItem(self._start_handle)
        self._end_handle = QGraphicsRectItem()
        self._end_handle.setBrush(QBrush(QColor(166, 227, 161)))     # CAT green
        self._end_handle.setPen(QPen(QColor(166, 227, 161)))
        self._end_handle.setZValue(5)
        scene.addItem(self._end_handle)
        scene.setSceneRect(0, 0, self._strip_width, THUMB_H + 2)
        self._refresh_handles()

    def set_spike_markers(self, ratios):
        """Draw colored tick marks at the given positions (0..1 ratios)."""
        scene = self.scene()
        # Remove old markers
        for item in getattr(self, "_spike_items", []):
            scene.removeItem(item)
        self._spike_items = []
        spike_color = QColor(250, 179, 135)  # CAT peach
        for r in ratios:
            x = r * self._strip_width
            tick = QGraphicsRectItem(QRectF(x - 1, -4, 2, THUMB_H + 8))
            tick.setPen(QPen(spike_color, 1))
            tick.setBrush(QBrush(spike_color))
            tick.setZValue(4)  # Below handles (5), above dims
            tick.setToolTip(f"Chat spike @ {r * 100:.1f}%")
            scene.addItem(tick)
            self._spike_items.append(tick)

    def set_range_overlays(self, ranges_ratios, active_idx=0):
        """Draw colored overlays for inactive ranges on the filmstrip."""
        scene = self.scene()
        for item in getattr(self, "_range_items", []):
            scene.removeItem(item)
        self._range_items = []
        colors = [
            QColor(137, 180, 250, 60),   # blue
            QColor(203, 166, 247, 60),    # mauve
            QColor(148, 226, 213, 60),    # teal
            QColor(249, 226, 175, 60),    # yellow
            QColor(245, 194, 231, 60),    # pink
            QColor(166, 227, 161, 60),    # green
        ]
        for i, (sr, er) in enumerate(ranges_ratios):
            if i == active_idx:
                continue
            color = colors[i % len(colors)]
            x1 = sr * self._strip_width
            x2 = er * self._strip_width
            rect = QGraphicsRectItem(QRectF(x1, 0, max(0, x2 - x1), THUMB_H))
            rect.setPen(QPen(Qt.PenStyle.NoPen))
            rect.setBrush(QBrush(color))
            rect.setZValue(3)
            rect.setToolTip(f"Range {i + 1}")
            scene.addItem(rect)
            self._range_items.append(rect)

    def set_thumb(self, index, path):
        if not (0 <= index < len(self._thumb_items)):
            return
        pix = QPixmap(path)
        if pix.isNull():
            return
        scaled = pix.scaled(
            THUMB_W - 1, THUMB_H,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb_items[index].setPixmap(scaled)

    def set_handles(self, start_ratio, end_ratio, *, emit=True):
        start_ratio = max(0.0, min(1.0, float(start_ratio)))
        end_ratio = max(0.0, min(1.0, float(end_ratio)))
        if end_ratio < start_ratio:
            end_ratio = start_ratio
        self._start_ratio = start_ratio
        self._end_ratio = end_ratio
        self._refresh_handles()
        if emit:
            self.handles_changed.emit(self._start_ratio, self._end_ratio)

    def _refresh_handles(self):
        if self._strip_width <= 0:
            return
        sx = self._start_ratio * self._strip_width
        ex = self._end_ratio * self._strip_width
        self._start_handle.setRect(sx - 2, -2, 4, THUMB_H + 4)
        self._end_handle.setRect(ex - 2, -2, 4, THUMB_H + 4)
        self._dim_left.setRect(0, 0, max(0, sx), THUMB_H)
        self._dim_right.setRect(ex, 0, max(0, self._strip_width - ex), THUMB_H)

    def resizeEvent(self, event):
        # Scale the scene so the strip fills the view width exactly.
        self.fitInView(QRectF(0, 0, self._strip_width, THUMB_H),
                       Qt.AspectRatioMode.IgnoreAspectRatio)
        super().resizeEvent(event)

    def _ratio_from_event(self, event):
        pt = self.mapToScene(event.pos())
        return max(0.0, min(1.0, pt.x() / max(1.0, self._strip_width)))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        ratio = self._ratio_from_event(event)
        # Pick whichever handle is closer. Clicking the dead middle grabs
        # whichever side you're nearer to.
        if abs(ratio - self._start_ratio) <= abs(ratio - self._end_ratio):
            self._drag_target = "start"
            self.set_handles(ratio, self._end_ratio)
        else:
            self._drag_target = "end"
            self.set_handles(self._start_ratio, ratio)
        self.preview_requested.emit(ratio)

    def mouseMoveEvent(self, event):
        if self._drag_target is None:
            return super().mouseMoveEvent(event)
        ratio = self._ratio_from_event(event)
        if self._drag_target == "start":
            self.set_handles(min(ratio, self._end_ratio), self._end_ratio)
        else:
            self.set_handles(self._start_ratio, max(ratio, self._start_ratio))
        self.preview_requested.emit(ratio)

    def mouseReleaseEvent(self, event):
        self._drag_target = None
        super().mouseReleaseEvent(event)


WAVE_H = 48           # Waveform widget height
WAVE_SAMPLE_RATE = 8000  # Mono 8 kHz — ~1 MB per minute of audio
WAVE_BIN_VERSION = 1


class _WaveformWorker(QThread):
    """Extract audio peaks from a media file via ffmpeg.

    Output is a list of (min_peak, max_peak) tuples normalised to [-1, 1],
    one pair per display column. The result is cached as `.waveform.bin`
    next to the source file so re-opens are instant.
    """

    ready = pyqtSignal(list)    # list[(float, float)] — per-column peaks
    log = pyqtSignal(str)

    def __init__(self, src_path, columns=600):
        super().__init__()
        self.src_path = src_path
        self.columns = columns
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            # Check cache first
            cache = self._cache_path()
            if cache and os.path.exists(cache):
                peaks = self._load_cache(cache)
                if peaks is not None:
                    self.ready.emit(peaks)
                    return

            # Extract raw 16-bit signed PCM mono at 8 kHz
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", self.src_path,
                "-ac", "1", "-ar", str(WAVE_SAMPLE_RATE),
                "-f", "s16le", "pipe:1",
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=_CREATE_NO_WINDOW,
                    timeout=120,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                self.ready.emit([])
                return

            if self._cancel or proc.returncode != 0 or not proc.stdout:
                self.ready.emit([])
                return

            raw = proc.stdout
            # Each sample is 2 bytes (s16le)
            n_samples = len(raw) // 2
            if n_samples < 2:
                self.ready.emit([])
                return

            # Compute per-column min/max peaks
            cols = max(1, self.columns)
            samples_per_col = max(1, n_samples // cols)
            peaks = []
            offset = 0
            for _ in range(cols):
                if self._cancel:
                    self.ready.emit([])
                    return
                end = min(offset + samples_per_col, n_samples)
                chunk = raw[offset * 2 : end * 2]
                if not chunk:
                    peaks.append((0.0, 0.0))
                    offset = end
                    continue
                # Unpack s16le samples
                count = len(chunk) // 2
                samples = struct.unpack(f"<{count}h", chunk)
                lo = min(samples) / 32768.0
                hi = max(samples) / 32768.0
                peaks.append((lo, hi))
                offset = end

            # Cache
            if cache:
                self._save_cache(cache, peaks)

            if not self._cancel:
                self.ready.emit(peaks)
        except Exception:
            self.ready.emit([])

    def _cache_path(self):
        try:
            d = os.path.dirname(self.src_path)
            base = os.path.basename(self.src_path)
            return os.path.join(d, f".{base}.waveform.bin")
        except Exception:
            return None

    def _save_cache(self, path, peaks):
        try:
            with open(path, "wb") as f:
                f.write(struct.pack("<BH", WAVE_BIN_VERSION, len(peaks)))
                for lo, hi in peaks:
                    f.write(struct.pack("<ff", lo, hi))
        except OSError:
            pass

    def _load_cache(self, path):
        try:
            with open(path, "rb") as f:
                header = f.read(3)
                if len(header) < 3:
                    return None
                ver, count = struct.unpack("<BH", header)
                if ver != WAVE_BIN_VERSION:
                    return None
                data = f.read(count * 8)
                if len(data) < count * 8:
                    return None
                peaks = []
                for i in range(count):
                    lo, hi = struct.unpack_from("<ff", data, i * 8)
                    peaks.append((lo, hi))
                return peaks
        except (OSError, struct.error):
            return None


class WaveformWidget(QWidget):
    """Filled amplitude-envelope waveform synced with the scrubber handles.

    Displays selection region tint and supports click-to-seek.
    """

    seek_requested = pyqtSignal(float)  # ratio 0..1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._peaks = []
        self._start_ratio = 0.0
        self._end_ratio = 1.0
        self.setFixedHeight(WAVE_H)
        self.setMinimumWidth(200)

    def set_peaks(self, peaks):
        self._peaks = peaks
        self.update()

    def set_selection(self, start_ratio, end_ratio):
        self._start_ratio = start_ratio
        self._end_ratio = end_ratio
        self.update()

    def paintEvent(self, event):
        if not self._peaks:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        mid = h / 2.0

        # Background
        p.fillRect(0, 0, w, h, QColor(24, 24, 37))  # CAT crust

        # Dim region outside selection
        sx = int(self._start_ratio * w)
        ex = int(self._end_ratio * w)
        dim = QColor(0, 0, 0, 120)
        if sx > 0:
            p.fillRect(0, 0, sx, h, dim)
        if ex < w:
            p.fillRect(ex, 0, w - ex, h, dim)

        # Draw waveform columns
        n_peaks = len(self._peaks)
        in_color = QColor(137, 180, 250, 180)    # CAT blue
        out_color = QColor(88, 91, 112, 140)      # CAT overlay0 dimmed
        for x in range(w):
            idx = int(x * n_peaks / w)
            if idx >= n_peaks:
                idx = n_peaks - 1
            lo, hi = self._peaks[idx]
            # Map [-1, 1] to pixel Y
            y_top = int(mid - hi * mid)
            y_bot = int(mid - lo * mid)
            col = in_color if sx <= x <= ex else out_color
            p.setPen(QPen(col, 1))
            p.drawLine(x, y_top, x, y_bot)

        # Handle markers
        p.setPen(QPen(QColor(137, 180, 250), 2))
        p.drawLine(sx, 0, sx, h)
        p.setPen(QPen(QColor(166, 227, 161), 2))
        p.drawLine(ex, 0, ex, h)

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.width() > 0:
            ratio = max(0.0, min(1.0, event.pos().x() / self.width()))
            self.seek_requested.emit(ratio)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.width() > 0:
            ratio = max(0.0, min(1.0, event.pos().x() / self.width()))
            self.seek_requested.emit(ratio)


class ClipDialog(QDialog):
    """Modal dialog that runs a ClipWorker with a visual scrubber."""

    def __init__(self, parent, source_path, *, default_end=None):
        super().__init__(parent)
        self.setWindowTitle("Trim / Clip")
        self.setMinimumSize(920, 860)
        self.setModal(True)
        self.source_path = source_path
        self._worker = None
        self._thumb_worker = None
        self._preview_worker = None
        self._waveform_worker = None
        self._scene_worker = None
        self._duration = probe_duration(source_path)
        if default_end is None:
            default_end = self._duration or 0.0
        self._ranges = [(0.0, default_end)]
        self._active_range_idx = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        hero, _, _, self._hero_badge = make_dialog_hero(
            "Trim, package, and export moments cleanly",
            "Set in and out points visually, build highlight reels from multiple ranges, and export in the format that best fits the destination.",
            eyebrow="CLIP STUDIO",
            badge_text="Single clip",
        )
        root.addWidget(hero)

        self._status_banner, self._status_title, self._status_body = make_status_banner()
        root.addWidget(self._status_banner)

        source_card, source_content = make_dialog_section(
            "Source media",
            "Work from the current recording without touching the original file.",
        )
        self._source_meta = QLabel(
            f"<b>File</b>: {os.path.basename(source_path)}"
            f"<br><b>Duration</b>: {fmt_duration(self._duration) if self._duration else 'Unknown'}"
        )
        self._source_meta.setObjectName("fieldHint")
        self._source_meta.setWordWrap(True)
        source_content.addWidget(self._source_meta)
        root.addWidget(source_card)

        timeline_card, timeline_content = make_dialog_section(
            "Timeline and preview",
            "Drag the handles or click the waveform to refine your clip visually before export.",
        )

        # Filmstrip + preview row
        strip_row = QHBoxLayout()
        strip_row.setSpacing(10)
        self.scrubber = ScrubberView()
        self.scrubber.handles_changed.connect(self._on_handles_changed)
        self.scrubber.preview_requested.connect(self._on_preview_requested)
        strip_row.addWidget(self.scrubber, 4)
        # Live preview panel
        preview_col = QVBoxLayout()
        preview_col.setSpacing(4)
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(260, 146)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            f"background-color: {CAT['mantle']}; border: 1px solid {CAT['surface0']}; "
            f"border-radius: 8px; color: {CAT['overlay0']};"
        )
        self.preview_label.setText("Drag the handles")
        preview_col.addWidget(self.preview_label)
        self.preview_time_label = QLabel("—")
        self.preview_time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_time_label.setStyleSheet(f"color: {CAT['subtext0']};")
        preview_col.addWidget(self.preview_time_label)
        strip_row.addLayout(preview_col, 0)
        timeline_content.addLayout(strip_row)

        # Audio waveform strip (F34) — sits below filmstrip
        self.waveform = WaveformWidget()
        self.waveform.seek_requested.connect(self._on_waveform_seek)
        self.scrubber.handles_changed.connect(self.waveform.set_selection)
        timeline_content.addWidget(self.waveform)

        # Storyboard panel (F30) — click a scene thumbnail to jump
        story_bar = QHBoxLayout()
        story_bar.setSpacing(6)
        self._story_scroll = QScrollArea()
        self._story_scroll.setFixedHeight(76)
        self._story_scroll.setWidgetResizable(True)
        self._story_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._story_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._story_scroll.setStyleSheet(
            f"QScrollArea {{ background: {CAT['mantle']}; border: 1px solid {CAT['surface0']}; "
            f"border-radius: 6px; }}")
        self._story_widget = QWidget()
        self._story_lay = QHBoxLayout(self._story_widget)
        self._story_lay.setContentsMargins(4, 2, 4, 2)
        self._story_lay.setSpacing(4)
        self._story_placeholder = QLabel(
            "No storyboard yet. Detect scenes to create quick jump points."
        )
        self._story_placeholder.setObjectName("fieldHint")
        self._story_placeholder.setWordWrap(True)
        self._story_lay.addWidget(self._story_placeholder)
        self._story_lay.addStretch(1)
        self._story_scroll.setWidget(self._story_widget)
        story_bar.addWidget(self._story_scroll, 1)
        gen_btn = QPushButton("Detect scenes")
        gen_btn.setObjectName("secondary")
        gen_btn.setToolTip("Run scene detection (requires scenedetect)")
        gen_btn.setFixedWidth(100)
        gen_btn.clicked.connect(self._generate_storyboard)
        story_bar.addWidget(gen_btn)
        timeline_content.addLayout(story_bar)
        root.addWidget(timeline_card)

        ranges_card, ranges_content = make_dialog_section(
            "Ranges",
            "Use one range for a clean trim, or stack multiple ranges to export a highlight reel.",
        )

        # In / Out text fields (kept so power users can type exact times)
        range_row = QHBoxLayout()
        range_row.setSpacing(10)
        in_col = QVBoxLayout()
        in_col.setSpacing(4)
        in_col.addWidget(QLabel("Start (HH:MM:SS)"))
        self.start_input = QLineEdit("00:00:00.000")
        self.start_input.editingFinished.connect(self._on_text_changed)
        in_col.addWidget(self.start_input)
        range_row.addLayout(in_col, 1)
        out_col = QVBoxLayout()
        out_col.setSpacing(4)
        out_col.addWidget(QLabel("End (HH:MM:SS)"))
        self.end_input = QLineEdit(format_hhmmss(default_end))
        self.end_input.editingFinished.connect(self._on_text_changed)
        out_col.addWidget(self.end_input)
        range_row.addLayout(out_col, 1)
        dur_col = QVBoxLayout()
        dur_col.setSpacing(4)
        dur_col.addWidget(QLabel("Clip length"))
        self.dur_label = QLabel(format_hhmmss(default_end))
        self.dur_label.setStyleSheet(f"color: {CAT['green']}; font-weight: 600;")
        dur_col.addWidget(self.dur_label)
        range_row.addLayout(dur_col, 0)
        ranges_content.addLayout(range_row)

        # Range list (F9 — multi-range highlight reel)
        ranges_toolbar = QHBoxLayout()
        ranges_toolbar.setSpacing(8)
        self.range_list = QListWidget()
        self.range_list.setFixedHeight(90)
        self.range_list.currentRowChanged.connect(self._on_range_selected)
        ranges_toolbar.addWidget(self.range_list, 1)
        range_btns = QVBoxLayout()
        range_btns.setSpacing(4)
        for symbol, tip, slot in [
            ("+", "Add a new range after the current one", self._add_range),
            ("\u2212", "Remove selected range", self._remove_range),
            ("\u25b2", "Move range up", self._move_range_up),
            ("\u25bc", "Move range down", self._move_range_down),
        ]:
            b = QPushButton(symbol)
            b.setToolTip(tip)
            b.setFixedWidth(32)
            b.setObjectName("secondary")
            b.clicked.connect(slot)
            range_btns.addWidget(b)
        range_btns.addStretch(1)
        ranges_toolbar.addLayout(range_btns)
        ranges_content.addLayout(ranges_toolbar)
        root.addWidget(ranges_card)
        self._refresh_range_list()

        export_card, export_content = make_dialog_section(
            "Export settings",
            "Choose accuracy, framing, and destination before saving the final clip.",
        )

        # Mode
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self.reencode_check = QCheckBox("Frame-accurate (re-encode)")
        self.reencode_check.setToolTip(
            "Off (default): lossless stream copy — fast, but cut-points "
            "snap to the nearest keyframe.\nOn: frame-exact trim using "
            "the selected codec — slower."
        )
        self.reencode_check.toggled.connect(self._on_reencode_toggled)
        mode_row.addWidget(self.reencode_check)
        self.codec_combo = QComboBox()
        for key, label in VIDEO_CODECS.items():
            if key == "copy":
                continue
            self.codec_combo.addItem(label, userData=key)
        self.codec_combo.setVisible(False)
        mode_row.addWidget(self.codec_combo)
        mode_row.addStretch(1)
        export_content.addLayout(mode_row)

        # Social platform preset (F31)
        social_row = QHBoxLayout()
        social_row.setSpacing(10)
        social_row.addWidget(QLabel("Platform:"))
        self.social_combo = QComboBox()
        for key, label in SOCIAL_PRESETS:
            self.social_combo.addItem(label, userData=key)
        self.social_combo.currentIndexChanged.connect(self._on_social_changed)
        social_row.addWidget(self.social_combo, 1)
        self._crop_lbl = QLabel("Crop offset:")
        self._crop_lbl.setVisible(False)
        social_row.addWidget(self._crop_lbl)
        self.crop_slider = QSlider(Qt.Orientation.Horizontal)
        self.crop_slider.setRange(0, 100)
        self.crop_slider.setValue(50)
        self.crop_slider.setFixedWidth(120)
        self.crop_slider.setVisible(False)
        self.crop_slider.valueChanged.connect(self._refresh_crop_overlay)
        social_row.addWidget(self.crop_slider)
        self.crop_pct_label = QLabel("50%")
        self.crop_pct_label.setFixedWidth(32)
        self.crop_pct_label.setVisible(False)
        social_row.addWidget(self.crop_pct_label)
        export_content.addLayout(social_row)
        self._last_preview_pix = None

        # Output path
        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        out_row.addWidget(QLabel("Output:"))
        self.out_input = QLineEdit(self._default_output_path(source_path))
        self.out_input.setClearButtonEnabled(True)
        out_row.addWidget(self.out_input, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.setObjectName("secondary")
        browse_btn.clicked.connect(self._on_browse)
        out_row.addWidget(browse_btn)
        export_content.addLayout(out_row)

        # Progress + log
        self.progress = QProgressBar()
        self.progress.setValue(0)
        export_content.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(110)
        self.log_view.setPlaceholderText("Export progress and ffmpeg messages appear here.")
        export_content.addWidget(self.log_view)
        root.addWidget(export_card)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.setObjectName("secondary")
        self.cancel_btn.clicked.connect(self._on_close_or_cancel)
        btn_row.addWidget(self.cancel_btn)
        self.trim_btn = QPushButton("Export clip")
        self.trim_btn.setObjectName("primary")
        self.trim_btn.clicked.connect(self._on_trim)
        btn_row.addWidget(self.trim_btn)
        root.addLayout(btn_row)

        if not self._duration:
            self._set_status(
                "Duration could not be read",
                "Manual start and end entry still works, but the visual scrubber may be limited until ffprobe is available.",
                tone="warning",
            )
            self._log_line(
                "[WARN] ffprobe could not determine duration. Scrubber "
                "disabled; enter values manually."
            )
        else:
            # Seed initial handle state from default_end.
            end_ratio = min(1.0, max(0.0, default_end / self._duration))
            self.scrubber.set_handles(0.0, end_ratio, emit=False)
            self.waveform.set_selection(0.0, end_ratio)
            self._kick_off_thumbnails()
            self._kick_off_waveform()
            self._load_chat_spikes()
            self._load_storyboard_cache()
            self._refresh_status_summary()

    # ── Thumbnail + preview ─────────────────────────────────────

    def _kick_off_thumbnails(self):
        self._thumb_worker = ThumbWorker(
            self.source_path, count=THUMB_COUNT, width=THUMB_W,
        )
        self._thumb_worker.thumb_ready.connect(self.scrubber.set_thumb)
        self._thumb_worker.start()

    def _kick_off_waveform(self):
        """Extract audio peaks in the background for the waveform strip."""
        cols = max(200, self.waveform.width() or 600)
        self._waveform_worker = _WaveformWorker(self.source_path, columns=cols)
        self._waveform_worker.ready.connect(self._on_waveform_ready)
        self._waveform_worker.start()

    def _on_waveform_ready(self, peaks):
        if peaks:
            self.waveform.set_peaks(peaks)

    def _load_chat_spikes(self):
        """Look for a chat.jsonl in the source directory and overlay spike
        markers on the filmstrip if found."""
        src_dir = os.path.dirname(self.source_path) or "."
        jsonl = os.path.join(src_dir, "chat.jsonl")
        if not os.path.isfile(jsonl) or not self._duration:
            return
        try:
            from ..chat.spike_detect import detect_spikes
            spikes = detect_spikes(jsonl)
        except Exception:
            return
        if not spikes:
            return
        ratios = []
        for sp in spikes:
            t = sp.get("time", 0)
            if self._duration > 0:
                ratios.append(t / self._duration)
        if ratios:
            self.scrubber.set_spike_markers(ratios)
            self._log_line(
                f"[CHAT] Found {len(ratios)} chat spike(s) — "
                f"peach markers on the filmstrip."
            )

    def _on_waveform_seek(self, ratio):
        """Click/drag on waveform → move nearest scrubber handle + preview."""
        if abs(ratio - self.scrubber._start_ratio) <= abs(ratio - self.scrubber._end_ratio):
            self.scrubber.set_handles(ratio, self.scrubber._end_ratio)
        else:
            self.scrubber.set_handles(self.scrubber._start_ratio, ratio)
        self.scrubber.preview_requested.emit(ratio)

    def _on_preview_requested(self, ratio):
        if not self._duration:
            return
        at = ratio * self._duration
        self.preview_time_label.setText(format_hhmmss(at))
        # Debounce: if a preview worker is still running, let it finish
        # rather than piling up — users drag fast.
        if self._preview_worker is not None and self._preview_worker.isRunning():
            return
        pw = _PreviewWorker(self.source_path, at)
        pw.ready.connect(self._on_preview_ready)
        self._preview_worker = pw
        pw.start()

    def _on_preview_ready(self, path):
        if not path or not os.path.exists(path):
            return
        pix = QPixmap(path)
        if pix.isNull():
            return
        scaled = pix.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._last_preview_pix = scaled
        self.preview_label.setPixmap(self._apply_crop_overlay(scaled))

    # ── Scrubber <-> text field sync ────────────────────────────

    def _on_handles_changed(self, start_ratio, end_ratio):
        if not self._duration:
            return
        s = start_ratio * self._duration
        e = end_ratio * self._duration
        # Block editingFinished re-entry
        self.start_input.blockSignals(True)
        self.end_input.blockSignals(True)
        self.start_input.setText(format_hhmmss(s))
        self.end_input.setText(format_hhmmss(e))
        self.start_input.blockSignals(False)
        self.end_input.blockSignals(False)
        self.dur_label.setText(format_hhmmss(max(0.0, e - s)))
        if 0 <= self._active_range_idx < len(self._ranges):
            self._ranges[self._active_range_idx] = (s, e)
            self._refresh_range_list()
            self._refresh_range_overlays()

    def _on_text_changed(self):
        if not self._duration:
            # Still update the displayed length so users have feedback.
            s = parse_hhmmss(self.start_input.text(), 0.0)
            e = parse_hhmmss(self.end_input.text(), 0.0)
            self.dur_label.setText(format_hhmmss(max(0.0, e - s)))
            return
        s = parse_hhmmss(self.start_input.text(), 0.0)
        e = parse_hhmmss(self.end_input.text(), self._duration)
        sr = min(1.0, max(0.0, s / self._duration))
        er = min(1.0, max(0.0, e / self._duration))
        if er < sr:
            er = sr
        self.scrubber.set_handles(sr, er, emit=False)
        self.dur_label.setText(format_hhmmss(max(0.0, e - s)))
        if 0 <= self._active_range_idx < len(self._ranges):
            self._ranges[self._active_range_idx] = (s, e)
            self._refresh_range_list()
            self._refresh_range_overlays()

    # ── Misc ────────────────────────────────────────────────────

    def _set_status(self, title, body, *, tone="info"):
        update_status_banner(
            self._status_banner,
            self._status_title,
            self._status_body,
            title=title,
            body=body,
            tone=tone,
        )

    def _refresh_status_summary(self):
        if not all(
            hasattr(self, name)
            for name in ("reencode_check", "social_combo", "out_input", "_hero_badge")
        ):
            return
        range_count = len(self._ranges)
        export_mode = "highlight reel" if range_count > 1 else "clip"
        accuracy = (
            "frame-accurate re-encode"
            if self.reencode_check.isChecked()
            else "fast stream copy"
        )
        framing = self.social_combo.currentText()
        if not (self.social_combo.currentData() or ""):
            framing = "Original framing"
        output_name = (
            os.path.basename(self.out_input.text().strip())
            if self.out_input.text().strip()
            else "No output file chosen yet"
        )

        self._hero_badge.setText("Highlight reel" if range_count > 1 else "Single clip")
        self._set_status(
            f"Ready to export a {export_mode}",
            f"{range_count} range(s) selected, using {accuracy}. Framing: {framing}. Output: {output_name}.",
            tone="info",
        )

    def _default_output_path(self, source_path):
        base, ext = os.path.splitext(source_path)
        return f"{base}.clip{ext}"

    def _on_browse(self):
        start_dir = os.path.dirname(self.out_input.text().strip()) or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Clip output", self.out_input.text().strip() or start_dir
        )
        if path:
            self.out_input.setText(path)
            self._refresh_status_summary()

    def _on_reencode_toggled(self, checked):
        self.codec_combo.setVisible(bool(checked))
        if not (self.social_combo.currentData() or ""):
            self._refresh_status_summary()

    # ── Social clip export (F31) ───────────────────────────────

    def _on_social_changed(self, _idx):
        key = self.social_combo.currentData()
        is_vertical = key in _VERTICAL_PRESETS
        for w in (self._crop_lbl, self.crop_slider, self.crop_pct_label):
            w.setVisible(is_vertical)
        if key:
            self.reencode_check.setChecked(True)
            self.reencode_check.setEnabled(False)
        else:
            self.reencode_check.setEnabled(True)
        self._refresh_crop_overlay()
        self._refresh_status_summary()

    def _apply_crop_overlay(self, pix):
        """Draw crop region overlay on QPixmap for vertical social presets."""
        key = self.social_combo.currentData() if hasattr(self, "social_combo") else ""
        if key not in _VERTICAL_PRESETS:
            return pix
        result = pix.copy()
        p = QPainter(result)
        crop_pct = self.crop_slider.value() / 100.0
        sw = result.width()
        sh = result.height()
        crop_w = max(1, int(sh * 9 / 16))
        crop_x = int(max(0, sw - crop_w) * crop_pct)
        dim = QColor(0, 0, 0, 140)
        if crop_x > 0:
            p.fillRect(0, 0, crop_x, sh, dim)
        right = crop_x + crop_w
        if right < sw:
            p.fillRect(right, 0, sw - right, sh, dim)
        p.setPen(QPen(QColor(137, 180, 250), 2))
        p.drawRect(crop_x, 0, crop_w - 1, sh - 1)
        p.end()
        return result

    def _refresh_crop_overlay(self, _value=None):
        self.crop_pct_label.setText(f"{self.crop_slider.value()}%")
        if self._last_preview_pix and not self._last_preview_pix.isNull():
            self.preview_label.setPixmap(
                self._apply_crop_overlay(self._last_preview_pix))

    def _build_social_vf(self):
        """Return an ffmpeg -vf string for the selected social preset,
        or empty string for Original."""
        key = self.social_combo.currentData()
        if not key:
            return ""
        spec = SOCIAL_SPECS.get(key)
        if not spec:
            return ""
        if key in _VERTICAL_PRESETS:
            pct = self.crop_slider.value() / 100.0
            return (
                f"crop=ih*9/16:ih:(iw-ih*9/16)*{pct:.2f}:0,"
                f"scale={spec['w']}:{spec['h']}"
            )
        # Twitter / landscape — scale preserving aspect + pad
        return (
            f"scale={spec['w']}:{spec['h']}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={spec['w']}:{spec['h']}:(ow-iw)/2:(oh-ih)/2"
        )

    def _log_line(self, msg):
        self.log_view.append(msg)

    def _set_busy(self, busy):
        self.trim_btn.setEnabled(not busy)
        self.start_input.setEnabled(not busy)
        self.end_input.setEnabled(not busy)
        self.out_input.setEnabled(not busy)
        self.reencode_check.setEnabled(not busy)
        self.codec_combo.setEnabled(not busy)
        self.scrubber.setEnabled(not busy)
        self.range_list.setEnabled(not busy)
        self.social_combo.setEnabled(not busy)
        self.crop_slider.setEnabled(not busy)
        self.cancel_btn.setText("Cancel" if busy else "Close")
        if busy:
            mode = "highlight reel" if len(self._ranges) > 1 else "clip"
            self._set_status(
                f"Exporting {mode}",
                "StreamKeep is processing the selected range and will keep logging progress below.",
                tone="info",
            )

    def _on_trim(self):
        out_path = self.out_input.text().strip()
        if not out_path:
            self._set_status(
                "Choose an output path",
                "Pick where the exported clip should be saved before starting the job.",
                tone="error",
            )
            self._log_line("[ERROR] Output path is empty.")
            return
        if os.path.abspath(out_path) == os.path.abspath(self.source_path):
            self._set_status(
                "Output path conflicts with the source",
                "Choose a different filename so the original recording stays untouched.",
                tone="error",
            )
            self._log_line("[ERROR] Output cannot overwrite the source file.")
            return
        codec = "libx264"
        if self.reencode_check.isChecked():
            codec = self.codec_combo.currentData() or "libx264"
        # Multi-range highlight reel
        if len(self._ranges) > 1:
            valid = [(s, e) for s, e in self._ranges if e > s]
            if not valid:
                self._set_status(
                    "No valid ranges to export",
                    "Add at least one range with an end time later than its start time.",
                    tone="error",
                )
                self._log_line("[ERROR] No valid ranges to export.")
                return
            self._worker = HighlightWorker(
                self.source_path, out_path, valid,
                reencode=self.reencode_check.isChecked(),
                video_codec=codec, audio_codec="aac",
            )
            self._worker.progress.connect(self._on_progress)
            self._worker.log.connect(self._log_line)
            self._worker.done.connect(self._on_done)
            self._set_busy(True)
            self._worker.start()
            return
        # Single range
        start_s = parse_hhmmss(self.start_input.text(), 0.0)
        end_s = parse_hhmmss(self.end_input.text(), self._duration or 0.0)
        if end_s <= start_s:
            self._set_status(
                "End time needs to be later than start time",
                "Adjust the in and out points so the clip has a positive duration.",
                tone="error",
            )
            self._log_line("[ERROR] End must be greater than start.")
            return
        vf = self._build_social_vf()
        self._worker = ClipWorker(
            self.source_path,
            out_path,
            start_s,
            end_s,
            reencode=self.reencode_check.isChecked(),
            video_codec=codec,
            audio_codec="aac",
            video_filter=vf,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._log_line)
        self._worker.done.connect(self._on_done)
        self._set_busy(True)
        self._worker.start()

    def _on_progress(self, pct, _status):
        self.progress.setValue(int(pct))

    def _on_done(self, ok, out_path):
        self._set_busy(False)
        self.progress.setValue(100 if ok else 0)
        if ok:
            self._set_status(
                "Export complete",
                f"Saved the finished clip to {out_path}.",
                tone="success",
            )
            self._log_line(f"[DONE] Saved {out_path}")
        else:
            self._set_status(
                "Export failed",
                "StreamKeep could not finish the clip. The log below should point to the next fix.",
                tone="error",
            )
            self._log_line("[DONE] Trim failed — see log above.")

    # ── Storyboard (F30) ─────────────────────────────────────

    def _load_storyboard_cache(self):
        from ..postprocess.scene_worker import load_cached_scenes
        scenes = load_cached_scenes(self.source_path)
        if scenes:
            self._populate_storyboard(scenes)

    def _generate_storyboard(self):
        from ..postprocess.scene_worker import SceneWorker
        self._scene_worker = SceneWorker(self.source_path)
        self._scene_worker.log.connect(self._log_line)
        self._scene_worker.scenes_ready.connect(self._on_scenes_ready)
        self._scene_worker.start()
        self._set_status(
            "Detecting scenes",
            "StreamKeep is scanning for scene changes so you can jump through the recording faster.",
            tone="info",
        )
        self._log_line("[SCENE] Starting scene detection\u2026")

    def _on_scenes_ready(self, scenes):
        if scenes:
            self._populate_storyboard(scenes)

    def _populate_storyboard(self, scenes):
        while self._story_lay.count():
            item = self._story_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for sc in scenes:
            t = sc.get("time", 0)
            thumb_path = sc.get("thumb", "")
            if not os.path.isfile(str(thumb_path)):
                continue
            frame = QWidget()
            col = QVBoxLayout(frame)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(1)
            img = QLabel()
            pix = QPixmap(thumb_path)
            if not pix.isNull():
                img.setPixmap(pix.scaled(
                    100, 56, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            img.setCursor(Qt.CursorShape.PointingHandCursor)
            img.setToolTip(f"Jump to {format_hhmmss(t)[:8]}")
            img.mousePressEvent = lambda ev, ts=t: self._on_story_click(ts)
            col.addWidget(img)
            lbl = QLabel(format_hhmmss(t)[:8])
            lbl.setStyleSheet(f"color: {CAT['subtext0']}; font-size: 10px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(lbl)
            self._story_lay.addWidget(frame)
        self._story_lay.addStretch(1)
        if scenes:
            self._set_status(
                "Storyboard ready",
                f"Detected {len(scenes)} scene marker(s). Click any frame to jump the nearest handle.",
                tone="success",
            )

    def _on_story_click(self, timestamp):
        if not self._duration or self._duration <= 0:
            return
        ratio = timestamp / self._duration
        sr = self.scrubber._start_ratio
        er = self.scrubber._end_ratio
        if abs(ratio - sr) <= abs(ratio - er):
            self.scrubber.set_handles(ratio, er)
        else:
            self.scrubber.set_handles(sr, ratio)
        self.scrubber.preview_requested.emit(ratio)

    # ── Range list (F9) ────────────────────────────────────────

    def _add_range(self):
        if not self._duration or self._duration <= 0:
            return
        # New range starts at the end of the active range
        if self._ranges:
            _, prev_end = self._ranges[self._active_range_idx]
            new_start = min(prev_end, self._duration)
            new_end = min(new_start + 30.0, self._duration)
        else:
            new_start = 0.0
            new_end = min(30.0, self._duration)
        if new_end <= new_start:
            new_end = self._duration
        if new_end <= new_start:
            return
        self._ranges.append((new_start, new_end))
        self._active_range_idx = len(self._ranges) - 1
        self._select_active_range()
        self._refresh_range_list()
        self._refresh_range_overlays()

    def _remove_range(self):
        if len(self._ranges) <= 1:
            return
        idx = self._active_range_idx
        if 0 <= idx < len(self._ranges):
            self._ranges.pop(idx)
            self._active_range_idx = min(idx, len(self._ranges) - 1)
            self._select_active_range()
            self._refresh_range_list()
            self._refresh_range_overlays()

    def _move_range_up(self):
        idx = self._active_range_idx
        if idx <= 0 or idx >= len(self._ranges):
            return
        self._ranges[idx], self._ranges[idx - 1] = (
            self._ranges[idx - 1], self._ranges[idx])
        self._active_range_idx = idx - 1
        self._refresh_range_list()
        self._refresh_range_overlays()

    def _move_range_down(self):
        idx = self._active_range_idx
        if idx < 0 or idx >= len(self._ranges) - 1:
            return
        self._ranges[idx], self._ranges[idx + 1] = (
            self._ranges[idx + 1], self._ranges[idx])
        self._active_range_idx = idx + 1
        self._refresh_range_list()
        self._refresh_range_overlays()

    def _on_range_selected(self, row):
        if row < 0 or row >= len(self._ranges):
            return
        self._active_range_idx = row
        self._select_active_range()
        self._refresh_range_overlays()

    def _select_active_range(self):
        if not self._ranges or self._active_range_idx >= len(self._ranges):
            return
        s, e = self._ranges[self._active_range_idx]
        if self._duration and self._duration > 0:
            sr = s / self._duration
            er = e / self._duration
            self.scrubber.set_handles(sr, er, emit=False)
            self.waveform.set_selection(sr, er)
        self.start_input.blockSignals(True)
        self.end_input.blockSignals(True)
        self.start_input.setText(format_hhmmss(s))
        self.end_input.setText(format_hhmmss(e))
        self.start_input.blockSignals(False)
        self.end_input.blockSignals(False)
        self.dur_label.setText(format_hhmmss(max(0.0, e - s)))

    def _refresh_range_list(self):
        self.range_list.blockSignals(True)
        self.range_list.clear()
        for i, (s, e) in enumerate(self._ranges):
            dur = max(0.0, e - s)
            label = (f"{i + 1}. {format_hhmmss(s)[:8]} \u2192 "
                     f"{format_hhmmss(e)[:8]}  ({format_hhmmss(dur)[:8]})")
            self.range_list.addItem(label)
        self.range_list.setCurrentRow(self._active_range_idx)
        self.range_list.blockSignals(False)
        if hasattr(self, "trim_btn"):
            self.trim_btn.setText(
                "Export Highlight Reel" if len(self._ranges) > 1 else "Export Clip")
        self._refresh_status_summary()

    def _refresh_range_overlays(self):
        if not self._duration or self._duration <= 0:
            return
        ratios = [(s / self._duration, e / self._duration)
                  for s, e in self._ranges]
        self.scrubber.set_range_overlays(ratios, self._active_range_idx)

    def _on_close_or_cancel(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
            self._set_busy(False)
            self._set_status(
                "Export canceled",
                "The current clip job was stopped before completion.",
                tone="warning",
            )
            return
        self.accept()

    def reject(self):
        for w in (self._worker, self._thumb_worker, self._preview_worker,
                  self._waveform_worker, self._scene_worker):
            try:
                if w is not None and w.isRunning():
                    w.cancel() if hasattr(w, "cancel") else None
                    w.wait(1000)
            except Exception:
                pass
        super().reject()


class _PreviewWorker(QThread):
    """One-shot preview thumbnail at an arbitrary second. Writes to a
    rotating temp path so consecutive drags don't clobber each other's
    files before QPixmap has loaded them."""

    ready = pyqtSignal(str)

    def __init__(self, src_path, at_secs):
        super().__init__()
        self.src_path = src_path
        self.at_secs = float(at_secs)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            src_dir = os.path.dirname(self.src_path) or "."
            cache_dir = os.path.join(src_dir, ".streamkeep_thumbs")
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except OSError:
                self.ready.emit("")
                return
            dst = os.path.join(cache_dir, f"_preview_{int(self.at_secs * 1000):010d}.jpg")
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-ss", f"{max(0.0, self.at_secs):.3f}",
                "-i", self.src_path,
                "-frames:v", "1",
                "-vf", "scale=260:-2",
                "-q:v", "4",
                "-y", dst,
            ]
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=_CREATE_NO_WINDOW,
                    timeout=15,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                self.ready.emit("")
                return
            if self._cancel:
                return
            if proc.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0:
                self.ready.emit(dst)
            else:
                self.ready.emit("")
        except Exception:
            self.ready.emit("")
