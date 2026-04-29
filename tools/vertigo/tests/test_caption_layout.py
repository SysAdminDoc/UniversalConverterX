"""Face-aware caption placement heuristic coverage."""

from __future__ import annotations

import unittest

from core.caption_layout import (
    ALIGN_BOTTOM_CENTER,
    ALIGN_TOP_CENTER,
    caption_zone_norm,
    chunk_alignment,
    plan_alignments,
)
from core.caption_styles import resolve
from core.face_samples import FaceSample


def _preset(preset_id: str = "pop"):
    return resolve(preset_id)


class CaptionLayoutTests(unittest.TestCase):
    def test_caption_zone_respects_margin(self) -> None:
        preset = _preset()
        top, bottom = caption_zone_norm(preset)
        self.assertAlmostEqual(bottom, 1.0 - preset.margin_v_fraction, places=5)
        self.assertLess(top, bottom)
        self.assertGreaterEqual(top, 0.0)

    def test_face_in_bottom_zone_flips_to_top(self) -> None:
        preset = _preset()
        samples = [FaceSample(t=1.0, boxes=((0.3, 0.72, 0.3, 0.2),))]
        self.assertEqual(
            chunk_alignment(preset, 0.5, 2.0, samples),
            ALIGN_TOP_CENTER,
        )

    def test_face_in_top_keeps_default(self) -> None:
        preset = _preset()
        samples = [FaceSample(t=1.0, boxes=((0.3, 0.10, 0.3, 0.2),))]
        self.assertEqual(
            chunk_alignment(preset, 0.5, 2.0, samples),
            ALIGN_BOTTOM_CENTER,
        )

    def test_tiny_face_is_ignored(self) -> None:
        preset = _preset()
        # area = 0.1 * 0.1 = 0.01 < default min_face_area=0.015
        samples = [FaceSample(t=1.0, boxes=((0.3, 0.80, 0.1, 0.1),))]
        self.assertEqual(
            chunk_alignment(preset, 0.5, 2.0, samples),
            ALIGN_BOTTOM_CENTER,
        )

    def test_sample_outside_chunk_window_is_ignored(self) -> None:
        preset = _preset()
        samples = [FaceSample(t=5.0, boxes=((0.3, 0.80, 0.3, 0.2),))]
        self.assertEqual(
            chunk_alignment(preset, 0.5, 2.0, samples),
            ALIGN_BOTTOM_CENTER,
        )

    def test_letterbox_short_circuits_to_default(self) -> None:
        preset = _preset()
        samples = [FaceSample(t=1.0, boxes=((0.3, 0.80, 0.3, 0.2),))]
        self.assertEqual(
            chunk_alignment(preset, 0.5, 2.0, samples, letterbox=True),
            ALIGN_BOTTOM_CENTER,
        )

    def test_empty_samples_keep_default(self) -> None:
        preset = _preset()
        self.assertEqual(
            chunk_alignment(preset, 0.5, 2.0, []),
            ALIGN_BOTTOM_CENTER,
        )

    def test_plan_alignments_zips_correctly(self) -> None:
        preset = _preset()
        samples = [
            FaceSample(t=1.0, boxes=((0.3, 0.72, 0.3, 0.2),)),  # overlap
            FaceSample(t=3.0, boxes=((0.3, 0.10, 0.3, 0.2),)),  # safe
        ]
        alignments = plan_alignments(
            preset,
            [(0.0, 2.0), (2.0, 4.0)],
            samples,
        )
        self.assertEqual(
            alignments,
            [ALIGN_TOP_CENTER, ALIGN_BOTTOM_CENTER],
        )


if __name__ == "__main__":
    unittest.main()
