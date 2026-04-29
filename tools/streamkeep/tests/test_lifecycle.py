import os
import tempfile
import unittest
from pathlib import Path

from streamkeep.lifecycle import evaluate_cleanup, removal_real_paths
from streamkeep.models import HistoryEntry


class LifecycleTests(unittest.TestCase):
    def test_evaluate_cleanup_uses_watched_state_from_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recording_dir = Path(tmpdir) / "recording"
            recording_dir.mkdir()
            (recording_dir / "clip.mp4").write_bytes(b"x" * 32)

            history = [
                HistoryEntry(title="Primary", path=str(recording_dir), watched=False),
                HistoryEntry(title="Duplicate", path=str(recording_dir), watched=True),
            ]

            removals = evaluate_cleanup(
                history,
                {"enabled": True, "delete_watched": True, "favorites_exempt": True},
            )

            self.assertEqual(len(removals), 1)
            self.assertEqual(removals[0][1], "watched")
            self.assertEqual(removal_real_paths(removals), {os.path.realpath(str(recording_dir))})

    def test_evaluate_cleanup_honors_favorite_exemption_across_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recording_dir = Path(tmpdir) / "recording"
            recording_dir.mkdir()
            (recording_dir / "clip.mp4").write_bytes(b"x" * 32)

            history = [
                HistoryEntry(title="Primary", path=str(recording_dir), watched=True),
                HistoryEntry(title="Duplicate", path=str(recording_dir), favorite=True),
            ]

            removals = evaluate_cleanup(
                history,
                {"enabled": True, "delete_watched": True, "favorites_exempt": True},
            )

            self.assertEqual(removals, [])


if __name__ == "__main__":
    unittest.main()
