"""Command, validation, and atomicity tests for the IAMF bridge."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("iamf_sidecar", ROOT / "tools" / "iamf" / "sidecar.py")
assert SPEC and SPEC.loader
iamf = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = iamf
SPEC.loader.exec_module(iamf)


def iamf_payload(profile: str) -> dict[str, object]:
    streams = [{"channels": 2, "channel_layout": "stereo"}]
    if profile == "scalable-5.1":
        streams = [
            {"channels": 2, "channel_layout": "stereo"},
            {"channels": 2, "channel_layout": "stereo"},
            {"channels": 1, "channel_layout": "mono"},
            {"channels": 1, "channel_layout": "mono"},
        ]
    return {
        "streams": streams,
        "stream_groups": [
            {"type": "IAMF Audio Element"},
            {"type": "IAMF Mix Presentation"},
        ],
        "format": {"duration": "2.0"},
    }


class IamfTests(unittest.TestCase):
    def test_stereo_encode_command_builds_two_stream_groups(self) -> None:
        command = iamf.build_encode_command("ffmpeg.exe", Path("in.wav"), Path("out.iamf"), "stereo")
        self.assertEqual(2, command.count("-stream_group"))
        self.assertIn(iamf.STEREO_AUDIO_GROUP, command)
        self.assertIn(iamf.STEREO_MIX_GROUP, command)
        self.assertIn("libopus", command)

    def test_surround_encode_splits_standard_six_channel_input(self) -> None:
        command = iamf.build_encode_command("ffmpeg.exe", Path("in.wav"), Path("out.iamf"), "scalable-5.1")
        self.assertIn(iamf.SURROUND_SPLIT, command)
        self.assertEqual(4, command.count("-map"))
        self.assertIn(iamf.SURROUND_AUDIO_GROUP, command)
        self.assertEqual(["0:0", "1:1", "2:2", "3:3"], [command[index + 1] for index, item in enumerate(command) if item == "-streamid"])

    def test_profile_requires_audio_and_mix_groups(self) -> None:
        self.assertEqual("stereo", iamf._iamf_profile(iamf_payload("stereo")))
        self.assertEqual("scalable-5.1", iamf._iamf_profile(iamf_payload("scalable-5.1")))
        malformed = iamf_payload("stereo")
        malformed["stream_groups"] = [{"type": "IAMF Audio Element"}]
        self.assertIsNone(iamf._iamf_profile(malformed))

    def test_package_maps_every_substream_and_both_groups(self) -> None:
        command = iamf.build_package_command("ffmpeg.exe", Path("in.iamf"), Path("out.mp4"), 4)
        self.assertIn("0:a", command)
        self.assertIn("map=0=0:st=0:st=1:st=2:st=3", command)
        self.assertIn("map=0=1:stg=0", command)
        self.assertIn("copy", command)

    def test_surround_render_rejoins_channels_in_51_side_order(self) -> None:
        command = iamf.build_render_command(
            "ffmpeg.exe", Path("in.iamf"), Path("out.flac"), "scalable-5.1", "5.1",
        )
        self.assertIn(iamf.SURROUND_JOIN, command)
        self.assertIn("[out]", command)
        self.assertIn("flac", command)

    def test_stereo_render_uses_base_layer(self) -> None:
        command = iamf.build_render_command(
            "ffmpeg.exe", Path("in.iamf"), Path("out.wav"), "scalable-5.1", "stereo",
        )
        self.assertNotIn("-filter_complex", command)
        self.assertEqual("0:a:0", command[command.index("-map") + 1])
        self.assertIn("pcm_s24le", command)

    def test_failed_encode_does_not_replace_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "in.wav"; source.write_bytes(b"audio")
            output = root / "out.iamf"; output.write_bytes(b"old")
            args = argparse.Namespace(input=str(source), output=str(output), profile="stereo", overwrite=True)
            media = {"streams": [{"codec_type": "audio", "channels": 2}], "format": {"duration": "1"}}
            with mock.patch.object(iamf, "find_ffmpeg", return_value="ffmpeg.exe"), \
                    mock.patch.object(iamf, "find_ffprobe", return_value="ffprobe.exe"), \
                    mock.patch.object(iamf, "probe_media", return_value=media), \
                    mock.patch.object(iamf, "run_ffmpeg", return_value=1):
                result = iamf.op_encode(args)
            self.assertEqual(1, result)
            self.assertEqual(b"old", output.read_bytes())

    def test_presets_cover_create_package_and_render(self) -> None:
        names = {path.name for path in (ROOT / "presets").glob("iamf-*.preset.xml")}
        self.assertEqual({
            "iamf-create-stereo.preset.xml", "iamf-create-scalable-5.1.preset.xml",
            "iamf-package-mp4.preset.xml", "iamf-render-stereo.preset.xml",
            "iamf-render-5.1.preset.xml",
        }, names)


if __name__ == "__main__":
    unittest.main()
