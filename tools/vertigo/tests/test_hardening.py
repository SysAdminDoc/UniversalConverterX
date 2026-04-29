"""Regression tests for the hardening pass (see commit 'Hardening pass').

Each test here pins a concrete defect to a specific failure mode so a
refactor that reintroduces the bug has a red test to show for it.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock


# ---------------------------------------------------------------- reframe

class CropDimsGuardsTests(unittest.TestCase):
    def test_crop_dims_survives_zero_target(self) -> None:
        """_crop_dims must not raise on a bad preset / probe combination.

        Before the hardening pass this divided by target_h with no guard
        and crashed ``build_plan`` when a zero slipped in from anywhere.
        """
        from core.probe import VideoInfo
        from core.reframe import _crop_dims
        info = VideoInfo(
            path=Path("/tmp/x.mp4"), width=1920, height=1080,
            duration=10.0, fps=30.0, codec="h264", has_audio=False,
            audio_codec=None,
        )
        # target_h == 0 historically crashed
        cw, ch = _crop_dims(info, 1080, 0)
        self.assertGreaterEqual(cw, 2)
        self.assertGreaterEqual(ch, 2)

    def test_crop_dims_survives_zero_source(self) -> None:
        from core.probe import VideoInfo
        from core.reframe import _crop_dims
        info = VideoInfo(
            path=Path("/tmp/x.mp4"), width=0, height=0,
            duration=10.0, fps=30.0, codec="h264", has_audio=False,
            audio_codec=None,
        )
        cw, ch = _crop_dims(info, 1080, 1920)
        self.assertGreaterEqual(cw, 2)
        self.assertGreaterEqual(ch, 2)


class TrackExpressionStrideTests(unittest.TestCase):
    def test_long_tracks_are_strided_for_the_expression(self) -> None:
        """Smart-track on a long clip must not generate an expression
        deep enough to blow FFmpeg's parser."""
        from core.detect import TrackPoint
        from core.probe import VideoInfo
        from core.reframe import _MAX_TRACK_EXPR_POINTS, ReframeMode, build_plan
        from core.presets import default_preset

        # Simulate 600 keyframes — a 5-minute clip sampled at 2 fps.
        points = [
            TrackPoint(t=i * 0.5, x=0.5 + (i % 7) * 0.01, confidence=0.8)
            for i in range(600)
        ]
        info = VideoInfo(
            path=Path("/tmp/x.mp4"), width=1920, height=1080,
            duration=300.0, fps=30.0, codec="h264", has_audio=False,
            audio_codec=None,
        )
        plan = build_plan(info, default_preset(), ReframeMode.SMART_TRACK,
                          track_points=points)
        # The notes carry the actual keyframe count that reached FFmpeg;
        # assert it's within the documented ceiling.
        # Example: "Smart-track (128 keyframes, smoothed)"
        import re
        m = re.search(r"Smart-track \((\d+) keyframes", plan.notes)
        self.assertIsNotNone(m)
        kept = int(m.group(1))
        self.assertLessEqual(kept, _MAX_TRACK_EXPR_POINTS + 1)

    def test_short_tracks_are_left_alone(self) -> None:
        from core.detect import TrackPoint
        from core.probe import VideoInfo
        from core.reframe import ReframeMode, build_plan
        from core.presets import default_preset
        points = [TrackPoint(t=i * 0.5, x=0.5, confidence=0.8) for i in range(10)]
        info = VideoInfo(
            path=Path("/tmp/x.mp4"), width=1920, height=1080,
            duration=30.0, fps=30.0, codec="h264", has_audio=False,
            audio_codec=None,
        )
        plan = build_plan(info, default_preset(), ReframeMode.SMART_TRACK,
                          track_points=points)
        import re
        m = re.search(r"Smart-track \((\d+) keyframes", plan.notes)
        self.assertEqual(int(m.group(1)), 10)


# ---------------------------------------------------------------- encode

class SubtitlesFilterEscapingTests(unittest.TestCase):
    def test_single_quote_in_path_is_escaped(self) -> None:
        """A clip whose path contains ``'`` must not break the filter."""
        from core.caption_styles import default_preset
        from core.encode import _subtitles_filter
        path = Path("/tmp/it's a clip.srt")
        out = _subtitles_filter(path, default_preset(), 1920)
        # The apostrophe is replaced with the FFmpeg-documented escape
        # `'\''` (close quote / literal / reopen), never left raw.
        self.assertNotIn("/it's ", out)
        self.assertIn(r"'\''", out)

    def test_windows_drive_colon_escaped(self) -> None:
        from core.caption_styles import default_preset
        from core.encode import _subtitles_filter
        # Use a path that looks like a Windows drive letter; Path on
        # POSIX won't actually normalise it, but _subtitles_filter should
        # still prepend the escape on any second-char colon.
        path = Path("C:/videos/clip.srt")
        out = _subtitles_filter(path, default_preset(), 1920)
        # The colon immediately after the drive letter should be escaped
        # so libavfilter doesn't treat it as an argument separator.
        self.assertIn(r"C\:", out)


# ---------------------------------------------------------------- batch queue

class QueueIdSequenceTests(unittest.TestCase):
    def test_ids_are_monotonically_increasing(self) -> None:
        from ui.batch_queue import QueueEntry
        a = QueueEntry(path=Path("/tmp/a.mp4"))
        b = QueueEntry(path=Path("/tmp/b.mp4"))
        c = QueueEntry(path=Path("/tmp/c.mp4"))
        self.assertLess(a.id, b.id)
        self.assertLess(b.id, c.id)
        self.assertGreaterEqual(a.id, 1)


# ---------------------------------------------------------------- detect worker

class DetectWorkerCancelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_cancel_before_start_emits_failed_not_ok(self) -> None:
        """A worker cancelled before (or during) run must not emit a
        ``finished_ok`` signal with an empty / partial track."""
        from workers.detect_worker import DetectWorker
        w = DetectWorker(Path("/tmp/does-not-exist.mp4"))

        ok_calls: list = []
        fail_calls: list = []
        w.finished_ok.connect(ok_calls.append)
        w.failed.connect(fail_calls.append)

        # Pretend cancel was hit before start; run() will see _cancel=True
        # either through the tracker's cancel_cb or on the post-return check.
        w.cancel()
        w.run()  # direct-call: exercise the method on the test thread

        self.assertEqual(ok_calls, [], "must not emit finished_ok after cancel")
        self.assertTrue(fail_calls, "must emit failed() on cancel")
        self.assertEqual(fail_calls[0], "Cancelled.")


# ---------------------------------------------------------------- hook_score

class HookScoreBoundsTests(unittest.TestCase):
    def test_zero_sample_rate_returns_silent(self) -> None:
        from core.hook_score import _analyse
        vf, mve = _analyse([1, 2, 3], sample_rate=0)
        self.assertEqual((vf, mve), (0.0, 0.0))

    def test_empty_samples_returns_silent(self) -> None:
        from core.hook_score import _analyse
        vf, mve = _analyse([], sample_rate=16000)
        self.assertEqual((vf, mve), (0.0, 0.0))


# ---------------------------------------------------------------- main controller

class ClipSubsCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("QT_ANIMATION_DURATION_FACTOR", "0")
        from PyQt6.QtWidgets import QApplication
        cls._app = QApplication.instance() or QApplication(sys.argv)
        from ui.theme import apply_app_theme
        apply_app_theme(cls._app, "mocha")

    def test_drop_clip_subs_unlinks_srt_on_disk(self) -> None:
        """Removing a queue entry must clean up the auto-generated SRT."""
        import tempfile
        from ui.main_window import MainWindow

        with tempfile.TemporaryDirectory() as tmp:
            srt = Path(tmp) / "demo.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

            win = MainWindow()
            try:
                # Plant an entry + its subtitle path directly on the
                # controller; there's no real transcribe running.
                win._ctl.clip_subs[42] = srt
                self.assertTrue(srt.exists())

                win._ctl.drop_clip_subs(42)

                self.assertFalse(srt.exists(), "SRT should be unlinked")
                self.assertNotIn(42, win._ctl.clip_subs)
            finally:
                win.close()
                win.deleteLater()


if __name__ == "__main__":
    unittest.main()
