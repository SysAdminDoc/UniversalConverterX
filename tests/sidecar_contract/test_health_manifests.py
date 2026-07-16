"""Focused schema tests for declarative sidecar health manifests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from check_contract import check_health_manifest, check_onnx_runtime_compatibility


class SidecarHealthManifestTests(unittest.TestCase):
    def test_missing_manifest_is_a_violation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sidecar = Path(temp) / "sample" / "sidecar.py"
            sidecar.parent.mkdir()
            sidecar.touch()

            violations = check_health_manifest(sidecar)

            self.assertEqual(["missing ucx.sidecar.json"], [item.detail for item in violations])

    def test_manifest_rejects_mismatch_unknown_fields_and_unsafe_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sidecar = Path(temp) / "sample" / "sidecar.py"
            sidecar.parent.mkdir()
            sidecar.touch()
            (sidecar.parent / "ucx.sidecar.json").write_text(
                json.dumps(
                    {
                        "engine": "other",
                        "typo": True,
                        "tools": [
                            {
                                "id": "../ffmpeg",
                                "executable": "bin/ffmpeg",
                                "display": "FFmpeg",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            details = [item.detail for item in check_health_manifest(sidecar)]

            self.assertTrue(any("unknown top-level" in detail for detail in details))
            self.assertTrue(any("exactly match" in detail for detail in details))
            self.assertTrue(any("unsafe characters" in detail for detail in details))
            self.assertTrue(any("without a path" in detail for detail in details))

    def test_conditional_tool_manifest_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sidecar = Path(temp) / "sample" / "sidecar.py"
            sidecar.parent.mkdir()
            sidecar.touch()
            (sidecar.parent / "ucx.sidecar.json").write_text(
                json.dumps(
                    {
                        "engine": "sample",
                        "models": True,
                        "gpu": "cuda-required",
                        "onnxRuntime": "cuda12-transition",
                        "tools": [
                            {
                                "id": "ffmpeg",
                                "executable": "ffmpeg",
                                "display": "FFmpeg",
                                "managed": True,
                                "whenArgContainsAny": ["video", "mp4"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual([], check_health_manifest(sidecar))

    def test_missing_ffmpeg_error_requires_manifest_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sidecar = Path(temp) / "sample" / "sidecar.py"
            sidecar.parent.mkdir()
            sidecar.write_text('return fail("missing_ffmpeg")', encoding="utf-8")
            (sidecar.parent / "ucx.sidecar.json").write_text(
                json.dumps({"engine": "sample"}),
                encoding="utf-8",
            )

            details = [item.detail for item in check_health_manifest(sidecar)]

            self.assertIn(
                "sidecar reports missing_ffmpeg but does not declare the managed ffmpeg tool",
                details,
            )

    def test_onnx_runtime_matrix_rejects_floor_or_manifest_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sidecar_dir = Path(temp) / "alphacut"
            sidecar_dir.mkdir()
            (sidecar_dir / "requirements.txt").write_text(
                "onnxruntime>=1.27,<1.28\n",
                encoding="utf-8",
            )
            (sidecar_dir / "ucx.sidecar.json").write_text(
                json.dumps({"engine": "alphacut", "onnxRuntime": "cpu"}),
                encoding="utf-8",
            )

            details = [
                item.detail
                for item in check_onnx_runtime_compatibility(sidecar_dir)
            ]

            self.assertTrue(any("expected onnxruntime>=1.26,<1.27" in item for item in details))
            self.assertTrue(any("cuda12-transition" in item for item in details))


if __name__ == "__main__":
    unittest.main()
