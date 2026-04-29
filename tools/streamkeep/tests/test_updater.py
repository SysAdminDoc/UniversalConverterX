import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from streamkeep.updater import DownloadUpdateWorker


class _FakeResponse:
    def __init__(self, chunks, headers=None):
        self._chunks = list(chunks)
        self.headers = headers or {}

    def read(self, _size):
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class UpdaterTests(unittest.TestCase):
    def test_cancelled_update_download_removes_partial_new_file(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        done_events = []
        with tempfile.TemporaryDirectory() as tmpdir:
            exe_path = Path(tmpdir) / "StreamKeep.exe"
            exe_path.write_bytes(b"old")
            worker = DownloadUpdateWorker("https://example.com/StreamKeep.exe", 0)
            worker._cancel = True
            worker.done.connect(lambda ok, msg: done_events.append((ok, msg)))

            with mock.patch.object(worker, "_target_path", return_value=str(exe_path)), \
                 mock.patch("streamkeep.updater.urllib.request.urlopen", return_value=_FakeResponse([b"new-bits"])), \
                 mock.patch("streamkeep.updater.sys", create=True) as mock_sys:
                mock_sys.executable = str(exe_path)
                mock_sys.frozen = True
                worker.run()

            app.processEvents()
            self.assertEqual(done_events, [(False, "Download cancelled.")])
            self.assertFalse((exe_path.parent / "StreamKeep.exe.new").exists())

    def test_invalid_content_length_header_does_not_crash_update_download(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        done_events = []
        with tempfile.TemporaryDirectory() as tmpdir:
            exe_path = Path(tmpdir) / "StreamKeep.exe"
            exe_path.write_bytes(b"old")
            worker = DownloadUpdateWorker("https://example.com/StreamKeep.exe", 0)
            worker.done.connect(lambda ok, msg: done_events.append((ok, msg)))

            with mock.patch.object(worker, "_target_path", return_value=str(exe_path)), \
                 mock.patch(
                     "streamkeep.updater.urllib.request.urlopen",
                     return_value=_FakeResponse([b"fresh-binary"], headers={"Content-Length": "not-a-number"}),
                 ), \
                 mock.patch("streamkeep.updater.sys", create=True) as mock_sys:
                mock_sys.executable = str(exe_path)
                mock_sys.frozen = True
                worker.run()

            app.processEvents()
            self.assertTrue(done_events)
            self.assertTrue(done_events[0][0], done_events[0][1])
            self.assertTrue((exe_path.parent / "StreamKeep.exe.new").exists())


if __name__ == "__main__":
    unittest.main()
