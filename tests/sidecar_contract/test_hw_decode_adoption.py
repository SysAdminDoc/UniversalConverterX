"""Keep the shared frame iterator wired into every Item 126 consumer."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class HwDecodeAdoptionTests(unittest.TestCase):
    def test_analysis_sidecars_use_shared_fallback_iterator(self) -> None:
        for relative in (
            "tools/lipsight/sidecar.py",
            "tools/vertigo/sidecar.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("hw_decode.frames_or_opencv", source, relative)
            self.assertIn("hw_decode.frames_backend", source, relative)

    def test_frame_producers_require_explicit_opt_in(self) -> None:
        for relative in (
            "tools/clipforge/clipforge_ops/privacy.py",
            "tools/colorize/sidecar.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn('getattr(args, "hw_decode", False)', source, relative)
            self.assertIn("allow_hw=allow_hw", source, relative)


if __name__ == "__main__":
    unittest.main()
