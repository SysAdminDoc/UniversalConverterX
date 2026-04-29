"""Embedded preview player with scrubber.

Uses QMediaPlayer + QVideoSink, then paints an overlay rectangle showing
the live crop viewport for the selected reframe mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QRectF, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink, QVideoFrame
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .range_slider import RangeSlider
from .theme import current_palette, qcolor


class PreviewCanvas(QWidget):
    """Paints the latest video frame and a translucent crop-viewport overlay."""

    viewport_dragged = pyqtSignal(float)  # manual-mode x (0..1)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(420, 240))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Video preview")
        self._frame: QImage | None = None
        self._aspect_w = 9
        self._aspect_h = 16
        self._manual_x = 0.5
        self._mode = "center"
        self._track_x: float | None = None
        self._interactive = False

    def set_aspect(self, w: int, h: int) -> None:
        self._aspect_w = w
        self._aspect_h = h
        self.update()

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._interactive = mode == "manual"
        self.setCursor(
            Qt.CursorShape.SplitHCursor if self._interactive else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def set_manual_x(self, x: float) -> None:
        self._manual_x = max(0.0, min(1.0, x))
        self.update()

    def set_track_x(self, x: float | None) -> None:
        self._track_x = x
        self.update()

    def push_frame(self, frame: QVideoFrame) -> None:
        if not frame.isValid():
            return
        img = frame.toImage()
        if img.isNull():
            return
        self._frame = img
        self.update()

    def clear(self) -> None:
        self._frame = None
        self.update()

    # paint ------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        theme = current_palette()
        p.fillRect(self.rect(), QColor(theme.crust))

        if self._frame is None:
            # Empty-state composition: muted 9:16 frame + aspect badge +
            # single-line helper. Visual language matches the drop zone.
            cx = self.rect().center().x()
            cy = self.rect().center().y()
            glyph_h = min(120.0, self.rect().height() * 0.48)
            glyph_w = glyph_h * 9.0 / 16.0

            frame_rect = QRectF(cx - glyph_w / 2, cy - glyph_h / 2 - 6,
                                glyph_w, glyph_h)
            frame_pen = QPen(qcolor(theme.surface2))
            frame_pen.setWidthF(1.4)
            p.setPen(frame_pen)
            p.setBrush(qcolor(theme.mantle))
            p.drawRoundedRect(frame_rect, 8, 8)

            # Aspect ratio badge inside the frame
            badge_font = QFont()
            badge_font.setPointSize(10)
            badge_font.setWeight(QFont.Weight.DemiBold)
            badge_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
            p.setFont(badge_font)
            p.setPen(QColor(theme.overlay1))
            p.drawText(frame_rect, Qt.AlignmentFlag.AlignCenter, "9 : 16")

            # Helper text below the frame
            helper_font = QFont()
            helper_font.setPointSize(11)
            helper_font.setWeight(QFont.Weight.Medium)
            p.setFont(helper_font)
            p.setPen(QColor(theme.subtext0))
            p.drawText(
                QRectF(0, frame_rect.bottom() + 16,
                       self.rect().width(), 20),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "Preview ready once a clip is loaded",
            )
            p.end()
            return

        # fit-inside
        canvas = self.rect()
        fw, fh = self._frame.width(), self._frame.height()
        if fw == 0 or fh == 0:
            p.end()
            return
        scale = min(canvas.width() / fw, canvas.height() / fh)
        dw, dh = int(fw * scale), int(fh * scale)
        dx = (canvas.width() - dw) // 2
        dy = (canvas.height() - dh) // 2
        p.drawImage(
            canvas.x() + dx, canvas.y() + dy, self._frame.scaled(
                dw, dh,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

        # overlay: crop viewport rectangle
        target_aspect = self._aspect_w / self._aspect_h
        src_aspect = fw / fh
        if src_aspect >= target_aspect:
            vp_h_px = dh
            vp_w_px = int(dh * target_aspect)
        else:
            vp_w_px = dw
            vp_h_px = int(dw / target_aspect)

        center_x: float
        if self._mode == "manual":
            center_x = self._manual_x
        elif self._mode == "smart_track" and self._track_x is not None:
            center_x = self._track_x
        else:
            center_x = 0.5

        max_left = dw - vp_w_px
        vp_x = int(max_left * center_x) + dx
        vp_y = (dh - vp_h_px) // 2 + dy

        # dim outside viewport
        dim = qcolor(theme.overlay_scrim)
        p.fillRect(dx, dy, vp_x - dx, dh, dim)
        p.fillRect(vp_x + vp_w_px, dy, (dx + dw) - (vp_x + vp_w_px), dh, dim)
        p.fillRect(vp_x, dy, vp_w_px, vp_y - dy, dim)
        p.fillRect(vp_x, vp_y + vp_h_px, vp_w_px, (dy + dh) - (vp_y + vp_h_px), dim)

        # viewport outline
        pen = QPen(QColor(theme.accent))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(vp_x, vp_y, vp_w_px, vp_h_px)

        # corner markers
        pen2 = QPen(QColor(theme.pink))
        pen2.setWidth(3)
        p.setPen(pen2)
        cl = 14
        for (cx, cy, sx, sy) in [
            (vp_x, vp_y, 1, 1),
            (vp_x + vp_w_px, vp_y, -1, 1),
            (vp_x, vp_y + vp_h_px, 1, -1),
            (vp_x + vp_w_px, vp_y + vp_h_px, -1, -1),
        ]:
            p.drawLine(cx, cy, cx + cl * sx, cy)
            p.drawLine(cx, cy, cx, cy + cl * sy)

        if self._interactive:
            hint = "Drag to position crop"
            hint_rect = QRectF(vp_x + 12, vp_y + vp_h_px - 34, 158, 24)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(theme.hint_bg))
            p.drawRoundedRect(hint_rect, 8, 8)
            p.setPen(QColor(theme.hint_text))
            p.drawText(hint_rect, Qt.AlignmentFlag.AlignCenter, hint)

        p.end()

    # mouse: manual drag -----------------------------------------------
    def mousePressEvent(self, event):
        if self._interactive and self._frame is not None:
            self._drag(event.position().x())

    def mouseMoveEvent(self, event):
        if self._interactive and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag(event.position().x())

    def _drag(self, x: float) -> None:
        if self._frame is None:
            return
        fw, fh = self._frame.width(), self._frame.height()
        scale = min(self.width() / fw, self.height() / fh)
        dw = int(fw * scale)
        dh = int(fh * scale)
        dx = (self.width() - dw) // 2
        target_aspect = self._aspect_w / self._aspect_h
        src_aspect = fw / fh
        if src_aspect >= target_aspect:
            vp_w_px = int(dh * target_aspect)
        else:
            vp_w_px = dw
        max_left = max(1, dw - vp_w_px)
        local_x = x - dx - vp_w_px / 2
        nx = max(0.0, min(1.0, local_x / max_left))
        self._manual_x = nx
        self.viewport_dragged.emit(nx)
        self.update()


@dataclass(frozen=True)
class SegmentBand:
    """Duration band used by the local segment-proposal worker."""

    min_sec: float = 30.0
    max_sec: float = 90.0
    target_sec: float = 45.0


class SegmentSettingsBar(QWidget):
    """Compact sliders for long-form segment proposal length."""

    changed = pyqtSignal(object)  # SegmentBand

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._band = SegmentBand()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(8)

        self._summary = QLabel("")
        self._summary.setObjectName("valueMuted")
        self._summary.setWordWrap(False)
        self._summary.setMinimumWidth(174)
        lay.addWidget(self._summary)

        self._min = self._slider(
            15, 90, int(self._band.min_sec), "Minimum segment length"
        )
        self._target = self._slider(
            15, 180, int(self._band.target_sec), "Target segment length"
        )
        self._max = self._slider(
            45, 180, int(self._band.max_sec), "Maximum segment length"
        )

        self._min_v = self._value_label()
        self._target_v = self._value_label()
        self._max_v = self._value_label()

        self._add_control(lay, "Min", self._min, self._min_v)
        self._add_control(lay, "Target", self._target, self._target_v)
        self._add_control(lay, "Max", self._max, self._max_v)

        self._min.valueChanged.connect(self._recompute)
        self._target.valueChanged.connect(self._recompute)
        self._max.valueChanged.connect(self._recompute)
        self._recompute()

    def band(self) -> SegmentBand:
        return self._band

    def set_band(self, min_sec: float, max_sec: float, target_sec: float) -> None:
        min_i = int(round(max(15.0, min(90.0, min_sec))))
        max_i = int(round(max(45.0, min(180.0, max_sec))))
        if max_i <= min_i:
            max_i = min(180, min_i + 5)
            if max_i <= min_i:
                min_i = max(15, max_i - 5)
        target_i = int(round(max(min_i, min(max_i, target_sec))))

        self._set_slider_value(self._min, min_i)
        self._set_slider_value(self._max, max_i)
        self._target.setRange(min_i, max_i)
        self._set_slider_value(self._target, target_i)
        self._recompute()

    def _slider(self, lo: int, hi: int, default: int, name: str) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(default)
        slider.setSingleStep(5)
        slider.setPageStep(15)
        slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        slider.setToolTip(name)
        slider.setAccessibleName(name)
        slider.setMinimumWidth(80)
        return slider

    def _value_label(self) -> QLabel:
        label = QLabel("")
        label.setObjectName("formValue")
        label.setFixedWidth(48)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return label

    def _add_control(
        self,
        lay: QHBoxLayout,
        title: str,
        slider: QSlider,
        value: QLabel,
    ) -> None:
        label = QLabel(title)
        label.setObjectName("formLabel")
        lay.addWidget(label)
        lay.addWidget(slider, 1)
        lay.addWidget(value)

    def _set_slider_value(self, slider: QSlider, value: int) -> None:
        old = slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(old)

    def _recompute(self) -> None:
        min_v = int(self._min.value())
        max_v = int(self._max.value())
        if max_v <= min_v:
            sender = self.sender()
            if sender is self._min:
                max_v = min(180, min_v + 5)
                self._set_slider_value(self._max, max_v)
            else:
                min_v = max(15, max_v - 5)
                self._set_slider_value(self._min, min_v)

        self._target.setRange(min_v, max_v)
        target_v = int(max(min_v, min(max_v, self._target.value())))
        self._set_slider_value(self._target, target_v)

        self._band = SegmentBand(float(min_v), float(max_v), float(target_v))
        self._min_v.setText(_fmt(min_v))
        self._target_v.setText(_fmt(target_v))
        self._max_v.setText(_fmt(max_v))
        self._summary.setText(
            f"Segments {_fmt(min_v)}–{_fmt(max_v)} · target {_fmt(target_v)}"
        )
        self.setAccessibleName("Segment proposal length settings")
        self.setAccessibleDescription(self._summary.text())
        self.changed.emit(self._band)


class VideoPlayer(QWidget):
    """Media player widget wrapping a canvas + transport + trim scrubber."""

    position_changed = pyqtSignal(float)  # seconds
    duration_changed = pyqtSignal(float)
    trim_changed = pyqtSignal(float, float)  # low, high seconds

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.canvas = PreviewCanvas(self)
        self.canvas.setFocusProxy(self)
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self.canvas.push_frame)

        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setVideoSink(self._sink)
        self._player.setAudioOutput(self._audio)
        self._player.positionChanged.connect(self._on_pos)
        self._player.durationChanged.connect(self._on_dur)
        self._loaded = False

        self._play_btn = QPushButton("\u25b6")
        self._play_btn.setObjectName("ghostBtn")
        self._play_btn.setFixedWidth(48)
        self._play_btn.setEnabled(False)
        self._play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._play_btn.setToolTip("Play preview (Space)")
        self._play_btn.setAccessibleName("Play preview")
        self._play_btn.clicked.connect(self.toggle_play)

        self._time = QLabel("0:00 / 0:00")
        self._time.setObjectName("statusPill")

        self._trim_label = QLabel("Trim: 0:00 \u2013 0:00")
        self._trim_label.setObjectName("subtitle")

        self.tighten_btn = QPushButton("Tighten to speech")
        self.tighten_btn.setObjectName("ghostBtn")
        self.tighten_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tighten_btn.setToolTip(
            "Runs voice-activity detection and pulls the trim handles "
            "to the outer speech edges. Silero VAD (optional)."
        )
        self.tighten_btn.setAccessibleName("Tighten trim to detected speech")
        self.tighten_btn.setEnabled(False)

        self.highlights_btn = QPushButton("Find highlights")
        self.highlights_btn.setObjectName("ghostBtn")
        self.highlights_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.highlights_btn.setToolTip(
            "Scan the clip for high-energy moments. Click a result to "
            "drop the trim handles on it. Uses Lighthouse when "
            "installed; falls back to an audio-energy sweep otherwise."
        )
        self.highlights_btn.setAccessibleName("Find highlight moments")
        self.highlights_btn.setEnabled(False)

        self.segments_btn = QPushButton("Suggest segments")
        self.segments_btn.setObjectName("ghostBtn")
        self.segments_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.segments_btn.setToolTip(
            "Split long clips (> 10 min) into candidate 30\u201390 s segments "
            "using local TextTiling on the cached transcript. Generate "
            "captions first, then pick a segment to drop the trim on it."
        )
        self.segments_btn.setAccessibleName("Suggest candidate segments")
        self.segments_btn.setEnabled(False)

        self.trim_silences_btn = QPushButton("Trim silences")
        self.trim_silences_btn.setObjectName("ghostBtn")
        self.trim_silences_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.trim_silences_btn.setToolTip(
            "Run auto-editor over the clip. Pick from the longest "
            "speech-contiguous sections to drop the trim on one of "
            "them. Requires the 'auto-editor' CLI on PATH."
        )
        self.trim_silences_btn.setAccessibleName("Trim to a speech section")
        self.trim_silences_btn.setEnabled(False)

        self._trim_hint = QLabel("Load a clip to scrub, trim in and out points, and snap to scene cuts.")
        self._trim_hint.setObjectName("valueMuted")
        self._trim_hint.setWordWrap(True)

        self._scrubber = RangeSlider()
        self._scrubber.playhead_seek.connect(
            lambda t: self._player.setPosition(int(t * 1000))
        )
        self._scrubber.range_changed.connect(self._on_range)

        transport = QHBoxLayout()
        transport.setSpacing(10)
        transport.addWidget(self._play_btn)
        transport.addWidget(self._scrubber, 1)
        transport.addWidget(self._time)

        trim_row = QHBoxLayout()
        trim_row.setSpacing(10)
        trim_row.addWidget(self._trim_label, 1)
        trim_row.addWidget(self.segments_btn)
        trim_row.addWidget(self.highlights_btn)
        trim_row.addWidget(self.trim_silences_btn)
        trim_row.addWidget(self.tighten_btn)

        self._segment_settings = SegmentSettingsBar()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.canvas, 1)
        lay.addLayout(transport)
        lay.addLayout(trim_row)
        lay.addWidget(self._segment_settings)
        lay.addWidget(self._trim_hint)

    # public API -------------------------------------------------------
    def load(self, path: Path) -> None:
        self._player.stop()
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        self._player.play()
        self._player.pause()  # show first frame only
        self._loaded = True
        self._play_btn.setEnabled(True)
        self._play_btn.setText("\u25b6")
        self._play_btn.setToolTip("Play preview (Space)")
        self._play_btn.setAccessibleName("Play preview")
        self.tighten_btn.setEnabled(True)
        self.highlights_btn.setEnabled(True)
        self.trim_silences_btn.setEnabled(True)
        # segments button gated on clip length + cached transcript by the controller
        self._time.setProperty("tone", "accent")
        self._time.style().unpolish(self._time)
        self._time.style().polish(self._time)
        self._trim_hint.setText("Press Space to play or pause. Click the timeline to scrub, and drag the trim handles to set in and out points.")

    def toggle_play(self) -> None:
        if not self._loaded:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self._play_btn.setText("\u25b6")
            self._play_btn.setToolTip("Play preview (Space)")
            self._play_btn.setAccessibleName("Play preview")
            self._time.setProperty("tone", "accent")
        else:
            self._player.play()
            self._play_btn.setText("\u2759\u2759")
            self._play_btn.setToolTip("Pause preview (Space)")
            self._play_btn.setAccessibleName("Pause preview")
            self._time.setProperty("tone", "success")
        self._time.style().unpolish(self._time)
        self._time.style().polish(self._time)

    def stop(self) -> None:
        self._player.stop()

    def clear(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        self.canvas.clear()
        self._scrubber.reset()
        self._loaded = False
        self._play_btn.setText("\u25b6")
        self._play_btn.setEnabled(False)
        self._play_btn.setToolTip("Play preview (Space)")
        self._play_btn.setAccessibleName("Play preview")
        self.tighten_btn.setEnabled(False)
        self.highlights_btn.setEnabled(False)
        self.trim_silences_btn.setEnabled(False)
        self.segments_btn.setEnabled(False)
        self._time.setText("0:00 / 0:00")
        self._time.setProperty("tone", None)
        self._time.style().unpolish(self._time)
        self._time.style().polish(self._time)
        self._update_trim_label(0.0, 0.0)
        self._trim_hint.setText("Load a clip to scrub, trim in and out points, and snap to scene cuts.")

    def keyPressEvent(self, event) -> None:
        if not self._loaded:
            super().keyPressEvent(event)
            return
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_K):
            self.toggle_play()
            event.accept()
            return
        if event.key() == Qt.Key.Key_J:
            self._player.setPosition(max(0, self._player.position() - 5000))
            event.accept()
            return
        if event.key() == Qt.Key.Key_L:
            self._player.setPosition(min(self._player.duration(), self._player.position() + 5000))
            event.accept()
            return
        super().keyPressEvent(event)

    def set_aspect(self, w: int, h: int) -> None:
        self.canvas.set_aspect(w, h)

    def set_mode(self, mode: str) -> None:
        self.canvas.set_mode(mode)

    def set_manual_x(self, x: float) -> None:
        self.canvas.set_manual_x(x)

    def set_track_x(self, x: float | None) -> None:
        self.canvas.set_track_x(x)

    def set_shot_boundaries(self, boundaries: list[float]) -> None:
        """Forward scene cuts to the scrubber for tick drawing + snap."""
        self._scrubber.set_shot_boundaries(boundaries)

    def segment_band(self) -> tuple[float, float, float]:
        band = self._segment_settings.band()
        return band.min_sec, band.max_sec, band.target_sec

    def set_segment_band(self, min_sec: float, max_sec: float, target_sec: float) -> None:
        self._segment_settings.set_band(min_sec, max_sec, target_sec)

    def trim_range(self) -> tuple[float, float]:
        return self._scrubber.low(), self._scrubber.high()

    def set_trim_range(self, low: float, high: float) -> None:
        """Programmatic trim-handle update — used by VAD / auto-edit
        workers to drop the handles onto the detected keep span."""
        self._scrubber.set_range(low, high)

    def refresh_theme(self) -> None:
        self.canvas.update()
        self._scrubber.update()

    # internal slots ---------------------------------------------------
    def _on_pos(self, ms: int) -> None:
        self._scrubber.set_playhead(ms / 1000.0)
        dur = self._player.duration() or 1
        self._time.setText(f"{_fmt(ms/1000)} / {_fmt(dur/1000)}")
        self.position_changed.emit(ms / 1000.0)

    def _on_dur(self, ms: int) -> None:
        self._scrubber.set_duration(ms / 1000.0)
        self.duration_changed.emit(ms / 1000.0)
        self._update_trim_label(0.0, ms / 1000.0)

    def _on_range(self, low: float, high: float) -> None:
        self._update_trim_label(low, high)
        self.trim_changed.emit(low, high)

    def _update_trim_label(self, low: float, high: float) -> None:
        self._trim_label.setText(
            f"Trim:  {_fmt(low)} \u2013 {_fmt(high)}   \u00b7   duration {_fmt(high - low)}"
        )


def _fmt(sec: float) -> str:
    sec = max(0.0, sec)
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m}:{s:02d}"
