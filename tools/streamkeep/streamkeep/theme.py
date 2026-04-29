"""Theme system — Catppuccin Mocha (dark) + Latte (light) + System toggle.

Palettes are dicts with the same keys. ``build_stylesheet(palette)``
interpolates any palette into the QSS template. ``CAT`` always points
to the active palette; ``STYLESHEET`` is the active QSS string.

Consumer code that reads ``CAT["blue"]`` etc. continues to work — the
dict is mutated in-place when the theme changes via ``apply_theme()``.
"""

CAT_MOCHA = {
    "base": "#1e1e2e", "mantle": "#181825", "crust": "#11111b",
    "surface0": "#313244", "surface1": "#45475a", "surface2": "#585b70",
    "overlay0": "#6c7086", "overlay1": "#7f849c",
    "text": "#cdd6f4", "subtext0": "#a6adc8", "subtext1": "#bac2de",
    "lavender": "#b4befe", "blue": "#89b4fa", "sapphire": "#74c7ec",
    "sky": "#89dceb", "teal": "#94e2d5", "green": "#a6e3a1",
    "yellow": "#f9e2af", "peach": "#fab387", "maroon": "#eba0ac",
    "red": "#f38ba8", "mauve": "#cba6f7", "pink": "#f5c2e7",
    "flamingo": "#f2cdcd", "rosewater": "#f5e0dc",
    "panel": "#131b2f", "panelHi": "#1a2440", "panelSoft": "#10192b",
    "stroke": "#2b3652", "muted": "#8f9ab8", "accent": "#7dd3fc",
    "accentSoft": "#6ee7b7", "gold": "#f8d38a",
}

CAT_LATTE = {
    "base": "#eff1f5", "mantle": "#e6e9ef", "crust": "#dce0e8",
    "surface0": "#ccd0da", "surface1": "#bcc0cc", "surface2": "#acb0be",
    "overlay0": "#9ca0b0", "overlay1": "#8c8fa1",
    "text": "#4c4f69", "subtext0": "#6c6f85", "subtext1": "#5c5f77",
    "lavender": "#7287fd", "blue": "#1e66f5", "sapphire": "#209fb5",
    "sky": "#04a5e5", "teal": "#179299", "green": "#40a02b",
    "yellow": "#df8e1d", "peach": "#fe640b", "maroon": "#e64553",
    "red": "#d20f39", "mauve": "#8839ef", "pink": "#ea76cb",
    "flamingo": "#dd7878", "rosewater": "#dc8a78",
    "panel": "#e6e9ef", "panelHi": "#dce0e8", "panelSoft": "#eff1f5",
    "stroke": "#bcc0cc", "muted": "#6c6f85", "accent": "#1e66f5",
    "accentSoft": "#40a02b", "gold": "#df8e1d",
}

# CAT is the "live" palette — mutated in-place so all ``CAT["x"]`` refs
# across the app pick up theme changes without reimporting.
CAT = dict(CAT_MOCHA)

CAT_HIGH_CONTRAST = {
    "base": "#000000", "mantle": "#0a0a0a", "crust": "#000000",
    "surface0": "#1a1a1a", "surface1": "#2a2a2a", "surface2": "#3a3a3a",
    "overlay0": "#555555", "overlay1": "#666666",
    "text": "#ffffff", "subtext0": "#cccccc", "subtext1": "#dddddd",
    "lavender": "#8888ff", "blue": "#6699ff", "sapphire": "#55bbff",
    "sky": "#55ddff", "teal": "#55eedd", "green": "#55ff55",
    "yellow": "#ffff55", "peach": "#ffaa55", "maroon": "#ff8888",
    "red": "#ff4444", "mauve": "#bb77ff", "pink": "#ff88cc",
    "flamingo": "#ff9999", "rosewater": "#ffbbbb",
    "panel": "#0a0a0a", "panelHi": "#151515", "panelSoft": "#050505",
    "stroke": "#444444", "muted": "#999999", "accent": "#6699ff",
    "accentSoft": "#55ff55", "gold": "#ffff55",
}

THEMES = {"dark": CAT_MOCHA, "light": CAT_LATTE, "high_contrast": CAT_HIGH_CONTRAST}

# Layout density presets (F75)
DENSITY_COMPACT = {"font_size": 11, "row_height": 48, "padding": 4, "thumb_w": 80, "name": "compact"}
DENSITY_COZY = {"font_size": 13, "row_height": 72, "padding": 8, "thumb_w": 112, "name": "cozy"}
DENSITY_SPACIOUS = {"font_size": 16, "row_height": 96, "padding": 12, "thumb_w": 160, "name": "spacious"}
DENSITIES = {"compact": DENSITY_COMPACT, "cozy": DENSITY_COZY, "spacious": DENSITY_SPACIOUS}
_active_density = dict(DENSITY_COZY)


def get_density():
    """Return the active density preset dict."""
    return dict(_active_density)


def set_density(name):
    """Set the active layout density. Returns the density dict."""
    global _active_density
    _active_density = dict(DENSITIES.get(name, DENSITY_COZY))
    return _active_density


def _detect_system_theme():
    """Return 'dark' or 'light' based on OS preference."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "light" if val == 1 else "dark"
    except Exception:
        return "dark"

def build_stylesheet(p=None):
    """Build the full QSS string from a palette dict."""
    if p is None:
        p = CAT
    return f"""
QMainWindow {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {p['crust']},
        stop: 0.55 {p['mantle']},
        stop: 1 {p['base']}
    );
}}
QDialog {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {p['crust']},
        stop: 0.45 {p['mantle']},
        stop: 1 {p['base']}
    );
}}
QWidget {{
    color: {p['text']};
    font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif;
    font-size: 13px;
}}
QWidget#chrome {{
    background-color: transparent;
}}
QAbstractScrollArea#chrome,
QAbstractScrollArea#chrome > QWidget#chrome {{
    background-color: transparent;
    border: none;
}}
QFrame#shellCard {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {p['panelHi']},
        stop: 0.5 {p['panel']},
        stop: 1 {p['panelSoft']}
    );
    border: 1px solid {p['stroke']};
    border-radius: 26px;
}}
QFrame#shellMetaCard {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(137, 180, 250, 34),
        stop: 0.55 rgba(116, 199, 236, 22),
        stop: 1 rgba(166, 227, 161, 12)
    );
    border: 1px solid {p['stroke']};
    border-radius: 20px;
}}
QFrame#heroCard {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(137, 180, 250, 18),
        stop: 0.22 {p['panelHi']},
        stop: 0.62 {p['panel']},
        stop: 1 {p['panelSoft']}
    );
    border: 1px solid {p['stroke']};
    border-radius: 24px;
}}
QFrame#card, QFrame#panel, QFrame#footerBar {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {p['mantle']},
        stop: 1 {p['panelSoft']}
    );
    border: 1px solid {p['stroke']};
    border-radius: 20px;
}}
QFrame#activeRecordings {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(166, 227, 161, 35),
        stop: 1 rgba(137, 180, 250, 25)
    );
    border: 1px solid {p['green']};
    border-radius: 14px;
}}
QFrame#updateBanner {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(203, 166, 247, 50),
        stop: 1 rgba(137, 180, 250, 35)
    );
    border: 1px solid {p['mauve']};
    border-radius: 14px;
}}
QLabel#updateBannerLabel {{
    color: {p['text']};
    font-weight: 600;
}}
QFrame#resumeBanner {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 rgba(250, 179, 135, 45),
        stop: 1 rgba(137, 180, 250, 45)
    );
    border: 1px solid {p['peach']};
    border-radius: 14px;
}}
QLabel#resumeBannerLabel {{
    color: {p['text']};
    font-weight: 600;
}}
QFrame#subtleCard, QFrame#metricCard, QFrame#toolbar {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {p['panelSoft']},
        stop: 1 {p['panel']}
    );
    border: 1px solid {p['stroke']};
    border-radius: 18px;
}}
QFrame#dialogHero {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 rgba(137, 180, 250, 24),
        stop: 0.28 {p['panelHi']},
        stop: 0.72 {p['panel']},
        stop: 1 {p['panelSoft']}
    );
    border: 1px solid {p['stroke']};
    border-radius: 22px;
}}
QFrame#dialogSection {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {p['panelSoft']},
        stop: 1 {p['panel']}
    );
    border: 1px solid {p['stroke']};
    border-radius: 18px;
}}
QFrame#dialogStatus {{
    background-color: {p['panelSoft']};
    border: 1px solid {p['stroke']};
    border-radius: 16px;
}}
QFrame#dialogStatus[tone="info"] {{
    border-color: {p['accent']};
}}
QFrame#dialogStatus[tone="success"] {{
    border-color: {p['green']};
}}
QFrame#dialogStatus[tone="warning"] {{
    border-color: {p['yellow']};
}}
QFrame#dialogStatus[tone="error"] {{
    border-color: {p['red']};
}}
QFrame#emptyStateCard {{
    background-color: {p['panelSoft']};
    border: 1px dashed {p['stroke']};
    border-radius: 18px;
}}
QFrame#playerMetaBar, QFrame#playerSidebar, QFrame#playerTransportBar,
QFrame#playerSlotCard, QFrame#playerPipShell, QFrame#playerPipTitleBar {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {p['panelSoft']},
        stop: 1 {p['panel']}
    );
    border: 1px solid {p['stroke']};
    border-radius: 18px;
}}
QFrame#playerVideoCanvas {{
    background-color: {p['crust']};
    border: 1px solid {p['surface1']};
    border-radius: 22px;
}}
QLabel {{
    color: {p['text']};
    border: none;
}}
QLabel#dialogEyebrow {{
    color: {p['accent']};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}
QLabel#dialogTitle {{
    font-size: 24px;
    font-weight: 700;
    color: {p['rosewater']};
}}
QLabel#dialogBody {{
    color: {p['subtext1']};
    font-size: 13px;
    line-height: 1.35;
}}
QLabel#title {{
    font-size: 30px;
    font-weight: 700;
    color: {p['rosewater']};
}}
QLabel#subtitle {{
    font-size: 12px;
    color: {p['muted']};
}}
QLabel#shellStatValue {{
    font-size: 17px;
    font-weight: 700;
    color: {p['rosewater']};
}}
QLabel#shellStatBody {{
    font-size: 12px;
    color: {p['subtext1']};
}}
QLabel#shellStatMeta {{
    font-size: 11px;
    color: {p['muted']};
}}
QLabel#eyebrow {{
    color: {p['accent']};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#heroTitle {{
    font-size: 24px;
    font-weight: 700;
    color: {p['rosewater']};
}}
QLabel#heroBody {{
    font-size: 13px;
    color: {p['subtext1']};
}}
QLabel#sectionTitle {{
    font-size: 16px;
    font-weight: 700;
    color: {p['rosewater']};
}}
QLabel#sectionBody, QLabel#tableHint, QLabel#fieldHint, QLabel#subtleText {{
    color: {p['muted']};
    font-size: 12px;
}}
QLabel#fieldLabel {{
    color: {p['subtext1']};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#metricLabel {{
    color: {p['muted']};
    font-size: 11px;
    font-weight: 700;
}}
QLabel#metricValue {{
    color: {p['rosewater']};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#metricSubvalue {{
    color: {p['subtext1']};
    font-size: 12px;
}}
QLabel#statusLabel {{
    color: {p['subtext1']};
    font-size: 12px;
}}
QLabel#statusTitle {{
    color: {p['text']};
    font-size: 13px;
    font-weight: 700;
}}
QLabel#statusBody {{
    color: {p['subtext1']};
    font-size: 12px;
}}
QLabel#emptyStateTitle {{
    color: {p['rosewater']};
    font-size: 16px;
    font-weight: 700;
}}
QLabel#emptyStateBody {{
    color: {p['muted']};
    font-size: 12px;
}}
QLabel#playerKicker {{
    color: {p['accent']};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
}}
QLabel#playerTitle {{
    color: {p['rosewater']};
    font-size: 18px;
    font-weight: 700;
}}
QLabel#playerMeta {{
    color: {p['subtext1']};
    font-size: 12px;
}}
QLabel#playerHint, QLabel#playerTinyLabel {{
    color: {p['muted']};
    font-size: 11px;
}}
QLabel#playerSectionTitle {{
    color: {p['text']};
    font-size: 13px;
    font-weight: 700;
}}
QLabel#playerMiniTitle {{
    color: {p['text']};
    font-size: 12px;
    font-weight: 700;
}}
QLabel#playerMiniMeta {{
    color: {p['muted']};
    font-size: 10px;
}}
QLabel#playerBadgeMuted {{
    color: {p['subtext1']};
    background-color: rgba(203, 166, 247, 18);
    border: 1px solid {p['stroke']};
    border-radius: 999px;
    padding: 3px 9px;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#pillBadge {{
    color: {p['accent']};
    background-color: rgba(137, 180, 250, 18);
    border: 1px solid {p['stroke']};
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel#streamInfo {{
    font-size: 12px;
    color: {p['subtext1']};
    padding: 10px 12px;
    background-color: rgba(137, 180, 250, 16);
    border: 1px solid {p['stroke']};
    border-radius: 12px;
}}
QLineEdit, QComboBox, QSpinBox, QTimeEdit, QDateEdit {{
    background-color: {p['surface0']};
    color: {p['text']};
    border: 1px solid {p['stroke']};
    border-radius: 14px;
    padding: 11px 12px;
    font-size: 13px;
    selection-background-color: {p['accent']};
    selection-color: #081120;
}}
QLineEdit#shellSearch, QLineEdit#globalSearch {{
    background-color: {p['base']};
    border-radius: 15px;
    padding: 12px 14px;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QTimeEdit:hover, QDateEdit:hover {{
    border-color: {p['accent']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus, QDateEdit:focus {{
    border: 1px solid {p['accent']};
    background-color: {p['base']};
}}
QPushButton {{
    background-color: {p['surface0']};
    color: {p['text']};
    border: 1px solid {p['stroke']};
    border-radius: 14px;
    padding: 10px 16px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: {p['surface1']};
    border-color: {p['accent']};
}}
QPushButton:pressed {{
    background-color: {p['surface2']};
}}
QPushButton:focus {{
    border-color: {p['accent']};
}}
QPushButton:disabled {{
    background-color: {p['surface0']};
    color: {p['overlay0']};
    border-color: {p['surface0']};
}}
QPushButton#primary {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {p['accent']},
        stop: 1 {p['sky']}
    );
    color: #081120;
    border: 1px solid rgba(255, 255, 255, 35);
    padding: 11px 22px;
    font-size: 14px;
}}
QPushButton#primary:hover {{
    background-color: {p['sky']};
}}
QPushButton#primary:disabled {{
    background-color: {p['surface1']};
    color: {p['overlay0']};
}}
QPushButton#secondary {{
    background-color: {p['panel']};
    color: {p['text']};
}}
QPushButton#ghost {{
    background-color: transparent;
    color: {p['subtext1']};
    border: 1px solid transparent;
}}
QPushButton#ghost:hover {{
    background-color: {p['panel']};
    border-color: {p['stroke']};
}}
QPushButton#toggleAccent {{
    background-color: {p['panel']};
}}
QPushButton#toggleAccent:checked {{
    background-color: {p['accent']};
    color: #081120;
    border-color: {p['accent']};
}}
QPushButton#danger {{
    background-color: {p['red']};
    color: #081120;
    border: 1px solid rgba(255, 255, 255, 24);
}}
QPushButton#danger:hover {{
    background-color: {p['maroon']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {p['surface0']};
    color: {p['text']};
    selection-background-color: {p['panelHi']};
    border: 1px solid {p['stroke']};
    border-radius: 10px;
}}
QTableWidget {{
    background-color: {p['panel']};
    color: {p['text']};
    alternate-background-color: {p['panelSoft']};
    border: 1px solid {p['stroke']};
    border-radius: 18px;
    gridline-color: transparent;
    selection-background-color: {p['panelHi']};
    selection-color: {p['text']};
    font-size: 13px;
    padding: 4px;
}}
QTableWidget::item {{
    padding: 10px 12px;
    border-bottom: 1px solid {p['stroke']};
}}
QTableWidget::item:selected {{
    background-color: {p['panelHi']};
}}
QHeaderView::section {{
    background-color: {p['panelSoft']};
    color: {p['muted']};
    border: none;
    border-bottom: 1px solid {p['stroke']};
    padding: 12px;
    font-weight: 700;
    font-size: 12px;
}}
QTextEdit, QPlainTextEdit {{
    background-color: {p['panel']};
    color: {p['text']};
    border: 1px solid {p['stroke']};
    border-radius: 16px;
    padding: 10px;
    selection-background-color: {p['panelHi']};
    selection-color: {p['text']};
}}
QTextEdit#log {{
    background-color: {p['crust']};
    color: {p['subtext0']};
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 11px;
}}
QListWidget, QListWidget#globalResults {{
    background-color: {p['mantle']};
    border: 1px solid {p['stroke']};
    border-radius: 18px;
    padding: 6px;
    outline: none;
}}
QListWidget::item {{
    padding: 10px 12px;
    border-radius: 12px;
}}
QListWidget::item:hover {{
    background-color: {p['panel']};
}}
QListWidget::item:selected {{
    background-color: {p['panelHi']};
    color: {p['text']};
}}
QListWidget#playerChapterList {{
    background-color: {p['mantle']};
    border: 1px solid {p['stroke']};
    border-radius: 16px;
    padding: 8px;
}}
QListWidget#playerChapterList::item {{
    padding: 8px 10px;
    border-radius: 10px;
}}
QListWidget#playerChapterList::item:hover {{
    background-color: {p['panel']};
}}
QListWidget#playerChapterList::item:selected {{
    background-color: {p['panelHi']};
}}
QMenu {{
    background-color: {p['mantle']};
    border: 1px solid {p['stroke']};
    border-radius: 14px;
    padding: 8px;
}}
QMenu::item {{
    padding: 8px 12px;
    border-radius: 10px;
}}
QMenu::item:selected {{
    background-color: {p['panelHi']};
    color: {p['text']};
}}
QToolTip {{
    background-color: {p['panel']};
    color: {p['text']};
    border: 1px solid {p['stroke']};
    padding: 6px 8px;
    border-radius: 8px;
}}
QProgressBar {{
    background-color: {p['panelSoft']};
    border: 1px solid {p['stroke']};
    border-radius: 999px;
    height: 12px;
    text-align: center;
    color: transparent;
    padding: 1px;
}}
QProgressBar::chunk {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 {p['accent']},
        stop: 1 {p['green']}
    );
    border-radius: 999px;
}}
QCheckBox {{
    color: {p['text']};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {p['stroke']};
    background-color: {p['surface0']};
}}
QCheckBox::indicator:checked {{
    background-color: {p['accentSoft']};
    border-color: {p['accentSoft']};
}}
QRadioButton {{
    color: {p['text']};
    spacing: 8px;
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 1px solid {p['stroke']};
    background-color: {p['surface0']};
}}
QRadioButton::indicator:checked {{
    background-color: {p['accent']};
    border-color: {p['accent']};
}}
QScrollBar:vertical {{
    background-color: transparent;
    width: 10px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background-color: {p['surface2']};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {p['overlay0']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background-color: transparent;
    height: 10px;
    margin: 4px;
}}
QScrollBar::handle:horizontal {{
    background-color: {p['surface2']};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {p['overlay0']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QSplitter::handle {{
    background-color: {p['stroke']};
    height: 1px;
    margin: 6px 0;
}}
"""


ACCENT_PRESETS = {
    "Mauve": "#cba6f7", "Blue": "#89b4fa", "Green": "#a6e3a1",
    "Peach": "#fab387", "Pink": "#f5c2e7", "Red": "#f38ba8",
    "Teal": "#94e2d5", "Yellow": "#f9e2af",
}


def apply_accent(hex_color, app=None):
    """Override the accent color and rebuild the stylesheet (F73).

    Patches CAT["accent"], CAT["blue"], and CAT["lavender"] with the
    chosen color so all accent-dependent QSS picks it up.
    """
    global STYLESHEET
    if hex_color:
        CAT["accent"] = hex_color
        CAT["blue"] = hex_color
        CAT["lavender"] = hex_color
    STYLESHEET = build_stylesheet(CAT)
    if app is not None:
        app.setStyleSheet(STYLESHEET)
    return STYLESHEET


def apply_theme(name, app=None):
    """Switch the active theme. Updates CAT in-place and rebuilds STYLESHEET.

    *name*: 'dark', 'light', or 'system'.
    *app*: optional QApplication — if provided, calls ``app.setStyleSheet()``
           for an instant theme switch without restart.
    """
    global STYLESHEET
    if name == "system":
        name = _detect_system_theme()
    palette = THEMES.get(name, CAT_MOCHA)
    CAT.clear()
    CAT.update(palette)
    STYLESHEET = build_stylesheet(CAT)
    if app is not None:
        app.setStyleSheet(STYLESHEET)
    return STYLESHEET


# Build initial stylesheet from default (Mocha) palette
STYLESHEET = build_stylesheet(CAT)
