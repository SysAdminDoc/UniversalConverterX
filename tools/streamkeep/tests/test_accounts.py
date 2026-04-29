import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamkeep import accounts


class AccountTests(unittest.TestCase):
    def test_set_credential_preserves_existing_extra_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "library.db"
            with mock.patch.object(accounts, "DB_PATH", db_path), mock.patch.object(
                accounts, "CONFIG_DIR", Path(tmpdir)
            ):
                accounts.set_extra("twitch", {"region": "us"})
                accounts.set_credential("twitch", "secret-token")
                extra = accounts.get_extra("twitch")
                cred = accounts.get_credential("twitch")

            self.assertEqual(extra, {"region": "us"})
            self.assertEqual(cred, "secret-token")

    def test_set_extra_creates_row_when_platform_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "library.db"
            with mock.patch.object(accounts, "DB_PATH", db_path), mock.patch.object(
                accounts, "CONFIG_DIR", Path(tmpdir)
            ):
                accounts.set_extra("kick", {"header": "x-test"})
                extra = accounts.get_extra("kick")
                platforms = accounts.list_platforms()

            self.assertEqual(extra, {"header": "x-test"})
            self.assertIn("kick", platforms)


if __name__ == "__main__":
    unittest.main()
