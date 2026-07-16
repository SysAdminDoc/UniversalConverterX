"""Convergence and end-to-end coverage for HEICShift quality targeting."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "heicshift" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("heicshift_sidecar", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


class QualitySearchTests(unittest.TestCase):
    def test_size_search_chooses_highest_quality_under_cap(self) -> None:
        result = SIDECAR._binary_search_quality(
            lambda quality: (quality * 10 * 1024, None),
            500,
            "target-kb",
        )

        self.assertEqual((50, 500 * 1024, 500.0, True), result)

    def test_size_search_reports_unachievable_floor(self) -> None:
        quality, size, metric, target_met = SIDECAR._binary_search_quality(
            lambda candidate: ((candidate + 10) * 1024, None),
            5,
            "target-kb",
        )

        self.assertEqual(1, quality)
        self.assertEqual(11 * 1024, size)
        self.assertEqual(11.0, metric)
        self.assertFalse(target_met)

    def test_metric_search_chooses_lowest_quality_meeting_floor(self) -> None:
        result = SIDECAR._binary_search_quality(
            lambda quality: (quality * 100, quality / 2),
            35,
            "target-psnr",
        )

        self.assertEqual((70, 7000, 35.0, True), result)

    def test_metric_search_reports_unachievable_ceiling(self) -> None:
        quality, _, metric, target_met = SIDECAR._binary_search_quality(
            lambda candidate: (candidate * 100, candidate / 2),
            60,
            "target-ssimulacra2",
        )

        self.assertEqual(100, quality)
        self.assertEqual(50.0, metric)
        self.assertFalse(target_met)

    def test_target_modes_are_mutually_exclusive(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            SIDECAR.build_parser().parse_args(
                [
                    "convert", "--input", "in.png", "--output", "out.jpg",
                    "--format", "jpeg", "--target-kb", "500",
                    "--target-psnr", "40",
                ]
            )

    def test_lossless_format_rejects_quality_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.png"
            source.write_bytes(b"not decoded because validation runs first")
            args = SIDECAR.build_parser().parse_args(
                [
                    "convert", "--input", str(source),
                    "--output", str(Path(temp) / "out.png"),
                    "--format", "png", "--target-kb", "500",
                ]
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = SIDECAR.op_convert(args)

            self.assertEqual(1, result)
            event = json.loads(stdout.getvalue())
            self.assertEqual("unsupported_quality_target", event["code"])

    def test_real_jpeg_target_is_close_or_reports_best_achievable(self) -> None:
        try:
            from PIL import Image  # type: ignore
            import pillow_heif  # type: ignore  # noqa: F401
        except ImportError:
            self.skipTest("HEICShift managed image dependencies are not installed")

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "noise.png"
            output = directory / "target.jpg"
            Image.effect_noise((512, 512), 100).convert("RGB").save(source)

            completed = subprocess.run(
                [
                    sys.executable, str(SIDECAR_PATH), "convert",
                    "--input", str(source), "--output", str(output),
                    "--format", "jpeg", "--target-kb", "30",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
            final = events[-1]
            self.assertEqual("complete", final["event"])
            self.assertTrue(output.is_file())
            target = final["quality_target"]
            close = abs(final["size_bytes"] / 1024 - 30) <= 1.5
            self.assertTrue(close or target["warning"], target)


if __name__ == "__main__":
    unittest.main()
