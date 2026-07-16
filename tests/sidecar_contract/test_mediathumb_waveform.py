"""Waveform preview coverage for the mediathumb sidecar."""

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
SIDECAR_PATH = ROOT / "tools" / "mediathumb" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("mediathumb_waveform", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


def _run(args: list[str]) -> tuple[int, list[dict]]:
    parsed = SIDECAR.build_parser().parse_args(args)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = SIDECAR.op_waveform(parsed)
    events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    return code, events


class MediathumbWaveformTests(unittest.TestCase):
    def test_missing_input_fails_before_touching_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            code, events = _run([
                "waveform",
                "--input", str(Path(temp) / "does-not-exist.wav"),
                "--output", str(Path(temp) / "out.png"),
            ])
        self.assertEqual(1, code)
        self.assertEqual("missing_input", events[-1]["code"])

    def test_injection_in_colour_is_sanitised_to_hex_default(self) -> None:
        # A non-hex colour must never reach the FFmpeg filter string verbatim.
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "clip.wav"
            src.write_bytes(b"not really audio")
            out = Path(temp) / "wave.png"
            args = SIDECAR.build_parser().parse_args([
                "waveform", "--input", str(src), "--output", str(out),
                "--color", "bad;rm -rf /",
            ])
            captured: dict[str, list[str]] = {}
            real_run = subprocess.run

            def _capture(cmd, *a, **kw):
                captured["cmd"] = cmd
                # Force the "no waveform produced" path without a real encode.
                return subprocess.CompletedProcess(cmd, 1, "", "")

            subprocess.run = _capture  # type: ignore[assignment]
            try:
                SIDECAR.op_waveform(args)
            finally:
                subprocess.run = real_run  # type: ignore[assignment]

        if not captured:
            self.skipTest("FFmpeg not present; colour sanitisation path not exercised")
        joined = " ".join(captured["cmd"])
        self.assertNotIn("rm -rf", joined)
        self.assertIn("colors=#8AADF4", joined)

    def test_generates_png_for_real_audio(self) -> None:
        ffmpeg = SIDECAR._which("ffmpeg")
        if not ffmpeg:
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "tone.wav"
            gen = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(src)],
                capture_output=True, text=True, timeout=60)
            if gen.returncode != 0 or not src.is_file():
                self.skipTest("FFmpeg could not synthesise a test tone")
            out = Path(temp) / "wave.png"
            code, events = _run([
                "waveform", "--input", str(src), "--output", str(out),
                "--width", "320", "--height", "80",
            ])
            self.assertEqual(0, code, events)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 0)
            self.assertEqual("complete", events[-1]["event"])
            self.assertEqual(b"\x89PNG", out.read_bytes()[:4])


if __name__ == "__main__":
    unittest.main()
