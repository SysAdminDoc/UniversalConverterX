import ftplib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamkeep.upload.ftp import FTPDestination
from streamkeep.upload.s3 import S3Destination


class _FakeFTP:
    def __init__(self):
        self.cwd_path = "/"
        self.existing = {"/"}
        self.connected = None
        self.logged_in = None
        self.closed = False

    def connect(self, host, port, timeout=None):
        self.connected = (host, port, timeout)

    def login(self, username, password):
        self.logged_in = (username, password)

    def _normalize(self, part):
        if part == "/":
            return "/"
        if part.startswith("/"):
            return part.rstrip("/") or "/"
        if self.cwd_path == "/":
            return f"/{part}".rstrip("/")
        return f"{self.cwd_path.rstrip('/')}/{part}".rstrip("/")

    def cwd(self, part):
        target = self._normalize(part)
        if target not in self.existing:
            raise ftplib.error_perm("550 missing")
        self.cwd_path = target

    def mkd(self, part):
        target = self._normalize(part)
        self.existing.add(target)

    def storbinary(self, command, file_obj, blocksize=65536, callback=None):
        while True:
            chunk = file_obj.read(blocksize)
            if not chunk:
                break
            if callback is not None:
                callback(chunk)
        self.command = command

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


class UploadAdapterTests(unittest.TestCase):
    def test_ftp_upload_normalizes_remote_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "clip.bin"
            file_path.write_bytes(b"streamkeep")
            fake_ftp = _FakeFTP()
            progress = []
            dest = FTPDestination(
                {
                    "host": " ftp.example.com ",
                    "port": "21",
                    "username": "alice",
                    "password": "secret",
                    "remote_dir": r"\\nested//clips\\",
                }
            )

            with mock.patch("streamkeep.upload.ftp.ftplib.FTP", return_value=fake_ftp):
                ok, msg = dest.upload(
                    str(file_path),
                    progress_cb=lambda sent, total: progress.append((sent, total)),
                )

            self.assertTrue(ok, msg)
            self.assertEqual(msg, "Uploaded to ftp://ftp.example.com/nested/clips/clip.bin")
            self.assertEqual(fake_ftp.connected, ("ftp.example.com", 21, 15))
            self.assertEqual(fake_ftp.logged_in, ("alice", "secret"))
            self.assertEqual(fake_ftp.cwd_path, "/nested/clips")
            self.assertEqual(fake_ftp.command, "STOR clip.bin")
            self.assertEqual(progress[-1], (file_path.stat().st_size, file_path.stat().st_size))
            self.assertTrue(fake_ftp.closed)

    def test_ftp_connection_reports_invalid_port_cleanly(self):
        dest = FTPDestination({"host": "ftp.example.com", "port": "not-a-port"})

        with mock.patch("streamkeep.upload.ftp.ftplib.FTP") as mock_ftp:
            ok, msg = dest.test_connection()

        self.assertFalse(ok)
        self.assertEqual(msg, "FTP port is invalid")
        mock_ftp.assert_not_called()

    def test_s3_validation_runs_before_boto3_import(self):
        dest = S3Destination(
            {
                "access_key": "key",
                "secret_key": "secret",
                "bucket": "archive",
            }
        )

        ok, msg = dest.upload("C:\\definitely-missing-file.bin")

        self.assertFalse(ok)
        self.assertEqual(msg, "File not found")

    def test_s3_connection_reports_missing_bucket_cleanly(self):
        dest = S3Destination({"access_key": "key", "secret_key": "secret"})

        ok, msg = dest.test_connection()

        self.assertFalse(ok)
        self.assertEqual(msg, "S3 bucket not configured")


if __name__ == "__main__":
    unittest.main()
