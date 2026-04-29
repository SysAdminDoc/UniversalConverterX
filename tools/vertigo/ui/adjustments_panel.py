"""Adjustments panel — brightness / contrast / saturation sliders."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from core.reframe import Adjustments

class AdjustmentsPanel(QWidget):
    changed = pyqtSignal(object)  # Adjustments

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._adj = Adjustments()

        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setHorizontalSpacing(10)
        lay.setVerticalSpacing(10)

        self._bright = self._slider(-100, 100, 0, "Brightness adjustment")
        self._contrast = self._slider(0, 200, 100, "Contrast adjustment")
        self._sat = self._slider(0, 300, 100, "Saturation adjustment")

        self._bright_v = self._value_label()
        self._contrast_v = self._value_label()
        self._sat_v = self._value_label()

        self._add_row(lay, 0, "Brightness", self._bright, self._bright_v)
        self._add_row(lay, 1, "Contrast",   self._contrast, self._contrast_v)
        self._add_row(lay, 2, "Saturation", self._sat, self._sat_v)

        self._summary = QLabel("")
        self._summary.setObjectName("valueMuted")
        self._summary.setWordWrap(True)
        lay.addWidget(self._summary, 3, 0, 1, 3)

        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        self._reset = QPushButton("Reset")
        self._reset.setObjectName("ghostBtn")
        self._reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset.setToolTip("Return adjustments to neutral")
        self._reset.clicked.connect(self.reset)
        reset_row.addWidget(self._reset)
        lay.addLayout(reset_row, 4, 0, 1, 3)

        self._bright.valueChanged.connect(self._recompute)
        self._contrast.valueChanged.connect(self._recompute)
        self._sat.valueChanged.connect(self._recompute)
        self._recompute()

    def adjustments(self) -> Adjustments:
        return self._adj

    def reset(self) -> None:
        self._bright.setValue(0)
        self._contrast.setValue(100)
        self._sat.setValue(100)

    # -------------------------------------------------- impl
    def _slider(self, lo: int, hi: int, default: int, name: str) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(default)
        s.setPageStep(10)
        s.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        s.setToolTip(name)
        s.setAccessibleName(name)
        return s

    def _value_label(self) -> QLabel:
        lbl = QLabel("")
        lbl.setObjectName("formValue")
        lbl.setFixedWidth(48)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return lbl

    def _add_row(self, lay: QGridLayout, row: int, title: str, slider: QSlider, value: QLabel) -> None:
        t = QLabel(title)
        t.setObjectName("formLabel")
        lay.addWidget(t, row, 0)
        lay.addWidget(slider, row, 1)
        lay.addWidget(value, row, 2)

    def _recompute(self) -> None:
        b = self._bright.value() / 100.0           # -1..1
        c = self._contrast.value() / 100.0         #  0..2
        s = self._sat.value() / 100.0              #  0..3
        self._adj = Adjustments(brightness=b, contrast=c, saturation=s)
        self._bright_v.setText(f"{self._bright.value():+d}%")
        self._contrast_v.setText(f"{self._contrast.value():d}%")
        self._sat_v.setText(f"{self._sat.value():d}%")
        neutral = self._bright.value() == 0 and self._contrast.value() == 100 and self._sat.value() == 100
        if neutral:
            self._summary.setText("Neutral look. Leave these at default when the source already feels balanced.")
        else:
            self._summary.setText(
                "Current grade: "
                f"brightness {self._bright.value():+d}%, contrast {self._contrast.value():d}%, saturation {self._sat.value():d}%."
            )
        self._reset.setEnabled(not neutral)
        self.changed.emit(self._adj)
