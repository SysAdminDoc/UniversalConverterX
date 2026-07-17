"""Regression tests for the unified mixed-input OCR router."""

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
SIDECAR = ROOT / "tools" / "ocrkit" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("ocrkit_sidecar", SIDECAR)
assert SPEC and SPEC.loader
ocrkit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ocrkit
SPEC.loader.exec_module(ocrkit)


class FakeProcess:
    def __init__(self, lines: list[str], return_code: int = 0):
        self.stdout = iter(lines)
        self.return_code = return_code

    def wait(self) -> int:
        return self.return_code


class OcrkitRouterTests(unittest.TestCase):
    def test_source_checkout_locates_both_child_engines(self) -> None:
        self.assertIsNotNone(ocrkit.locate_engine("ocr"))
        self.assertIsNotNone(ocrkit.locate_engine("pdfocr"))

    def test_mixed_batch_routes_images_and_pdfs_with_shared_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "scan.png"
            pdf = root / "scan.pdf"
            image.write_bytes(b"image")
            pdf.write_bytes(b"%PDF")
            args = ocrkit.build_parser().parse_args([
                "recognize", "--input", str(image), str(pdf),
                "--output-dir", str(root / "out"), "--lang", "eng+fra",
                "--clean",
            ])
            calls: list[tuple[list[str], float, float]] = []

            def fake_child(_prefix, child_args, *, start_percent, end_percent):
                calls.append((child_args, start_percent, end_percent))
                return True, None

            with mock.patch.object(ocrkit, "locate_engine", side_effect=lambda name: [name]), \
                    mock.patch.object(ocrkit, "run_child", side_effect=fake_child):
                result = ocrkit.op_recognize(args)

        self.assertEqual(0, result)
        self.assertEqual(2, len(calls))
        self.assertIn(str(image), calls[0][0])
        self.assertIn("--format", calls[0][0])
        self.assertNotIn(str(pdf), calls[0][0])
        self.assertIn(str(pdf), calls[1][0])
        self.assertIn("pdfa-2", calls[1][0])
        self.assertIn("--deskew", calls[1][0])
        self.assertIn("--rotate-pages", calls[1][0])
        self.assertIn("--clean", calls[1][0])
        self.assertEqual((0.0, 50.0), calls[0][1:])
        self.assertEqual((50.0, 100.0), calls[1][1:])

    def test_child_progress_is_scaled_to_pipeline_range(self) -> None:
        process = FakeProcess([
            json.dumps({"event": "progress", "percent": 50, "stage": "ocr"}) + "\n",
            json.dumps({"event": "complete", "count": 1}) + "\n",
        ])
        captured = io.StringIO()
        with mock.patch.object(ocrkit.subprocess, "Popen", return_value=process), \
                contextlib.redirect_stdout(captured):
            success, error = ocrkit.run_child(
                ["ocr"], ["recognize"], start_percent=25, end_percent=75
            )

        events = [json.loads(line) for line in captured.getvalue().splitlines()]
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(50.0, events[0]["percent"])
        self.assertEqual(1, len(events))

    def test_child_probe_requires_successful_available_event(self) -> None:
        ready = mock.Mock(
            returncode=0,
            stdout=json.dumps({"event": "complete", "available": True}) + "\n",
        )
        blocked = mock.Mock(
            returncode=1,
            stdout=json.dumps({"event": "complete", "available": False}) + "\n",
        )
        with mock.patch.object(ocrkit.subprocess, "run", side_effect=[ready, blocked]):
            self.assertTrue(ocrkit.probe_child(["ocr"]))
            self.assertFalse(ocrkit.probe_child(["pdfocr"]))

    def test_unsupported_input_is_rejected_before_child_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "notes.docx"
            source.write_bytes(b"docx")
            args = argparse.Namespace(
                input=[str(source)], output_dir=str(Path(temp) / "out"),
                lang="eng", image_format="txt", psm=3, pdf_output_type="pdfa-2",
                deskew=True, rotate_pages=True, clean=False, skip_text=True,
            )
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                result = ocrkit.op_recognize(args)

        event = json.loads(captured.getvalue().splitlines()[-1])
        self.assertEqual(1, result)
        self.assertEqual("unsupported_input", event["code"])


if __name__ == "__main__":
    unittest.main()
