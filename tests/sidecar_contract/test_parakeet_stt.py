#!/usr/bin/env python3
"""Dependency-free contract tests for the Parakeet TDT sidecar."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "parakeet-stt" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("parakeet_stt_sidecar", SIDECAR)
assert SPEC and SPEC.loader
parakeet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parakeet)


class ParakeetSttTests(unittest.TestCase):
    def test_model_directory_appends_stable_slug(self):
        with tempfile.TemporaryDirectory() as temp:
            result = parakeet.resolve_model_dir(temp)

        self.assertEqual(parakeet.MODEL_SLUG, result.name)

    def test_download_requires_explicit_license_acceptance(self):
        output = io.StringIO()
        args = argparse.Namespace(accept_license=False, model_dir=None)

        with contextlib.redirect_stdout(output):
            result = parakeet.download_model(args)

        event = json.loads(output.getvalue())
        self.assertEqual(1, result)
        self.assertEqual("license_acceptance_required", event["code"])

    def test_word_timestamps_group_into_readable_cues(self):
        words = [
            {"text": "Hello", "timestamp": (0.0, 0.4)},
            {"text": "world.", "timestamp": (0.5, 1.0)},
            {"text": "Next", "timestamp": (1.2, 1.5)},
            {"text": "cue", "timestamp": (1.6, 2.0)},
        ]

        segments = parakeet.words_to_segments(words)

        self.assertEqual(2, len(segments))
        self.assertEqual("Hello world.", segments[0]["text"])
        self.assertEqual((1.2, 2.0), (segments[1]["start"], segments[1]["end"]))

    def test_rendered_srt_and_vtt_have_timestamp_parity(self):
        segments = [{"start": 1.25, "end": 2.5, "text": "Ready."}]

        srt = parakeet.render_segments(segments, "srt")
        vtt = parakeet.render_segments(segments, "vtt")

        self.assertIn("00:00:01,250 --> 00:00:02,500", srt)
        self.assertIn("00:00:01.250 --> 00:00:02.500", vtt)
        self.assertTrue(vtt.startswith("WEBVTT\n"))

    def test_supported_language_catalog_matches_multilingual_model(self):
        self.assertEqual(26, len(parakeet.SUPPORTED_LANGUAGES))
        self.assertTrue({"auto", "en", "es", "uk", "mt"} <= parakeet.SUPPORTED_LANGUAGES)
        self.assertNotIn("ja", parakeet.SUPPORTED_LANGUAGES)

    def test_transcribe_writes_srt_through_local_only_cuda_path(self):
        case = self

        class FakeProcessor:
            tokenizer = object()
            feature_extractor = object()

        class FakeAutoProcessor:
            @staticmethod
            def from_pretrained(_path, **kwargs):
                case.assertTrue(kwargs["local_files_only"])
                return FakeProcessor()

        class FakeModel:
            def to(self, device):
                case.assertEqual("cuda", device)
                return self

            def eval(self):
                return self

        class FakeAutoModel:
            @staticmethod
            def from_pretrained(_path, **kwargs):
                case.assertTrue(kwargs["local_files_only"])
                return FakeModel()

        torch = types.ModuleType("torch")
        torch.float16 = "float16"
        torch.bfloat16 = "bfloat16"
        torch.cuda = types.SimpleNamespace(
            is_available=lambda: True,
            is_bf16_supported=lambda: False,
        )
        transformers = types.ModuleType("transformers")
        transformers.AutoProcessor = FakeAutoProcessor
        transformers.AutoModelForTDT = FakeAutoModel
        transformers.pipeline = lambda *_args, **_kwargs: (
            lambda *_call_args, **_call_kwargs: {
                "text": "Hello world.",
                "chunks": [
                    {"text": "Hello", "timestamp": (0.0, 0.4)},
                    {"text": "world.", "timestamp": (0.5, 1.0)},
                ],
            }
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model_dir = root / parakeet.MODEL_SLUG
            model_dir.mkdir()
            for name in parakeet.REQUIRED_MODEL_FILES:
                (model_dir / name).touch()
            source = root / "input.wav"
            source.touch()
            output = root / "output.srt"
            args = argparse.Namespace(
                input=str(source), output=str(output), format="srt",
                language="auto", word_timestamps=False,
                model_dir=str(model_dir), chunk_seconds=600,
            )

            with patch.dict(sys.modules, {"torch": torch, "transformers": transformers}), \
                    patch.object(parakeet, "convert_to_pcm", return_value=(True, "")), \
                    patch.object(parakeet, "load_pcm", return_value=[0.0] * 16000), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = parakeet.transcribe(args)

            self.assertEqual(0, result)
            self.assertIn("00:00:00,000 --> 00:00:01,000", output.read_text(encoding="utf-8"))
            self.assertIn("Hello world.", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
