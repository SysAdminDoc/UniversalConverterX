import argparse
import importlib.util
import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock


SIDECAR_PATH = Path(__file__).resolve().parents[1] / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ucx_videocrush_sidecar", SIDECAR_PATH)
sidecar = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(sidecar)


class TargetSizeTests(TestCase):
    def test_ndjson_output_is_safe_for_legacy_windows_code_pages(self):
        output = io.StringIO()

        with mock.patch.object(sidecar.sys, "stdout", output):
            sidecar.emit("log", level="info", message="9.5 MB \u2192 1200 kbps \U0001f3ac")

        encoded = output.getvalue().encode("ascii")
        payload = json.loads(encoded)
        self.assertEqual("9.5 MB \u2192 1200 kbps \U0001f3ac", payload["message"])

    def test_social_presets_reserve_muxing_headroom(self):
        expected = {
            "discord-10mb": 9.5,
            "discord-25mb": 23.75,
            "discord-50mb": 47.5,
            "email-25mb": 23.75,
        }

        for name, target_mb in expected.items():
            preset = sidecar.PRESETS[name]
            self.assertEqual(target_mb, preset["target_mb"])
            self.assertEqual("libx264", preset["codec"])
            self.assertLess(target_mb, float(name.split("-")[-1].removesuffix("mb")))

    def test_apv_presets_cover_delivery_and_intermediate_targets(self):
        expected = {
            "apv-to-h265": ("libx265", "yuv420p10le"),
            "apv-to-prores-422-hq": ("prores_ks", None),
            "apv-to-h264": ("libx264", "yuv420p"),
        }

        for name, (codec, pixel_format) in expected.items():
            preset = sidecar.PRESETS[name]
            self.assertEqual(codec, preset["codec"])
            self.assertEqual(pixel_format, preset.get("pixel_format"))

    def test_apv_prores_preset_does_not_require_lossy_quality_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.apv"
            output_path = root / "output.mov"
            input_path.write_bytes(b"aPv1")
            commands = []

            def fake_run(command, *_args):
                commands.append(command)
                output_path.write_bytes(b"output")
                return 0

            args = argparse.Namespace(
                input=str(input_path),
                output=str(output_path),
                preset="apv-to-prores-422-hq",
                target_mb=None,
                crf=None,
                codec=None,
                ffmpeg_preset=None,
                resolution=None,
                audio_codec=None,
                audio_bitrate=None,
                audio_vbr_quality=None,
                hwaccel="none",
                max_bitrate=None,
                prores_profile=None,
                dnxhd_profile=None,
            )
            # Raw RFC 9924 elementary streams have no container duration.
            probe = {"format": {}, "streams": [{"codec_name": "apv"}]}
            with (
                mock.patch.object(sidecar, "find_ffmpeg", return_value="ffmpeg"),
                mock.patch.object(sidecar, "find_ffprobe", return_value="ffprobe"),
                mock.patch.object(sidecar, "probe", return_value=probe),
                mock.patch.object(sidecar, "run_ffmpeg", side_effect=fake_run),
            ):
                result = sidecar.compress(args)

        self.assertEqual(0, result)
        self.assertEqual(1, len(commands))
        self.assertIn("prores_ks", commands[0])
        self.assertIn("yuv422p10le", commands[0])
        self.assertEqual(0, commands[0][1:].count("-t"))

    def test_target_mode_uses_two_pass_bitrate_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.mp4"
            output_path = root / "output.mp4"
            input_path.write_bytes(b"input")
            commands = []

            def fake_run(command, *_args):
                commands.append(command)
                if command[command.index("-pass") + 1] == "2":
                    output_path.write_bytes(b"output")
                return 0

            args = argparse.Namespace(
                input=str(input_path),
                output=str(output_path),
                preset="discord-10mb",
                target_mb=None,
                crf=None,
                codec=None,
                ffmpeg_preset=None,
                resolution=None,
                audio_codec=None,
                audio_bitrate=None,
                audio_vbr_quality=None,
                hwaccel="none",
                max_bitrate=None,
                prores_profile=None,
                dnxhd_profile=None,
            )
            probe = {"format": {"duration": "60"}, "streams": []}
            with (
                mock.patch.object(sidecar, "find_ffmpeg", return_value="ffmpeg"),
                mock.patch.object(sidecar, "find_ffprobe", return_value="ffprobe"),
                mock.patch.object(sidecar, "probe", return_value=probe),
                mock.patch.object(sidecar, "run_ffmpeg", side_effect=fake_run),
                mock.patch.object(sidecar, "cleanup_pass_logs"),
            ):
                result = sidecar.compress(args)

        self.assertEqual(0, result)
        self.assertEqual(2, len(commands))
        self.assertEqual("1", commands[0][commands[0].index("-pass") + 1])
        self.assertEqual("2", commands[1][commands[1].index("-pass") + 1])
        expected_video_kbps = int(((9.5 * 8 * 1024 * 1024) - (96_000 * 60)) / 60 / 1000)
        self.assertIn(f"{expected_video_kbps}k", commands[0])
