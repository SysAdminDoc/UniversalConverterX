import json
import tempfile
import unittest
from pathlib import Path

from streamkeep import resume


class ResumeTests(unittest.TestCase):
    def test_load_resume_state_rejects_oversized_sidecar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sidecar = root / resume.SIDECAR_NAME
            sidecar.write_text("x" * 32, encoding="utf-8")

            original_limit = resume.MAX_SIDECAR_BYTES
            resume.MAX_SIDECAR_BYTES = 8
            try:
                state = resume.load_resume_state(str(root))
            finally:
                resume.MAX_SIDECAR_BYTES = original_limit

            self.assertIsNone(state)

    def test_load_resume_state_uses_sidecar_directory_and_sanitizes_lists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sidecar = root / resume.SIDECAR_NAME
            sidecar.write_text(
                json.dumps(
                    {
                        "output_dir": "C:/wrong/place",
                        "segments": [
                            [0, "Segment 0", 0, 10],
                            ["bad", "Segment 1", 10, 10],
                            [2, "Segment 2", "oops", 5],
                        ],
                        "completed": ["1", "bad", -1, "1"],
                        "title": "Recovered",
                    }
                ),
                encoding="utf-8",
            )

            state = resume.load_resume_state(str(root))

            self.assertIsNotNone(state)
            self.assertEqual(state.output_dir, str(root.resolve()))
            self.assertEqual(state.segments, [[0, "Segment 0", 0.0, 10.0]])
            self.assertEqual(state.completed, [1])


if __name__ == "__main__":
    unittest.main()
