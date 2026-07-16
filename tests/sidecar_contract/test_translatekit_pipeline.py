import argparse
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SIDECAR = ROOT / "tools" / "translatekit" / "sidecar.py"


def load_sidecar():
    spec = importlib.util.spec_from_file_location("translatekit_sidecar", SIDECAR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TranslateKitPipelineTests(unittest.TestCase):
    def test_helsinki_model_id_is_deterministic_and_validated(self):
        sidecar = load_sidecar()

        self.assertEqual(
            sidecar.helsinki_model_id("en", "es"),
            "Helsinki-NLP/opus-mt-en-es",
        )
        self.assertEqual(
            sidecar.helsinki_model_id("en", "ja"),
            "Helsinki-NLP/opus-mt-en-jap",
        )
        with self.assertRaises(ValueError):
            sidecar.helsinki_model_id("en;rm", "es")
        with self.assertRaises(ValueError):
            sidecar.helsinki_model_id("en", "en")

    def test_srt_translation_preserves_cue_numbers_and_timecodes(self):
        sidecar = load_sidecar()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "sample.srt"
            source.write_text(
                "1\n00:00:01,000 --> 00:00:02,500\nHello world\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\nSecond line\n",
                encoding="utf-8",
            )
            output = root / "out"
            args = argparse.Namespace(
                input=[str(source)],
                output_dir=str(output),
                source="en",
                target="es",
                model="opus-mt",
                device="cpu",
            )

            with mock.patch.object(sidecar, "_build_translator", return_value=lambda text: f"T:{text}"), \
                    redirect_stdout(io.StringIO()):
                result = sidecar.op_srt(args)

            self.assertEqual(result, 0)
            translated = (output / "sample.es.srt").read_text(encoding="utf-8")
            self.assertIn("00:00:01,000 --> 00:00:02,500", translated)
            self.assertIn("T:Hello world", translated)
            self.assertIn("T:Second line", translated)

    def test_opus_alias_routes_to_pair_specific_onnx_loader(self):
        sidecar = load_sidecar()
        args = argparse.Namespace(
            model="opus-mt",
            source="en",
            target="ja",
            device="cpu",
        )
        sentinel = object()

        with mock.patch.object(sidecar, "_load_helsinki_onnx", return_value=sentinel) as loader:
            result = sidecar._build_translator(args)

        self.assertIs(result, sentinel)
        loader.assert_called_once_with("Helsinki-NLP/opus-mt-en-jap", "cpu")


if __name__ == "__main__":
    unittest.main()
