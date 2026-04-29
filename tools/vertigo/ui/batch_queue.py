"""Batch queue — thumbnail list of imported clips with per-item status.

Uses a simple vertical list of QueueItem widgets. Clicking an item selects
it for preview; the queue driver in MainWindow runs them in order.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import current_palette


class QueueStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"


_GLYPH = {
    QueueStatus.PENDING: "\u25cb",
    QueueStatus.ACTIVE:  "\u25c9",
    QueueStatus.DONE:    "\u2713",
    QueueStatus.FAILED:  "\u2715",
}

_STATUS_LABEL = {
    QueueStatus.PENDING: "Queued",
    QueueStatus.ACTIVE: "Working",
    QueueStatus.DONE: "Done",
    QueueStatus.FAILED: "Needs review",
}


def _status_color(status: QueueStatus) -> str:
    theme = current_palette()
    return {
        QueueStatus.PENDING: theme.overlay1,
        QueueStatus.ACTIVE: theme.accent,
        QueueStatus.DONE: theme.green,
        QueueStatus.FAILED: theme.red,
    }[status]


# Monotonically-increasing queue-entry IDs. ``itertools.count`` hands out
# thread-safe increments (GIL-atomic under CPython) and avoids the module-
# global mutable state the previous ``_next_id()`` helper relied on.
_id_sequence = itertools.count(1)


@dataclass
class QueueEntry:
    path: Path
    status: QueueStatus = QueueStatus.PENDING
    message: str = ""
    id: int = field(default_factory=lambda: next(_id_sequence))


class QueueItem(QFrame):
    selected = pyqtSignal(int)
    removed = pyqtSignal(int)

    def __init__(self, entry: QueueEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("queueItem")
        self.setFixedHeight(72)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(entry.path))
        self.setAccessibleName(entry.path.name)
        self._selected = False
        self._apply_style()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 10)
        lay.setSpacing(12)

        self._status_icon = QLabel(_GLYPH[entry.status])
        self._status_icon.setFixedWidth(14)
        lay.addWidget(self._status_icon, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._name = QLabel(entry.path.name)
        self._name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._name.setToolTip(str(entry.path))
        self._sub = QLabel(entry.message or "Ready when you are")
        self._sub.setWordWrap(True)
        col.addWidget(self._name)
        col.addWidget(self._sub)
        lay.addLayout(col, 1)

        self._status_badge = QLabel("")
        self._status_badge.setObjectName("statusPill")
        self._status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_badge.setMinimumWidth(92)
        lay.addWidget(self._status_badge, 0, Qt.AlignmentFlag.AlignTop)

        self._rm_btn = QPushButton("\u2715")
        self._rm_btn.setFlat(True)
        self._rm_btn.setFixedSize(24, 24)
        self._rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rm_btn.setToolTip("Remove from queue")
        self._rm_btn.setAccessibleName(f"Remove {entry.path.name}")
        self._rm_btn.clicked.connect(lambda: self.removed.emit(self.entry.id))
        lay.addWidget(self._rm_btn)
        self._sync_remove_enabled()
        self.refresh_theme()

    def update_entry(self, entry: QueueEntry) -> None:
        self.entry = entry
        self._status_icon.setText(_GLYPH[entry.status])
        self._sub.setText(entry.message or _STATUS_LABEL[entry.status])
        self.setAccessibleDescription(self._sub.text())
        self._sync_remove_enabled()
        self.refresh_theme()

    def set_selected(self, on: bool) -> None:
        self._selected = on
        self._apply_style()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.entry.id)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.selected.emit(self.entry.id)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.entry.status is not QueueStatus.ACTIVE:
                self.removed.emit(self.entry.id)
            event.accept()
            return
        super().keyPressEvent(event)

    def _sync_remove_enabled(self) -> None:
        active = self.entry.status is QueueStatus.ACTIVE
        self._rm_btn.setEnabled(not active)
        self._rm_btn.setToolTip("Encoding clips cannot be removed" if active else "Remove from queue")

    def _apply_style(self) -> None:
        theme = current_palette()
        if self._selected:
            self.setStyleSheet(
                f"QFrame#queueItem {{background: {theme.accent_selected}; "
                f"border: 1px solid {theme.accent}; border-radius: 10px;}}"
            )
        else:
            self.setStyleSheet(
                f"QFrame#queueItem {{background: {theme.base}; "
                f"border: 1px solid {theme.surface0}; border-radius: 10px;}}"
                f"QFrame#queueItem:hover {{border-color: {theme.surface2}; background: {theme.accent_hover};}}"
                f"QFrame#queueItem:focus {{border-color: {theme.focus};}}"
            )

    def refresh_theme(self) -> None:
        theme = current_palette()
        self._status_icon.setStyleSheet(
            f"color: {_status_color(self.entry.status)}; font-size: 13px; font-weight: 700;"
        )
        self._name.setStyleSheet(f"color: {theme.text}; font-size: 12px; font-weight: 600;")
        self._sub.setStyleSheet(f"color: {theme.subtext0}; font-size: 10px;")
        tone = {
            QueueStatus.PENDING: None,
            QueueStatus.ACTIVE: "accent",
            QueueStatus.DONE: "success",
            QueueStatus.FAILED: "error",
        }[self.entry.status]
        self._status_badge.setText(_STATUS_LABEL[self.entry.status])
        self._status_badge.setProperty("tone", tone)
        self._status_badge.style().unpolish(self._status_badge)
        self._status_badge.style().polish(self._status_badge)
        self._rm_btn.setStyleSheet(
            f"QPushButton {{background: transparent; color: {theme.overlay0}; border: none; font-size: 12px;}}"
            f"QPushButton:hover {{color: {theme.red};}}"
            f"QPushButton:focus {{color: {theme.red}; border: 1px solid {theme.red}; border-radius: 6px;}}"
            f"QPushButton:disabled {{color: {theme.surface2};}}"
        )
        self._apply_style()


class BatchQueue(QWidget):
    entry_selected = pyqtSignal(object)  # QueueEntry
    entry_removed = pyqtSignal(int)      # id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[QueueEntry] = []
        self._items: dict[int, QueueItem] = {}
        self._selected_id: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        self._empty = QWidget()
        self._empty.setObjectName("emptyState")
        self._empty.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        empty_lay = QVBoxLayout(self._empty)
        empty_lay.setContentsMargins(24, 28, 24, 28)
        empty_lay.setSpacing(6)
        empty_lay.addStretch(1)
        empty_title = QLabel("Your queue is empty")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_body = QLabel(
            "Drop one clip to start polishing, or drop several to export a whole batch with the same framing, text, and output settings."
        )
        empty_body.setObjectName("emptyBody")
        empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_body.setWordWrap(True)
        empty_note = QLabel(
            "Everything in the queue stays in sync with your current preset, reframe mode, captions, and export settings."
        )
        empty_note.setObjectName("valueMuted")
        empty_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_note.setWordWrap(True)
        empty_lay.addWidget(empty_title)
        empty_lay.addWidget(empty_body)
        empty_lay.addWidget(empty_note)
        empty_lay.addStretch(1)

        self._list_host = QWidget()
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(6)
        self._list_lay.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._list_host)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("background: transparent;")
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        outer.addWidget(self._empty)
        outer.addWidget(self._scroll, 1)
        self._refresh_empty_state()

    # ---------------------------------------------- public api
    def add(self, path: Path) -> QueueEntry:
        entry = QueueEntry(path=Path(path))
        self._entries.append(entry)
        item = QueueItem(entry)
        item.selected.connect(self._on_item_selected)
        item.removed.connect(self._on_item_removed)
        self._items[entry.id] = item
        self._list_lay.insertWidget(self._list_lay.count() - 1, item)
        self._refresh_empty_state()
        return entry

    def update_status(self, entry_id: int, status: QueueStatus, message: str = "") -> None:
        for e in self._entries:
            if e.id == entry_id:
                e.status = status
                e.message = message
                item = self._items.get(entry_id)
                if item:
                    item.update_entry(e)
                return

    def select(self, entry_id: int) -> None:
        self._on_item_selected(entry_id)

    def entries(self) -> list[QueueEntry]:
        return list(self._entries)

    def pending_entries(self) -> list[QueueEntry]:
        return [e for e in self._entries if e.status == QueueStatus.PENDING]

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        """Remove every queue entry and emit ``entry_removed`` per id.

        Emitting per-entry keeps the controller's per-clip cleanup hook
        (``drop_clip_subs``) in the driver's seat for every removal
        path — otherwise a "Clear queue" click would silently leak the
        cached SRT/ASS files and the ``clip_captions`` /
        ``animated_styles`` dicts referenced by those ids.
        """
        removed_ids = [e.id for e in self._entries]
        for item in self._items.values():
            item.setParent(None)
            item.deleteLater()
        self._items.clear()
        self._entries.clear()
        self._selected_id = None
        self._refresh_empty_state()
        for eid in removed_ids:
            self.entry_removed.emit(eid)

    # ---------------------------------------------- slots
    def _on_item_selected(self, entry_id: int) -> None:
        self._selected_id = entry_id
        for eid, item in self._items.items():
            item.set_selected(eid == entry_id)
        entry = next((e for e in self._entries if e.id == entry_id), None)
        if entry:
            self.entry_selected.emit(entry)

    def _on_item_removed(self, entry_id: int) -> None:
        item = self._items.pop(entry_id, None)
        if item:
            item.setParent(None)
            item.deleteLater()
        self._entries = [e for e in self._entries if e.id != entry_id]
        if self._selected_id == entry_id:
            self._selected_id = None
        self.entry_removed.emit(entry_id)
        self._refresh_empty_state()

    def _refresh_empty_state(self) -> None:
        empty = not self._entries
        self._empty.setVisible(empty)
        self._scroll.setVisible(not empty)

    def refresh_theme(self) -> None:
        for item in self._items.values():
            item.refresh_theme()
