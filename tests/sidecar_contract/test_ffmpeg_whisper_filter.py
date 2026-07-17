"""Focused tests for the FFmpeg 8.1 native whisper-filter sidecar."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "ffmpeg-whisper" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ffmpeg_whisper_sidecar", SIDECAR)
assert SPEC and SPEC.loader
ffmpeg_whisper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ffmpeg_whisper
SPEC.loader.exec_module(ffmpeg_whisper)


class FfmpegWhisperTests(unittest.TestCase):
    def test_probe_detects_native_filter(self) -> None:
        completed = subprocess.CompletedProcess(
            ["ffmpeg", "-filters"], 0,
            stdout=" .. whisper           A->A       Transcribe audio using whisper.cpp.\n",
            stderr="",
        )
        captured = io.StringIO()
        with mock.patch.object(ffmpeg_whisper, "find_ffmpeg", return_value="ffmpeg"), \
                mock.patch.object(ffmpeg_whisper.subprocess, "run", return_value=completed), \
                contextlib.redirect_stdout(captured):
            result = ffmpeg_whisper.op_probe(argparse.Namespace())

        events = [json.loads(line) for line in captured.getvalue().splitlines()]
        self.assertEqual(0, result)
        self.assertTrue(events[0]["available"])
        self.assertEqual("backend", events[0]["event"])

    def test_transcribe_uses_local_model_and_native_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "speech.wav"
            model = root / "ggml-base.bin"
            output = root / "speech.srt"
            source.write_bytes(b"RIFF-fake")
            model.write_bytes(b"gguf-fake")
            command: list[str] = []

            def fake_run(args, **_kwargs):
                command.extend(args)
                output.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            args = ffmpeg_whisper.build_parser().parse_args([
                "transcribe", "--input", str(source), "--output", str(output),
                "--model", str(model), "--language", "en", "--no-use-gpu",
            ])
            captured = io.StringIO()
            with mock.patch.object(ffmpeg_whisper, "find_ffmpeg", return_value="ffmpeg"), \
                    mock.patch.object(ffmpeg_whisper.subprocess, "run", side_effect=fake_run), \
                    contextlib.redirect_stdout(captured):
                result = ffmpeg_whisper.op_transcribe(args)

            events = [json.loads(line) for line in captured.getvalue().splitlines()]

        self.assertEqual(0, result)
        self.assertIn("-nostdin", command)
        filter_graph = command[command.index("-af") + 1]
        self.assertIn("whisper=model=", filter_graph)
        self.assertIn("language='en'", filter_graph)
        self.assertIn("format=srt", filter_graph)
        self.assertIn("use_gpu=false", filter_graph)
        self.assertEqual("complete", events[-1]["event"])

    def test_vtt_conversion_preserves_cues(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.srt"
            output = root / "output.vtt"
            source.write_text(
                "1\n00:00:01,250 --> 00:00:03,500\nHello\n", encoding="utf-8"
            )
            ffmpeg_whisper._srt_to_vtt(source, output)
            text = output.read_text(encoding="utf-8")

        self.assertTrue(text.startswith("WEBVTT\n\n"))
        self.assertIn("00:00:01.250 --> 00:00:03.500", text)

    def test_model_discovery_reuses_whisper_cpp_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            model_root = Path(temp)
            cache = model_root / "whisper-cpp"
            cache.mkdir()
            expected = cache / "ggml-small.bin"
            expected.write_bytes(b"model")
            with mock.patch.dict(os.environ, {"UCX_MODEL_DIR": str(model_root)}):
                resolved = ffmpeg_whisper.resolve_model("small")

        self.assertEqual(expected.resolve(), resolved)


if __name__ == "__main__":
    unittest.main()
