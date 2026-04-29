import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamkeep import search


class SearchTests(unittest.TestCase):
    def test_index_recording_removes_stale_entries_when_transcripts_disappear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            db_path = tmp / "search.db"
            recording_dir = tmp / "recording"
            recording_dir.mkdir()
            transcript = recording_dir / "captions.srt"
            transcript.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello world\n",
                encoding="utf-8",
            )

            with mock.patch.object(search, "DB_PATH", db_path):
                indexed = search.index_recording(str(recording_dir))
                hits = search.search_transcripts("hello")

                transcript.unlink()
                reindexed = search.index_recording(str(recording_dir))
                stale_hits = search.search_transcripts("hello")

            self.assertEqual(indexed, 1)
            self.assertEqual(len(hits), 1)
            self.assertEqual(reindexed, 0)
            self.assertEqual(stale_hits, [])

    def test_search_transcripts_handles_invalid_fts_queries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "search.db"
            with mock.patch.object(search, "DB_PATH", db_path):
                hits = search.search_transcripts('"unterminated')
            self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
