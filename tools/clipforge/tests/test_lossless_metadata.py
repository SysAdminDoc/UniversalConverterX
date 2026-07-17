import argparse
import importlib.util
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, mock


SIDECAR_PATH = Path(__file__).resolve().parents[1] / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ucx_clipforge_sidecar", SIDECAR_PATH)
sidecar = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(sidecar)

from clipforge_ops import metadata


class LosslessMetadataTests(TestCase):
    def test_ffmpeg_runner_drains_stderr_while_reading_progress(self):
        script = (
            "import sys; "
            "[print('diagnostic-' + ('x' * 200), file=sys.stderr) for _ in range(200)]; "
            "print('progress=end')"
        )
        emit = mock.Mock()
        result = sidecar.run_ffmpeg(
            [sys.executable, "-c", script], 1.0, "pipe smoke",
            event_emitter=emit)

        self.assertEqual(0, result)
        emit.assert_any_call(
            "progress", percent=100, stage="pipe smoke", eta_seconds=0)

    def test_aspect_ratio_parser_normalizes_and_rejects_invalid_values(self):
        self.assertEqual((16, 9), sidecar._parse_aspect_ratio(" 32:18 "))
        self.assertEqual((4, 3), sidecar._parse_aspect_ratio("4/3"))
        self.assertIsNone(sidecar._parse_aspect_ratio("16x9"))
        self.assertIsNone(sidecar._parse_aspect_ratio("0:9"))

    def test_crop_meta_uses_h264_bitstream_filter_without_encoder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.mp4"
            output_path = root / "output.mp4"
            input_path.write_bytes(b"input")
            commands = []

            def fake_run(command, *_args):
                commands.append(command)
                output_path.write_bytes(b"output")
                return 0

            source_probe = {
                "format": {"duration": "1"},
                "streams": [{
                    "codec_type": "video", "codec_name": "h264",
                    "width": 320, "height": 240,
                }],
            }
            output_probe = {
                "streams": [{
                    "codec_type": "video", "codec_name": "h264",
                    "width": 288, "height": 224,
                }],
            }
            args = argparse.Namespace(
                input=str(input_path), output=str(output_path),
                left=16, right=16, top=8, bottom=8,
            )
            with (
                mock.patch.object(metadata, "find_ffmpeg", return_value="ffmpeg"),
                mock.patch.object(metadata, "find_ffprobe", return_value="ffprobe"),
                mock.patch.object(metadata, "probe", side_effect=[source_probe, output_probe]),
                mock.patch.object(metadata, "run_ffmpeg", side_effect=fake_run),
            ):
                result = sidecar.op_crop_meta(args)

        self.assertEqual(0, result)
        self.assertEqual(1, len(commands))
        command = commands[0]
        self.assertIn("copy", command)
        self.assertNotIn("libx264", command)
        bsf = command[command.index("-bsf:v:0") + 1]
        self.assertEqual(
            "h264_metadata=crop_left=16:crop_right=16:crop_top=8:crop_bottom=8",
            bsf,
        )

    def test_crop_meta_rejects_unsupported_codec_before_running_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.webm"
            input_path.write_bytes(b"input")
            args = argparse.Namespace(
                input=str(input_path), output=str(input_path.with_name("output.webm")),
                left=2, right=2, top=0, bottom=0,
            )
            source_probe = {
                "format": {"duration": "1"},
                "streams": [{
                    "codec_type": "video", "codec_name": "vp9",
                    "width": 320, "height": 240,
                }],
            }
            with (
                mock.patch.object(metadata, "find_ffmpeg", return_value="ffmpeg"),
                mock.patch.object(metadata, "find_ffprobe", return_value="ffprobe"),
                mock.patch.object(metadata, "probe", return_value=source_probe),
                mock.patch.object(metadata, "run_ffmpeg") as run,
            ):
                result = sidecar.op_crop_meta(args)

        self.assertEqual(1, result)
        run.assert_not_called()

    def test_aspect_override_stream_copies_and_verifies_display_ratio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.mp4"
            output_path = root / "output.mp4"
            input_path.write_bytes(b"input")
            commands = []

            def fake_run(command, *_args):
                commands.append(command)
                output_path.write_bytes(b"output")
                return 0

            source_probe = {
                "format": {"duration": "1"},
                "streams": [{
                    "codec_type": "video", "codec_name": "h264",
                    "width": 320, "height": 240,
                }],
            }
            output_probe = {
                "streams": [{
                    "codec_type": "video", "codec_name": "h264",
                    "display_aspect_ratio": "16:9",
                }],
            }
            args = argparse.Namespace(
                input=str(input_path), output=str(output_path), aspect="16:9")
            with (
                mock.patch.object(metadata, "find_ffmpeg", return_value="ffmpeg"),
                mock.patch.object(metadata, "find_ffprobe", return_value="ffprobe"),
                mock.patch.object(metadata, "probe", side_effect=[source_probe, output_probe]),
                mock.patch.object(metadata, "run_ffmpeg", side_effect=fake_run),
            ):
                result = sidecar.op_aspect_override(args)

        self.assertEqual(0, result)
        command = commands[0]
        self.assertIn("copy", command)
        self.assertEqual("16:9", command[command.index("-aspect:v:0") + 1])


if __name__ == "__main__":
    import unittest
    unittest.main()
