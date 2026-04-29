import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import QCoreApplication

from streamkeep.upload.base import UploadDestination
from streamkeep.upload.upload_worker import UploadWorker


class UploadRuntimeTests(unittest.TestCase):
    def test_builtin_upload_adapters_are_registered_in_clean_process(self):
        repo_root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import json;"
                    "from streamkeep.upload import UploadDestination;"
                    "print(json.dumps(sorted(UploadDestination.all_adapters().keys())))"
                ),
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(
            json.loads(proc.stdout.strip()),
            ["FTP / SFTP", "S3 / B2 / MinIO", "WebDAV"],
        )

    def test_upload_worker_emits_failure_when_adapter_crashes(self):
        app = QCoreApplication.instance() or QCoreApplication([])
        done_events = []
        log_events = []

        class BrokenAdapter:
            def __init__(self, config):
                self.config = config

            def upload(self, file_path, metadata=None, progress_cb=None):
                raise RuntimeError("boom")

        worker = UploadWorker("Broken", {}, "C:/tmp/file.bin")
        worker.done.connect(lambda ok, msg: done_events.append((ok, msg)))
        worker.log.connect(log_events.append)

        with mock.patch.object(
            UploadDestination,
            "all_adapters",
            return_value={"Broken": BrokenAdapter},
        ):
            worker.run()

        app.processEvents()
        self.assertEqual(len(done_events), 1)
        self.assertFalse(done_events[0][0])
        self.assertIn("upload crashed", done_events[0][1])
        self.assertTrue(any("[UPLOAD] FAIL:" in msg for msg in log_events))


if __name__ == "__main__":
    unittest.main()
