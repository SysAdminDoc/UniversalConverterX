"""Regression tests for Track Manager per-audio-stream timestamp offsets."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CLIPFORGE = ROOT / "tools" / "clipforge"
sys.path.insert(0, str(CLIPFORGE))
from clipforge_ops import tracks  # noqa: E402


STREAMS = [
    {"index": 0, "codec_type": "video"},
    {"index": 1, "codec_type": "audio"},
    {"index": 2, "codec_type": "audio"},
    {"index": 3, "codec_type": "subtitle"},
]


class ClipforgeTrackDelayTests(unittest.TestCase):
    def test_delay_parser_accepts_advance_and_delay(self) -> None:
        self.assertEqual({1: 250, 2: -80}, tracks.parse_track_delays("1=250, 2=-80"))
        with self.assertRaisesRegex(ValueError, "between"):
            tracks.parse_track_delays("1=600001")
        with self.assertRaisesRegex(ValueError, "stream=milliseconds"):
            tracks.parse_track_delays("1:250")

    def test_command_maps_each_delayed_audio_from_its_own_offset_input(self) -> None:
        command = tracks.build_track_edit_command(
            "ffmpeg", Path("source.mkv"), Path("output.mkv"),
            STREAMS, {3}, {1: 250, 2: -80},
        )

        self.assertEqual(2, command.count("-itsoffset"))
        self.assertIn("0.250", command)
        self.assertIn("-0.080", command)
        mappings = [command[index + 1] for index, value in enumerate(command) if value == "-map"]
        self.assertEqual(["0:0", "1:1", "2:2"], mappings)
        self.assertNotIn("0:3", mappings)
        self.assertIn("-c", command)
        self.assertIn("copy", command)

    def test_track_edit_rejects_delay_on_non_audio_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.mkv"
            source.write_bytes(b"container")
            args = argparse.Namespace(
                input=str(source), output=str(Path(temp) / "out.mkv"),
                remove="", delays="0=100",
            )
            captured = io.StringIO()
            info = {"streams": STREAMS, "format": {"duration": "2.0"}}
            with mock.patch.object(tracks, "find_ffmpeg", return_value="ffmpeg"), \
                    mock.patch.object(tracks, "find_ffprobe", return_value="ffprobe"), \
                    mock.patch.object(tracks, "probe", return_value=info), \
                    contextlib.redirect_stdout(captured):
                result = tracks.op_track_edit(args)

        event = json.loads(captured.getvalue().splitlines()[-1])
        self.assertEqual(1, result)
        self.assertEqual("not_audio", event["code"])

    def test_track_edit_reports_applied_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mkv"
            output = root / "output.mkv"
            source.write_bytes(b"container")
            args = argparse.Namespace(
                input=str(source), output=str(output), remove="3", delays="1=125",
            )
            captured = io.StringIO()
            info = {"streams": STREAMS, "format": {"duration": "2.0"}}

            def fake_run(_command, _duration, _stage):
                output.write_bytes(b"remuxed")
                return 0

            with mock.patch.object(tracks, "find_ffmpeg", return_value="ffmpeg"), \
                    mock.patch.object(tracks, "find_ffprobe", return_value="ffprobe"), \
                    mock.patch.object(tracks, "probe", return_value=info), \
                    mock.patch.object(tracks, "run_ffmpeg", side_effect=fake_run), \
                    contextlib.redirect_stdout(captured):
                result = tracks.op_track_edit(args)

        event = json.loads(captured.getvalue().splitlines()[-1])
        self.assertEqual(0, result)
        self.assertEqual([3], event["removed"])
        self.assertEqual({"1": 125}, event["delays_ms"])


if __name__ == "__main__":
    unittest.main()
