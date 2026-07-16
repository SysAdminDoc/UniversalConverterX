"""Focused scoring and interchange tests for Auto Highlight."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "scenedetect" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("scenedetect_sidecar", SIDECAR)
assert SPEC and SPEC.loader
scenedetect_sidecar = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scenedetect_sidecar
SPEC.loader.exec_module(scenedetect_sidecar)


def sample_scenes() -> list[dict]:
    return [
        {"start_seconds": 0.0, "end_seconds": 10.0, "start_frame": 0, "end_frame": 100, "cut_peak": 0.0},
        {"start_seconds": 10.0, "end_seconds": 20.0, "start_frame": 100, "end_frame": 200, "cut_peak": 80.0},
        {"start_seconds": 20.0, "end_seconds": 30.0, "start_frame": 200, "end_frame": 300, "cut_peak": 20.0},
    ]


class SceneDetectHighlightTests(unittest.TestCase):
    def test_scene_peak_and_motion_rank_non_overlapping_windows(self) -> None:
        motion = {frame: (0.9 if 120 <= frame < 180 else 0.1) for frame in range(300)}

        highlights = scenedetect_sidecar.rank_highlight_candidates(
            sample_scenes(), motion, fps=10.0, duration=30.0,
            clip_length=6.0, top_n=2, min_gap=0.0)

        self.assertEqual(2, len(highlights))
        self.assertEqual(120, highlights[0]["start_frame"])
        self.assertEqual("Strong transition and high motion", highlights[0]["reason"])
        self.assertGreater(highlights[0]["score"], highlights[1]["score"])
        self.assertTrue(
            highlights[0]["end_frame"] <= highlights[1]["start_frame"]
            or highlights[1]["end_frame"] <= highlights[0]["start_frame"])

    def test_motion_peak_can_anchor_highlight_inside_a_long_scene(self) -> None:
        scenes = [{
            "start_seconds": 0.0, "end_seconds": 60.0,
            "start_frame": 0, "end_frame": 600, "cut_peak": 0.0,
        }]
        motion = {frame: (1.0 if 500 <= frame < 530 else 0.0) for frame in range(600)}

        highlights = scenedetect_sidecar.rank_highlight_candidates(
            scenes, motion, fps=10.0, duration=60.0,
            clip_length=6.0, top_n=1, min_gap=0.0)

        self.assertEqual(1, len(highlights))
        self.assertLessEqual(highlights[0]["start_frame"], 500)
        self.assertGreater(highlights[0]["end_frame"], 500)
        self.assertEqual("High visible motion", highlights[0]["reason"])

    def test_edl_uses_exact_source_frames_and_sequential_record_time(self) -> None:
        highlights = [
            {"rank": 1, "start_frame": 120, "end_frame": 180, "score": 90.0},
            {"rank": 2, "start_frame": 220, "end_frame": 250, "score": 70.0},
        ]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "highlights.edl"
            source = Path(temp) / "source.mp4"
            scenedetect_sidecar.write_highlight_edl(output, source, highlights, 10.0)
            text = output.read_text(encoding="utf-8")

        self.assertIn("00:00:12:00 00:00:18:00 00:00:00:00 00:00:06:00", text)
        self.assertIn("00:00:22:00 00:00:25:00 00:00:06:00 00:00:09:00", text)

    def test_otio_preserves_frame_rate_and_source_ranges(self) -> None:
        highlights = [{
            "rank": 1, "start_frame": 120, "end_frame": 180,
            "score": 90.0, "reason": "High motion",
        }]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "highlights.otio"
            source = Path(temp) / "source.mp4"
            scenedetect_sidecar.write_highlight_otio(output, source, highlights, 10.0)
            payload = json.loads(output.read_text(encoding="utf-8"))

        clip = payload["tracks"]["children"][0]["children"][0]
        self.assertEqual("Timeline.1", payload["OTIO_SCHEMA"])
        self.assertEqual(120, clip["source_range"]["start_time"]["value"])
        self.assertEqual(60, clip["source_range"]["duration"]["value"])
        self.assertEqual(10.0, clip["source_range"]["duration"]["rate"])

    def test_range_parser_rejects_ranges_past_source_duration(self) -> None:
        with self.assertRaises(ValueError):
            scenedetect_sidecar.parse_highlight_ranges(
                '[{"start": 5, "end": 12}]', fps=30.0, duration=10.0)

    def test_range_parser_rejects_inverted_explicit_frame_bounds(self) -> None:
        with self.assertRaises(ValueError):
            scenedetect_sidecar.parse_highlight_ranges(
                '[{"start_seconds": 1, "end_seconds": 2, "start_frame": 60, "end_frame": 30}]',
                fps=30.0, duration=10.0)

    def test_reel_command_concatenates_video_and_audio(self) -> None:
        highlights = [
            {"start_seconds": 1.0, "end_seconds": 3.0},
            {"start_seconds": 7.0, "end_seconds": 9.5},
        ]
        captured: list[str] = []
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.mp4"
            output = Path(temp) / "reel.mp4"
            source.write_bytes(b"source")

            def fake_run(command, *_args, **_kwargs):
                captured.extend(command)
                output.write_bytes(b"reel")
                return 0

            with mock.patch.object(scenedetect_sidecar, "find_ffmpeg", return_value="ffmpeg"), \
                    mock.patch.object(scenedetect_sidecar, "shared_run_ffmpeg", side_effect=fake_run):
                success, diagnostic = scenedetect_sidecar.extract_highlight_reel(
                    source, output, highlights, has_audio=True)

        self.assertTrue(success, diagnostic)
        graph = captured[captured.index("-filter_complex") + 1]
        self.assertIn("atrim=start=1.000000:end=3.000000", graph)
        self.assertIn("concat=n=2:v=1:a=1[outv][outa]", graph)


if __name__ == "__main__":
    unittest.main()
