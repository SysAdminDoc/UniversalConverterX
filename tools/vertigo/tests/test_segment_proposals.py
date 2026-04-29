"""Tests for ``core.segment_proposals`` (T3b)."""
from __future__ import annotations

import unittest

from core.caption_types import Caption, Word
from core.segment_proposals import (
    DEFAULT_MAX_SEC,
    DEFAULT_MIN_CLIP_SEC_FOR_PROPOSALS,
    DEFAULT_MIN_SEC,
    DEFAULT_TARGET_SEC,
    SegmentProposal,
    _gap_after,
    _gap_before,
    _STOP_WORDS,
    _STOP_WORDS_DE,
    _STOP_WORDS_EN,
    _STOP_WORDS_ES,
    _STOP_WORDS_FR,
    _STOP_WORDS_IT,
    _STOP_WORDS_PT,
    _token_stream,
    propose_segments,
    should_propose_for_duration,
)


def _cap(start: float, end: float, text: str, words: tuple[Word, ...] = ()) -> Caption:
    return Caption(start=start, end=end, text=text, words=words)


SILENCE_GAP_SEC = 3.0  # > _SILENCE_BOUNDARY_SEC (2.5 s) so boundaries promote


def _synthetic_long_transcript(
    total_sec: float = 900.0,
    *,
    silence_gap: float = SILENCE_GAP_SEC,
) -> list[Caption]:
    """Ten distinct 'topics' roughly 90 s each separated by an explicit silence gap.

    Each topic repeats a unique content word set so the TextTiling window
    sees a Jaccard drop at the boundaries. A ``silence_gap`` second gap
    sits between adjacent topics so the silence-boundary codepath also
    fires during tests (this was previously documented-but-missing).
    """
    topic_lexicons = [
        ["dragon", "castle", "knight", "sword", "battle", "dawn"],
        ["kitchen", "flour", "bread", "oven", "recipe", "dough"],
        ["rocket", "launch", "orbit", "payload", "mission", "stage"],
        ["piano", "chord", "melody", "concert", "keyboard", "tempo"],
        ["garden", "soil", "plant", "tomato", "compost", "bloom"],
        ["startup", "founder", "pitch", "investor", "runway", "equity"],
        ["ocean", "coral", "reef", "diver", "shark", "current"],
        ["mountain", "summit", "rope", "glacier", "climber", "ridge"],
        ["theater", "actor", "script", "rehearse", "stage", "audience"],
        ["brewery", "barley", "hops", "yeast", "ferment", "keg"],
    ]
    captions: list[Caption] = []
    topic_span = total_sec / len(topic_lexicons)
    cursor = 0.0
    for i, lex in enumerate(topic_lexicons):
        # Plant a question + laugh token in topics 0 and 3 so they score higher.
        sentences: list[str] = []
        sentences.append(" ".join(lex[:4]))
        if i == 0:
            sentences.append(f"Can we {lex[4]} the {lex[5]}? haha that would be wild.")
        elif i == 3:
            sentences.append(f"Does this {lex[4]} really matter? [laughter]")
        else:
            sentences.append(" ".join(lex[2:]) + ".")
        sentences.append(" ".join(lex) + ".")
        t = cursor
        for s in sentences:
            # leave at least `silence_gap` seconds at the end of the topic
            dur = min((topic_span - silence_gap) / (len(sentences) + 1), 10.0)
            captions.append(_cap(t, t + dur, s))
            t += dur
        # advance into the next topic span, burning the silence gap
        cursor = (i + 1) * topic_span
    return captions


class SegmentProposalsTests(unittest.TestCase):
    def test_should_propose_gate(self) -> None:
        self.assertFalse(should_propose_for_duration(0.0))
        self.assertFalse(should_propose_for_duration(120.0))
        self.assertTrue(should_propose_for_duration(DEFAULT_MIN_CLIP_SEC_FOR_PROPOSALS))
        self.assertTrue(should_propose_for_duration(DEFAULT_MIN_CLIP_SEC_FOR_PROPOSALS + 1.0))

    def test_empty_captions_returns_empty(self) -> None:
        self.assertEqual(propose_segments([]), [])

    def test_short_clip_returns_empty(self) -> None:
        caps = [_cap(0.0, 5.0, "short clip")]
        self.assertEqual(propose_segments(caps, min_sec=30.0), [])

    def test_invalid_bounds_return_empty(self) -> None:
        caps = _synthetic_long_transcript()
        self.assertEqual(propose_segments(caps, min_sec=90.0, max_sec=30.0), [])
        self.assertEqual(propose_segments(caps, target_sec=0.0), [])

    def test_proposes_segments_in_band(self) -> None:
        caps = _synthetic_long_transcript(total_sec=900.0)
        out = propose_segments(caps, min_sec=30.0, max_sec=90.0, target_sec=45.0)
        self.assertGreater(len(out), 0)
        max_allowed = 90.0 + SILENCE_GAP_SEC  # fallback path may slightly overshoot
        for p in out:
            self.assertIsInstance(p, SegmentProposal)
            self.assertGreaterEqual(p.duration, 30.0)
            self.assertLessEqual(
                p.duration,
                max_allowed,
                f"segment duration {p.duration:.1f}s exceeds max+gap budget "
                f"{max_allowed:.1f}s — assembly drifted",
            )
            self.assertGreaterEqual(p.score, 0.0)
            self.assertLessEqual(p.score, 1.0)

    def test_silence_gap_drives_boundary(self) -> None:
        """With an explicit silence gap > 2.5 s between topics, at least
        one proposal should pick up ``silence before`` or ``silence after``
        in its ``reasons`` tuple."""
        caps = _synthetic_long_transcript()
        out = propose_segments(caps, top_n=20)
        silence_reasons = [
            p for p in out
            if any("silence" in r for r in p.reasons)
        ]
        self.assertGreater(
            len(silence_reasons),
            0,
            "no proposal surfaced the silence-gap reason — boundary path not exercised",
        )

    def test_results_sorted_descending_by_score(self) -> None:
        caps = _synthetic_long_transcript()
        out = propose_segments(caps)
        scores = [p.score for p in out]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_question_and_laugh_boost_score(self) -> None:
        caps = _synthetic_long_transcript()
        out = propose_segments(caps, top_n=20)
        # The first topic's segment contains both a '?' and 'haha'; it should
        # score above at least one segment that has neither.
        with_hits = [p for p in out if p.questions or p.laughter_hits]
        no_hits = [p for p in out if not p.questions and not p.laughter_hits]
        if with_hits and no_hits:
            self.assertGreaterEqual(max(p.score for p in with_hits), max(p.score for p in no_hits))

    def test_title_hint_populated(self) -> None:
        caps = _synthetic_long_transcript()
        out = propose_segments(caps)
        self.assertTrue(all(p.title_hint for p in out))
        for p in out:
            self.assertLessEqual(len(p.title_hint), 61)   # 60 + ellipsis char

    def test_reasons_are_explainable(self) -> None:
        caps = _synthetic_long_transcript()
        out = propose_segments(caps, top_n=20)
        # At least one proposal carries non-empty reasons
        self.assertTrue(any(p.reasons for p in out))

    def test_top_n_honoured(self) -> None:
        caps = _synthetic_long_transcript()
        self.assertLessEqual(len(propose_segments(caps, top_n=3)), 3)

    def test_defaults_are_sensible(self) -> None:
        self.assertLess(DEFAULT_MIN_SEC, DEFAULT_TARGET_SEC)
        self.assertLess(DEFAULT_TARGET_SEC, DEFAULT_MAX_SEC)
        # 10-minute gate — this is the charter line
        self.assertEqual(DEFAULT_MIN_CLIP_SEC_FOR_PROPOSALS, 600.0)

    def test_handles_captions_without_words(self) -> None:
        """Non-karaoke faster-whisper output has cap.words == () — must still work."""
        caps = _synthetic_long_transcript()
        for c in caps:
            self.assertEqual(c.words, ())
        out = propose_segments(caps)
        self.assertGreater(len(out), 0)


class GapHelperTests(unittest.TestCase):
    """Direct unit tests for the ``_gap_before`` / ``_gap_after`` fix.

    v0.12.0 rewrote both to find the pair that *straddles* the target
    time instead of the first-crossing pair. These tests pin the
    correct behaviour so a regression re-introduces the shadowed bug.
    """

    def _caps(self) -> list[Caption]:
        #          cap A     gap 1    cap B     gap 2    cap C
        # 0 ----- 5 ====== 8 ------- 10 ====== 15 ------ 22 ====== 28
        return [
            Caption(0.0, 5.0, "alpha"),
            Caption(8.0, 10.0, "bravo"),
            Caption(15.0, 22.0, "charlie"),
            Caption(28.0, 30.0, "delta"),
        ]

    def test_gap_before_finds_straddling_gap(self) -> None:
        caps = self._caps()
        # target t=11 sits in the 10..15 gap → gap is 5s
        self.assertAlmostEqual(_gap_before(11.0, caps), 5.0)
        # target t=7 sits in the 5..8 gap → gap is 3s
        self.assertAlmostEqual(_gap_before(7.0, caps), 3.0)
        # target t=25 sits in the 22..28 gap → gap is 6s
        self.assertAlmostEqual(_gap_before(25.0, caps), 6.0)

    def test_gap_before_inside_caption_returns_zero(self) -> None:
        caps = self._caps()
        # target t=3 lands inside cap A (0..5) — not a straddling gap
        self.assertEqual(_gap_before(3.0, caps), 0.0)
        # target t=16 lands inside cap C (15..22) — not a straddling gap
        self.assertEqual(_gap_before(16.0, caps), 0.0)

    def test_gap_after_mirrors_gap_before(self) -> None:
        caps = self._caps()
        # t=9 is inside cap B (8..10), not a gap → zero
        self.assertEqual(_gap_after(9.0, caps), 0.0)
        # t=6 is in gap 5..8 → 3s straddling gap
        self.assertAlmostEqual(_gap_after(6.0, caps), 3.0)
        # symmetric to gap_before: t=11 is in gap 10..15 → 5s
        self.assertAlmostEqual(_gap_after(11.0, caps), 5.0)
        # t=25 is in gap 22..28 → 6s
        self.assertAlmostEqual(_gap_after(25.0, caps), 6.0)

    def test_empty_or_single_caption_returns_zero(self) -> None:
        self.assertEqual(_gap_before(5.0, []), 0.0)
        self.assertEqual(_gap_after(5.0, []), 0.0)
        single = [Caption(0.0, 10.0, "alone")]
        self.assertEqual(_gap_before(5.0, single), 0.0)
        self.assertEqual(_gap_after(5.0, single), 0.0)

    def test_bisect_fast_path_matches_linear_semantics(self) -> None:
        """Precomputed-starts path must mirror the no-starts path exactly.

        The performance optimisation threads a precomputed ``starts``
        list through scoring to skip the per-call O(n) build; the two
        entry points must remain bit-for-bit equivalent for the
        surrounding scoring logic to stay stable.
        """
        caps = self._caps()
        starts = [c.start for c in caps]
        for t in (3.0, 5.0, 6.0, 7.0, 10.0, 11.0, 14.99, 15.0, 16.0, 25.0, 28.0, 30.0, 50.0):
            self.assertEqual(
                _gap_before(t, caps),
                _gap_before(t, caps, starts=starts),
                msg=f"_gap_before divergence at t={t}",
            )
            self.assertEqual(
                _gap_after(t, caps),
                _gap_after(t, caps, starts=starts),
                msg=f"_gap_after divergence at t={t}",
            )

    def test_stop_lists_cover_expected_languages(self) -> None:
        """Union must carry each language's native filler words."""
        # One high-frequency anchor per language so a future refactor
        # that drops a list fails loudly.
        self.assertIn("the", _STOP_WORDS_EN)
        self.assertIn("que", _STOP_WORDS_ES)
        self.assertIn("le", _STOP_WORDS_FR)
        self.assertIn("der", _STOP_WORDS_DE)
        self.assertIn("nao", _STOP_WORDS_PT)
        self.assertIn("che", _STOP_WORDS_IT)
        # Union is what segment_proposals actually uses.
        for tok in ("the", "que", "le", "der", "nao", "che"):
            self.assertIn(tok, _STOP_WORDS, msg=f"{tok!r} missing from union")

    def test_english_stop_filter_still_works(self) -> None:
        """No regression on the English path — segment_proposals was
        English-only before this pass; the multilingual union must not
        weaken English filtering."""
        caps = [Caption(0.0, 2.0, "the quick brown fox")]
        tokens = _token_stream(caps)
        surviving = {tok for _, tok in tokens}
        self.assertNotIn("the", surviving)
        self.assertIn("quick", surviving)
        self.assertIn("brown", surviving)
        self.assertIn("fox", surviving)

    def test_french_stop_filter(self) -> None:
        """French filler gets stripped so TextTiling sees real content."""
        caps = [Caption(0.0, 2.0, "le chat mange la souris dans la maison")]
        tokens = _token_stream(caps)
        surviving = {tok for _, tok in tokens}
        # Function words dropped
        for stop in ("le", "la", "dans"):
            self.assertNotIn(stop, surviving, msg=f"{stop!r} should be filtered")
        # Content words survive
        for content in ("chat", "mange", "souris", "maison"):
            self.assertIn(content, surviving, msg=f"{content!r} should survive")

    def test_german_stop_filter(self) -> None:
        """German filler gets stripped."""
        caps = [Caption(0.0, 2.0, "der hund lauft in den park mit dem ball")]
        tokens = _token_stream(caps)
        surviving = {tok for _, tok in tokens}
        for stop in ("der", "den", "mit", "dem"):
            self.assertNotIn(stop, surviving, msg=f"{stop!r} should be filtered")
        for content in ("hund", "lauft", "park", "ball"):
            self.assertIn(content, surviving, msg=f"{content!r} should survive")

    def test_bisect_scales_sublinearly(self) -> None:
        """5k-caption transcript stays responsive — gap lookup is O(log n).

        Not a strict micro-benchmark (CI jitter will happily inflate
        timing by 5x on a cold runner). The budget is wide: 5000
        captions * 1000 lookups should finish well under a second on
        any reasonable host once the linear scan is gone. A regression
        that restores the O(n) scan would push this into the minutes.
        """
        import time

        caps = [Caption(float(i), float(i) + 0.5, "word") for i in range(5000)]
        starts = [c.start for c in caps]
        probes = [float(i * 5) for i in range(1000)]
        t0 = time.perf_counter()
        for t in probes:
            _gap_before(t, caps, starts=starts)
            _gap_after(t, caps, starts=starts)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 1.0, f"scaling regression — {elapsed:.3f}s")


class PropsCancelCooperationTests(unittest.TestCase):
    """H5: ``propose_segments`` honours ``cancel_cb`` at loop heads."""

    def test_immediate_cancel_returns_empty(self) -> None:
        caps = _synthetic_long_transcript()
        calls = {"n": 0}

        def cancel() -> bool:
            calls["n"] += 1
            return True

        out = propose_segments(caps, cancel_cb=cancel)
        self.assertEqual(out, [])
        # Cancel was checked at least once before any heavy work.
        self.assertGreaterEqual(calls["n"], 1)

    def test_cancel_after_boundaries_returns_empty(self) -> None:
        caps = _synthetic_long_transcript()
        ticks = {"n": 0}

        def cancel() -> bool:
            # Allow initial pre-checks, then cancel between boundary scan
            # and assembly.
            ticks["n"] += 1
            return ticks["n"] > 2

        out = propose_segments(caps, cancel_cb=cancel)
        self.assertEqual(out, [])

    def test_non_cancelling_run_produces_proposals(self) -> None:
        caps = _synthetic_long_transcript()
        out = propose_segments(caps, cancel_cb=lambda: False)
        self.assertGreater(len(out), 0)


class SubtitlesReExportsCaptionTypesTests(unittest.TestCase):
    """H6: lifting Caption/Word into core/caption_types.py should not
    break existing ``from core.subtitles import Caption, Word`` callers."""

    def test_core_subtitles_still_exports_caption_and_word(self) -> None:
        from core import subtitles

        self.assertTrue(hasattr(subtitles, "Caption"))
        self.assertTrue(hasattr(subtitles, "Word"))

    def test_caption_types_and_subtitles_share_the_same_classes(self) -> None:
        from core import caption_types, subtitles

        self.assertIs(caption_types.Caption, subtitles.Caption)
        self.assertIs(caption_types.Word, subtitles.Word)


if __name__ == "__main__":
    unittest.main()
