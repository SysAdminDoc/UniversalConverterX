"""Chapter & Bookmark Navigation Panel — sidebar for the player (F55).

Lists chapters (from metadata.json, .chapters.auto.txt, embedded MP4
chapters) and user bookmarks (from HistoryEntry.bookmarks). Click to
seek. "Add bookmark" captures the current position.
"""

import json
import os

from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal

from ..ui.widgets import ask_premium_text_input


def _fmt_time(secs):
    s = max(0, int(secs or 0))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class ChapterPanel(QWidget):
    """Collapsible sidebar listing chapters + bookmarks with seek-on-click."""

    seek_requested = pyqtSignal(float)          # seconds
    bookmark_added = pyqtSignal(str, float)      # name, seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)

        self._entries = []   # list of (label, secs, kind)  kind = "chapter" | "bookmark"
        self._current_pos = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        shell = QFrame()
        shell.setObjectName("playerSidebar")
        shell_lay = QVBoxLayout(shell)
        shell_lay.setContentsMargins(14, 14, 14, 14)
        shell_lay.setSpacing(10)
        layout.addWidget(shell)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        kicker = QLabel("PLAYER")
        kicker.setObjectName("playerKicker")
        title_col.addWidget(kicker)
        header = QLabel("Chapters & Bookmarks")
        header.setObjectName("playerSectionTitle")
        title_col.addWidget(header)
        self._summary_label = QLabel("Jump to sections or save your own markers.")
        self._summary_label.setObjectName("playerHint")
        self._summary_label.setWordWrap(True)
        title_col.addWidget(self._summary_label)
        header_row.addLayout(title_col, 1)
        self._count_badge = QLabel("0 saved")
        self._count_badge.setObjectName("playerBadgeMuted")
        header_row.addWidget(self._count_badge, 0, Qt.AlignmentFlag.AlignTop)
        shell_lay.addLayout(header_row)

        self._list = QListWidget()
        self._list.setObjectName("playerChapterList")
        self._list.itemClicked.connect(self._on_item_click)
        shell_lay.addWidget(self._list, 1)

        # Add bookmark button
        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ Bookmark")
        add_btn.setObjectName("secondary")
        add_btn.clicked.connect(self._on_add_bookmark)
        btn_row.addWidget(add_btn)
        btn_row.addStretch(1)
        shell_lay.addLayout(btn_row)

        footer = QLabel(
            "Tip: click any entry to seek instantly, or save a bookmark at the current playback time."
        )
        footer.setObjectName("playerTinyLabel")
        footer.setWordWrap(True)
        shell_lay.addWidget(footer)

    def load_chapters(self, recording_dir, mpv_chapters=None, bookmarks=None):
        """Load chapters from all sources and populate the list.

        *mpv_chapters* is a list of (title, secs) from MpvWidget.chapter_list.
        *bookmarks* is the HistoryEntry.bookmarks list [{name, secs}].
        """
        self._entries.clear()
        self._list.clear()

        # 1. Embedded MP4 chapters (from mpv)
        if mpv_chapters:
            for title, secs in mpv_chapters:
                self._entries.append((title, float(secs), "chapter"))

        # 2. metadata.json chapters
        if recording_dir:
            meta_path = os.path.join(recording_dir, "metadata.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    for ch in meta.get("chapters", []):
                        title = ch.get("title", "Chapter")
                        start = float(ch.get("start", 0))
                        # Deduplicate against embedded chapters (within 5s)
                        if not any(abs(s - start) < 5 for _, s, _ in self._entries):
                            self._entries.append((title, start, "chapter"))
                except (OSError, json.JSONDecodeError, ValueError):
                    pass

            # 3. .chapters.auto.txt (Whisper-generated)
            auto_path = os.path.join(recording_dir, ".chapters.auto.txt")
            if os.path.isfile(auto_path):
                try:
                    with open(auto_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            parts = line.split(None, 1)
                            if len(parts) >= 2:
                                try:
                                    secs = _parse_ts(parts[0])
                                    title = parts[1]
                                    if not any(abs(s - secs) < 5 for _, s, _ in self._entries):
                                        self._entries.append((title, secs, "chapter"))
                                except ValueError:
                                    pass
                except OSError:
                    pass

        # 4. User bookmarks
        if bookmarks:
            for bm in bookmarks:
                name = bm.get("name", "Bookmark") if isinstance(bm, dict) else str(bm)
                secs = float(bm.get("secs", 0) if isinstance(bm, dict) else 0)
                self._entries.append((name, secs, "bookmark"))

        # Sort by time
        self._entries.sort(key=lambda e: e[1])

        # Populate list
        for label, secs, kind in self._entries:
            prefix = "[B] " if kind == "bookmark" else ""
            item = QListWidgetItem(f"{prefix}{_fmt_time(secs)}  {label}")
            item.setData(Qt.ItemDataRole.UserRole, secs)
            if kind == "bookmark":
                item.setForeground(Qt.GlobalColor.cyan)
            self._list.addItem(item)
        if not self._entries:
            self._show_empty_placeholder()
        self._refresh_summary()

    def set_position(self, secs):
        """Highlight the current chapter based on playback position."""
        self._current_pos = secs

    def _show_empty_placeholder(self):
        item = QListWidgetItem("No chapters or bookmarks yet. Add a bookmark to save this moment.")
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setForeground(Qt.GlobalColor.gray)
        self._list.addItem(item)

    def _refresh_summary(self):
        bookmarks = sum(1 for _label, _secs, kind in self._entries if kind == "bookmark")
        chapters = sum(1 for _label, _secs, kind in self._entries if kind == "chapter")
        total = len(self._entries)
        if total:
            self._count_badge.setText(f"{total} saved")
            self._summary_label.setText(
                f"{chapters} chapter(s) and {bookmarks} bookmark(s) are ready to jump through."
            )
        else:
            self._count_badge.setText("Waiting")
            self._summary_label.setText(
                "Load a recording with embedded chapters or save bookmarks while you watch."
            )

    def _on_item_click(self, item):
        secs = item.data(Qt.ItemDataRole.UserRole)
        if secs is not None:
            self.seek_requested.emit(float(secs))

    def _on_add_bookmark(self):
        name, ok = ask_premium_text_input(
            self,
            title="Add a bookmark",
            body="Save the current playback position so you can jump back to this moment later.",
            eyebrow="PLAYER",
            badge_text="Bookmark",
            tone="info",
            summary_title=f"Bookmarking {_fmt_time(self._current_pos)}.",
            summary_body="Use a short label you will recognize in the chapter list.",
            field_label="Bookmark name",
            field_hint="Examples: Intro, Best moment, Final reaction.",
            placeholder="Favorite moment",
            primary_label="Save bookmark",
            secondary_label="Cancel",
            validator=lambda value: (bool((value or "").strip()), "Enter a bookmark name."),
        )
        if not ok:
            return
        self.bookmark_added.emit(name.strip(), self._current_pos)
        # Add to list immediately
        self._entries.append((name.strip(), self._current_pos, "bookmark"))
        self._entries.sort(key=lambda e: e[1])
        self._list.clear()
        for label, secs, kind in self._entries:
            prefix = "[B] " if kind == "bookmark" else ""
            item = QListWidgetItem(f"{prefix}{_fmt_time(secs)}  {label}")
            item.setData(Qt.ItemDataRole.UserRole, secs)
            if kind == "bookmark":
                item.setForeground(Qt.GlobalColor.cyan)
            self._list.addItem(item)
        self._refresh_summary()


def _parse_ts(text):
    """Parse HH:MM:SS or MM:SS or seconds into float seconds."""
    parts = text.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(text)
