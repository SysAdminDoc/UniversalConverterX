import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamkeep.verify import STATUS_FAIL, verify_media


class VerifyTests(unittest.TestCase):
    def test_verify_media_handles_invalid_numeric_probe_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media_path = Path(tmpdir) / "clip.mp4"
            media_path.write_bytes(b"not-empty")

            probe_stdout = json.dumps(
                {"format": {"duration": "N/A", "nb_streams": "oops"}}
            ).encode("utf-8")
            completed = mock.Mock(returncode=0, stdout=probe_stdout, stderr=b"")

            with mock.patch("streamkeep.verify.subprocess.run", return_value=completed):
                status, details = verify_media(str(media_path), expected_duration=60)

            self.assertEqual(status, STATUS_FAIL)
            self.assertIn("invalid numeric metadata", details)


if __name__ == "__main__":
    unittest.main()
