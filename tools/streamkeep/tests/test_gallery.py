import tempfile
import unittest
from pathlib import Path

from streamkeep import gallery


class GalleryTests(unittest.TestCase):
    def test_serve_media_range_returns_partial_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media = Path(tmpdir) / "clip.webm"
            media.write_bytes(b"0123456789")

            data, status, headers = gallery.serve_media_range(
                str(media),
                "bytes=2-5",
            )

            self.assertEqual(status, 206)
            self.assertEqual(data, b"2345")
            self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
            self.assertEqual(headers["Content-Length"], "4")

    def test_serve_media_range_rejects_invalid_ranges(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            media = Path(tmpdir) / "clip.mp4"
            media.write_bytes(b"0123456789")

            data, status, headers = gallery.serve_media_range(
                str(media),
                "bytes=99-100",
            )

            self.assertIsNone(data)
            self.assertEqual(status, 416)
            self.assertEqual(headers["Content-Range"], "bytes */10")


if __name__ == "__main__":
    unittest.main()
