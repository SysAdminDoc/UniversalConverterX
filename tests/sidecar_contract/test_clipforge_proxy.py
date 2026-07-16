"""Preview-proxy coverage for ClipForge (ROADMAP Item 74)."""

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
SPEC = importlib.util.spec_from_file_location("clipforge_proxy", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


def _run(args) -> tuple[int, list[dict]]:
    parsed = SIDECAR.build_parser().parse_args(args)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = SIDECAR.op_proxy(parsed)
    events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    return code, events


class ClipForgeProxyTests(unittest.TestCase):
    def test_missing_input_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            code, events = _run(
                ["proxy", "--input", str(Path(temp) / "nope.mp4"),
                 "--output", str(Path(temp) / "o.mp4")])
        self.assertEqual(1, code)
        self.assertEqual("missing_input", events[-1]["code"])

    def test_generates_downscaled_proxy(self) -> None:
        ffmpeg = SIDECAR.find_ffmpeg()
        ffprobe = SIDECAR.find_ffprobe()
        if not ffmpeg or not ffprobe:
            self.skipTest("FFmpeg/FFprobe not installed")
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "src720.mp4"
            gen = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc=duration=2:size=1280x720:rate=30",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
                capture_output=True, text=True, timeout=60)
            if gen.returncode != 0 or not src.is_file():
                self.skipTest("FFmpeg could not synthesise a test clip")

            out = Path(temp) / "proxy.mp4"
            code, events = _run(
                ["proxy", "--input", str(src), "--output", str(out), "--height", "480"])
            self.assertEqual(0, code, events)
            self.assertTrue(out.is_file())
            self.assertEqual("proxy", events[-2]["event"])
            self.assertEqual("complete", events[-1]["event"])

            height = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=height", "-of", "csv=p=0", str(out)],
                capture_output=True, text=True, timeout=30).stdout.strip()
            self.assertEqual("480", height)
            self.assertGreater(out.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
