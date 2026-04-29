"""Centralized theme tokens, stylesheet generation, and app theme helpers."""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPalette
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication


@dataclass(frozen=True)
class ThemePalette:
    id: str
    label: str
    mode: str  # "dark" | "light"
    base: str
    mantle: str
    crust: str
    surface0: str
    surface1: str
    surface2: str
    overlay0: str
    overlay1: str
    overlay2: str
    subtext0: str
    subtext1: str
    text: str
    accent: str
    accent_soft: str
    accent_muted: str
    accent_hover: str
    accent_selected: str
    accent_text: str
    red: str
    red_soft: str
    yellow: str
    yellow_soft: str
    green: str
    green_soft: str
    pink: str
    focus: str
    scrim: str
    overlay_scrim: str
    hint_bg: str
    hint_text: str


THEMES: dict[str, ThemePalette] = {
    "mocha": ThemePalette(
        id="mocha",
        label="Mocha",
        mode="dark",
        base="#1e1e2e",
        mantle="#181825",
        crust="#11111b",
        surface0="#313244",
        surface1="#45475a",
        surface2="#585b70",
        overlay0="#6c7086",
        overlay1="#7f849c",
        overlay2="#9399b2",
        subtext0="#a6adc8",
        subtext1="#bac2de",
        text="#cdd6f4",
        accent="#cba6f7",
        accent_soft="#b990f2",
        accent_muted="rgba(203, 166, 247, 0.06)",
        accent_hover="rgba(203, 166, 247, 0.08)",
        accent_selected="rgba(203, 166, 247, 0.12)",
        accent_text="#11111b",
        red="#f38ba8",
        red_soft="rgba(243, 139, 168, 0.10)",
        yellow="#f9e2af",
        yellow_soft="rgba(249, 226, 175, 0.08)",
        green="#a6e3a1",
        green_soft="rgba(166, 227, 161, 0.08)",
        pink="#f5c2e7",
        focus="#b4befe",
        scrim="rgba(0, 0, 0, 0.60)",
        overlay_scrim="rgba(0, 0, 0, 0.58)",
        hint_bg="rgba(17, 17, 27, 0.84)",
        hint_text="#cdd6f4",
    ),
    "graphite": ThemePalette(
        id="graphite",
        label="Graphite",
        mode="dark",
        base="#181a20",
        mantle="#121419",
        crust="#0b0d11",
        surface0="#252832",
        surface1="#353946",
        surface2="#4a5060",
        overlay0="#687083",
        overlay1="#858da0",
        overlay2="#a0a8b8",
        subtext0="#b7bfcc",
        subtext1="#d3d8e3",
        text="#eef1f7",
        accent="#8ab4ff",
        accent_soft="#76a3f2",
        accent_muted="rgba(138, 180, 255, 0.07)",
        accent_hover="rgba(138, 180, 255, 0.10)",
        accent_selected="rgba(138, 180, 255, 0.16)",
        accent_text="#07111f",
        red="#ff7a90",
        red_soft="rgba(255, 122, 144, 0.11)",
        yellow="#ffd166",
        yellow_soft="rgba(255, 209, 102, 0.09)",
        green="#76d391",
        green_soft="rgba(118, 211, 145, 0.09)",
        pink="#c7a6ff",
        focus="#b9d3ff",
        scrim="rgba(0, 0, 0, 0.58)",
        overlay_scrim="rgba(0, 0, 0, 0.56)",
        hint_bg="rgba(11, 13, 17, 0.86)",
        hint_text="#eef1f7",
    ),
    "latte": ThemePalette(
        id="latte",
        label="Latte",
        mode="light",
        base="#f6f7fb",
        mantle="#ffffff",
        crust="#eef1f6",
        surface0="#e7ebf3",
        surface1="#d9deea",
        surface2="#c8cfdd",
        overlay0="#8791a3",
        overlay1="#667086",
        overlay2="#4d576b",
        subtext0="#596376",
        subtext1="#384255",
        text="#172033",
        accent="#7157d9",
        accent_soft="#624bc4",
        accent_muted="rgba(113, 87, 217, 0.07)",
        accent_hover="rgba(113, 87, 217, 0.10)",
        accent_selected="rgba(113, 87, 217, 0.14)",
        accent_text="#ffffff",
        red="#bd2942",
        red_soft="rgba(189, 41, 66, 0.09)",
        yellow="#805b00",
        yellow_soft="rgba(128, 91, 0, 0.08)",
        green="#23784a",
        green_soft="rgba(35, 120, 74, 0.08)",
        pink="#a43f91",
        focus="#4d68d8",
        scrim="rgba(20, 27, 42, 0.38)",
        overlay_scrim="rgba(20, 27, 42, 0.50)",
        hint_bg="rgba(255, 255, 255, 0.92)",
        hint_text="#172033",
    ),
}

DEFAULT_THEME_ID = "mocha"
SYSTEM_THEME_ID = "system"


class Mocha:
    """Compatibility palette for older imports. Prefer current_palette()."""

    base = THEMES["mocha"].base
    mantle = THEMES["mocha"].mantle
    crust = THEMES["mocha"].crust
    surface0 = THEMES["mocha"].surface0
    surface1 = THEMES["mocha"].surface1
    surface2 = THEMES["mocha"].surface2
    overlay0 = THEMES["mocha"].overlay0
    overlay1 = THEMES["mocha"].overlay1
    overlay2 = THEMES["mocha"].overlay2
    subtext0 = THEMES["mocha"].subtext0
    subtext1 = THEMES["mocha"].subtext1
    text = THEMES["mocha"].text
    mauve = THEMES["mocha"].accent
    pink = THEMES["mocha"].pink
    red = THEMES["mocha"].red
    peach = "#fab387"
    yellow = THEMES["mocha"].yellow
    green = THEMES["mocha"].green
    teal = "#94e2d5"
    sky = "#89dceb"
    sapphire = "#74c7ec"
    blue = "#89b4fa"
    lavender = THEMES["mocha"].focus


def theme_choices() -> list[tuple[str, str]]:
    return [(SYSTEM_THEME_ID, "System")] + [(theme.id, theme.label) for theme in THEMES.values()]


def sanitize_theme_preference(preference: str | None) -> str:
    if preference == SYSTEM_THEME_ID:
        return SYSTEM_THEME_ID
    if preference in THEMES:
        return preference
    return SYSTEM_THEME_ID


def resolved_theme_id(preference: str | None = None) -> str:
    pref = sanitize_theme_preference(preference or app_theme_preference())
    if pref != SYSTEM_THEME_ID:
        return pref
    return "mocha" if _system_is_dark() else "latte"


def _system_is_dark() -> bool:
    app = QApplication.instance()
    if app is None:
        return True
    try:
        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        pass
    window = app.palette().color(QPalette.ColorRole.Window)
    return window.lightness() < 128


def current_palette() -> ThemePalette:
    app = QApplication.instance()
    if app is not None:
        theme_id = app.property("vertigoThemeId")
        if isinstance(theme_id, str) and theme_id in THEMES:
            return THEMES[theme_id]
    return THEMES[resolved_theme_id()]


def app_theme_preference() -> str:
    app = QApplication.instance()
    if app is not None:
        pref = app.property("vertigoThemePreference")
        if isinstance(pref, str):
            return sanitize_theme_preference(pref)
    return SYSTEM_THEME_ID


def apply_app_theme(app: QApplication, preference: str | None) -> ThemePalette:
    pref = sanitize_theme_preference(preference)
    theme = THEMES[resolved_theme_id(pref)]
    app.setProperty("vertigoThemePreference", pref)
    app.setProperty("vertigoThemeId", theme.id)
    app.setPalette(build_qpalette(theme))
    # Bake glyph PNGs first so the stylesheet can reference real files —
    # QSS that points at a non-existent image silently renders nothing.
    ensure_glyph_assets(theme.id)
    app.setStyleSheet(build_stylesheet(pref))
    return theme


def build_qpalette(theme: ThemePalette) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(theme.base))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Base, QColor(theme.crust))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(theme.surface0))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(theme.surface0))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Text, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.Button, QColor(theme.surface0))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(theme.text))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(theme.red))
    palette.setColor(QPalette.ColorRole.Link, QColor(theme.accent))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(theme.accent))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme.accent_text))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme.overlay1))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(theme.overlay1))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(theme.overlay1))
    return palette


def to_qcolor(hex_str: str, alpha: int = 255) -> QColor:
    c = QColor(hex_str)
    c.setAlpha(alpha)
    return c


def qcolor(hex_or_rgba: str) -> QColor:
    value = hex_or_rgba.strip()
    if value.startswith("rgba(") and value.endswith(")"):
        raw = value[5:-1]
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) == 4:
            r, g, b = (int(float(parts[i])) for i in range(3))
            alpha_raw = float(parts[3])
            alpha = int(alpha_raw * 255) if alpha_raw <= 1 else int(alpha_raw)
            return QColor(r, g, b, max(0, min(255, alpha)))
    return QColor(value)


# ---------------------------------------------------------------- glyph cache
# Qt's QSS engine wants a concrete image file for indicator glyphs
# (::indicator image:, ::down-arrow image:). Data-URIs are flaky across Qt
# versions on Windows, so we bake one PNG per (theme, glyph) to a writable
# cache on disk and point QSS at it with forward-slash URLs.
#
# Each SVG in assets/ uses `currentColor` so a single source can be coloured
# at bake time — we substitute the colour into the source text before feeding
# it to QSvgRenderer and rendering to a QImage.

_GLYPH_SOURCES: dict[str, str] = {
    # glyph key -> asset filename; colour role is chosen per caller below.
    # Same SVG can back multiple tints (e.g. chevron at rest vs. hover/focus).
    "check":           "check.svg",
    "check_minus":     "check_minus.svg",
    "chevron":         "chevron.svg",
    "chevron_hover":   "chevron.svg",
    "chevron_focus":   "chevron.svg",
}

# Rendered at 2x the logical size so the QSS image stays crisp on HiDPI.
_GLYPH_PX = 32


def _cache_root() -> Path:
    """Writable glyph-cache directory.

    Mirrors ``vertigo._log_dir()`` so the glyphs live next to crash.log in
    %LOCALAPPDATA%/Vertigo (or the platform equivalent). Replicated here to
    avoid importing the entry module.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Logs")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    root = Path(base) / "Vertigo" / "glyphs"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        root = Path(os.environ.get("TEMP") or "/tmp") / "vertigo-glyphs"
        root.mkdir(parents=True, exist_ok=True)
    return root


def _asset_source(filename: str) -> str | None:
    """Read an SVG from the project's assets directory (repo or frozen bundle)."""
    try:
        from .assets import asset_root
    except Exception:
        return None
    path = asset_root() / filename
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _palette_hash(theme: ThemePalette, colours: tuple[str, ...]) -> str:
    """Short hash over the exact hex values used for this cache entry.

    Keyed so that edits to a single colour in a theme bust only that theme's
    PNG — not the others.
    """
    payload = "|".join(colours).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:8]


def _render_tinted_svg(source: str, hex_color: str, size: int = _GLYPH_PX) -> QImage:
    tinted = source.replace("currentColor", hex_color)
    renderer = QSvgRenderer(tinted.encode("utf-8"))
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return img


def ensure_glyph_assets(theme_id: str) -> dict[str, Path]:
    """Bake the per-theme glyph PNGs and return a map of keys to cached paths.

    Safe to call on every theme apply — existing files are reused without
    repainting. Missing source SVGs or render failures are tolerated: the
    affected key is simply omitted from the returned dict and QSS falls
    back to a bare indicator.
    """
    theme = THEMES.get(theme_id)
    if theme is None:
        return {}

    # (glyph key, hex color)
    recipes: tuple[tuple[str, str], ...] = (
        ("check",         theme.accent_text),
        ("check_minus",   theme.accent_text),
        ("chevron",       theme.subtext0),
        ("chevron_hover", theme.text),
        ("chevron_focus", theme.accent),
    )
    digest = _palette_hash(theme, tuple(c for _, c in recipes))
    out_dir = _cache_root() / theme_id
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Path] = {}
    for key, colour in recipes:
        filename = _GLYPH_SOURCES.get(key)
        if not filename:
            continue
        out_path = out_dir / f"{key}-{digest}.png"
        if not out_path.exists():
            source = _asset_source(filename)
            if source is None:
                continue
            try:
                img = _render_tinted_svg(source, colour)
                if not img.save(str(out_path), "PNG"):
                    continue
            except Exception:
                continue
        results[key] = out_path
    return results


def _qss_path(p: Path) -> str:
    """Forward-slash absolute path for QSS `url(...)` — Windows-safe."""
    return str(p).replace("\\", "/")


def build_stylesheet(preference: str | None = None) -> str:
    """Compose Vertigo's QSS from theme tokens.

    Conventions this stylesheet enforces:
      - One radius scale: 6 (chip) / 10 (control) / 14 (panel) / 18 (hero)
      - One spacing rhythm: multiples of 4 px
      - One type scale:   11 caption / 12 small / 13 body / 15 title / 20 display
      - Sentence-case labels (never SHOUTY CAPS on interactive elements);
        UPPERCASE reserved for low-weight section headers with clear tracking
      - Focus state is a coloured border that keeps the same 1 px width,
        so there is no layout shift between resting → focused
      - Backgrounds carry visual layering: base (resting) → mantle (elevated)
        → surface0 (raised) → surface1 (pressed/hovered raised)
    """
    theme_id = resolved_theme_id(preference)
    t = THEMES[theme_id]

    glyphs = ensure_glyph_assets(theme_id)
    check_url          = _qss_path(glyphs["check"])         if "check"         in glyphs else ""
    minus_url          = _qss_path(glyphs["check_minus"])   if "check_minus"   in glyphs else ""
    chevron_url        = _qss_path(glyphs["chevron"])       if "chevron"       in glyphs else ""
    chevron_hover_url  = _qss_path(glyphs["chevron_hover"]) if "chevron_hover" in glyphs else chevron_url
    chevron_focus_url  = _qss_path(glyphs["chevron_focus"]) if "chevron_focus" in glyphs else chevron_url

    check_img         = f"image: url({check_url});"         if check_url         else ""
    minus_img         = f"image: url({minus_url});"         if minus_url         else ""
    chevron_img       = f"image: url({chevron_url});"       if chevron_url       else ""
    chevron_hover_img = f"image: url({chevron_hover_url});" if chevron_hover_url else ""
    chevron_focus_img = f"image: url({chevron_focus_url});" if chevron_focus_url else ""

    return f"""
* {{
    font-family: "Segoe UI Variable Display", "Segoe UI", "Inter", system-ui, -apple-system, sans-serif;
    color: {t.text};
    selection-background-color: {t.accent};
    selection-color: {t.accent_text};
}}

QMainWindow, QWidget#rootWidget {{
    background: {t.base};
}}

/* ------------------------------------------------------------- chrome */

QWidget#titleBar {{
    background: {t.mantle};
    border-bottom: 1px solid {t.surface0};
}}

QLabel#titleText {{
    color: {t.subtext0};
    font-weight: 500;
    font-size: 12px;
}}

QLabel#brand {{
    color: {t.text};
    font-weight: 700;
    font-size: 15px;
    letter-spacing: 0.2px;
}}

QLabel#brandDot {{
    color: {t.accent};
    font-size: 16px;
}}

QLabel#titleSep {{
    color: {t.surface1};
    font-size: 12px;
}}

QPushButton#winCtl, QPushButton#winClose {{
    background: transparent;
    color: {t.subtext0};
    border: none;
    min-width: 44px;
    min-height: 32px;
    font-size: 13px;
}}
QPushButton#winCtl:hover {{
    background: {t.surface0};
    color: {t.text};
}}
QPushButton#winClose:hover {{
    background: {t.red};
    color: {t.accent_text};
}}
QPushButton#winCtl:focus, QPushButton#winClose:focus {{
    background: {t.surface0};
    color: {t.text};
}}

QComboBox#themePicker {{
    min-width: 108px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
    background: transparent;
    border: 1px solid transparent;
    color: {t.subtext1};
}}
QComboBox#themePicker:hover {{
    background: {t.surface0};
    border-color: {t.surface0};
    color: {t.text};
}}
QComboBox#themePicker:focus {{
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- surfaces */

QWidget#glassPanel, QFrame#glassPanel {{
    background: {t.mantle};
    border: 1px solid {t.surface0};
    border-radius: 14px;
}}

QWidget#heroPanel, QFrame#heroPanel {{
    background: {t.mantle};
    border: 1px solid {t.surface0};
    border-radius: 18px;
}}

QWidget#emptyState {{
    background: {t.base};
    border: 1px dashed {t.surface1};
    border-radius: 14px;
}}

/* ------------------------------------------------------------- type */

QLabel#sectionTitle {{
    color: {t.overlay2};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.4px;
    text-transform: uppercase;
}}

QLabel#bigTitle {{
    color: {t.text};
    font-size: 20px;
    font-weight: 600;
    letter-spacing: -0.2px;
}}

QLabel#subtitle {{
    color: {t.subtext0};
    font-size: 12px;
}}

QLabel#valueMuted {{
    color: {t.overlay2};
    font-size: 11px;
    font-weight: 500;
}}

QLabel#valueBright {{
    color: {t.text};
    font-size: 13px;
    font-weight: 600;
}}

QLabel#formLabel {{
    color: {t.subtext0};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
}}

QLabel#formValue {{
    color: {t.subtext1};
    font-size: 12px;
    font-weight: 600;
}}

QLabel#emptyTitle {{
    color: {t.text};
    font-size: 14px;
    font-weight: 600;
    letter-spacing: -0.1px;
}}

QLabel#emptyBody {{
    color: {t.subtext0};
    font-size: 12px;
}}

/* ------------------------------------------------------------- pills & notices */

QLabel#statusPill {{
    background: {t.base};
    color: {t.subtext1};
    border: 1px solid {t.surface0};
    border-radius: 999px;
    padding: 5px 12px;
    font-size: 11px;
    font-weight: 600;
}}
QLabel#statusPill[tone="accent"] {{
    color: {t.accent};
    border-color: {t.accent};
    background: {t.accent_muted};
}}
QLabel#statusPill[tone="success"] {{
    color: {t.green};
    border-color: {t.green};
    background: {t.green_soft};
}}
QLabel#statusPill[tone="warning"] {{
    color: {t.yellow};
    border-color: {t.yellow};
    background: {t.yellow_soft};
}}
QLabel#statusPill[tone="error"] {{
    color: {t.red};
    border-color: {t.red};
    background: {t.red_soft};
}}

QLabel#inlineNotice {{
    background: {t.base};
    color: {t.subtext0};
    border: 1px solid {t.surface0};
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 12px;
}}
QLabel#inlineNotice[tone="warning"] {{
    color: {t.yellow};
    border-color: {t.yellow};
    background: {t.yellow_soft};
}}
QLabel#inlineNotice[tone="success"] {{
    color: {t.green};
    border-color: {t.green};
    background: {t.green_soft};
}}
QLabel#inlineNotice[tone="accent"] {{
    color: {t.accent};
    border-color: {t.accent};
    background: {t.accent_muted};
}}

/* ------------------------------------------------------------- buttons */

QPushButton#primaryBtn {{
    background: {t.accent};
    color: {t.accent_text};
    border: 1px solid {t.accent};
    border-radius: 10px;
    padding: 11px 22px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.1px;
}}
QPushButton#primaryBtn:hover {{
    background: {t.accent_soft};
    border-color: {t.accent_soft};
}}
QPushButton#primaryBtn:pressed {{
    background: {t.accent_soft};
    border-color: {t.accent_soft};
}}
QPushButton#primaryBtn:focus {{
    border-color: {t.focus};
}}
QPushButton#primaryBtn:disabled {{
    background: {t.surface0};
    border-color: {t.surface0};
    color: {t.overlay0};
}}

QPushButton#ghostBtn {{
    background: transparent;
    color: {t.subtext1};
    border: 1px solid {t.surface1};
    border-radius: 10px;
    padding: 9px 16px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#ghostBtn:hover {{
    border-color: {t.surface2};
    color: {t.text};
    background: {t.accent_hover};
}}
QPushButton#ghostBtn:pressed {{
    background: {t.accent_muted};
}}
QPushButton#ghostBtn:focus {{
    border-color: {t.focus};
}}
QPushButton#ghostBtn:disabled {{
    border-color: {t.surface0};
    color: {t.overlay0};
}}

QPushButton#destructiveGhost {{
    background: transparent;
    color: {t.subtext1};
    border: 1px solid {t.surface1};
    border-radius: 10px;
    padding: 9px 16px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#destructiveGhost:hover {{
    border-color: {t.red};
    color: {t.red};
    background: {t.red_soft};
}}
QPushButton#destructiveGhost:focus {{
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- mode cards */

QPushButton#modeCard {{
    background: {t.base};
    color: {t.subtext1};
    border: 1px solid {t.surface0};
    border-radius: 14px;
    padding: 16px;
    text-align: left;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#modeCard:hover {{
    border-color: {t.surface2};
    background: {t.accent_hover};
    color: {t.text};
}}
QPushButton#modeCard:checked {{
    border-color: {t.accent};
    background: {t.accent_selected};
    color: {t.text};
}}
QPushButton#modeCard:disabled {{
    color: {t.overlay1};
    border-color: {t.surface0};
    background: {t.mantle};
}}
QPushButton#modeCard:focus {{
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- chips */

QPushButton#presetChip {{
    background: transparent;
    color: {t.subtext1};
    border: 1px solid {t.surface1};
    border-radius: 999px;
    padding: 8px 14px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.1px;
}}
QPushButton#presetChip:hover {{
    background: {t.accent_hover};
    color: {t.text};
    border-color: {t.surface2};
}}
QPushButton#presetChip:checked {{
    background: {t.accent};
    color: {t.accent_text};
    border-color: {t.accent};
}}
QPushButton#presetChip:disabled {{
    color: {t.overlay1};
    border-color: {t.surface0};
}}
QPushButton#presetChip:focus {{
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- drop zone */

QLabel#dropZone {{
    color: {t.subtext0};
    border: 1px dashed {t.surface2};
    border-radius: 14px;
    padding: 32px;
    background: {t.base};
    font-size: 13px;
}}
QLabel#dropZone[hover="true"] {{
    border-color: {t.accent};
    color: {t.text};
    background: {t.accent_hover};
}}
QLabel#dropZone:focus {{
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- sliders */

QSlider::groove:horizontal {{
    height: 4px;
    background: {t.surface0};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {t.accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {t.accent};
    border: 2px solid {t.mantle};
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 9px;
}}
QSlider::handle:horizontal:hover {{
    background: {t.accent_soft};
}}
QSlider::handle:horizontal:pressed {{
    background: {t.accent_soft};
    border-color: {t.focus};
}}
QSlider:focus {{
}}
QSlider:focus::handle:horizontal {{
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- progress */

QProgressBar {{
    background: {t.surface0};
    border: none;
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: {t.subtext0};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QProgressBar::chunk {{
    background: {t.accent};
    border-radius: 5px;
}}

/* ------------------------------------------------------------- log */

QTextEdit#logPanel {{
    background: {t.crust};
    border: 1px solid {t.surface0};
    border-radius: 10px;
    color: {t.subtext0};
    font-family: "Cascadia Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 11px;
    padding: 10px 12px;
    selection-background-color: {t.accent_selected};
    selection-color: {t.text};
}}

/* ------------------------------------------------------------- scrollbars */

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {t.surface1};
    border-radius: 4px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t.surface2};
}}
QScrollBar::handle:vertical:pressed {{
    background: {t.overlay0};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
    height: 0;
    width: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 0 2px;
}}
QScrollBar::handle:horizontal {{
    background: {t.surface1};
    border-radius: 4px;
    min-width: 32px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {t.surface2};
}}
QScrollBar::handle:horizontal:pressed {{
    background: {t.overlay0};
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: none;
    height: 0;
    width: 0;
}}

/* ------------------------------------------------------------- tooltip */

QToolTip {{
    background: {t.crust};
    color: {t.text};
    border: 1px solid {t.surface1};
    padding: 6px 10px;
    border-radius: 8px;
    font-size: 11px;
}}

/* ------------------------------------------------------------- combobox */

QComboBox {{
    background: {t.crust};
    border: 1px solid {t.surface1};
    border-radius: 10px;
    padding: 7px 12px;
    color: {t.text};
    font-size: 12px;
    font-weight: 500;
    selection-background-color: {t.accent};
    selection-color: {t.accent_text};
}}
QComboBox:hover {{
    border-color: {t.surface2};
}}
QComboBox:focus {{
    border-color: {t.focus};
}}
QComboBox:disabled {{
    color: {t.overlay1};
    background: {t.mantle};
    border-color: {t.surface0};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
    margin-right: 2px;
}}
QComboBox::down-arrow {{
    {chevron_img}
    width: 12px;
    height: 12px;
}}
QComboBox:hover::down-arrow {{
    {chevron_hover_img}
}}
QComboBox:focus::down-arrow, QComboBox::down-arrow:on {{
    {chevron_focus_img}
}}
QComboBox QAbstractItemView {{
    background: {t.mantle};
    color: {t.text};
    border: 1px solid {t.surface1};
    border-radius: 10px;
    padding: 4px;
    selection-background-color: {t.accent_selected};
    selection-color: {t.text};
    outline: none;
}}

/* ------------------------------------------------------------- inputs */

QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {t.crust};
    color: {t.text};
    border: 1px solid {t.surface1};
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 12px;
    selection-background-color: {t.accent};
    selection-color: {t.accent_text};
}}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {t.surface2};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {t.accent};
    background: {t.mantle};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {t.mantle};
    border-color: {t.surface0};
    color: {t.overlay1};
}}
QLineEdit[readOnly="true"] {{
    background: {t.mantle};
    color: {t.subtext0};
    border-color: {t.surface0};
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 16px;
    border: none;
    background: transparent;
}}

/* ------------------------------------------------------------- lists */

QListView, QTreeView, QTableView {{
    background: {t.crust};
    color: {t.text};
    border: 1px solid {t.surface0};
    border-radius: 10px;
    padding: 4px;
    selection-background-color: {t.accent_selected};
    selection-color: {t.text};
    alternate-background-color: {t.base};
}}
QListView::item, QTreeView::item, QTableView::item {{
    padding: 6px 10px;
    border-radius: 6px;
}}
QListView::item:hover, QTreeView::item:hover, QTableView::item:hover {{
    background: {t.accent_hover};
}}
QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {{
    background: {t.accent_selected};
    color: {t.text};
}}
QHeaderView::section {{
    background: {t.surface0};
    color: {t.subtext1};
    border: none;
    border-right: 1px solid {t.surface1};
    padding: 8px 10px;
    font-weight: 600;
    font-size: 11px;
}}

/* ------------------------------------------------------------- tabs */

QTabWidget::pane {{
    border: 1px solid {t.surface0};
    border-radius: 14px;
    background: {t.mantle};
    top: 0;
}}
QTabWidget QTabBar {{
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background: transparent;
    color: {t.overlay2};
    padding: 9px 12px;
    margin: 6px 4px 0 0;
    border: 1px solid transparent;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
}}
QTabBar::tab:hover {{
    color: {t.subtext1};
    background: {t.accent_hover};
}}
QTabBar::tab:selected {{
    color: {t.text};
    border-color: {t.surface1};
    background: {t.accent_muted};
}}
QTabBar::tab:focus {{
    color: {t.text};
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- splitter */

QSplitter::handle {{
    background: {t.base};
}}
QSplitter::handle:horizontal {{
    width: 6px;
    margin: 0 2px;
    border-radius: 3px;
}}
QSplitter::handle:hover {{
    background: {t.surface0};
}}
QSplitter::handle:pressed {{
    background: {t.surface1};
}}

/* ------------------------------------------------------------- dialogs */

QMessageBox, QDialog, QFileDialog {{
    background: {t.mantle};
    color: {t.text};
}}
QMessageBox QLabel, QDialog QLabel, QFileDialog QLabel {{
    color: {t.text};
}}
QMessageBox QPushButton, QDialog QPushButton, QFileDialog QPushButton {{
    background: transparent;
    color: {t.subtext1};
    border: 1px solid {t.surface1};
    border-radius: 10px;
    padding: 8px 16px;
    min-width: 82px;
    font-size: 12px;
    font-weight: 600;
}}
QMessageBox QPushButton:hover, QDialog QPushButton:hover, QFileDialog QPushButton:hover {{
    border-color: {t.surface2};
    color: {t.text};
    background: {t.accent_hover};
}}
QMessageBox QPushButton:default, QDialog QPushButton:default, QFileDialog QPushButton:default {{
    background: {t.accent};
    border-color: {t.accent};
    color: {t.accent_text};
}}
QMessageBox QPushButton:default:hover, QDialog QPushButton:default:hover, QFileDialog QPushButton:default:hover {{
    background: {t.accent_soft};
    border-color: {t.accent_soft};
}}
QMessageBox QPushButton:focus, QDialog QPushButton:focus, QFileDialog QPushButton:focus {{
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- checkbox */

QCheckBox {{
    color: {t.subtext1};
    font-size: 12px;
    spacing: 10px;
    padding: 2px 0;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid {t.surface2};
    background: {t.crust};
}}
QCheckBox::indicator:hover {{
    border-color: {t.accent};
    background: {t.accent_muted};
}}
QCheckBox::indicator:checked {{
    background: {t.accent};
    border-color: {t.accent};
    {check_img}
}}
QCheckBox::indicator:checked:hover {{
    background: {t.accent_soft};
    border-color: {t.accent_soft};
    {check_img}
}}
QCheckBox::indicator:indeterminate {{
    background: {t.accent};
    border-color: {t.accent};
    {minus_img}
}}
QCheckBox::indicator:indeterminate:hover {{
    background: {t.accent_soft};
    border-color: {t.accent_soft};
    {minus_img}
}}
QCheckBox::indicator:checked:disabled,
QCheckBox::indicator:indeterminate:disabled {{
    background: {t.surface1};
    border-color: {t.surface1};
    {check_img}
}}
QCheckBox::indicator:disabled {{
    background: {t.mantle};
    border-color: {t.surface0};
}}
QCheckBox:disabled {{
    color: {t.overlay1};
}}
QCheckBox:focus {{
    color: {t.text};
}}
QCheckBox::indicator:focus {{
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- radio */

QRadioButton {{
    color: {t.subtext1};
    font-size: 12px;
    spacing: 10px;
    padding: 2px 0;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 9px;
    border: 1px solid {t.surface2};
    background: {t.crust};
}}
QRadioButton::indicator:hover {{
    border-color: {t.accent};
    background: {t.accent_muted};
}}
QRadioButton::indicator:checked {{
    background: {t.crust};
    border: 5px solid {t.accent};
}}
QRadioButton::indicator:checked:hover {{
    border-color: {t.accent_soft};
}}
QRadioButton::indicator:disabled {{
    background: {t.mantle};
    border-color: {t.surface0};
}}
QRadioButton:disabled {{
    color: {t.overlay1};
}}
QRadioButton::indicator:focus {{
    border-color: {t.focus};
}}

/* ------------------------------------------------------------- group */

QGroupBox {{
    color: {t.subtext0};
    border: 1px solid {t.surface0};
    border-radius: 10px;
    margin-top: 16px;
    padding: 12px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.4px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: {t.overlay2};
    text-transform: uppercase;
}}

/* ------------------------------------------------------------- menu */

QMenu {{
    background: {t.mantle};
    color: {t.text};
    border: 1px solid {t.surface1};
    border-radius: 10px;
    padding: 4px;
}}
QMenu::item {{
    padding: 7px 14px 7px 14px;
    border-radius: 6px;
    margin: 1px;
}}
QMenu::item:selected {{
    background: {t.accent_selected};
    color: {t.text};
}}
QMenu::item:disabled {{
    color: {t.overlay1};
}}
QMenu::separator {{
    height: 1px;
    background: {t.surface0};
    margin: 4px 6px;
}}
"""


STYLESHEET = build_stylesheet(DEFAULT_THEME_ID)
