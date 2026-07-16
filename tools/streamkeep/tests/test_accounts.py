import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sqlite3
from unittest import mock

from streamkeep import accounts


class AccountTests(unittest.TestCase):
    def test_set_credential_preserves_existing_extra_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "library.db"
            with mock.patch.object(accounts, "DB_PATH", db_path), mock.patch.object(
                accounts, "CONFIG_DIR", Path(tmpdir)
            ), mock.patch.object(
                accounts.dpapi,
                "encrypt_text",
                return_value="dpapi2:cHJvdGVjdGVk",
            ), mock.patch.object(
                accounts.dpapi,
                "decrypt_text",
                return_value="secret-token",
            ):
                accounts.set_extra("twitch", {"region": "us"})
                ok, _ = accounts.set_credential("twitch", "secret-token")
                extra = accounts.get_extra("twitch")
                cred = accounts.get_credential("twitch")

            self.assertTrue(ok)
            self.assertEqual(extra, {"region": "us"})
            self.assertEqual(cred, "secret-token")

    def test_dpapi_failure_preserves_existing_credential(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "library.db"
            with mock.patch.object(accounts, "DB_PATH", db_path), mock.patch.object(
                accounts, "CONFIG_DIR", Path(tmpdir)
            ):
                accounts._ensure_table()
                with closing(sqlite3.connect(str(db_path))) as db:
                    db.execute(
                        "INSERT INTO accounts (platform, credential, extra) VALUES (?,?,?)",
                        ("twitch", "b64:b2xkLXRva2Vu", "{}"),
                    )
                    db.commit()
                with mock.patch.object(
                    accounts.dpapi,
                    "encrypt_text",
                    side_effect=OSError("DPAPI denied"),
                ):
                    ok, message = accounts.set_credential("twitch", "new-token")
                with closing(sqlite3.connect(str(db_path))) as db:
                    stored = db.execute(
                        "SELECT credential FROM accounts WHERE platform='twitch'"
                    ).fetchone()[0]

            self.assertFalse(ok)
            self.assertIn("not saved", message)
            self.assertEqual(stored, "b64:b2xkLXRva2Vu")

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
