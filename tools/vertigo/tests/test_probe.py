"""FPS parser / probe helpers."""

from __future__ import annotations

import math
import unittest

from core.probe import _parse_fps


class ParseFpsTests(unittest.TestCase):
    def test_ratio(self) -> None:
        self.assertAlmostEqual(_parse_fps("30000/1001"), 30000 / 1001, places=6)

    def test_plain_float(self) -> None:
        self.assertAlmostEqual(_parse_fps("29.97"), 29.97, places=6)

    def test_missing_returns_zero(self) -> None:
        self.assertEqual(_parse_fps(""), 0.0)
        self.assertEqual(_parse_fps("0/0"), 0.0)
        self.assertEqual(_parse_fps("bogus"), 0.0)
        self.assertEqual(_parse_fps("N/A"), 0.0)

    def test_negative_or_nonfinite_coerced_to_zero(self) -> None:
        self.assertEqual(_parse_fps("-5"), 0.0)
        self.assertEqual(_parse_fps("-10/1"), 0.0)
        self.assertEqual(_parse_fps("inf"), 0.0)
        # explicit infinity via division
        self.assertEqual(_parse_fps("1/0"), 0.0)

    def test_finite_only(self) -> None:
        value = _parse_fps("24")
        self.assertTrue(math.isfinite(value) and value > 0)


if __name__ == "__main__":
    unittest.main()
