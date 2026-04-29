"""Output settings panel — encoder pick, quality slider, speed preset.

Surfaces every available FFmpeg encoder we detect on the system so power
users can pin a specific GPU pipeline (NVENC / QuickSync / AMF /
VideoToolbox) and dial in quality vs. size.

Exposes `current_selection()` returning a dataclass the main window feeds
into EncodeJob.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from core.encoders import Encoder, all_available, pick_default


@dataclass(frozen=True)
class OutputChoice:
    encoder: Encoder | None
    quality: int
    speed_preset: str | None


class OutputPanel(QWidget):
    changed = pyqtSignal(object)  # OutputChoice
    _QUALITY_PRESETS: tuple[tuple[str, int], ...] = (
        ("Smaller", 56),
        ("Balanced", 75),
        ("Mastering", 92),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._encoders: list[Encoder] = all_available()

        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(10)
        lay.setVerticalSpacing(10)

        # encoder -------------------------------------------------------
        self._encoder_combo = QComboBox()
        self._encoder_combo.setAccessibleName("Video encoder")
        self._encoder_combo.setToolTip("Which encoder FFmpeg will hand the frames to")
        self._encoder_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._encoders:
            for enc in self._encoders:
                tag = "  \u2605 GPU" if enc.hardware else "  \u00b7 CPU"
                self._encoder_combo.addItem(enc.label + tag, enc)
            default = pick_default("h264") or self._encoders[0]
            idx = next(
                (i for i, e in enumerate(self._encoders) if e.id == default.id),
                0,
            )
            self._encoder_combo.setCurrentIndex(idx)
        else:
            self._encoder_combo.addItem("No encoders found", None)
            self._encoder_combo.setEnabled(False)
        self._encoder_combo.currentIndexChanged.connect(self._on_encoder_changed)

        self._add_row(lay, 0, "Encoder", self._encoder_combo, None)

        # quality -------------------------------------------------------
        self._quality = QSlider(Qt.Orientation.Horizontal)
        self._quality.setRange(1, 100)
        self._quality.setValue(75)
        self._quality.setPageStep(5)
        self._quality.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._quality.setToolTip("Higher keeps more detail; lower makes the file smaller")
        self._quality.setAccessibleName("Output quality")

        self._quality_v = QLabel("75")
        self._quality_v.setObjectName("formValue")
        self._quality_v.setFixedWidth(116)
        self._quality_v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._add_row(lay, 1, "Quality", self._quality, self._quality_v)
        self._quality.valueChanged.connect(self._on_quality_changed)

        self._quality_group = QButtonGroup(self)
        self._quality_group.setExclusive(True)
        self._quality_buttons: dict[str, QPushButton] = {}
        quality_row = QHBoxLayout()
        quality_row.setSpacing(8)
        for label, value in self._QUALITY_PRESETS:
            btn = QPushButton(label)
            btn.setObjectName("presetChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(30)
            btn.setToolTip(f"Set quality to {value}")
            btn.clicked.connect(lambda _=False, v=value: self._quality.setValue(v))
            self._quality_group.addButton(btn)
            self._quality_buttons[label] = btn
            quality_row.addWidget(btn)
        quality_row.addStretch(1)
        lay.addLayout(quality_row, 2, 0, 1, 3)

        self._quality_hint = QLabel("")
        self._quality_hint.setObjectName("valueMuted")
        self._quality_hint.setWordWrap(True)
        lay.addWidget(self._quality_hint, 3, 0, 1, 3)

        # speed preset --------------------------------------------------
        self._speed_combo = QComboBox()
        self._speed_combo.setAccessibleName("Encoder speed preset")
        self._speed_combo.setToolTip("Slower presets squeeze more quality out of each bit")
        self._speed_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_row(lay, 4, "Speed", self._speed_combo, None)
        self._speed_combo.currentIndexChanged.connect(self._emit_change)

        # status line ---------------------------------------------------
        self._status = QLabel("")
        self._status.setObjectName("inlineNotice")
        self._status.setWordWrap(True)
        lay.addWidget(self._status, 5, 0, 1, 3)

        # hardware summary ---------------------------------------------
        self._summary = QLabel("")
        self._summary.setObjectName("valueMuted")
        self._summary.setWordWrap(True)
        lay.addWidget(self._summary, 6, 0, 1, 3)

        self._refresh_summary()
        self._on_encoder_changed()

    # ------------------------------------------------------------ api
    def current_selection(self) -> OutputChoice:
        enc = self._encoder_combo.currentData()
        speed = self._speed_combo.currentData()
        return OutputChoice(encoder=enc, quality=self._quality.value(), speed_preset=speed)

    # ------------------------------------------------------------ impl
    def _on_encoder_changed(self) -> None:
        enc: Encoder | None = self._encoder_combo.currentData()
        self._speed_combo.blockSignals(True)
        self._speed_combo.clear()
        if enc and enc.preset_values:
            for preset in enc.preset_values:
                self._speed_combo.addItem(preset, preset)
            if enc.preset_default:
                idx = self._speed_combo.findData(enc.preset_default)
                if idx >= 0:
                    self._speed_combo.setCurrentIndex(idx)
            self._speed_combo.setEnabled(True)
        else:
            self._speed_combo.addItem("Not adjustable", None)
            self._speed_combo.setEnabled(False)
        self._speed_combo.blockSignals(False)

        if enc:
            self._quality.setValue(enc.quality_default)
            tone = "success" if enc.hardware else None
            detail = "Fastest exports on this machine." if enc.hardware else "Best compatibility when GPU codecs are unavailable."
            self._set_status(f"{enc.label} selected. Codec: {enc.codec.upper()}. {detail}", tone=tone)
        else:
            self._set_status("No encoder available. Install FFmpeg to unlock export.", tone="warning")

        self._emit_change()

    def _on_quality_changed(self, value: int) -> None:
        label, hint = self._describe_quality(value)
        self._quality_v.setText(f"{value}  ·  {label}")
        self._quality_hint.setText(hint)
        self._sync_quality_preset(value)
        self._emit_change()

    def _emit_change(self) -> None:
        self.changed.emit(self.current_selection())

    def _refresh_summary(self) -> None:
        if not self._encoders:
            self._summary.setText("No video encoders detected.")
            return
        gpu = [e.label for e in self._encoders if e.hardware]
        cpu = [e.label for e in self._encoders if not e.hardware]
        parts: list[str] = []
        if gpu:
            parts.append("GPU: " + ", ".join(e.split(" (")[0] for e in gpu))
        if cpu:
            parts.append("CPU: libx264 / libx265")
        self._summary.setText("  \u00b7  ".join(parts))

    def _describe_quality(self, value: int) -> tuple[str, str]:
        if value >= 88:
            return "mastering", "Highest detail with larger files. Best for final exports or difficult footage."
        if value >= 72:
            return "balanced", "Recommended default for most shorts. Keeps detail while staying reasonably compact."
        if value >= 50:
            return "lighter", "Smaller files and faster uploads with a modest quality tradeoff."
        return "smallest", "Use when file size matters most. Fine detail and gradients will compress more aggressively."

    def _sync_quality_preset(self, value: int) -> None:
        if value >= 88:
            target = "Mastering"
        elif value >= 72:
            target = "Balanced"
        else:
            target = "Smaller"
        for label, btn in self._quality_buttons.items():
            blocked = btn.blockSignals(True)
            btn.setChecked(label == target)
            btn.blockSignals(blocked)

    def _set_status(self, text: str, *, tone: str | None = None) -> None:
        self._status.setText(text)
        self._status.setProperty("tone", tone)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def _add_row(self, lay: QGridLayout, row: int, title: str, widget: QWidget, value: QLabel | None) -> None:
        t = QLabel(title)
        t.setObjectName("formLabel")
        lay.addWidget(t, row, 0)
        lay.addWidget(widget, row, 1)
        if value is not None:
            lay.addWidget(value, row, 2)
