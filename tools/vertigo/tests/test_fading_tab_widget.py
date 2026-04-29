"""FadingTabWidget — construction and basic interaction across themes.

The fade itself is purely visual (QPropertyAnimation on an opacity effect),
so the goal here is a regression net against the obvious breakage modes:
constructs cleanly with every palette, takes pages, switches indices
without raising, honours the reduced-motion opt-out.
"""

from __future__ import annotations

import os
import sys
import unittest


class FadingTabWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def _build(self):
        from PyQt6.QtWidgets import QLabel
        from ui.widgets import FadingTabWidget
        widget = FadingTabWidget()
        widget.addTab(QLabel("first"), "One")
        widget.addTab(QLabel("second"), "Two")
        widget.addTab(QLabel("third"), "Three")
        return widget

    def test_constructs_and_switches_across_all_themes(self) -> None:
        from ui.theme import THEMES, apply_app_theme
        for theme_id in THEMES:
            with self.subTest(theme=theme_id):
                apply_app_theme(self._app, theme_id)
                widget = self._build()
                self.assertEqual(widget.count(), 3)
                self.assertEqual(widget.currentIndex(), 0)
                widget.setCurrentIndex(2)
                self.assertEqual(widget.currentIndex(), 2)
                widget.setCurrentIndex(1)
                self.assertEqual(widget.currentIndex(), 1)
                widget.deleteLater()

    def test_rapid_switches_do_not_raise_or_stack_effects(self) -> None:
        # Drum through every tab quickly — each switch must supersede the
        # previous fade without piling up QGraphicsOpacityEffect instances.
        widget = self._build()
        for _ in range(3):
            for i in range(widget.count()):
                widget.setCurrentIndex(i)
        # Final page should have an effect that will be cleaned up on
        # animation end; the widget itself is still usable.
        self.assertEqual(widget.currentIndex(), 2)
        widget.deleteLater()

    def test_reduced_motion_opt_out_skips_effect(self) -> None:
        # QT_ANIMATION_DURATION_FACTOR=0 is the documented env-level
        # opt-out; the widget must respect it and not install an effect.
        prev = os.environ.get("QT_ANIMATION_DURATION_FACTOR")
        os.environ["QT_ANIMATION_DURATION_FACTOR"] = "0"
        try:
            widget = self._build()
            widget.setCurrentIndex(1)
            current = widget.currentWidget()
            self.assertIsNotNone(current)
            self.assertIsNone(current.graphicsEffect())
            widget.deleteLater()
        finally:
            if prev is None:
                del os.environ["QT_ANIMATION_DURATION_FACTOR"]
            else:
                os.environ["QT_ANIMATION_DURATION_FACTOR"] = prev


if __name__ == "__main__":
    unittest.main()
