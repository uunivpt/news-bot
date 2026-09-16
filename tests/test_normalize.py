import unittest

from app.normalize import fingerprint, normalize_text, normalize_url


class NormalizeTests(unittest.TestCase):
    def test_text_normalization(self):
        self.assertEqual(normalize_text("  Hello   WORLD  "), "hello world")

    def test_url_normalization(self):
        self.assertEqual(normalize_url("HTTPS://Example.COM/story/"), "https://example.com/story")

    def test_same_values_have_same_fingerprint(self):
        self.assertEqual(
            fingerprint("https://example.com/a/", "Breaking News"),
            fingerprint("HTTPS://EXAMPLE.COM/a", " breaking   news "),
        )


if __name__ == "__main__":
    unittest.main()
