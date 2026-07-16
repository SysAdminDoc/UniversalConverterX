import sys
import unittest

from streamkeep import dpapi


@unittest.skipUnless(sys.platform == "win32", "Windows DPAPI is required")
class DpapiTests(unittest.TestCase):
    def test_binary_round_trip_uses_entropy_bound_format(self):
        protected = dpapi.encrypt(b"cookie-secret", "StreamKeep test")

        self.assertTrue(protected.startswith(dpapi.MAGIC))
        self.assertNotIn(b"cookie-secret", protected)
        self.assertEqual(dpapi.decrypt(protected), b"cookie-secret")

    def test_text_round_trip_uses_versioned_prefix(self):
        protected = dpapi.encrypt_text("credential-secret", "StreamKeep test")

        self.assertTrue(protected.startswith(dpapi.TEXT_PREFIX))
        self.assertNotIn("credential-secret", protected)
        self.assertEqual(dpapi.decrypt_text(protected), "credential-secret")

    def test_changed_entropy_cannot_decrypt_ciphertext(self):
        protected = dpapi.encrypt(b"purpose-bound", "StreamKeep test")
        original_entropy = dpapi._ENTROPY
        try:
            dpapi._ENTROPY = bytes(reversed(original_entropy))
            with self.assertRaises(OSError):
                dpapi.decrypt(protected)
        finally:
            dpapi._ENTROPY = original_entropy


if __name__ == "__main__":
    unittest.main()
