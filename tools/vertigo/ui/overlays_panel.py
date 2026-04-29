"""Text overlays editor — add / edit / remove title cards and lower-thirds.

Presents a scrollable list of OverlayRow widgets. Each row owns its
controls (text, time range, placement, size) and emits a `changed` signal
whenever the user edits anything. The container aggregates rows into a
list[TextOverlay] that the main window hands to `build_plan(...)`.
"""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.overlays import OverlayPosition, TextOverlay


_POSITION_LABELS: list[tuple[OverlayPosition, str]] = [
    (OverlayPosition.TITLE,       "Title card (centered)"),
    (OverlayPosition.TOP,         "Top strap"),
    (OverlayPosition.LOWER_THIRD, "Lower third (left)"),
    (OverlayPosition.CAPTION,     "Bottom caption"),
]

_next_id = 0


def _mint_id() -> int:
    global _next_id
    _next_id += 1
    return _next_id


class OverlayRow(QFrame):
    changed = pyqtSignal()
    removed = pyqtSignal(int)

    def __init__(self, overlay: TextOverlay, *, max_seconds: float = 60.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("queueItem")   # reuse themed row styling
        self._overlay = overlay
        self._max = max(5.0, max_seconds)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # row 1: text + remove
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self._text = QLineEdit(overlay.text)
        self._text.setPlaceholderText("Overlay text  \u2014  type \\n for a new line")
        self._text.setToolTip("What the overlay says. Use \\n to force a line break.")
        self._text.setAccessibleName("Overlay text")
        self._text.textChanged.connect(self._bump)
        row1.addWidget(self._text, 1)

        self._rm = QPushButton("\u2715")
        self._rm.setFlat(True)
        self._rm.setFixedSize(24, 24)
        self._rm.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rm.setToolTip("Remove overlay")
        self._rm.clicked.connect(lambda: self.removed.emit(overlay.id))
        row1.addWidget(self._rm)

        outer.addLayout(row1)

        # row 2: placement + size + color
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self._position = QComboBox()
        self._position.setCursor(Qt.CursorShape.PointingHandCursor)
        for value, label in _POSITION_LABELS:
            self._position.addItem(label, value)
        idx = self._position.findData(overlay.position)
        if idx >= 0:
            self._position.setCurrentIndex(idx)
        self._position.currentIndexChanged.connect(self._bump)
        row2.addWidget(self._position, 2)

        self._size = QSpinBox()
        self._size.setRange(16, 200)
        self._size.setSuffix(" px")
        self._size.setValue(overlay.size)
        self._size.setToolTip("Font size")
        self._size.valueChanged.connect(self._bump)
        row2.addWidget(self._size)

        self._color_btn = QPushButton(overlay.color)
        self._color_btn.setObjectName("ghostBtn")
        self._color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color_btn.setToolTip("Text color")
        self._color_btn.clicked.connect(self._pick_color)
        self._apply_color_swatch(overlay.color)
        row2.addWidget(self._color_btn)

        outer.addLayout(row2)

        # row 3: time range
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        self._start = QDoubleSpinBox()
        self._start.setRange(0.0, self._max)
        self._start.setDecimals(2)
        self._start.setSuffix(" s")
        self._start.setSingleStep(0.25)
        self._start.setValue(overlay.start)
        self._start.valueChanged.connect(self._bump)
        row3.addWidget(QLabel("From"))
        row3.addWidget(self._start)

        self._end = QDoubleSpinBox()
        self._end.setRange(0.0, self._max)
        self._end.setDecimals(2)
        self._end.setSuffix(" s")
        self._end.setSingleStep(0.25)
        self._end.setValue(overlay.end)
        self._end.valueChanged.connect(self._bump)
        row3.addWidget(QLabel("to"))
        row3.addWidget(self._end)
        row3.addStretch(1)
        outer.addLayout(row3)

    def overlay(self) -> TextOverlay:
        return replace(
            self._overlay,
            text=self._text.text(),
            start=self._start.value(),
            end=self._end.value(),
            position=self._position.currentData(),
            size=self._size.value(),
            color=self._color_btn.text(),
        )

    def set_duration(self, seconds: float) -> None:
        self._max = max(5.0, seconds)
        self._start.setMaximum(self._max)
        self._end.setMaximum(self._max)

    def _bump(self, *_args) -> None:
        # clamp: end >= start
        if self._end.value() <= self._start.value():
            self._end.blockSignals(True)
            self._end.setValue(min(self._max, self._start.value() + 0.5))
            self._end.blockSignals(False)
        self._overlay = self.overlay()
        self.changed.emit()

    def _pick_color(self) -> None:
        from PyQt6.QtGui import QColor
        start = QColor(self._color_btn.text())
        chosen = QColorDialog.getColor(start, self, "Pick overlay color")
        if chosen.isValid():
            hex_str = chosen.name()
            self._color_btn.setText(hex_str)
            self._apply_color_swatch(hex_str)
            self._bump()

    def _apply_color_swatch(self, color: str) -> None:
        self._color_btn.setStyleSheet(
            self._color_btn.styleSheet() +
            f";background: {color}; color: #11111b; font-weight: 700;"
        )


class OverlaysPanel(QWidget):
    overlays_changed = pyqtSignal(list)  # list[TextOverlay]
    _PRESET_LIBRARY: dict[str, tuple[str, TextOverlay]] = {
        "intro": (
            "Intro title",
            TextOverlay(
                text="Title",
                start=0.0,
                end=2.5,
                position=OverlayPosition.TITLE,
                size=110,
                color="#ffffff",
                id=0,
            ),
        ),
        "lower_third": (
            "Lower third",
            TextOverlay(
                text="Your Name\\nRole · Company",
                start=1.0,
                end=5.0,
                position=OverlayPosition.LOWER_THIRD,
                size=56,
                color="#cba6f7",
                id=0,
            ),
        ),
        "hook": (
            "Hook strap",
            TextOverlay(
                text="Wait for it…",
                start=0.0,
                end=3.0,
                position=OverlayPosition.TOP,
                size=64,
                color="#f5c2e7",
                id=0,
            ),
        ),
        "cta": (
            "CTA caption",
            TextOverlay(
                text="Follow for more",
                start=0.0,
                end=60.0,
                position=OverlayPosition.CAPTION,
                size=52,
                color="#ffffff",
                id=0,
            ),
        ),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[OverlayRow] = []
        self._duration: float = 60.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        self._hint = QLabel("Title cards and lower-thirds are burned into every export.")
        self._hint.setObjectName("subtitle")
        self._hint.setWordWrap(True)
        hdr.addWidget(self._hint, 1)

        self._presets_btn = QPushButton("Add preset")
        self._presets_btn.setObjectName("ghostBtn")
        self._presets_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._presets_btn.setToolTip("Insert a pre-styled overlay preset")
        self._presets_btn.clicked.connect(self._show_presets)
        hdr.addWidget(self._presets_btn)

        self._add_btn = QPushButton("Add overlay")
        self._add_btn.setObjectName("primaryBtn")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.clicked.connect(lambda: self._add(TextOverlay(text="", id=_mint_id())))
        hdr.addWidget(self._add_btn)
        root.addLayout(hdr)

        self._list_host = QWidget()
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(8)
        self._list_lay.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._list_host)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._scroll.setStyleSheet("background: transparent;")

        self._empty = QWidget()
        self._empty.setObjectName("emptyState")
        self._empty.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        empty_lay = QVBoxLayout(self._empty)
        empty_lay.setContentsMargins(18, 18, 18, 18)
        empty_lay.setSpacing(8)
        empty_title = QLabel("No text overlays yet")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_body = QLabel(
            "Add a title card, hook strap, lower third, or CTA caption. Overlay timing stays synced to the loaded clip."
        )
        empty_body.setObjectName("emptyBody")
        empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_body.setWordWrap(True)
        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        quick_row.addStretch(1)
        for key in ("intro", "lower_third", "cta"):
            btn = QPushButton(self._PRESET_LIBRARY[key][0])
            btn.setObjectName("presetChip")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, preset_key=key: self._add_preset(preset_key))
            quick_row.addWidget(btn)
        quick_row.addStretch(1)
        empty_hint = QLabel("Need more starting points? Use Add preset for the full library.")
        empty_hint.setObjectName("valueMuted")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setWordWrap(True)
        empty_lay.addWidget(empty_title)
        empty_lay.addWidget(empty_body)
        empty_lay.addLayout(quick_row)
        empty_lay.addWidget(empty_hint)
        root.addWidget(self._empty)
        root.addWidget(self._scroll, 1)
        self._refresh_empty_state()

    # ------------------------------------------------------------ api
    def overlays(self) -> list[TextOverlay]:
        return [row.overlay() for row in self._rows if row.overlay().text.strip()]

    def set_duration(self, seconds: float) -> None:
        self._duration = max(5.0, seconds)
        for row in self._rows:
            row.set_duration(self._duration)

    def clear(self) -> None:
        for row in list(self._rows):
            self._remove(row.overlay().id, silent=True)
        self._emit()

    # ------------------------------------------------------------ impl
    def _add(self, overlay: TextOverlay) -> None:
        if not overlay.id:
            overlay = replace(overlay, id=_mint_id())
        row = OverlayRow(overlay, max_seconds=self._duration)
        row.changed.connect(self._emit)
        row.removed.connect(self._remove)
        self._rows.append(row)
        insert_index = self._list_lay.count() - 1  # before the stretch
        self._list_lay.insertWidget(insert_index, row)
        self._refresh_empty_state()
        self._emit()

    def _remove(self, overlay_id: int, *, silent: bool = False) -> None:
        row = next((r for r in self._rows if r.overlay().id == overlay_id), None)
        if not row:
            return
        self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._refresh_empty_state()
        if not silent:
            self._emit()

    def _refresh_empty_state(self) -> None:
        has_rows = bool(self._rows)
        self._empty.setVisible(not has_rows)
        self._scroll.setVisible(has_rows)

    def _emit(self) -> None:
        self.overlays_changed.emit(self.overlays())

    def _show_presets(self) -> None:
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        for key, (label, _overlay) in self._PRESET_LIBRARY.items():
            menu.addAction(label, lambda preset_key=key: self._add_preset(preset_key))
        menu.exec(self._presets_btn.mapToGlobal(self._presets_btn.rect().bottomLeft()))

    def _add_preset(self, key: str) -> None:
        preset = self._PRESET_LIBRARY.get(key)
        if preset is None:
            return
        overlay = replace(preset[1], id=_mint_id())
        if key == "cta":
            overlay = replace(overlay, end=self._duration)
        else:
            overlay = replace(overlay, end=min(self._duration, overlay.end))
        self._add(overlay)
