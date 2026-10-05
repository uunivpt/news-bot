import unittest

from api.index import _public_title


class PublicTitleTests(unittest.TestCase):
    def test_public_title_normalizes_whitespace(self):
        self.assertEqual(_public_title("  India   announces   new policy  "), "India announces new policy")

    def test_public_title_strips_leading_punctuation(self):
        self.assertEqual(_public_title("***India announces new policy"), "India announces new policy")


if __name__ == "__main__":
    unittest.main()
