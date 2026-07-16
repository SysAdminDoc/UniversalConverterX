import unittest
from unittest import mock

from streamkeep import secrets


class SecretTests(unittest.TestCase):
    def test_try_protect_reports_failure_without_plaintext_fallback(self):
        with mock.patch.object(
            secrets.dpapi, "encrypt_text", side_effect=OSError("DPAPI denied")
        ):
            succeeded, protected, error = secrets.try_protect("sensitive-value")

        self.assertFalse(succeeded)
        self.assertIsNone(protected)
        self.assertIn("DPAPI protection failed", error)

    def test_config_protection_is_atomic_when_a_field_fails(self):
        config = {
            "webhook_url": "https://example.test/hook",
            "proxy": "user:password@example.test",
        }
        original = dict(config)
        with mock.patch.object(
            secrets.dpapi, "encrypt_text", side_effect=OSError("DPAPI denied")
        ):
            succeeded, _ = secrets.protect_config_fields(config)

        self.assertFalse(succeeded)
        self.assertEqual(config, original)


if __name__ == "__main__":
    unittest.main()
