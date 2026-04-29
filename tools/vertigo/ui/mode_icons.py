"""Procedurally-painted icons for each reframe mode.

The Unicode geometric squares (■ ◉ ▣ ▩) read as placeholders. These
icons draw the actual concept of each mode using the theme accent:

    center         : 16:9 outer frame, 9:16 crop centred inside
    smart_track    : 16:9 outer frame, 9:16 crop offset + a subject dot
                     with a short motion arc suggesting tracking
    blur_letterbox : 16:9 outer frame, 9:16 crop centred with stippled
                     "blurred" side bars
    manual         : 16:9 outer frame, 9:16 crop with drag handles on
                     its left and right edges
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PyQt6.QtWidgets import QWidget

from .theme import current_palette


class ModeIcon(QWidget):
    """28 × 28 painted icon matching the reframe mode semantics."""

    KINDS = ("center", "smart_track", "blur_letterbox", "manual")

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind if kind in self.KINDS else "center"
        self._active = False
        self.setFixedSize(28, 28)

    def set_active(self, on: bool) -> None:
        if self._active == on:
            return
        self._active = on
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        theme = current_palette()
        # Outer 16:9 frame — muted when the card is at rest, accent when
        # the card is checked/active. Caller toggles via `set_active`.
        outer_color = QColor(theme.accent if self._active else theme.overlay1)
        accent_fill = QColor(theme.accent)
        if not self._active:
            accent_fill.setAlpha(180)

        # Full bounding box, slight inset for antialiased edges
        box = QRectF(self.rect()).adjusted(1.0, 3.0, -1.0, -3.0)
        # Outer 16:9 rectangle (26 × 14 area inside the widget)
        outer = QRectF(box.left(), box.top(), box.width(), box.height())

        outer_pen = QPen(outer_color)
        outer_pen.setWidthF(1.2)
        p.setPen(outer_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(outer, 2.5, 2.5)

        painter_method = getattr(self, f"_paint_{self._kind}", self._paint_center)
        painter_method(p, outer, accent_fill, theme)
        p.end()

    # ---------------------------------------------------------- per mode
    def _paint_center(self, p: QPainter, outer: QRectF, fill: QColor, theme) -> None:
        # 9:16 rectangle centred inside the 16:9 outer frame
        vp_h = outer.height() - 2
        vp_w = vp_h * 9.0 / 16.0
        vp = QRectF(
            outer.center().x() - vp_w / 2,
            outer.center().y() - vp_h / 2,
            vp_w,
            vp_h,
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(vp, 1.5, 1.5)

    def _paint_smart_track(self, p: QPainter, outer: QRectF, fill: QColor, theme) -> None:
        # Subject dot on the left + 9:16 viewport pulled towards it,
        # with a motion arc suggesting the viewport follows subjects.
        vp_h = outer.height() - 2
        vp_w = vp_h * 9.0 / 16.0
        vp_cx = outer.center().x() + 2.5  # slight rightward bias
        vp = QRectF(
            vp_cx - vp_w / 2,
            outer.center().y() - vp_h / 2,
            vp_w,
            vp_h,
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(vp, 1.5, 1.5)

        # Subject dot on the left
        dot_r = 1.6
        dot_cx = outer.left() + 3.5
        dot_cy = outer.center().y()
        p.setPen(Qt.PenStyle.NoPen)
        subject = QColor(theme.accent if self._active else theme.subtext0)
        p.setBrush(subject)
        p.drawEllipse(QPointF(dot_cx, dot_cy), dot_r, dot_r)

        # Motion arc (dashed) from dot toward viewport centre
        arc_pen = QPen(QColor(theme.accent if self._active else theme.overlay1))
        arc_pen.setWidthF(0.8)
        arc_pen.setStyle(Qt.PenStyle.DotLine)
        p.setPen(arc_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(dot_cx + dot_r + 0.5, dot_cy),
                   QPointF(vp.left() - 0.5, dot_cy))

    def _paint_blur_letterbox(self, p: QPainter, outer: QRectF, fill: QColor, theme) -> None:
        # Stippled side bars (simulating blur) flanking a centred 9:16.
        vp_h = outer.height() - 2
        vp_w = vp_h * 9.0 / 16.0
        vp = QRectF(
            outer.center().x() - vp_w / 2,
            outer.center().y() - vp_h / 2,
            vp_w,
            vp_h,
        )

        # Left + right stippled "blur" rails — short horizontal dashes.
        rail_color = QColor(theme.accent if self._active else theme.overlay1)
        rail_color.setAlpha(160 if self._active else 120)
        rail_pen = QPen(rail_color)
        rail_pen.setWidthF(1.0)
        rail_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(rail_pen)

        dash_len = 2.6
        gap = 1.8
        y = outer.top() + 2
        bottom = outer.bottom() - 2
        while y <= bottom:
            p.drawLine(QPointF(outer.left() + 1.6, y),
                       QPointF(vp.left() - 1.2, y))
            p.drawLine(QPointF(vp.right() + 1.2, y),
                       QPointF(outer.right() - 1.6, y))
            y += dash_len + gap

        # Centre viewport on top
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(vp, 1.5, 1.5)

    def _paint_manual(self, p: QPainter, outer: QRectF, fill: QColor, theme) -> None:
        # 9:16 with drag handles (small bars) on left + right edges.
        vp_h = outer.height() - 2
        vp_w = vp_h * 9.0 / 16.0
        vp = QRectF(
            outer.center().x() - vp_w / 2,
            outer.center().y() - vp_h / 2,
            vp_w,
            vp_h,
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(vp, 1.5, 1.5)

        # Drag-handle bars on left + right midpoints
        handle_color = QColor(theme.accent_text if self._active else theme.mantle)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(handle_color)
        handle_h = 4.0
        handle_w = 1.4
        cy = vp.center().y()
        p.drawRoundedRect(
            QRectF(vp.left() + 0.6, cy - handle_h / 2, handle_w, handle_h),
            0.6, 0.6,
        )
        p.drawRoundedRect(
            QRectF(vp.right() - handle_w - 0.6, cy - handle_h / 2, handle_w, handle_h),
            0.6, 0.6,
        )
