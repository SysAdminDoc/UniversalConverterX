"""Regression tests for offline spatial-audio conversion."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "spatialaudio" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("spatialaudio_sidecar", SIDECAR)
assert SPEC and SPEC.loader
spatial = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = spatial
SPEC.loader.exec_module(spatial)


class SpatialAudioTests(unittest.TestCase):
    def test_foa_binaural_uses_acn_sn3d_w_y_z_x_order(self) -> None:
        graph = spatial.foa_pan_graph("stereo")
        self.assertTrue(graph.startswith("pan=stereo|c0="))
        self.assertIn("0.7071*c0", graph)
        self.assertIn("0.4330*c3", graph)
        self.assertIn("+0.2500*c1", graph)
        self.assertIn("-0.2500*c1", graph)

    def test_foa_surround_matrices_expose_expected_layouts(self) -> None:
        five = spatial.foa_pan_graph("5.1")
        seven = spatial.foa_pan_graph("7.1")
        for label in ("FL=", "FR=", "FC=", "LFE=", "BL=", "BR="):
            self.assertIn(label, five)
        for label in ("SL=", "SR="):
            self.assertIn(label, seven)

    def test_sofalizer_requires_local_hrtf(self) -> None:
        with self.assertRaisesRegex(ValueError, "local --sofa"):
            spatial.filter_for_mode("surround-to-binaural")

    def test_output_codec_is_selected_by_extension(self) -> None:
        self.assertEqual(["-c:a", "flac"], spatial.codec_args(Path("out.flac")))
        self.assertIn("libopus", spatial.codec_args(Path("out.opus")))
        with self.assertRaisesRegex(ValueError, "extension"):
            spatial.codec_args(Path("out.xyz"))

    def test_conversion_rejects_non_foa_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "stereo.wav"
            source.write_bytes(b"RIFF")
            args = argparse.Namespace(
                input=str(source), output=str(root / "out.flac"),
                mode="foa-to-binaural", sofa=None,
            )
            info = {
                "streams": [{"codec_type": "audio", "channels": 2}],
                "format": {"duration": "1.0"},
            }
            captured = io.StringIO()
            with mock.patch.object(spatial, "find_ffmpeg", return_value="ffmpeg"), \
                    mock.patch.object(spatial, "find_ffprobe", return_value="ffprobe"), \
                    mock.patch.object(spatial, "probe_media", return_value=info), \
                    contextlib.redirect_stdout(captured):
                result = spatial.op_convert(args)

        event = json.loads(captured.getvalue().splitlines()[-1])
        self.assertEqual(1, result)
        self.assertEqual("invalid_channels", event["code"])


if __name__ == "__main__":
    unittest.main()
