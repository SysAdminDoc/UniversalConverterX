"""Shared premium widgets — panel, mode card, and toast feedback."""

from __future__ import annotations

import os

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QSize,
    QTimer,
    Qt,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from PyQt6 import sip

from . import tokens
from .mode_icons import ModeIcon
from .theme import current_palette


class GlassPanel(QFrame):
    """Quiet rounded panel with optional section title."""

    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("glassPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(16, 16, 16, 16)
        self._outer.setSpacing(12)

        if title:
            lbl = QLabel(title)
            lbl.setObjectName("sectionTitle")
            self._outer.addWidget(lbl)

    def add(self, w: QWidget) -> None:
        self._outer.addWidget(w)

    def layout(self) -> QVBoxLayout:
        return self._outer


class ModeCard(QPushButton):
    """Toggleable card for a reframe mode.

    First positional arg is the *kind* string (``center`` / ``smart_track``
    / ``blur_letterbox`` / ``manual``) which drives both the painted icon
    and accessibility metadata. The legacy glyph-character first arg is
    still accepted for backwards compatibility and is mapped through.
    """

    _LEGACY_GLYPH_MAP = {
        "\u25A0": "center",
        "\u25C9": "smart_track",
        "\u25A3": "blur_letterbox",
        "\u25A9": "manual",
    }

    def __init__(
        self,
        kind: str,
        title: str,
        subtitle: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("modeCard")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(84)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(subtitle)
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

        resolved_kind = self._LEGACY_GLYPH_MAP.get(kind, kind)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)

        self._icon = ModeIcon(resolved_kind)
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._title = QLabel(title)
        self._subtitle = QLabel(subtitle)
        self._subtitle.setWordWrap(True)
        text_col.addWidget(self._title)
        text_col.addWidget(self._subtitle)
        lay.addLayout(text_col, 1)
        self.refresh_theme()
        self.toggled.connect(self._icon.set_active)

    def refresh_theme(self) -> None:
        theme = current_palette()
        self._title.setStyleSheet(
            f"color: {theme.text}; font-size: 13px; font-weight: 600; letter-spacing: -0.1px;"
        )
        self._subtitle.setStyleSheet(
            f"color: {theme.subtext0}; font-size: 11px;"
        )
        self._icon.update()

    def sizeHint(self) -> QSize:
        hint = self.layout().sizeHint()
        return QSize(max(180, hint.width()), max(84, hint.height()))

    def minimumSizeHint(self) -> QSize:
        hint = self.layout().minimumSize()
        return QSize(max(180, hint.width()), max(84, hint.height()))


class Toast(QLabel):
    """Transient floating message."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._kind = "info"
        self._apply_style()
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(250)

    def show_toast(self, text: str, duration_ms: int = 2200, kind: str = "info") -> None:
        self._kind = kind
        self._apply_style()
        self.setText("  " + text + "  ")
        self.adjustSize()
        p = self.parent()
        if isinstance(p, QWidget):
            x = (p.width() - self.width()) // 2
            y = p.height() - self.height() - 48
            self.move(x, y)
        self.setWindowOpacity(0.0)
        self.show()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(duration_ms)

    def _apply_style(self) -> None:
        theme = current_palette()
        tones = {
            "success": theme.green,
            "warning": theme.yellow,
            "error": theme.red,
            "info": theme.accent,
        }
        accent = tones.get(self._kind, theme.accent)
        self.setStyleSheet(
            f"background: {theme.mantle};"
            f"color: {theme.text};"
            f"border: 1px solid {accent};"
            f"border-radius: 10px;"
            f"padding: 10px 16px; font-size: 12px; font-weight: 600;"
        )

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._hide_once)
        self._fade.start()

    def _hide_once(self) -> None:
        try:
            self._fade.finished.disconnect(self._hide_once)
        except TypeError:
            pass
        self.hide()

    def refresh_theme(self) -> None:
        self._apply_style()


def _reduced_motion_requested() -> bool:
    """Honour the reduced-motion opt-out.

    Qt has no first-class reduced-motion signal on Windows, so we fall back
    to the environment variable the rest of the app already respects:
    ``QT_ANIMATION_DURATION_FACTOR=0`` zeros out every Qt animation. If a
    caller has explicitly set it to 0 (or 0.0), skip the fade entirely.
    """
    raw = os.environ.get("QT_ANIMATION_DURATION_FACTOR", "").strip()
    if not raw:
        return False
    try:
        return float(raw) == 0.0
    except ValueError:
        return False


class FadingTabWidget(QTabWidget):
    """QTabWidget subclass that cross-fades the incoming page on tab change.

    Plain ``QTabWidget`` snaps between pages with no transition — the cut
    reads as abrupt once every other surface in the app is styled. This
    subclass hooks ``currentChanged`` and runs a short opacity ramp on the
    new page so the switch reads as a soft dissolve instead of a cut.

    The fade is non-invasive: the stylesheet is untouched, geometry is
    unchanged, and tab order / focus behaviour is identical to the base
    class. If the user has asked for reduced motion (via
    ``QT_ANIMATION_DURATION_FACTOR=0``) the widget falls through to the
    default QTabWidget behaviour without creating an effect or animation.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fade_ms: int = tokens.M.base
        # One persistent effect + animation per page. Created lazily on
        # first reveal and stored on the widget as a dynamic property so
        # we never have to worry about stale closures or dangling pointers
        # after a deleteLater. Tearing down the page takes the effect and
        # animation with it via normal Qt parent ownership.
        self.currentChanged.connect(self._on_current_changed)

    def _on_current_changed(self, index: int) -> None:
        if sip.isdeleted(self):
            return
        widget = self.widget(index)
        if widget is None or sip.isdeleted(widget):
            return
        if _reduced_motion_requested():
            return

        effect, anim = self._ensure_fade_actors(widget)
        anim.stop()
        # Reset opacity for a clean fade-in every time the tab is shown.
        effect.setEnabled(True)
        effect.setOpacity(0.0)
        anim.start()

    def _ensure_fade_actors(self, widget: QWidget) -> tuple[QGraphicsOpacityEffect, QPropertyAnimation]:
        """Lazily attach (and cache) the effect + animation on the page.

        Cached on the widget via ``setProperty``-style private attrs so that
        when the widget is destroyed, the effect and animation go with it.
        Nothing outside the widget holds a reference, so there is no way
        for the finished() signal to fire on a dead target.
        """
        effect: QGraphicsOpacityEffect | None = getattr(widget, "_vertigo_fade_effect", None)
        anim: QPropertyAnimation | None = getattr(widget, "_vertigo_fade_anim", None)
        if effect is None or sip.isdeleted(effect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            widget._vertigo_fade_effect = effect  # type: ignore[attr-defined]
        if anim is None or sip.isdeleted(anim):
            anim = QPropertyAnimation(effect, b"opacity", widget)
            anim.setDuration(self._fade_ms)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            widget._vertigo_fade_anim = anim  # type: ignore[attr-defined]
        return effect, anim
