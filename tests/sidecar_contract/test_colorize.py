"""Coverage for the offline colourisation sidecar.

The model gating, licence consent, and argument paths are always exercised.
The actual colourisation only runs when the SHA-256 verified model pack is
already present in the shared model cache (the 123 MB weights are never
downloaded during tests); otherwise those cases skip.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_PATH = ROOT / "tools" / "colorize" / "sidecar.py"
SPEC = importlib.util.spec_from_file_location("colorize", SIDECAR_PATH)
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


class ColorizeTests(unittest.TestCase):
    def test_download_requires_license_acceptance(self) -> None:
        code, events = _run(SIDECAR.op_download_model, ["download-model"])
        self.assertEqual(1, code)
        self.assertEqual("license_not_accepted", events[-1]["code"])

    def test_check_model_reports_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with _model_dir(temp):
                code, events = _run(SIDECAR.op_check_model, ["check-model"])
        self.assertEqual(0, code)
        status = next(e for e in events if e["event"] == "model_status")
        self.assertFalse(status["ready"])
        self.assertIn("license", status)

    def test_image_gated_on_model(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "in.png"
            src.write_bytes(b"\x89PNG\r\n")  # never read — gate fires first
            with _model_dir(temp):
                code, events = _run(
                    SIDECAR.op_image,
                    ["image", "--input", str(src), "--output", str(Path(temp) / "o.png")])
        self.assertEqual(1, code)
        self.assertEqual("model_missing", events[-1]["code"])

    def test_colorizes_image_when_model_present(self) -> None:
        try:
            import cv2  # noqa: F401
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV/numpy not installed")
        if not SIDECAR.model_ready(SIDECAR.model_dir()):
            self.skipTest("Colourisation model pack is not present in UCX_MODEL_DIR")

        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "gray.png"
            gray = np.tile(np.linspace(20, 220, 128, dtype=np.uint8), (96, 1))
            cv2.imwrite(str(src), cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
            out = Path(temp) / "colour.png"
            code, events = _run(
                SIDECAR.op_image,
                ["image", "--input", str(src), "--output", str(out)])
            self.assertEqual(0, code, events)
            self.assertTrue(out.is_file())
            self.assertEqual("complete", events[-1]["event"])
            # A grayscale input has ~0 chroma; colourisation must introduce some.
            lab = cv2.cvtColor(cv2.imread(str(out)), cv2.COLOR_BGR2LAB).astype("float32")
            chroma = float(np.mean(np.abs(lab[:, :, 1] - 128) + np.abs(lab[:, :, 2] - 128)))
            self.assertGreater(chroma, 2.0)


@contextlib.contextmanager
def _model_dir(path: str):
    previous = os.environ.get("UCX_MODEL_DIR")
    os.environ["UCX_MODEL_DIR"] = path
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("UCX_MODEL_DIR", None)
        else:
            os.environ["UCX_MODEL_DIR"] = previous


if __name__ == "__main__":
    unittest.main()
