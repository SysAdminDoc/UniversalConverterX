"""Regression tests for auto-detected frame-rate-doubling deinterlace."""

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
from clipforge_ops import video  # noqa: E402


class ClipforgeDeinterlaceTests(unittest.TestCase):
    def test_field_order_detection_uses_first_video_stream(self) -> None:
        info = {"streams": [
            {"codec_type": "audio"},
            {"codec_type": "video", "field_order": "tt"},
        ]}
        self.assertEqual("tt", video.detected_field_order(info))
        self.assertEqual("unknown", video.detected_field_order({"streams": []}))

    def test_double_rate_uses_one_progressive_frame_per_field(self) -> None:
        command, interlaced, mode = video.build_deinterlace_command(
            "ffmpeg", Path("input.mkv"), Path("output.mkv"),
            field_order="tb", filter_name="bwdif", rate="double",
            codec="libx264", crf=18, preset="medium",
        )
        self.assertTrue(interlaced)
        self.assertEqual("double-rate", mode)
        self.assertEqual(
            "bwdif=mode=send_field:parity=auto:deint=interlaced",
            command[command.index("-vf") + 1],
        )
        self.assertIn("copy", command)

    def test_single_rate_override_uses_send_frame(self) -> None:
        self.assertEqual(
            "yadif=mode=send_frame:parity=auto:deint=interlaced",
            video.build_deinterlace_filter("yadif", "single"),
        )

    def test_progressive_same_container_is_stream_copied(self) -> None:
        command, interlaced, mode = video.build_deinterlace_command(
            "ffmpeg", Path("input.mkv"), Path("output.mkv"),
            field_order="progressive", filter_name="bwdif", rate="double",
            codec="libx264", crf=18, preset="medium",
        )
        self.assertFalse(interlaced)
        self.assertEqual("copy-progressive", mode)
        self.assertNotIn("-vf", command)
        self.assertIn("copy", command)

    def test_operation_reports_detected_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mkv"
            output = root / "output.mkv"
            source.write_bytes(b"container")
            args = argparse.Namespace(
                input=str(source), output=str(output), filter="bwdif",
                rate="double", codec="libx264", crf=18, preset="medium",
            )
            info = {
                "streams": [{"index": 0, "codec_type": "video", "field_order": "tt"}],
                "format": {"duration": "2.0"},
            }
            captured = io.StringIO()

            def fake_run(_command, _duration, _stage):
                output.write_bytes(b"progressive")
                return 0

            with mock.patch.object(video, "find_ffmpeg", return_value="ffmpeg"), \
                    mock.patch.object(video, "find_ffprobe", return_value="ffprobe"), \
                    mock.patch.object(video, "probe", return_value=info), \
                    mock.patch.object(video, "run_ffmpeg", side_effect=fake_run), \
                    contextlib.redirect_stdout(captured):
                result = video.op_deinterlace(args)

        event = json.loads(captured.getvalue().splitlines()[-1])
        self.assertEqual(0, result)
        self.assertEqual("double-rate", event["mode"])
        self.assertTrue(event["interlaced"])


if __name__ == "__main__":
    unittest.main()
