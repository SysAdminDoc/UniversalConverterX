"""Multi-Stream Sync Viewer — play 2-4 recordings side by side (F54).

All players share a single transport (play/pause/seek moves all together).
Per-stream audio toggle and offset adjustment (+-30s).

Usage::

    viewer = SyncViewer(parent)
    viewer.add_stream("/path/to/video1.mp4", "xQc POV")
    viewer.add_stream("/path/to/video2.mp4", "Kai POV")
    viewer.show()
"""

import os

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt, QTimer

from ..ui.widgets import (
    make_dialog_hero,
    make_empty_state,
    make_status_banner,
    update_status_banner,
)
from .mpv_widget import MpvWidget, is_mpv_available


def _fmt_time(secs):
    s = max(0, int(secs or 0))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class _StreamSlot:
    """Internal state for one player slot."""
    def __init__(self):
        self.widget = None       # MpvWidget
        self.label = ""
        self.offset_secs = 0.0   # +-30s offset for sync
        self.file_path = ""
        self.muted = True        # only one stream plays audio at a time


class SyncViewer(QDialog):
    """Dialog showing 2-4 synchronized mpv players in a grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("StreamKeep — Multi-Stream Sync Viewer")
        self.setMinimumSize(900, 560)
        self.resize(1200, 720)

        self._slots = []          # list of _StreamSlot
        self._duration = 0.0
        self._paused = True
        self._audio_slot = 0      # index of the slot that plays audio

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        hero, _, _, self._hero_badge = make_dialog_hero(
            "Multi-stream sync viewer",
            "Compare 2-4 recordings side by side, keep one stream on audio, and nudge offsets until moments line up cleanly.",
            eyebrow="PLAYER",
            badge_text="Waiting",
        )
        root.addWidget(hero)

        self._status_banner, self._status_title, self._status_body = make_status_banner()
        root.addWidget(self._status_banner)

        # Video grid
        self._grid_shell = QFrame()
        self._grid_shell.setObjectName("playerVideoCanvas")
        grid_shell_lay = QVBoxLayout(self._grid_shell)
        grid_shell_lay.setContentsMargins(12, 12, 12, 12)
        grid_shell_lay.setSpacing(10)
        self._grid_widget = QWidget()
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10)
        self._empty_card, _, _ = make_empty_state(
            "Add recordings to compare",
            "The sync viewer shines with multiple POVs. Once streams are added, playback stays locked to one shared transport bar.",
        )
        grid_shell_lay.addWidget(self._empty_card)
        grid_shell_lay.addWidget(self._grid_widget, 1)
        root.addWidget(self._grid_shell, 1)

        # Transport bar
        transport = QFrame()
        transport.setObjectName("playerTransportBar")
        tlay = QHBoxLayout(transport)
        tlay.setContentsMargins(16, 12, 16, 12)
        tlay.setSpacing(8)

        self._play_btn = QPushButton("||")
        self._play_btn.setFixedWidth(36)
        self._play_btn.setObjectName("primary")
        self._play_btn.clicked.connect(self._toggle_pause)
        tlay.addWidget(self._play_btn)

        self._time_label = QLabel("0:00")
        self._time_label.setObjectName("playerMeta")
        self._time_label.setFixedWidth(60)
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tlay.addWidget(self._time_label)

        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.sliderReleased.connect(self._on_seek)
        tlay.addWidget(self._seek_slider, 1)

        self._dur_label = QLabel("0:00")
        self._dur_label.setObjectName("playerMeta")
        self._dur_label.setFixedWidth(60)
        tlay.addWidget(self._dur_label)

        audio_lbl = QLabel("Audio")
        audio_lbl.setObjectName("playerTinyLabel")
        tlay.addWidget(audio_lbl)
        self._audio_combo = QComboBox()
        self._audio_combo.setFixedWidth(120)
        self._audio_combo.currentIndexChanged.connect(self._on_audio_switch)
        tlay.addWidget(self._audio_combo)

        root.addWidget(transport)

        # Poll timer for position sync
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._poll_position)
        self._refresh_chrome()

    def add_stream(self, file_path, label=""):
        """Add a stream to the viewer. Max 4 streams."""
        if len(self._slots) >= 4:
            return
        if not is_mpv_available():
            return

        slot = _StreamSlot()
        slot.file_path = file_path
        slot.label = label or os.path.basename(file_path)
        slot.widget = MpvWidget(self)
        slot.muted = len(self._slots) != 0  # first slot has audio
        self._slots.append(slot)

        # Update grid layout
        self._relayout_grid()

        # Update audio combo
        self._audio_combo.blockSignals(True)
        self._audio_combo.addItem(slot.label[:20])
        self._audio_combo.blockSignals(False)
        self._refresh_chrome()

    def start_all(self):
        """Begin playback on all streams."""
        for i, slot in enumerate(self._slots):
            slot.widget.play(slot.file_path)
            # Mute all except the audio slot
            if i != self._audio_slot:
                slot.widget.volume = 0
        self._paused = False
        self._play_btn.setText("||")
        self._poll.start()

        # Get duration from first stream
        if self._slots:
            self._slots[0].widget.duration_changed.connect(self._on_duration)
        self._refresh_chrome()

    def _relayout_grid(self):
        """Arrange player widgets in a grid based on count."""
        # Remove items from the grid without destroying them — the MpvWidget
        # instances inside the cards are still alive in self._slots and must
        # not be deleted.
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        n = len(self._slots)
        if n <= 1:
            cols = 1
        elif n <= 2:
            cols = 2
        else:
            cols = 2

        for i, slot in enumerate(self._slots):
            card = QFrame()
            card.setObjectName("playerSlotCard")
            container = QVBoxLayout(card)
            container.setContentsMargins(10, 10, 10, 10)
            container.setSpacing(8)
            head_row = QHBoxLayout()
            head_row.setContentsMargins(0, 0, 0, 0)
            head_row.setSpacing(8)
            title_col = QVBoxLayout()
            title_col.setSpacing(2)
            label = QLabel(slot.label)
            label.setObjectName("playerMiniTitle")
            label.setWordWrap(True)
            title_col.addWidget(label)
            meta = QLabel(os.path.basename(slot.file_path))
            meta.setObjectName("playerMiniMeta")
            meta.setWordWrap(True)
            title_col.addWidget(meta)
            head_row.addLayout(title_col, 1)
            badge = QLabel("Audio" if i == self._audio_slot else "Silent")
            badge.setObjectName("playerBadgeMuted")
            head_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            container.addLayout(head_row)
            container.addWidget(slot.widget, 1)

            # Offset control
            offset_row = QHBoxLayout()
            offset_row.setSpacing(4)
            offset_label = QLabel("Offset:")
            offset_label.setObjectName("playerTinyLabel")
            offset_row.addWidget(offset_label)
            spin = QSpinBox()
            spin.setRange(-30, 30)
            spin.setSuffix("s")
            spin.setValue(int(slot.offset_secs))
            spin.setFixedWidth(70)
            idx = i  # capture
            spin.valueChanged.connect(lambda v, si=idx: self._set_offset(si, v))
            offset_row.addWidget(spin)
            offset_row.addStretch(1)
            container.addLayout(offset_row)

            row, col = divmod(i, cols)
            self._grid.addWidget(card, row, col)
        self._refresh_chrome()

    def _refresh_chrome(self):
        count = len(self._slots)
        self._hero_badge.setText(f"{count} stream(s)" if count else "Waiting")
        self._hero_badge.setVisible(True)
        self._grid_widget.setVisible(bool(count))
        self._empty_card.setVisible(not bool(count))
        self._audio_combo.setEnabled(count > 1)
        self._play_btn.setEnabled(bool(count))
        self._seek_slider.setEnabled(bool(count))
        if not count:
            update_status_banner(
                self._status_banner,
                self._status_title,
                self._status_body,
                title="Ready for a side-by-side session",
                body="Add two or more recordings to compare reactions, timing, or multiple points of view on the same moment.",
                tone="info",
            )
        elif count == 1:
            update_status_banner(
                self._status_banner,
                self._status_title,
                self._status_body,
                title="One stream loaded",
                body="Add at least one more recording to make sync comparison useful.",
                tone="warning",
            )
        else:
            update_status_banner(
                self._status_banner,
                self._status_title,
                self._status_body,
                title="Sync viewer ready",
                body="Use the shared transport below, pick one audio stream, and adjust offsets until the moments line up.",
                tone="success" if not self._paused else "info",
            )

    def _toggle_pause(self):
        self._paused = not self._paused
        for slot in self._slots:
            if slot.widget._mpv:
                try:
                    slot.widget._mpv.pause = self._paused
                except Exception:
                    pass
        self._play_btn.setText(">" if self._paused else "||")
        self._refresh_chrome()

    def _on_seek(self):
        if self._duration <= 0:
            return
        target = self._seek_slider.value() / 1000.0 * self._duration
        for slot in self._slots:
            slot.widget.seek(target + slot.offset_secs)

    def _set_offset(self, slot_idx, offset_secs):
        if 0 <= slot_idx < len(self._slots):
            self._slots[slot_idx].offset_secs = float(offset_secs)

    def _on_audio_switch(self, idx):
        self._audio_slot = idx
        for i, slot in enumerate(self._slots):
            slot.widget.volume = 100 if i == idx else 0
        self._relayout_grid()

    def _on_duration(self, secs):
        self._duration = secs
        self._dur_label.setText(_fmt_time(secs))

    def _poll_position(self):
        if not self._slots:
            return
        # Use the audio slot as the reference position
        ref = self._slots[min(self._audio_slot, len(self._slots) - 1)]
        pos = ref.widget.position
        self._time_label.setText(_fmt_time(pos))
        if self._duration > 0:
            pct = min(1000, int(pos / self._duration * 1000))
            self._seek_slider.setValue(pct)

    def closeEvent(self, event):
        self._poll.stop()
        for slot in self._slots:
            slot.widget.destroy_mpv()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space:
            self._toggle_pause()
        elif key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            for s in self._slots:
                s.widget.seek_relative(-5)
        elif key == Qt.Key.Key_Right:
            for s in self._slots:
                s.widget.seek_relative(5)
        else:
            super().keyPressEvent(event)
