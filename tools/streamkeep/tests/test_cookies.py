import unittest
import tempfile
from pathlib import Path
from unittest import mock

from streamkeep import cookies


class CookieTests(unittest.TestCase):
    def test_sanitize_cookie_field_strips_row_breakers(self):
        cleaned = cookies._sanitize_cookie_field("a\tb\r\nc")
        self.assertEqual(cleaned, "a b c")

    def test_dpapi_failure_does_not_replace_existing_cookie_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cookie_path = Path(tmpdir) / "cookies.txt"
            cookie_path.write_bytes(b"existing-protected-value")
            with mock.patch.object(cookies, "CONFIG_DIR", Path(tmpdir)), mock.patch.object(
                cookies, "COOKIES_FILE", cookie_path
            ), mock.patch.object(
                cookies.dpapi, "encrypt", side_effect=OSError("DPAPI denied")
            ):
                with self.assertRaises(OSError):
                    cookies._write_encrypted_or_plain(b"new plaintext cookies")

            self.assertEqual(cookie_path.read_bytes(), b"existing-protected-value")

    def test_plaintext_cookie_store_is_not_returned_when_migration_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cookie_path = Path(tmpdir) / "cookies.txt"
            cookie_path.write_bytes(b"legacy plaintext cookies")
            with mock.patch.object(cookies, "CONFIG_DIR", Path(tmpdir)), mock.patch.object(
                cookies, "COOKIES_FILE", cookie_path
            ), mock.patch.object(
                cookies.dpapi, "encrypt", side_effect=OSError("DPAPI denied")
            ):
                result = cookies.cookies_file_path()

            self.assertEqual(result, "")
            self.assertEqual(cookie_path.read_bytes(), b"legacy plaintext cookies")


if __name__ == "__main__":
    unittest.main()
