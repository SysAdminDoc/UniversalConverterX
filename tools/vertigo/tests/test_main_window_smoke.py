"""Main-window smoke test — a regression net for the controller split.

The test pre-dates the ui/main_window.py → main_window + main_controller
decomposition. It constructs MainWindow with no clip, drives the paths
the controller touches (queue add/select, mode change, preset change,
theme change), and asserts that nothing raises. Probe errors from the
fake clip path are expected and must be absorbed by the window rather
than propagated out of the signal handlers.

Scope: construction + pure UI-state signal flow. It deliberately avoids
starting workers (detect/encode/subtitle), which would need real media
and a full ffmpeg pipeline.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        # Zero-out animations so the fade on tab switches and toast fades
        # don't leak live timers into other tests running in the same proc.
        os.environ.setdefault("QT_ANIMATION_DURATION_FACTOR", "0")
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication(sys.argv)
        # Prime the theme so MainWindow sees a valid stylesheet / palette.
        from ui.theme import apply_app_theme
        apply_app_theme(cls._app, "mocha")

    def test_constructs_clean_and_exercises_core_signals(self) -> None:
        from core.presets import PRESETS
        from core.reframe import ReframeMode
        from ui.main_window import MainWindow

        # A temp path is enough to append a QueueEntry — probe will fail
        # on the empty file and the window is expected to toast + skip.
        with tempfile.TemporaryDirectory() as tmp:
            fake_clip = Path(tmp) / "fake.mp4"
            fake_clip.write_bytes(b"")

            win = MainWindow()
            try:
                # queue add + select -> exercises probe() error path
                entry = win._queue.add(fake_clip)
                self.assertGreaterEqual(win._queue.count(), 1)
                win._queue.select(entry.id)

                # mode change — every mode should apply without raising
                for mode in ReframeMode:
                    win._on_mode_changed(mode)

                # preset swap — cycle through every declared preset id
                for pid in PRESETS:
                    win._choose_preset(pid)

                # theme switch — must not raise for any palette
                for theme_id in ("mocha", "graphite", "latte"):
                    win._apply_theme(theme_id, persist=False)

                self.assertEqual(win._player.segment_band(), (30.0, 90.0, 45.0))
                win._player.set_segment_band(25.0, 120.0, 60.0)
                self.assertEqual(win._player.segment_band(), (25.0, 120.0, 60.0))

                # Exercise the full clear path (confirm=False skips the
                # modal that would otherwise hang offscreen tests).
                win._clear_queue(confirm=False)
                self.assertEqual(win._queue.count(), 0)
            finally:
                win.close()
                win.deleteLater()

    def test_segment_band_settings_feed_worker_kwargs(self) -> None:
        from core.caption_types import Caption
        from core.probe import VideoInfo
        from ui.batch_queue import QueueEntry
        import ui.main_controller as main_controller
        from ui.main_window import MainWindow

        class FakeSignal:
            def __init__(self) -> None:
                self.slots = []

            def connect(self, slot) -> None:
                self.slots.append(slot)

        class FakeSegmentWorker:
            instances = []

            def __init__(self, captions, *, min_sec, max_sec, target_sec, top_n=8):
                self.captions = captions
                self.min_sec = min_sec
                self.max_sec = max_sec
                self.target_sec = target_sec
                self.top_n = top_n
                self.finished_ok = FakeSignal()
                self.failed = FakeSignal()
                FakeSegmentWorker.instances.append(self)

            def start(self) -> None:
                pass

            def isRunning(self) -> bool:
                return False

        with tempfile.TemporaryDirectory() as tmp:
            fake_clip = Path(tmp) / "long.mp4"
            fake_clip.write_bytes(b"")

            win = MainWindow()
            try:
                entry = QueueEntry(path=fake_clip)
                win._current_entry = entry
                win._info = VideoInfo(
                    path=fake_clip,
                    width=1920,
                    height=1080,
                    duration=900.0,
                    fps=30.0,
                    codec="h264",
                    has_audio=True,
                    audio_codec="aac",
                )
                win._player.set_segment_band(25.0, 120.0, 60.0)
                win._ctl._set_cached_captions(
                    entry.id,
                    [Caption(0.0, 4.0, "Can this make a useful short?")],
                )

                with patch.object(
                    main_controller, "SegmentProposalsWorker", FakeSegmentWorker
                ):
                    win._ctl.run_suggest_segments()

                self.assertEqual(len(FakeSegmentWorker.instances), 1)
                worker = FakeSegmentWorker.instances[0]
                self.assertEqual(worker.min_sec, 25.0)
                self.assertEqual(worker.max_sec, 120.0)
                self.assertEqual(worker.target_sec, 60.0)
                self.assertEqual(worker.top_n, 8)
            finally:
                win.close()
                win.deleteLater()


if __name__ == "__main__":
    unittest.main()
