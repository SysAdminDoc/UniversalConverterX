"""Alpha-safe and multi-frame coverage for HEICShift batch edits."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "heicshift" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("heicshift_edits_sidecar", SIDECAR_PATH)
assert SPEC and SPEC.loader
SIDECAR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIDECAR)


class HeicshiftEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from PIL import Image  # type: ignore  # noqa: F401
            import pillow_heif  # type: ignore  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("HEICShift managed image dependencies are not installed")

    def test_named_preset_stacks_with_explicit_adjustments(self) -> None:
        args = SIDECAR.build_parser().parse_args(
            [
                "convert", "--input", "in.png", "--output", "out.png",
                "--format", "png", "--adjust-preset", "vivid",
                "--saturation", "-10", "--vignette", "30",
            ]
        )

        edits = SIDECAR._resolve_edits(args)

        self.assertEqual(20, edits["saturation"])
        self.assertEqual(15, edits["contrast"])
        self.assertEqual(30, edits["vignette"])

    def test_vivid_vignette_preserves_png_alpha(self) -> None:
        from PIL import Image  # type: ignore

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "alpha.png"
            output = directory / "edited.png"
            image = Image.new("RGBA", (64, 64), (90, 120, 150, 255))
            alpha = Image.new("L", image.size)
            alpha.putdata([(x * 4) % 256 for y in range(64) for x in range(64)])
            image.putalpha(alpha)
            image.save(source)

            events = self._run(
                source, output, "png",
                "--adjust-preset", "vivid", "--vignette", "30",
            )

            with Image.open(output) as edited:
                self.assertEqual(alpha.tobytes(), edited.getchannel("A").tobytes())
                self.assertNotEqual(image.convert("RGB").getpixel((0, 0)), edited.convert("RGB").getpixel((0, 0)))
            self.assertTrue(events[-1]["edits_applied"])
            self.assertEqual(1, events[-1]["frames"])

    def test_multiframe_tiff_edits_every_frame_and_preserves_alpha(self) -> None:
        from PIL import Image  # type: ignore

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "pages.tiff"
            output = directory / "edited.tiff"
            first = Image.new("RGBA", (12, 10), (255, 0, 0, 64))
            second = Image.new("RGBA", (12, 10), (0, 255, 0, 192))
            first.save(source, save_all=True, append_images=[second])

            events = self._run(source, output, "tiff", "--invert")

            with Image.open(output) as edited:
                self.assertEqual(2, edited.n_frames)
                edited.seek(0)
                self.assertEqual((0, 255, 255, 64), edited.convert("RGBA").getpixel((0, 0)))
                edited.seek(1)
                self.assertEqual((255, 0, 255, 192), edited.convert("RGBA").getpixel((0, 0)))
            self.assertEqual(2, events[-1]["frames"])
            self.assertTrue(events[-1]["edits_applied"])

    def test_invalid_adjustment_fails_closed(self) -> None:
        from PIL import Image  # type: ignore

        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / "source.png"
            Image.new("RGB", (2, 2), "white").save(source)
            completed = self._process(
                source, directory / "out.png", "png", "--brightness", "101")

            self.assertEqual(1, completed.returncode)
            event = json.loads(completed.stdout.splitlines()[-1])
            self.assertEqual("invalid_edit", event["code"])

    def _run(self, source: Path, output: Path, fmt: str, *arguments: str) -> list[dict]:
        completed = self._process(source, output, fmt, *arguments)
        self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
        events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        self.assertEqual("complete", events[-1]["event"])
        return events

    @staticmethod
    def _process(source: Path, output: Path, fmt: str, *arguments: str):
        return subprocess.run(
            [
                sys.executable, str(SIDECAR_PATH), "convert",
                "--input", str(source), "--output", str(output),
                "--format", fmt, *arguments,
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
