import tempfile
import unittest
from pathlib import Path

from streamkeep.upload.webdav import WebDAVDestination


class _FakeResponse:
    def __init__(self, status=201):
        self.status = status

    def read(self):
        return b""


class _FakeConnection:
    def __init__(self, status=201):
        self.status = status
        self.sent = []
        self.headers = []
        self.closed = False

    def putrequest(self, method, path):
        self.method = method
        self.path = path

    def putheader(self, key, value):
        self.headers.append((key, value))

    def endheaders(self):
        self.ended = True

    def send(self, data):
        self.sent.append(bytes(data))

    def getresponse(self):
        return _FakeResponse(self.status)

    def close(self):
        self.closed = True


class WebDAVTests(unittest.TestCase):
    def test_upload_streams_file_in_chunks_and_reports_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "clip.bin"
            file_path.write_bytes(b"a" * (1024 * 1024 + 7))
            conn = _FakeConnection()
            progress = []
            dest = WebDAVDestination({"url": "https://dav.example.com/root"})

            import streamkeep.upload.webdav as webdav_mod

            original_chunk = webdav_mod._CHUNK_SIZE
            webdav_mod._CHUNK_SIZE = 1024
            try:
                original_open = webdav_mod._open_http_connection
                webdav_mod._open_http_connection = lambda parsed, timeout: conn
                try:
                    ok, msg = dest.upload(str(file_path), progress_cb=lambda sent, total: progress.append((sent, total)))
                finally:
                    webdav_mod._open_http_connection = original_open
            finally:
                webdav_mod._CHUNK_SIZE = original_chunk

            self.assertTrue(ok, msg)
            self.assertGreater(len(conn.sent), 1)
            self.assertEqual(b"".join(conn.sent), file_path.read_bytes())
            self.assertEqual(progress[-1], (file_path.stat().st_size, file_path.stat().st_size))
            self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main()
