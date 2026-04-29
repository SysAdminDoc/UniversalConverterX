"""Theme token coverage for Vertigo's PyQt theme system."""

from __future__ import annotations

import os
import sys
import unittest

from ui.theme import (
    SYSTEM_THEME_ID,
    THEMES,
    apply_app_theme,
    build_stylesheet,
    ensure_glyph_assets,
    qcolor,
    resolved_theme_id,
    sanitize_theme_preference,
)


def _rgb(hex_color: str) -> tuple[float, float, float]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _linear(channel: float) -> float:
    if channel <= 0.03928:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    r, g, b = (_linear(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(foreground: str, background: str) -> float:
    a = _luminance(foreground)
    b = _luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


class ThemeTokenTests(unittest.TestCase):
    def test_stylesheet_builds_for_every_theme(self) -> None:
        for theme_id, theme in THEMES.items():
            with self.subTest(theme=theme_id):
                stylesheet = build_stylesheet(theme_id)
                self.assertIn(theme.text, stylesheet)
                self.assertIn(theme.accent, stylesheet)
                self.assertIn("QFileDialog", stylesheet)
                self.assertIn("QLineEdit", stylesheet)

    def test_stylesheet_covers_every_common_widget_class(self) -> None:
        required_selectors = (
            "QCheckBox", "QRadioButton", "QGroupBox", "QMenu",
            "QComboBox", "QSlider", "QProgressBar", "QTabWidget",
            "QScrollBar", "QToolTip",
        )
        for theme_id in THEMES:
            stylesheet = build_stylesheet(theme_id)
            for selector in required_selectors:
                with self.subTest(theme=theme_id, selector=selector):
                    self.assertIn(selector, stylesheet)

    def test_stylesheet_is_free_of_dead_line_height_rules(self) -> None:
        # Qt Widgets QSS ignores `line-height`; keep the stylesheet free of
        # it so readers don't expect the declared spacing to apply.
        for theme_id in THEMES:
            self.assertNotIn("line-height", build_stylesheet(theme_id))

    def test_radii_follow_token_scale(self) -> None:
        # We reserve 6 / 10 / 14 / 18 / 999 for the product. Any other
        # radius would be drift worth cleaning up before we ship.
        # 2/3/4/5/9 are half-values used on handle-sized elements
        # (scrollbar, splitter, progress chunk, slider thumb).
        allowed = {"6px", "8px", "10px", "14px", "18px", "999px",
                   "2px", "3px", "4px", "5px", "9px"}
        import re
        for theme_id in THEMES:
            sheet = build_stylesheet(theme_id)
            for match in re.findall(r"border-radius:\s*([^;]+);", sheet):
                value = match.strip()
                with self.subTest(theme=theme_id, value=value):
                    self.assertIn(value, allowed)

    def test_theme_preference_sanitization(self) -> None:
        self.assertEqual(sanitize_theme_preference("mocha"), "mocha")
        self.assertEqual(sanitize_theme_preference("latte"), "latte")
        self.assertEqual(sanitize_theme_preference("missing"), SYSTEM_THEME_ID)
        self.assertEqual(sanitize_theme_preference(None), SYSTEM_THEME_ID)

    def test_explicit_theme_resolution_does_not_need_qapp(self) -> None:
        self.assertEqual(resolved_theme_id("mocha"), "mocha")
        self.assertEqual(resolved_theme_id("graphite"), "graphite")
        self.assertEqual(resolved_theme_id("latte"), "latte")

    def test_rgba_token_parsing(self) -> None:
        color = qcolor("rgba(10, 20, 30, 0.50)")
        self.assertEqual((color.red(), color.green(), color.blue()), (10, 20, 30))
        self.assertIn(color.alpha(), (127, 128))

    def test_core_text_contrast_is_accessible(self) -> None:
        pairs = (
            ("text", "base"),
            ("text", "mantle"),
            ("text", "crust"),
            ("subtext1", "base"),
            ("subtext1", "mantle"),
            ("accent_text", "accent"),
        )
        for theme_id, theme in THEMES.items():
            for fg_name, bg_name in pairs:
                with self.subTest(theme=theme_id, pair=f"{fg_name}/{bg_name}"):
                    fg = getattr(theme, fg_name)
                    bg = getattr(theme, bg_name)
                    self.assertGreaterEqual(_contrast(fg, bg), 4.5)

    def test_status_text_contrast_is_accessible_on_main_surfaces(self) -> None:
        for theme_id, theme in THEMES.items():
            for color_name in ("red", "yellow", "green"):
                with self.subTest(theme=theme_id, color=color_name):
                    self.assertGreaterEqual(_contrast(getattr(theme, color_name), theme.base), 3.0)
                    self.assertGreaterEqual(_contrast(getattr(theme, color_name), theme.mantle), 3.0)


class GlyphCacheTests(unittest.TestCase):
    """Rendering PNG glyphs needs a QApplication; create one lazily."""

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_apply_app_theme_writes_checkbox_glyphs_for_every_theme(self) -> None:
        # Each explicit theme must produce a cached 'check' PNG on disk —
        # otherwise the QCheckBox indicator falls back to bare accent fill.
        for theme_id in THEMES:
            with self.subTest(theme=theme_id):
                apply_app_theme(self._app, theme_id)
                glyphs = ensure_glyph_assets(theme_id)
                self.assertIn("check", glyphs)
                self.assertTrue(glyphs["check"].exists(), glyphs["check"])
                self.assertGreater(glyphs["check"].stat().st_size, 0)
                self.assertIn("check_minus", glyphs)
                self.assertTrue(glyphs["check_minus"].exists())

    def test_apply_app_theme_writes_chevron_glyphs_for_every_theme(self) -> None:
        # Same story for QComboBox::down-arrow — three tints per theme.
        for theme_id in THEMES:
            with self.subTest(theme=theme_id):
                apply_app_theme(self._app, theme_id)
                glyphs = ensure_glyph_assets(theme_id)
                for key in ("chevron", "chevron_hover", "chevron_focus"):
                    self.assertIn(key, glyphs)
                    self.assertTrue(glyphs[key].exists())
                    self.assertGreater(glyphs[key].stat().st_size, 0)

    def test_glyph_cache_is_reused_between_calls(self) -> None:
        # Second call must not re-bake: mtime stable for an existing file.
        apply_app_theme(self._app, "mocha")
        first = ensure_glyph_assets("mocha")["check"]
        mtime_before = first.stat().st_mtime
        again = ensure_glyph_assets("mocha")["check"]
        self.assertEqual(first, again)
        self.assertEqual(mtime_before, again.stat().st_mtime)


if __name__ == "__main__":
    unittest.main()
