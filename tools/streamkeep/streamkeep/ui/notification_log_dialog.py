"""Notification log viewer — searchable, filterable history of all events."""

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..theme import CAT
from .widgets import (
    make_dialog_hero,
    make_dialog_section,
    make_empty_state,
    make_status_banner,
    style_table,
    update_status_banner,
)


class NotificationLogDialog(QDialog):
    """Modal dialog showing the full notification history."""

    def __init__(self, parent, center):
        super().__init__(parent)
        self.setWindowTitle("Notification Log")
        self.setMinimumSize(760, 560)
        self.setModal(True)

        self._entries = center.load_history()
        self._filtered = list(self._entries)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        hero, _, _, self._hero_badge = make_dialog_hero(
            "Notification history",
            "Search, filter, and export recent alerts so it is easier to trace what happened across downloads, monitoring, and background tasks.",
            eyebrow="ACTIVITY",
            badge_text="",
        )
        root.addWidget(hero)

        filters_card, filters_content = make_dialog_section(
            "Filters",
            "Use level and search together to narrow the log quickly.",
        )
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        level_lbl = QLabel("Level")
        level_lbl.setObjectName("fieldLabel")
        filter_row.addWidget(level_lbl)
        self.level_combo = QComboBox()
        self.level_combo.addItems(["All", "Info", "Success", "Warning", "Error"])
        self.level_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.level_combo)

        search_lbl = QLabel("Search")
        search_lbl.setObjectName("fieldLabel")
        filter_row.addWidget(search_lbl)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search messages, channels, or task details…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self.search_input, 1)

        filters_content.addLayout(filter_row)
        self._feedback_banner, self._feedback_title, self._feedback_body = make_status_banner()
        filters_content.addWidget(self._feedback_banner)
        root.addWidget(filters_card)

        results_card, results_content = make_dialog_section(
            "Results",
            "Newest events are shown first in the table below.",
        )
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Time", "Level", "Message"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 86)
        style_table(self.table, row_height=38)
        results_content.addWidget(self.table)

        self.empty_card, self.empty_title, self.empty_body = make_empty_state(
            "No notifications yet",
            "Alerts from downloads, monitoring, and background jobs will appear here once the app has more activity to show.",
        )
        results_content.addWidget(self.empty_card)
        root.addWidget(results_card, 1)

        btn_row = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("statusLabel")
        btn_row.addWidget(self.count_label)
        btn_row.addStretch(1)
        export_btn = QPushButton("Export filtered log…")
        export_btn.setObjectName("secondary")
        export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(export_btn)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._apply_filter()

    def _apply_filter(self):
        level_filter = self.level_combo.currentText().lower()
        search = self.search_input.text().strip().lower()

        self._filtered = []
        for entry in self._entries:
            if level_filter != "all" and entry.get("level", "info") != level_filter:
                continue
            if search and search not in entry.get("text", "").lower():
                continue
            self._filtered.append(entry)

        level_colors = {
            "success": CAT["green"],
            "warning": CAT["yellow"],
            "error": CAT["red"],
            "info": CAT["subtext1"],
        }
        self.table.setRowCount(len(self._filtered))
        for i, entry in enumerate(reversed(self._filtered)):
            level = entry.get("level", "info")
            color = QColor(level_colors.get(level, CAT["subtext1"]))
            ts_item = QTableWidgetItem(entry.get("ts", ""))
            ts_item.setForeground(QColor(CAT["muted"]))
            self.table.setItem(i, 0, ts_item)

            level_item = QTableWidgetItem(level.capitalize())
            level_item.setForeground(color)
            self.table.setItem(i, 1, level_item)

            message_item = QTableWidgetItem(entry.get("text", ""))
            self.table.setItem(i, 2, message_item)

        self._hero_badge.setText(f"{len(self._entries)} saved")
        self._hero_badge.setVisible(bool(self._entries))
        self.count_label.setText(
            f"Showing {len(self._filtered)} of {len(self._entries)} saved notification(s)"
        )

        show_empty = len(self._filtered) == 0
        self.table.setVisible(not show_empty)
        self.empty_card.setVisible(show_empty)
        if not self._entries:
            self.empty_title.setText("No notifications yet")
            self.empty_body.setText(
                "Alerts from downloads, monitoring, and background jobs will appear here once the app has more activity to show."
            )
            update_status_banner(
                self._feedback_banner,
                self._feedback_title,
                self._feedback_body,
                title="History is empty",
                body="Once the app records activity, you can filter or export it from here.",
                tone="info",
            )
        elif show_empty:
            self.empty_title.setText("No matches for the current filters")
            self.empty_body.setText(
                "Try clearing the search box or switching the level filter to All."
            )
            update_status_banner(
                self._feedback_banner,
                self._feedback_title,
                self._feedback_body,
                title="Nothing matched",
                body="The saved log is still intact — this view is just narrowed by your current filters.",
                tone="warning",
            )
        else:
            update_status_banner(
                self._feedback_banner,
                self._feedback_title,
                self._feedback_body,
                title="History ready",
                body="Use search and level filters together to zero in on a specific event faster.",
                tone="info",
            )

    def _on_export(self):
        if not self._filtered:
            update_status_banner(
                self._feedback_banner,
                self._feedback_title,
                self._feedback_body,
                title="Nothing to export",
                body="Adjust the filters or wait for more activity before exporting the log.",
                tone="warning",
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export notifications",
            "",
            "Text files (*.txt)",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for entry in self._filtered:
                    f.write(
                        f"{entry.get('ts', '')}  [{entry.get('level', 'info')}]  "
                        f"{entry.get('text', '')}\n"
                    )
        except OSError:
            update_status_banner(
                self._feedback_banner,
                self._feedback_title,
                self._feedback_body,
                title="Export failed",
                body="StreamKeep could not write the selected file. Try a different folder or filename.",
                tone="error",
            )
            return

        update_status_banner(
            self._feedback_banner,
            self._feedback_title,
            self._feedback_body,
            title="Export complete",
            body=f"Saved {len(self._filtered)} notification(s) to {path}.",
            tone="success",
        )
