"""Coverage for the drawtext filter-chain builder."""

from __future__ import annotations

import math
import unittest

from core.overlays import (
    OverlayPosition,
    TextOverlay,
    _ffmpeg_color,
    build_filter_chain,
)


def _overlay(**kwargs) -> TextOverlay:
    base = dict(text="Hello", start=0.0, end=3.0, position=OverlayPosition.TITLE)
    base.update(kwargs)
    return TextOverlay(**base)


class BuildFilterTests(unittest.TestCase):
    def test_empty_list_returns_empty_string(self) -> None:
        self.assertEqual(build_filter_chain([]), "")

    def test_blank_text_is_dropped(self) -> None:
        self.assertEqual(build_filter_chain([_overlay(text="   ")]), "")

    def test_zero_duration_dropped(self) -> None:
        self.assertEqual(build_filter_chain([_overlay(end=0.0)]), "")

    def test_nan_start_or_end_dropped(self) -> None:
        self.assertEqual(build_filter_chain([_overlay(start=float("nan"))]), "")
        self.assertEqual(build_filter_chain([_overlay(end=float("inf"))]), "")

    def test_single_overlay_contains_escaped_text(self) -> None:
        chain = build_filter_chain([_overlay(text="a:b'c", size=48)])
        self.assertIn("drawtext=text='a", chain)
        self.assertIn("fontsize=48", chain)
        self.assertIn("enable='between(t,0.000,3.000)'", chain)

    def test_size_is_clamped_to_sane_range(self) -> None:
        # Extremely large or tiny sizes must be clamped before hitting FFmpeg.
        chain_big = build_filter_chain([_overlay(size=99999)])
        chain_tiny = build_filter_chain([_overlay(size=-10)])
        self.assertIn("fontsize=512", chain_big)
        self.assertIn("fontsize=8", chain_tiny)

    def test_background_alpha_clamped(self) -> None:
        chain = build_filter_chain([_overlay(background=True, background_alpha=5.0)])
        self.assertIn("@1.00", chain)

    def test_chain_joins_multiple_overlays_with_comma(self) -> None:
        chain = build_filter_chain([
            _overlay(text="one"),
            _overlay(text="two"),
        ])
        # two drawtext filters, comma-separated
        self.assertEqual(chain.count("drawtext=text="), 2)


class ColorNormalisationTests(unittest.TestCase):
    def test_hash_hex(self) -> None:
        self.assertEqual(_ffmpeg_color("#ff00aa"), "0xFF00AA")

    def test_bare_hex(self) -> None:
        self.assertEqual(_ffmpeg_color("123abc"), "0x123ABC")

    def test_zerox_prefixed(self) -> None:
        self.assertEqual(_ffmpeg_color("0xDEADBE"), "0xDEADBE")

    def test_malformed_falls_back_to_white(self) -> None:
        self.assertEqual(_ffmpeg_color(""), "0xFFFFFF")
        self.assertEqual(_ffmpeg_color("bogus"), "0xFFFFFF")
        self.assertEqual(_ffmpeg_color("#gggggg"), "0xFFFFFF")
        self.assertEqual(_ffmpeg_color("red"), "0xFFFFFF")


if __name__ == "__main__":
    unittest.main()
