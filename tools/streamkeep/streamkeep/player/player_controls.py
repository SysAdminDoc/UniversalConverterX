"""Player transport controls — play/pause, seek, volume, speed, subs (F52).

Extended with 5-band EQ, dynaudnorm toggle, and mono/stereo toggle (F56).
"""

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal

def _fmt_time(secs):
    s = max(0, int(secs or 0))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class PlayerControls(QWidget):
    """Transport bar: play/pause, seek slider, volume, speed, subtitle picker."""

    seek_requested = pyqtSignal(float)      # absolute seconds
    toggle_pause = pyqtSignal()
    stop_requested = pyqtSignal()
    volume_changed = pyqtSignal(int)
    speed_changed = pyqtSignal(float)
    subtitle_changed = pyqtSignal(object)   # track_id or False
    fullscreen_requested = pyqtSignal()
    pip_requested = pyqtSignal()
    eq_changed = pyqtSignal(list)           # [bass, lo_mid, mid, hi_mid, treble] dB
    normalize_changed = pyqtSignal(bool)
    mono_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0.0
        self._seeking = False
        self.setObjectName("playerTransportBar")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        # Row 1: main transport
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        outer.addLayout(lay)

        # Play/Pause
        self.play_btn = QPushButton("||")
        self.play_btn.setFixedWidth(36)
        self.play_btn.setObjectName("primary")
        self.play_btn.setToolTip("Play or pause the current recording")
        self.play_btn.clicked.connect(self.toggle_pause.emit)
        lay.addWidget(self.play_btn)

        # Stop
        stop_btn = QPushButton("[]")
        stop_btn.setFixedWidth(36)
        stop_btn.setObjectName("secondary")
        stop_btn.setToolTip("Stop playback")
        stop_btn.clicked.connect(self.stop_requested.emit)
        lay.addWidget(stop_btn)

        # Time label (current)
        self.time_label = QLabel("0:00")
        self.time_label.setObjectName("playerMeta")
        self.time_label.setFixedWidth(60)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.time_label)

        # Seek slider
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.sliderPressed.connect(self._on_seek_press)
        self.seek_slider.sliderReleased.connect(self._on_seek_release)
        self.seek_slider.sliderMoved.connect(self._on_seek_move)
        lay.addWidget(self.seek_slider, 1)

        # Duration label
        self.dur_label = QLabel("0:00")
        self.dur_label.setObjectName("playerMeta")
        self.dur_label.setFixedWidth(60)
        lay.addWidget(self.dur_label)

        # Volume
        vol_label = QLabel("Vol")
        vol_label.setObjectName("playerTinyLabel")
        vol_label.setFixedWidth(24)
        lay.addWidget(vol_label)
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 150)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(80)
        self.vol_slider.valueChanged.connect(self.volume_changed.emit)
        lay.addWidget(self.vol_slider)

        # Speed
        self.speed_combo = QComboBox()
        self.speed_combo.setFixedWidth(70)
        for s in ("0.25x", "0.5x", "0.75x", "1x", "1.25x", "1.5x", "2x", "3x"):
            self.speed_combo.addItem(s, float(s.rstrip("x")))
        self.speed_combo.setCurrentIndex(3)  # 1x
        self.speed_combo.currentIndexChanged.connect(
            lambda i: self.speed_changed.emit(self.speed_combo.itemData(i))
        )
        lay.addWidget(self.speed_combo)

        # Subtitle track
        self.sub_combo = QComboBox()
        self.sub_combo.setFixedWidth(90)
        self.sub_combo.addItem("Subs Off", False)
        self.sub_combo.currentIndexChanged.connect(
            lambda i: self.subtitle_changed.emit(self.sub_combo.itemData(i))
        )
        lay.addWidget(self.sub_combo)

        # PiP (F53)
        pip_btn = QPushButton("PiP")
        pip_btn.setFixedWidth(36)
        pip_btn.setObjectName("ghost")
        pip_btn.setToolTip("Picture-in-Picture mini player")
        pip_btn.clicked.connect(self.pip_requested.emit)
        lay.addWidget(pip_btn)

        # Fullscreen
        fs_btn = QPushButton("[ ]")
        fs_btn.setFixedWidth(36)
        fs_btn.setObjectName("ghost")
        fs_btn.setToolTip("Toggle fullscreen")
        fs_btn.clicked.connect(self.fullscreen_requested.emit)
        lay.addWidget(fs_btn)

        # Row 2: EQ + audio toggles (F56)
        eq_row = QHBoxLayout()
        eq_row.setContentsMargins(0, 0, 0, 0)
        eq_row.setSpacing(6)
        eq_label = QLabel("EQ")
        eq_label.setObjectName("playerTinyLabel")
        eq_row.addWidget(eq_label)
        self._eq_sliders = []
        _EQ_BANDS = ["Bass", "Lo-Mid", "Mid", "Hi-Mid", "Treble"]
        for band_name in _EQ_BANDS:
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(-12, 12)
            sl.setValue(0)
            sl.setFixedWidth(50)
            sl.setToolTip(f"{band_name} (-12 to +12 dB)")
            sl.valueChanged.connect(self._emit_eq)
            eq_row.addWidget(sl)
            self._eq_sliders.append(sl)
        self._normalize_check = QCheckBox("Normalize")
        self._normalize_check.setToolTip("Dynamic audio normalization (mpv dynaudnorm)")
        self._normalize_check.toggled.connect(self.normalize_changed.emit)
        eq_row.addWidget(self._normalize_check)
        self._mono_check = QCheckBox("Mono")
        self._mono_check.setToolTip("Downmix to mono")
        self._mono_check.toggled.connect(self.mono_changed.emit)
        eq_row.addWidget(self._mono_check)
        eq_row.addStretch(1)
        outer.addLayout(eq_row)

    def _emit_eq(self):
        vals = [sl.value() for sl in self._eq_sliders]
        self.eq_changed.emit(vals)

    def set_position(self, secs):
        """Update the seek slider and time label from the current position."""
        if self._seeking:
            return
        self.time_label.setText(_fmt_time(secs))
        if self._duration > 0:
            pct = min(1000, int(secs / self._duration * 1000))
            self.seek_slider.setValue(pct)

    def set_duration(self, secs):
        self._duration = secs
        self.dur_label.setText(_fmt_time(secs))

    def set_paused(self, paused):
        self.play_btn.setText(">" if paused else "||")

    def set_subtitle_tracks(self, tracks):
        """Populate the subtitle combo. *tracks* is [(id, label), ...]."""
        self.sub_combo.blockSignals(True)
        self.sub_combo.clear()
        self.sub_combo.addItem("Subs Off", False)
        for tid, label in tracks:
            self.sub_combo.addItem(label[:20], tid)
        self.sub_combo.blockSignals(False)

    def _on_seek_press(self):
        self._seeking = True

    def _on_seek_move(self, val):
        if self._duration > 0:
            secs = val / 1000.0 * self._duration
            self.time_label.setText(_fmt_time(secs))

    def _on_seek_release(self):
        self._seeking = False
        if self._duration > 0:
            secs = self.seek_slider.value() / 1000.0 * self._duration
            self.seek_requested.emit(secs)
