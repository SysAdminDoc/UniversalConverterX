"""Deleted VOD Recovery Wizard — recover expired Twitch VODs with clearer UX."""

import datetime

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
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


class _RecoverWorker(QThread):
    """Run recovery in a background thread."""

    progress = pyqtSignal(int, str)
    done = pyqtSignal(list)  # list of StreamInfo

    def __init__(self, channel, year, month, log_fn=None):
        super().__init__()
        self.channel = channel
        self.year = year
        self.month = month
        self._log_fn = log_fn

    def run(self):
        from ..extractors.twitch_recover import recover_channel_vods

        results = recover_channel_vods(
            self.channel,
            self.year,
            self.month,
            log_fn=self._log_fn,
            progress_fn=lambda pct, msg: self.progress.emit(pct, msg),
        )
        self.done.emit(results)


class RecoverDialog(QDialog):
    """VOD recovery dialog."""

    download_requested = pyqtSignal(str)  # M3U8 URL

    def __init__(self, parent, log_fn=None):
        super().__init__(parent)
        self.setWindowTitle("Deleted VOD Recovery")
        self.setMinimumSize(760, 560)
        self.setModal(True)
        self._log_fn = log_fn
        self._results = []
        self._worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        hero, _, _, self._hero_badge = make_dialog_hero(
            "Recover deleted or expired Twitch VODs",
            "StreamKeep checks tracker metadata and probes cached CDN paths for a selected month. Recovery depends on what Twitch still has cached, so results can vary.",
            eyebrow="RECOVERY",
            badge_text="Twitch only",
        )
        root.addWidget(hero)

        search_card, search_content = make_dialog_section(
            "Search window",
            "Pick the channel and the month you want to inspect. Use the exact Twitch channel name without the full URL.",
        )
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        input_row.addWidget(self._field_label("Channel"))
        self.channel_input = QLineEdit()
        self.channel_input.setPlaceholderText("streamer_name")
        self.channel_input.setClearButtonEnabled(True)
        self.channel_input.setMaximumWidth(230)
        self.channel_input.returnPressed.connect(self._on_search)
        input_row.addWidget(self.channel_input)

        input_row.addWidget(self._field_label("Month"))
        self.month_combo = QComboBox()
        now = datetime.datetime.now()
        for i in range(1, 13):
            self.month_combo.addItem(datetime.date(2000, i, 1).strftime("%B"), i)
        self.month_combo.setCurrentIndex(max(0, now.month - 1))
        input_row.addWidget(self.month_combo)

        input_row.addWidget(self._field_label("Year"))
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2016, now.year)
        self.year_spin.setValue(now.year)
        input_row.addWidget(self.year_spin)

        self.search_btn = QPushButton("Search recovery window")
        self.search_btn.setObjectName("primary")
        self.search_btn.clicked.connect(self._on_search)
        input_row.addWidget(self.search_btn)
        input_row.addStretch(1)
        search_content.addLayout(input_row)

        self.status_banner, self.status_title, self.status_body = make_status_banner(
            "Ready to search",
            "Enter a channel name and pick a month to start scanning.",
            tone="info",
        )
        search_content.addWidget(self.status_banner)
        root.addWidget(search_card)

        results_card, results_content = make_dialog_section(
            "Recoverable VODs",
            "When results are available, use Download to send the recovered stream URL back to the main download flow.",
        )
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Date", "Stream ID", "Quality", "Action"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 110)
        style_table(self.table)
        results_content.addWidget(self.table)

        self.empty_card, self.empty_title, self.empty_body = make_empty_state(
            "No recovery results yet",
            "Once you run a search, any recoverable VODs for that month will appear here.",
        )
        results_content.addWidget(self.empty_card)
        root.addWidget(results_card, 1)

        btn_row = QHBoxLayout()
        self.count_label = QLabel("No results loaded")
        self.count_label.setObjectName("statusLabel")
        btn_row.addWidget(self.count_label)
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("secondary")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        self._refresh_results_table()

    def _field_label(self, text):
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _set_search_running(self, running):
        self.search_btn.setEnabled(not running)
        self.channel_input.setEnabled(not running)
        self.month_combo.setEnabled(not running)
        self.year_spin.setEnabled(not running)
        if running:
            self.search_btn.setText("Searching…")
        else:
            self.search_btn.setText("Search recovery window")

    def _refresh_results_table(self):
        has_results = bool(self._results)
        self.table.setVisible(has_results)
        self.empty_card.setVisible(not has_results)
        self._hero_badge.setText(f"{len(self._results)} found")
        self._hero_badge.setVisible(has_results)
        if has_results:
            self.count_label.setText(f"{len(self._results)} recoverable VOD(s) ready")
        else:
            self.count_label.setText("No recoverable VODs loaded")

    def _on_search(self):
        channel = self.channel_input.text().strip().lower()
        if not channel:
            update_status_banner(
                self.status_banner,
                self.status_title,
                self.status_body,
                title="Enter a channel name first",
                body="Use the Twitch channel name only, for example `streamer_name`.",
                tone="warning",
            )
            return
        month = self.month_combo.currentData()
        year = self.year_spin.value()

        if self._worker is not None and self._worker.isRunning():
            update_status_banner(
                self.status_banner,
                self.status_title,
                self.status_body,
                title="Search already running",
                body="Wait for the current recovery scan to finish before starting another one.",
                tone="warning",
            )
            return

        self._set_search_running(True)
        self._results = []
        self.table.setRowCount(0)
        self._refresh_results_table()
        update_status_banner(
            self.status_banner,
            self.status_title,
            self.status_body,
            title=f"Scanning {channel}",
            body=f"Checking tracker data and cached CDN paths for {year}-{month:02d}. This can take a little time.",
            tone="info",
        )

        self._worker = _RecoverWorker(channel, year, month, log_fn=self._log_fn)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, pct, msg):
        update_status_banner(
            self.status_banner,
            self.status_title,
            self.status_body,
            title=f"Search in progress ({pct}%)",
            body=msg,
            tone="info",
        )

    def _on_done(self, results):
        self._set_search_running(False)
        self._results = results or []

        if not self._results:
            update_status_banner(
                self.status_banner,
                self.status_title,
                self.status_body,
                title="No recoverable VODs found",
                body="That month may already be purged from Twitch's CDN cache. Try a more recent month or confirm the channel name.",
                tone="warning",
            )
            self.empty_title.setText("No recoverable VODs found")
            self.empty_body.setText(
                "Try a more recent month, confirm the channel name, or search again later if the stream ended recently."
            )
            self._refresh_results_table()
            return

        update_status_banner(
            self.status_banner,
            self.status_title,
            self.status_body,
            title="Recovery results ready",
            body=f"Found {len(self._results)} recoverable VOD(s). Use Download to send one back to the main workflow.",
            tone="success",
        )

        self.table.setRowCount(len(self._results))
        for i, info in enumerate(self._results):
            date_text = info.title.replace("Recovered VOD — ", "")
            date_item = QTableWidgetItem(date_text)
            self.table.setItem(i, 0, date_item)

            parts = info.url.split("/")
            stream_id = parts[-3] if len(parts) >= 3 else ""
            sid_item = QTableWidgetItem(stream_id)
            self.table.setItem(i, 1, sid_item)

            quality_count = len(info.qualities)
            quality_item = QTableWidgetItem(f"{quality_count} stream(s)")
            quality_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            quality_item.setForeground(QColor(CAT["green"]))
            self.table.setItem(i, 2, quality_item)

            dl_btn = QPushButton("Download")
            dl_btn.setObjectName("primary")
            dl_btn.setFixedHeight(30)
            dl_btn.clicked.connect(lambda _checked=False, url=info.url: self._on_download(url))
            self.table.setCellWidget(i, 3, dl_btn)

        self._refresh_results_table()

    def reject(self):
        if self._worker is not None and self._worker.isRunning():
            try:
                self._worker.progress.disconnect()
            except Exception:
                pass
            try:
                self._worker.done.disconnect()
            except Exception:
                pass
            self._worker.quit()
            self._worker.wait(2000)
        super().reject()

    def _on_download(self, url):
        self.download_requested.emit(url)
        update_status_banner(
            self.status_banner,
            self.status_title,
            self.status_body,
            title="Sent to Download",
            body="The recovered URL was handed back to the main downloader so you can finish from the primary workflow.",
            tone="success",
        )
