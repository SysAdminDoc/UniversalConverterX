"""Closed-caption extraction/conversion coverage for the ccextract sidecar."""

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
SIDECAR_PATH = ROOT / "tools" / "ccextract" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ccextract", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


def _run(func, args) -> tuple[int, list[dict]]:
    parsed = SIDECAR.build_parser().parse_args(args)
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        code = func(parsed)
    events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    return code, events


_SCC = (
    "Scenarist_SCC V1.0\n\n"
    "00:00:01;00\t94ae 94ae 9420 9420 947a 947a 91b0 91b0 "
    "c8c5 4c4c cf21 942c 942c 942f 942f\n\n"
    "00:00:03;00\t942c 942c\n"
)


class CcExtractTests(unittest.TestCase):
    def test_missing_input_fails(self) -> None:
        code, events = _run(SIDECAR.op_detect, ["detect", "--input", "/no/file.mp4"])
        self.assertEqual(1, code)
        self.assertEqual("missing_input", events[-1]["code"])

    def test_scc_output_target_is_rejected(self) -> None:
        # FFmpeg has no CEA-608 encoder, so SCC must not be an output format.
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "in.srt"
            src.write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n", encoding="utf-8")
            code, events = _run(
                SIDECAR.op_convert,
                ["convert", "--input", str(src), "--output", str(Path(temp) / "o.scc"),
                 "--format", "scc"])
        self.assertEqual(1, code)
        self.assertEqual("bad_format", events[-1]["code"])

    def test_scc_input_converts_to_srt(self) -> None:
        if not SIDECAR._ffmpeg():
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as temp:
            scc = Path(temp) / "broadcast.scc"
            scc.write_text(_SCC, encoding="utf-8")
            out = Path(temp) / "out.srt"
            code, events = _run(
                SIDECAR.op_convert,
                ["convert", "--input", str(scc), "--output", str(out), "--format", "srt"])
            self.assertEqual(0, code, events)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 0)
            self.assertEqual("complete", events[-1]["event"])
            self.assertIn("-->", out.read_text(encoding="utf-8"))

    def test_detect_and_extract_embedded_track(self) -> None:
        ffmpeg = SIDECAR._ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as temp:
            scc = Path(temp) / "cap.scc"
            scc.write_text(_SCC, encoding="utf-8")
            video = Path(temp) / "withcc.mp4"
            gen = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc=duration=4:size=320x240:rate=30",
                 "-i", str(scc), "-map", "0:v", "-map", "1",
                 "-c:v", "libx264", "-c:s", "mov_text", str(video)],
                capture_output=True, text=True, timeout=90)
            if gen.returncode != 0 or not video.is_file():
                self.skipTest("FFmpeg could not synthesise a captioned test clip")

            code, events = _run(SIDECAR.op_detect, ["detect", "--input", str(video)])
            self.assertEqual(0, code, events)
            streams = [e for e in events if e["event"] == "stream"]
            self.assertGreaterEqual(len(streams), 1)

            out = Path(temp) / "extracted.srt"
            code, events = _run(
                SIDECAR.op_extract,
                ["extract", "--input", str(video), "--output", str(out), "--format", "srt"])
            self.assertEqual(0, code, events)
            self.assertTrue(out.is_file())
            self.assertIn("-->", out.read_text(encoding="utf-8"))

    def test_extract_without_captions_fails_cleanly(self) -> None:
        ffmpeg = SIDECAR._ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg is not installed")
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "plain.mp4"
            gen = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=30",
                 "-c:v", "libx264", str(video)],
                capture_output=True, text=True, timeout=60)
            if gen.returncode != 0:
                self.skipTest("FFmpeg could not synthesise a test clip")
            code, events = _run(
                SIDECAR.op_extract,
                ["extract", "--input", str(video), "--output", str(Path(temp) / "x.srt"),
                 "--format", "srt"])
            self.assertEqual(1, code)
            self.assertEqual("no_captions", events[-1]["code"])


if __name__ == "__main__":
    unittest.main()
