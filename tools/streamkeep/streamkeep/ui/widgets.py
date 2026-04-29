"""Reusable UI widget helpers — pure functions that build styled Qt widgets.

These were previously methods on the StreamKeep class even though none of
them touched `self`. Moving them to module level makes the main window
smaller, easier to test, and lets future tab-widget splits reuse them
without importing the god object.
"""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QTextEdit, QVBoxLayout,
)

from ..theme import CAT


# Platform badge mapping — key → (CAT colour key, display text).
# Resolved via PLATFORM_BADGES property so colours track theme changes.
_BADGE_MAP = {
    "Kick":       ("green",    "Kick"),
    "Twitch":     ("mauve",    "Twitch"),
    "Rumble":     ("green",    "Rumble"),
    "SoundCloud": ("peach",    "SoundCloud"),
    "Reddit":     ("peach",    "Reddit"),
    "Audius":     ("mauve",    "Audius"),
    "Podcast":    ("yellow",   "Podcast"),
    "Direct":     ("blue",     "Direct"),
    "yt-dlp":     ("overlay1", "yt-dlp"),
}


class _BadgeLookup(dict):
    """Dict-like that rebuilds badge colours from the live CAT dict on
    every access, so theme switches are reflected immediately."""

    def __getitem__(self, key):
        cat_key, text = _BADGE_MAP[key]
        return {"color": CAT[cat_key], "text": text}

    def __contains__(self, key):
        return key in _BADGE_MAP

    def get(self, key, default=None):
        if key in _BADGE_MAP:
            return self[key]
        return default


PLATFORM_BADGES = _BadgeLookup()


def TAB_STYLE():
    """Build tab stylesheet from the live CAT dict (theme-safe)."""
    return f"""
QPushButton#tab {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {CAT['panelSoft']},
        stop: 1 {CAT['panel']}
    );
    color: {CAT['subtext1']};
    border: 1px solid {CAT['stroke']};
    padding: 11px 18px;
    font-weight: 600;
    font-size: 13px;
    border-radius: 14px;
}}
QPushButton#tab:hover {{
    color: {CAT['text']};
    border-color: {CAT['accent']};
    background-color: {CAT['panelHi']};
}}
QPushButton#tabActive {{
    background-color: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {CAT['accent']},
        stop: 1 {CAT['sky']}
    );
    color: #081120;
    border: 1px solid rgba(255, 255, 255, 40);
    padding: 11px 18px;
    font-weight: 700;
    font-size: 13px;
    border-radius: 14px;
}}
"""


def path_label(path_text, fallback="Choose folder"):
    """Return the basename of a path for display, or `fallback` if empty."""
    path_text = (path_text or "").strip()
    if not path_text:
        return fallback
    try:
        p = Path(path_text)
        if p.name:
            return p.name
    except Exception:
        pass
    return path_text


def make_metric_card(label_text, value_text="--", sub_text=""):
    """Build a dashboard metric card. Returns (card, value_label, sub_label)."""
    card = QFrame()
    card.setObjectName("metricCard")
    card.setMinimumHeight(102)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(6)

    label = QLabel(label_text)
    label.setObjectName("metricLabel")
    value = QLabel(value_text)
    value.setObjectName("metricValue")
    value.setWordWrap(True)
    sub = QLabel(sub_text)
    sub.setObjectName("metricSubvalue")
    sub.setWordWrap(True)
    sub.setVisible(bool(sub_text))

    lay.addWidget(label)
    lay.addWidget(value)
    lay.addWidget(sub)
    lay.addStretch(1)
    return card, value, sub


def make_field_block(title, hint=""):
    """Build a Settings-style titled container. Returns (card, vbox_layout)."""
    card = QFrame()
    card.setObjectName("subtleCard")
    card.setMinimumHeight(108)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)

    label = QLabel(title)
    label.setObjectName("fieldLabel")
    lay.addWidget(label)

    if hint:
        hint_label = QLabel(hint)
        hint_label.setObjectName("fieldHint")
        hint_label.setWordWrap(True)
        lay.addWidget(hint_label)

    return card, lay


def make_dialog_hero(title, body="", eyebrow="", badge_text=""):
    """Build a premium dialog intro card.

    Returns ``(card, title_label, body_label, badge_label)``.
    """
    card = QFrame()
    card.setObjectName("dialogHero")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(18, 18, 18, 18)
    lay.setSpacing(8)

    top_row = QHBoxLayout()
    top_row.setContentsMargins(0, 0, 0, 0)
    top_row.setSpacing(8)
    eyebrow_label = QLabel(eyebrow or "")
    eyebrow_label.setObjectName("dialogEyebrow")
    eyebrow_label.setVisible(bool(eyebrow))
    top_row.addWidget(eyebrow_label)
    top_row.addStretch(1)
    badge_label = QLabel(badge_text or "")
    badge_label.setObjectName("pillBadge")
    badge_label.setVisible(bool(badge_text))
    top_row.addWidget(badge_label)
    lay.addLayout(top_row)

    title_label = QLabel(title)
    title_label.setObjectName("dialogTitle")
    title_label.setWordWrap(True)
    lay.addWidget(title_label)

    body_label = QLabel(body)
    body_label.setObjectName("dialogBody")
    body_label.setWordWrap(True)
    body_label.setVisible(bool(body))
    lay.addWidget(body_label)

    return card, title_label, body_label, badge_label


def make_dialog_section(title="", body=""):
    """Build a dialog section card. Returns ``(card, content_layout)``."""
    card = QFrame()
    card.setObjectName("dialogSection")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(10)

    if title:
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        lay.addWidget(title_label)
    if body:
        body_label = QLabel(body)
        body_label.setObjectName("sectionBody")
        body_label.setWordWrap(True)
        lay.addWidget(body_label)

    content = QVBoxLayout()
    content.setContentsMargins(0, 0, 0, 0)
    content.setSpacing(10)
    lay.addLayout(content)
    return card, content


def make_status_banner(title="", body="", tone="info"):
    """Build a tone-aware inline status banner.

    Returns ``(card, title_label, body_label)``.
    """
    card = QFrame()
    card.setObjectName("dialogStatus")
    card.setProperty("tone", tone or "info")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(4)

    title_label = QLabel(title)
    title_label.setObjectName("statusTitle")
    title_label.setWordWrap(True)
    body_label = QLabel(body)
    body_label.setObjectName("statusBody")
    body_label.setWordWrap(True)
    body_label.setVisible(bool(body))

    lay.addWidget(title_label)
    lay.addWidget(body_label)
    card.setVisible(bool(title or body))
    return card, title_label, body_label


def update_status_banner(card, title_label, body_label, *, title="", body="", tone="info"):
    """Update a status banner created by ``make_status_banner``."""
    title_label.setText(title)
    body_label.setText(body)
    body_label.setVisible(bool(body))
    card.setProperty("tone", tone or "info")
    style = card.style()
    if style is not None:
        style.unpolish(card)
        style.polish(card)
    card.setVisible(bool(title or body))


def make_empty_state(title, body="", *, compact=False):
    """Build a consistent empty-state card.

    Returns ``(card, title_label, body_label)``.
    """
    card = QFrame()
    card.setObjectName("emptyStateCard")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(18, 18, 18, 18)
    lay.setSpacing(6 if compact else 8)

    title_label = QLabel(title)
    title_label.setObjectName("emptyStateTitle")
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title_label.setWordWrap(True)
    body_label = QLabel(body)
    body_label.setObjectName("emptyStateBody")
    body_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    body_label.setWordWrap(True)

    lay.addStretch(1)
    lay.addWidget(title_label)
    lay.addWidget(body_label)
    lay.addStretch(1)
    return card, title_label, body_label


def _run_premium_dialog(
    parent,
    *,
    title,
    body="",
    eyebrow="",
    badge_text="",
    tone="info",
    summary_title="",
    summary_body="",
    details_title="Details",
    details_body="",
    primary_label="OK",
    secondary_label="",
    default_action="primary",
    min_width=560,
    min_height=0,
    details_monospaced=False,
):
    """Run a premium confirmation/info dialog and return the chosen action."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumWidth(max(420, int(min_width or 420)))
    if min_height:
        dlg.setMinimumHeight(int(min_height))

    root = QVBoxLayout(dlg)
    root.setContentsMargins(18, 18, 18, 18)
    root.setSpacing(12)

    hero, _, _, _ = make_dialog_hero(
        title,
        body,
        eyebrow=eyebrow,
        badge_text=badge_text,
    )
    root.addWidget(hero)

    if summary_title or summary_body:
        banner, banner_title, banner_body = make_status_banner()
        update_status_banner(
            banner,
            banner_title,
            banner_body,
            title=summary_title,
            body=summary_body,
            tone=tone,
        )
        root.addWidget(banner)

    if details_body:
        section, content = make_dialog_section(details_title)
        details_view = QTextEdit()
        if details_monospaced:
            details_view.setObjectName("log")
        details_view.setReadOnly(True)
        details_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        details_view.setPlainText(str(details_body))
        details_view.setMinimumHeight(120)
        content.addWidget(details_view)
        root.addWidget(section, 1)

    choice = {"value": "secondary" if secondary_label else "primary"}

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)

    secondary_btn = None
    if secondary_label:
        secondary_btn = QPushButton(secondary_label)
        secondary_btn.setObjectName("secondary")
        secondary_btn.clicked.connect(lambda: (choice.__setitem__("value", "secondary"), dlg.reject()))
        btn_row.addWidget(secondary_btn)

    primary_btn = QPushButton(primary_label)
    primary_btn.setObjectName("primary")
    primary_btn.clicked.connect(lambda: (choice.__setitem__("value", "primary"), dlg.accept()))
    btn_row.addWidget(primary_btn)
    root.addLayout(btn_row)

    if default_action == "secondary" and secondary_btn is not None:
        secondary_btn.setDefault(True)
        secondary_btn.setAutoDefault(True)
    else:
        primary_btn.setDefault(True)
        primary_btn.setAutoDefault(True)

    dlg.exec()
    return choice["value"]


def ask_premium_confirmation(parent, **kwargs):
    """Show a premium confirmation dialog and return ``True`` on confirm."""
    return _run_premium_dialog(parent, **kwargs) == "primary"


def show_premium_message(parent, **kwargs):
    """Show a premium informational dialog."""
    _run_premium_dialog(parent, **kwargs)


def ask_premium_text_input(
    parent,
    *,
    title,
    body="",
    eyebrow="",
    badge_text="",
    tone="info",
    summary_title="",
    summary_body="",
    field_label="Value",
    field_hint="",
    placeholder="",
    text="",
    primary_label="Save",
    secondary_label="Cancel",
    default_action="primary",
    min_width=560,
    min_height=0,
    validator=None,
    strip_result=True,
):
    """Show a premium text-input dialog and return ``(text, accepted)``."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    dlg.setMinimumWidth(max(420, int(min_width or 420)))
    if min_height:
        dlg.setMinimumHeight(int(min_height))

    root = QVBoxLayout(dlg)
    root.setContentsMargins(18, 18, 18, 18)
    root.setSpacing(12)

    hero, _, _, _ = make_dialog_hero(
        title,
        body,
        eyebrow=eyebrow,
        badge_text=badge_text,
    )
    root.addWidget(hero)

    if summary_title or summary_body:
        banner, banner_title, banner_body = make_status_banner()
        update_status_banner(
            banner,
            banner_title,
            banner_body,
            title=summary_title,
            body=summary_body,
            tone=tone,
        )
        root.addWidget(banner)

    section, content = make_dialog_section(field_label, field_hint)
    input_edit = QLineEdit(str(text or ""))
    input_edit.setClearButtonEnabled(True)
    input_edit.setPlaceholderText(placeholder or "")
    content.addWidget(input_edit)

    error_banner, error_title, error_body = make_status_banner()
    error_banner.setVisible(False)
    content.addWidget(error_banner)
    root.addWidget(section)

    result = {"accepted": False, "value": str(text or "")}

    def _hide_error():
        if error_banner.isVisible():
            update_status_banner(error_banner, error_title, error_body, title="", body="", tone="error")

    def _validate(value):
        if validator is None:
            return True, ""
        try:
            outcome = validator(value)
        except Exception:
            return False, "Validate the entry and try again."
        if isinstance(outcome, tuple):
            ok = bool(outcome[0])
            msg = str(outcome[1] or "") if len(outcome) > 1 else ""
            return ok, msg
        return bool(outcome), ""

    def _accept():
        value = input_edit.text()
        if strip_result:
            value = value.strip()
        ok, msg = _validate(value)
        if not ok:
            update_status_banner(
                error_banner,
                error_title,
                error_body,
                title="Check the value and try again",
                body=msg or "Enter a valid value before continuing.",
                tone="error",
            )
            input_edit.setFocus()
            input_edit.selectAll()
            return
        result["accepted"] = True
        result["value"] = value
        dlg.accept()

    def _reject():
        dlg.reject()

    input_edit.textChanged.connect(lambda _text: _hide_error())

    btn_row = QHBoxLayout()
    btn_row.addStretch(1)

    secondary_btn = QPushButton(secondary_label)
    secondary_btn.setObjectName("secondary")
    secondary_btn.clicked.connect(_reject)
    btn_row.addWidget(secondary_btn)

    primary_btn = QPushButton(primary_label)
    primary_btn.setObjectName("primary")
    primary_btn.clicked.connect(_accept)
    btn_row.addWidget(primary_btn)
    root.addLayout(btn_row)

    input_edit.returnPressed.connect(_accept)
    input_edit.setFocus()
    input_edit.selectAll()

    if default_action == "secondary":
        secondary_btn.setDefault(True)
        secondary_btn.setAutoDefault(True)
    else:
        primary_btn.setDefault(True)
        primary_btn.setAutoDefault(True)

    dlg.exec()
    return result["value"], result["accepted"]


def wrap_scroll_page(page):
    """Wrap a page widget in a QScrollArea with styled chrome."""
    page.setObjectName("chrome")
    page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    scroll = QScrollArea()
    scroll.setObjectName("chrome")
    scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.viewport().setObjectName("chrome")
    scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    scroll.setWidget(page)
    return scroll


def style_table(table, row_height=46):
    """Apply the premium midnight theme to a QTableWidget."""
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.verticalHeader().setDefaultSectionSize(row_height)
    table.horizontalHeader().setHighlightSections(False)


def set_metric(value_label, sub_label, value, sub=""):
    """Update a metric card's value and subtitle."""
    value_label.setText(value)
    sub_label.setText(sub)
    sub_label.setVisible(bool(sub))
