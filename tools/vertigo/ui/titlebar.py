"""Frameless custom titlebar — draggable, brand mark, window controls."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPixmap
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from .assets import icon_path


class TitleBar(QWidget):
    minimize_requested = pyqtSignal()
    toggle_max_requested = pyqtSignal()
    close_requested = pyqtSignal()
    theme_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(48)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._drag_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 0, 0)
        lay.setSpacing(12)

        brand_wrap = QHBoxLayout()
        brand_wrap.setSpacing(10)

        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setFixedSize(QSize(26, 26))
        pix = QPixmap(str(icon_path()))
        if not pix.isNull():
            mark.setPixmap(pix.scaled(
                26, 26,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            mark.setText("\u25cf")
            mark.setObjectName("brandDot")

        brand = QLabel("Vertigo")
        brand.setObjectName("brand")
        brand_wrap.addWidget(mark)
        brand_wrap.addWidget(brand)
        lay.addLayout(brand_wrap)

        sep = QLabel("\u2022")
        sep.setObjectName("titleSep")
        lay.addWidget(sep)

        self._subtitle = QLabel("Vertical video studio")
        self._subtitle.setObjectName("titleText")
        lay.addWidget(self._subtitle)

        lay.addStretch(1)

        self._theme = QComboBox()
        self._theme.setObjectName("themePicker")
        self._theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme.setToolTip("Theme appearance")
        self._theme.setAccessibleName("Theme")
        self._theme.currentIndexChanged.connect(self._emit_theme)
        lay.addWidget(self._theme)

        self._min = self._make_ctl("\u2013")
        self._max = self._make_ctl("\u25a1")
        self._close = self._make_ctl("\u2715", close=True)
        self._min.setToolTip("Minimize")
        self._max.setToolTip("Maximize or restore")
        self._close.setToolTip("Close Vertigo")
        self._min.setAccessibleName("Minimize window")
        self._max.setAccessibleName("Maximize or restore window")
        self._close.setAccessibleName("Close window")
        lay.addWidget(self._min)
        lay.addWidget(self._max)
        lay.addWidget(self._close)

        self._min.clicked.connect(self.minimize_requested)
        self._max.clicked.connect(self.toggle_max_requested)
        self._close.clicked.connect(self.close_requested)

    def set_subtitle(self, text: str) -> None:
        self._subtitle.setText(text)

    def set_theme_choices(self, choices: list[tuple[str, str]], current: str) -> None:
        self._theme.blockSignals(True)
        self._theme.clear()
        for value, label in choices:
            self._theme.addItem(label, value)
        self.set_theme(current)
        self._theme.blockSignals(False)

    def set_theme(self, theme_id: str) -> None:
        index = self._theme.findData(theme_id)
        if index >= 0:
            blocked = self._theme.blockSignals(True)
            self._theme.setCurrentIndex(index)
            self._theme.blockSignals(blocked)

    def _make_ctl(self, glyph: str, *, close: bool = False) -> QPushButton:
        btn = QPushButton(glyph)
        btn.setObjectName("winClose" if close else "winCtl")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(32)
        btn.setFlat(True)
        return btn

    def _emit_theme(self) -> None:
        theme_id = self._theme.currentData()
        if isinstance(theme_id, str):
            self.theme_changed.emit(theme_id)

    # dragging ---------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            self._drag_pos = event.globalPosition().toPoint() - win.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            win = self.window()
            if win.isMaximized():
                win.showNormal()
            win.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.toggle_max_requested.emit()
