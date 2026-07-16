"""Keyframe-listing coverage for ClipForge (lossless-cut snapping backend)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "clipforge" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("clipforge_keyframes", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


def _run(args: list[str]) -> tuple[int, list[dict]]:
    parsed = SIDECAR.build_parser().parse_args(args)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = SIDECAR.op_keyframes(parsed)
    events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    return code, events


class ClipForgeKeyframesTests(unittest.TestCase):
    def test_missing_input_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            code, events = _run(["keyframes", "--input", str(Path(temp) / "nope.mp4")])
        self.assertEqual(1, code)
        self.assertEqual("missing_input", events[-1]["code"])

    def test_lists_keyframes_at_gop_boundaries(self) -> None:
        ffmpeg = SIDECAR.find_ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "gop.mp4"
            gen = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=30",
                 "-g", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
                capture_output=True, text=True, timeout=60)
            if gen.returncode != 0 or not src.is_file():
                self.skipTest("FFmpeg could not synthesise a test clip")
            code, events = _run(["keyframes", "--input", str(src)])
            self.assertEqual(0, code, events)
            kf = next(e for e in events if e["event"] == "keyframes")
            # A 30-frame GOP at 30 fps yields a keyframe every second.
            self.assertGreaterEqual(kf["count"], 4)
            self.assertEqual(kf["timestamps"], sorted(kf["timestamps"]))
            self.assertEqual(kf["timestamps"][0], 0.0)
            self.assertEqual("complete", events[-1]["event"])


if __name__ == "__main__":
    unittest.main()
