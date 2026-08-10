"""Unit tests for the shared UniversalConverterX sidecar primitives."""

from __future__ import annotations

import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ucx_sidecar as u  # noqa: E402


class RunTimeoutTests(unittest.TestCase):
    def test_success_path_returns_completed_process(self):
        result = u.run([sys.executable, "-c", "print('hi')"], timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hi", result.stdout)

    def test_timeout_raises_subprocess_timeout(self):
        with self.assertRaises(u.SubprocessTimeout) as ctx:
            u.run(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout=0.3,
            )
        self.assertIn("timeout", str(ctx.exception).lower())

    def test_default_timeout_is_applied(self):
        # The stdlib default is None (wait forever); the wrapper must always
        # pass a concrete ceiling.
        self.assertEqual(u.DEFAULT_SUBPROCESS_TIMEOUT, 600)

    def test_nonzero_exit_is_not_raised_without_check(self):
        result = u.run([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=30)
        self.assertEqual(result.returncode, 3)

    def test_check_true_raises_on_nonzero_exit(self):
        import subprocess
        with self.assertRaises(subprocess.CalledProcessError):
            u.run(
                [sys.executable, "-c", "import sys; sys.exit(4)"],
                timeout=30,
                check=True,
            )


class SafeZipExtractionTests(unittest.TestCase):
    def test_extracts_members_under_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "archive.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("nested/result.txt", "ok")

            with zipfile.ZipFile(archive_path) as archive:
                count = u.safe_zip_extractall(archive, root / "dest")

            self.assertEqual(count, 1)
            self.assertEqual((root / "dest" / "nested" / "result.txt").read_text(), "ok")

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "archive.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", "escape")

            with self.assertRaises(ValueError):
                with zipfile.ZipFile(archive_path) as archive:
                    u.safe_zip_extractall(archive, root / "dest")
            self.assertFalse((root / "outside.txt").exists())

    def test_rejects_zip_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "archive.zip"
            info = zipfile.ZipInfo("link")
            info.external_attr = (0o120777 & 0xFFFF) << 16
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(info, "target")

            with self.assertRaises(ValueError):
                with zipfile.ZipFile(archive_path) as archive:
                    u.safe_zip_extractall(archive, root / "dest")

    def test_rejects_oversized_zip_member_before_writing(self):
        info = zipfile.ZipInfo("huge.bin")
        info.file_size = u.MAX_ARCHIVE_MEMBER_BYTES + 1
        info.compress_size = 1

        class Archive:
            def infolist(self):
                return [info]

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                u.safe_zip_extractall(Archive(), Path(temp) / "dest")


class SafeTarExtractionTests(unittest.TestCase):
    def test_rejects_oversized_tar_member_before_writing(self):
        info = tarfile.TarInfo("huge.bin")
        info.size = u.MAX_ARCHIVE_MEMBER_BYTES + 1

        class Archive:
            def getmembers(self):
                return [info]

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                u.safe_tar_extractall(Archive(), Path(temp) / "dest")


if __name__ == "__main__":
    unittest.main()
