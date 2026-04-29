"""History tab — completed downloads table + stats dashboard."""

from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QTableWidget, QVBoxLayout, QWidget,
)

from ..widgets import make_metric_card, style_table


def build_history_tab(win):
    """Build the History tab page. Stashes widget refs on `win.*`."""
    page = QWidget()
    lay = QVBoxLayout(page)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(14)

    hero = QFrame()
    hero.setObjectName("heroCard")
    hero_lay = QVBoxLayout(hero)
    hero_lay.setContentsMargins(18, 18, 18, 18)
    hero_lay.setSpacing(14)

    hero_copy = QVBoxLayout()
    hero_copy.setSpacing(4)
    kicker = QLabel("History")
    kicker.setObjectName("eyebrow")
    title = QLabel("Keep a clean record of what you captured")
    title.setObjectName("heroTitle")
    title.setWordWrap(True)
    body = QLabel(
        "Completed downloads are listed here so you can quickly revisit "
        "folders, compare qualities, and confirm recent jobs."
    )
    body.setObjectName("heroBody")
    body.setWordWrap(True)
    hero_copy.addWidget(kicker)
    hero_copy.addWidget(title)
    hero_copy.addWidget(body)
    hero_lay.addLayout(hero_copy)

    history_metrics = QHBoxLayout()
    history_metrics.setSpacing(12)
    count_card, win.history_count_value, win.history_count_sub = make_metric_card(
        "Downloads", "0", "saved downloads"
    )
    latest_card, win.history_latest_value, win.history_latest_sub = make_metric_card(
        "Latest", "No entries", "Completed downloads appear here"
    )
    platform_card, win.history_platform_value, win.history_platform_sub = make_metric_card(
        "Top Platform", "—", "appears most in history"
    )
    channel_card, win.history_channel_value, win.history_channel_sub = make_metric_card(
        "Top Channel", "—", "most downloaded"
    )
    history_metrics.addWidget(count_card)
    history_metrics.addWidget(latest_card, 1)
    history_metrics.addWidget(platform_card)
    history_metrics.addWidget(channel_card, 1)
    hero_lay.addLayout(history_metrics)
    lay.addWidget(hero)

    card = QFrame()
    card.setObjectName("card")
    card_lay = QVBoxLayout(card)
    card_lay.setContentsMargins(18, 18, 18, 18)
    card_lay.setSpacing(10)

    header = QHBoxLayout()
    header_copy = QVBoxLayout()
    header_copy.setSpacing(4)
    sec = QLabel("Download History")
    sec.setObjectName("sectionTitle")
    win.history_summary_label = QLabel(
        "Download history builds automatically after each completed job."
    )
    win.history_summary_label.setObjectName("sectionBody")
    win.history_summary_label.setWordWrap(True)
    header_copy.addWidget(sec)
    header_copy.addWidget(win.history_summary_label)
    header.addLayout(header_copy, 1)
    clear_btn = QPushButton("Clear History")
    clear_btn.setObjectName("secondary")
    clear_btn.clicked.connect(win._on_clear_history)
    header.addWidget(clear_btn)
    card_lay.addLayout(header)

    search_card = QFrame()
    search_card.setObjectName("toolbar")
    search_wrap = QVBoxLayout(search_card)
    search_wrap.setContentsMargins(14, 14, 14, 14)
    search_wrap.setSpacing(10)

    search_head = QHBoxLayout()
    search_head.setSpacing(12)
    search_copy = QVBoxLayout()
    search_copy.setSpacing(4)
    search_title = QLabel("Find a Download")
    search_title.setObjectName("fieldLabel")
    search_hint = QLabel(
        "Search metadata instantly or switch to transcript text when you need quoted moments."
    )
    search_hint.setObjectName("subtleText")
    search_hint.setWordWrap(True)
    search_copy.addWidget(search_title)
    search_copy.addWidget(search_hint)
    search_head.addLayout(search_copy, 1)
    win.history_filter_summary = QLabel("Showing all downloads")
    win.history_filter_summary.setObjectName("subtleText")
    search_head.addWidget(win.history_filter_summary)
    search_wrap.addLayout(search_head)

    search_row = QHBoxLayout()
    search_row.setSpacing(8)
    win.history_search = QLineEdit()
    win.history_search.setPlaceholderText("Search title, platform, channel, path, or URL…")
    win.history_search.setClearButtonEnabled(True)
    win.history_search.textChanged.connect(win._on_history_search)
    search_row.addWidget(win.history_search, 1)
    win.transcript_search_check = QCheckBox("Search Transcript Text")
    win.transcript_search_check.setToolTip(
        "When checked, queries search indexed transcript text (SRT/VTT) instead of metadata."
    )
    win.transcript_search_check.toggled.connect(lambda _: win._on_history_search(""))
    search_row.addWidget(win.transcript_search_check)
    search_wrap.addLayout(search_row)
    card_lay.addWidget(search_card)

    win.history_table = QTableWidget()
    win.history_table.setColumnCount(7)
    win.history_table.setHorizontalHeaderLabels(
        ["", "Date", "Platform", "Title", "Quality", "Size", "Path"]
    )
    hh = win.history_table.horizontalHeader()
    hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
    hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
    hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
    hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
    hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
    hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
    win.history_table.setColumnWidth(0, 112)
    win.history_table.setColumnWidth(1, 150)
    win.history_table.setColumnWidth(2, 84)
    win.history_table.setColumnWidth(4, 110)
    win.history_table.setColumnWidth(5, 88)
    win.history_table.verticalHeader().setVisible(False)
    win.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    win.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    win.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    win.history_table.doubleClicked.connect(win._on_history_double_click)
    # Enable hover preview (F46)
    win.history_table.setMouseTracking(True)
    win.history_table.cellEntered.connect(win._on_history_cell_hover)
    style_table(win.history_table, 72)
    card_lay.addWidget(win.history_table)

    lay.addWidget(card, 1)
    win._refresh_history_summary()
    return page
