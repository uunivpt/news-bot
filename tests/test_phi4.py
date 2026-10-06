import os
import unittest

from app import phi4


class Phi4EndpointTests(unittest.TestCase):
    def setUp(self):
        self.previous = os.environ.get("PHI4_ENDPOINT")

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("PHI4_ENDPOINT", None)
        else:
            os.environ["PHI4_ENDPOINT"] = self.previous

    def test_host_gets_v1_chat_completions(self):
        os.environ["PHI4_ENDPOINT"] = "https://example.test"
        self.assertEqual(
            phi4.endpoint(),
            "https://example.test/v1/chat/completions",
        )

    def test_v1_base_does_not_duplicate_v1(self):
        os.environ["PHI4_ENDPOINT"] = "https://example.test/v1/"
        self.assertEqual(
            phi4.endpoint(),
            "https://example.test/v1/chat/completions",
        )

    def test_full_endpoint_is_preserved(self):
        os.environ["PHI4_ENDPOINT"] = "https://example.test/v1/chat/completions"
        self.assertEqual(
            phi4.endpoint(),
            "https://example.test/v1/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
