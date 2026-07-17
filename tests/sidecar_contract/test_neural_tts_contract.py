"""Focused contracts for the pinned offline neural-speech sidecars."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DIA = _load("ucx_test_dia2tts", "tools/dia2tts/sidecar.py")
CHATTERBOX = _load("ucx_test_chatterboxtts", "tools/chatterboxtts/sidecar.py")


class NeuralTtsContractTests(unittest.TestCase):
    def test_reviewed_asset_sets_are_exact_and_non_placeholder(self) -> None:
        self.assertEqual(11, len(DIA.DIA_ASSETS) + len(DIA.MIMI_ASSETS))
        self.assertEqual(8, len(CHATTERBOX.MODEL_ASSETS))
        self.assertEqual({"Apache-2.0"}, {asset.license for asset in DIA.DIA_ASSETS})
        self.assertEqual({"CC-BY-4.0"}, {asset.license for asset in DIA.MIMI_ASSETS})
        self.assertEqual({"MIT (Chatterbox and model weights)"}, {asset.license for asset in CHATTERBOX.MODEL_ASSETS})
        for asset in (*DIA.DIA_ASSETS, *DIA.MIMI_ASSETS, *CHATTERBOX.MODEL_ASSETS):
            self.assertEqual(64, len(asset.sha256))
            self.assertNotEqual("0" * 64, asset.sha256)
            self.assertIn("/resolve/", asset.url)
            self.assertNotIn("/main/", asset.url)

    def test_output_allocation_never_overwrites_an_existing_wav(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample_dia2.wav").write_bytes(b"existing")
            (root / "sample_chatterbox.wav").write_bytes(b"existing")
            dia = DIA._output_path(root, "sample", set())
            chatterbox = CHATTERBOX._output_path(root, "sample", set())
            self.assertEqual("sample_dia2-2.wav", dia.name)
            self.assertEqual("sample_chatterbox-2.wav", chatterbox.name)
            self.assertEqual(b"existing", (root / "sample_dia2.wav").read_bytes())
            self.assertEqual(b"existing", (root / "sample_chatterbox.wav").read_bytes())

    def test_staging_files_stay_beside_the_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            final = root / "speech.wav"
            for module in (DIA, CHATTERBOX):
                staging = module._staging_path(final)
                try:
                    self.assertEqual(root, staging.parent)
                    self.assertTrue(staging.name.endswith(".part.wav"))
                finally:
                    staging.unlink(missing_ok=True)

    def test_presets_expose_consent_and_offline_engines(self) -> None:
        dia = (ROOT / "presets/tts-dia2-dialogue.preset.xml").read_text(encoding="utf-8")
        chatterbox = (ROOT / "presets/tts-chatterbox-turbo-clone.preset.xml").read_text(encoding="utf-8")
        self.assertIn("<Engine>dia2tts</Engine>", dia)
        self.assertIn("<Engine>chatterboxtts</Engine>", chatterbox)
        self.assertIn("<Arg>--accept-voice-cloning</Arg>", chatterbox)

    def test_vendored_dia_loaders_are_local_only(self) -> None:
        context = (ROOT / "tools/dia2tts/vendor/dia2/runtime/context.py").read_text(encoding="utf-8")
        codec = (ROOT / "tools/dia2tts/vendor/dia2/audio/codec.py").read_text(encoding="utf-8")
        self.assertIn("trust_remote_code=False", context)
        self.assertIn("local_files_only=True", context)
        self.assertIn("local_files_only=True", codec)

    def test_chatterbox_batch_limit_accounts_for_separate_reference(self) -> None:
        source = (ROOT / "tools/chatterboxtts/sidecar.py").read_text(encoding="utf-8")
        self.assertIn("input_limit = 100 if args.reference else 101", source)
        self.assertIn("len(args.input) > input_limit", source)


if __name__ == "__main__":
    unittest.main()
