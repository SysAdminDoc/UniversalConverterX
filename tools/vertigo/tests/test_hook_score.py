"""Pure-Python hook-score pipeline coverage.

These tests cover the signal-processing layer (`_analyse`, `_rms`, `_zcr`,
`_decode_mono_s16le`, `_label_for`) without touching FFmpeg — the
extractor is mocked via `_decode_mono_s16le` which is deterministic.
"""

from __future__ import annotations

import math
import struct
import unittest

from core.hook_score import (
    HookScore,
    _analyse,
    _decode_mono_s16le,
    _label_for,
    _percentile,
    _rms,
    _zcr,
)


def _sine_samples(seconds: float, *, freq: float = 440.0, rate: int = 16000,
                  amplitude: float = 0.5) -> list[int]:
    n = int(round(seconds * rate))
    return [
        int(round(amplitude * 32767 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(n)
    ]


def _silence(seconds: float, rate: int = 16000) -> list[int]:
    return [0] * int(round(seconds * rate))


class HookSignalTests(unittest.TestCase):
    def test_rms_of_silence_is_zero(self) -> None:
        self.assertAlmostEqual(_rms([0] * 320), 0.0)

    def test_rms_of_sine_is_nonzero(self) -> None:
        rms = _rms(_sine_samples(0.02))
        self.assertGreater(rms, 0.0)
        self.assertLess(rms, 1.0)

    def test_zcr_of_silence_is_zero(self) -> None:
        self.assertEqual(_zcr([0] * 320), 0.0)

    def test_zcr_of_alternating_is_high(self) -> None:
        alt = [32000 if i % 2 == 0 else -32000 for i in range(320)]
        self.assertGreater(_zcr(alt), 0.9)

    def test_zcr_empty_guard(self) -> None:
        self.assertEqual(_zcr([]), 0.0)
        self.assertEqual(_zcr([42]), 0.0)

    def test_percentile_handles_empty_list(self) -> None:
        self.assertEqual(_percentile([], 0.95), 0.0)

    def test_percentile_monotonic(self) -> None:
        xs = [0.0, 0.25, 0.5, 0.75, 1.0]
        self.assertLessEqual(_percentile(xs, 0.1), _percentile(xs, 0.9))


class HookAnalyseTests(unittest.TestCase):
    def test_silence_scores_zero(self) -> None:
        vf, mve = _analyse(_silence(3.0), sample_rate=16000)
        self.assertEqual(vf, 0.0)
        self.assertEqual(mve, 0.0)

    def test_too_few_samples_returns_zero(self) -> None:
        self.assertEqual(_analyse([0] * 10, sample_rate=16000), (0.0, 0.0))

    def test_sine_gives_some_energy(self) -> None:
        vf, mve = _analyse(_sine_samples(3.0), sample_rate=16000)
        # sine is unrealistic for voice but it exercises the path — we
        # only assert that the algorithm remains bounded.
        self.assertGreaterEqual(vf, 0.0)
        self.assertLessEqual(vf, 1.0)
        self.assertGreaterEqual(mve, 0.0)
        self.assertLessEqual(mve, 1.0)


class HookDecodeTests(unittest.TestCase):
    def test_decode_empty(self) -> None:
        self.assertEqual(_decode_mono_s16le(b""), [])

    def test_decode_odd_bytes_truncates(self) -> None:
        # one trailing byte — must not crash
        raw = struct.pack("<hh", 123, -456) + b"\x00"
        self.assertEqual(_decode_mono_s16le(raw), [123, -456])

    def test_decode_round_trip(self) -> None:
        values = [0, 1000, -1000, 32000, -32000]
        raw = struct.pack(f"<{len(values)}h", *values)
        self.assertEqual(_decode_mono_s16le(raw), values)


class HookLabelTests(unittest.TestCase):
    def test_label_thresholds(self) -> None:
        self.assertEqual(_label_for(0), "silent")
        self.assertEqual(_label_for(9), "silent")
        self.assertEqual(_label_for(10), "weak")
        self.assertEqual(_label_for(39), "weak")
        self.assertEqual(_label_for(40), "moderate")
        self.assertEqual(_label_for(69), "moderate")
        self.assertEqual(_label_for(70), "strong")
        self.assertEqual(_label_for(100), "strong")

    def test_badge_format(self) -> None:
        s = HookScore(
            score=72, label="strong",
            voice_fraction=0.9, mean_voiced_energy=0.6, window_sec=3.0,
        )
        self.assertEqual(s.as_badge(), "72 \u00b7 strong")


if __name__ == "__main__":
    unittest.main()
