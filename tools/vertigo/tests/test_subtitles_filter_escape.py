"""Regression tests for the FFmpeg ``subtitles=`` filter-path escape.

Pins the v0.12.2 fix (H-1 from the postflight security audit): the
``_subtitles_filter`` helper used to escape only the Windows drive
colon. A caption file at a path with a second colon — unusual on
Windows but trivial on POSIX timestamped paths or adversarial
filenames — slipped an inner colon through, and libavfilter's
filter-graph parser split the ``subtitles=...`` argument at that
colon, interpreting the tail as additional filter options.

These tests call into the private helper by name, which is stable
because it's called from a narrow section of ``core.encode``. If the
helper is renamed, wire the test to the public call site instead.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from core.caption_styles import default_preset
from core.encode import _subtitles_filter


class SubtitlesFilterEscapeTests(unittest.TestCase):
    """Defensive escaping: every colon and every quote must be neutralised."""

    def test_windows_drive_colon_escaped(self) -> None:
        p = Path("C:/Users/alice/captions.srt")
        with mock.patch.object(Path, "resolve", return_value=p):
            out = _subtitles_filter(p, default_preset(), 1920)
        # "C:/..." -> "C\:/..." (single backslash + colon)
        self.assertIn(r"C\:/Users/alice/captions.srt", out)
        # Bare unescaped "C:" must not appear — that's the injection vector
        self.assertNotIn("'C:/", out)

    def test_inner_colon_also_escaped(self) -> None:
        """The old code only touched position 1 (drive colon). Verify
        every colon in the filename body is now escaped."""
        # The reviewer's example attack: a filename with a second colon
        # the old regex would have missed.
        p = Path("/tmp/foo:bar.srt")
        with mock.patch.object(Path, "resolve", return_value=p):
            out = _subtitles_filter(p, default_preset(), 1920)
        # Expect both colons escaped
        self.assertIn(r"/tmp/foo\:bar.srt", out)
        # The un-escaped inner colon would have split the filter arg
        self.assertNotIn("foo:bar.srt", out)

    def test_single_quote_escaped_with_ffmpeg_idiom(self) -> None:
        p = Path("/tmp/alice's_clip.srt")
        with mock.patch.object(Path, "resolve", return_value=p):
            out = _subtitles_filter(p, default_preset(), 1920)
        # FFmpeg-documented: 'abc'\''def' — close, literal-quote, re-open
        self.assertIn(r"alice'\''s_clip.srt", out)

    def test_force_style_block_emitted(self) -> None:
        p = Path("/tmp/captions.srt")
        with mock.patch.object(Path, "resolve", return_value=p):
            out = _subtitles_filter(p, default_preset(), 1920)
        self.assertIn("force_style=", out)
        self.assertTrue(out.startswith("subtitles='"))

    def test_backslashes_normalised_to_forward_slashes(self) -> None:
        p = Path(r"C:\Users\alice\captions.srt")
        with mock.patch.object(Path, "resolve", return_value=p):
            out = _subtitles_filter(p, default_preset(), 1920)
        # No raw backslashes in the escaped path (they all became /)
        self.assertNotIn("\\U", out)
        self.assertIn("C\\:/Users/alice/captions.srt", out)


if __name__ == "__main__":
    unittest.main()
