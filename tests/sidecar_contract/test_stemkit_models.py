#!/usr/bin/env python3
"""Regression tests for the curated stemkit model catalog and UI-facing flags."""

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
SPEC = importlib.util.spec_from_file_location(
    "stemkit_sidecar", ROOT / "tools" / "stemkit" / "sidecar.py"
)
assert SPEC and SPEC.loader
STEMKIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STEMKIT)


class FakeSeparator:
    instances: list["FakeSeparator"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.loaded_model = None
        self.__class__.instances.append(self)

    def load_model(self, model_filename=None):
        self.loaded_model = model_filename

    def separate(self, _source):
        output = Path(self.kwargs["output_dir"]) / "vocals.wav"
        output.write_bytes(b"RIFF-fake-stem")
        return [str(output)]

    def list_supported_model_files(self):
        return {"MDXC": {"BS-RoFormer SW": "BS-Roformer-SW.ckpt"}}


def fake_audio_separator_modules() -> dict[str, types.ModuleType]:
    package = types.ModuleType("audio_separator")
    separator = types.ModuleType("audio_separator.separator")
    separator.Separator = FakeSeparator
    package.separator = separator
    return {
        "audio_separator": package,
        "audio_separator.separator": separator,
    }


class StemkitModelTests(unittest.TestCase):
    def setUp(self):
        FakeSeparator.instances.clear()

    def test_defaults_cover_mel_vocals_and_bs_roformer_six_stem(self):
        self.assertEqual("vocals-roformer", STEMKIT.DEFAULT_MODEL_ALIAS)
        self.assertEqual("BS-Roformer-SW.ckpt", STEMKIT.ALIASES["bs-roformer-sw"])
        self.assertEqual(
            "vocals_mel_band_roformer.ckpt", STEMKIT.ALIASES["vocals-roformer"]
        )
        self.assertEqual(
            "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            STEMKIT.ALIASES["vocals-roformer-viperx"],
        )
        self.assertEqual("htdemucs_ft.yaml", STEMKIT.ALIASES["4stem"])
        self.assertEqual("htdemucs_6s.yaml", STEMKIT.ALIASES["6stem"])

    def test_parser_defaults_to_roformer_two_stem(self):
        args = STEMKIT.build_parser().parse_args(
            ["separate", "--input", "song.wav", "--output-dir", "out"]
        )

        self.assertEqual("vocals-roformer", args.model)
        self.assertEqual("2stem", args.stems)
        self.assertEqual(0, args.shifts)

    def test_vocals_only_is_forwarded_with_demucs_quality_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "song.wav"
            source.write_bytes(b"RIFF-fake-input")
            args = argparse.Namespace(
                input=[str(source)],
                output_dir=str(root / "out"),
                model="vocals-roformer",
                stems="vocals",
                shifts=2,
                format="wav",
            )
            stdout = io.StringIO()

            with patch.dict(sys.modules, fake_audio_separator_modules()), contextlib.redirect_stdout(stdout):
                result = STEMKIT.op_separate(args)

        self.assertEqual(0, result)
        separator = FakeSeparator.instances[-1]
        self.assertEqual("vocals_mel_band_roformer.ckpt", separator.loaded_model)
        self.assertEqual("Vocals", separator.kwargs["output_single_stem"])
        self.assertEqual(2, separator.kwargs["demucs_params"]["shifts"])
        events = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertTrue(any(event["event"] == "complete" for event in events))

    def test_bs_roformer_sw_is_reserved_for_six_stem_runs(self):
        self.assertEqual(
            "vocals-roformer", STEMKIT.resolve_model_alias("bs-roformer-sw", "2stem")
        )
        self.assertEqual(
            "bs-roformer-sw", STEMKIT.resolve_model_alias("bs-roformer-sw", "6stem")
        )

    def test_model_listing_includes_family_and_stems_metadata(self):
        stdout = io.StringIO()
        with patch.dict(sys.modules, fake_audio_separator_modules()), contextlib.redirect_stdout(stdout):
            result = STEMKIT.op_models(argparse.Namespace())

        self.assertEqual(0, result)
        event = next(
            json.loads(line)
            for line in stdout.getvalue().splitlines()
            if json.loads(line)["event"] == "stem_models"
        )
        alias = next(item for item in event["aliases"] if item["alias"] == "bs-roformer-sw")
        self.assertEqual("BS-RoFormer", alias["family"])
        self.assertIn("guitar", alias["stems"])


if __name__ == "__main__":
    unittest.main()
