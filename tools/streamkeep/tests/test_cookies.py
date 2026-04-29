import unittest

from streamkeep import cookies


class CookieTests(unittest.TestCase):
    def test_sanitize_cookie_field_strips_row_breakers(self):
        cleaned = cookies._sanitize_cookie_field("a\tb\r\nc")
        self.assertEqual(cleaned, "a b c")


if __name__ == "__main__":
    unittest.main()
