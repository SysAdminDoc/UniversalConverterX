"""Focused schema tests for declarative sidecar health manifests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from check_contract import check_health_manifest


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
                        "gpu": "cuda-optional",
                        "tools": [
                            {
                                "id": "ffmpeg",
                                "executable": "ffmpeg",
                                "display": "FFmpeg",
                                "managed": True,
                                "whenArgContains": "video",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual([], check_health_manifest(sidecar))


if __name__ == "__main__":
    unittest.main()
