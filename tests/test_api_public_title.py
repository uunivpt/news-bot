import unittest

from api.index import _public_title, _rank_public


class PublicTitleTests(unittest.TestCase):
    def test_public_title_normalizes_whitespace(self):
        self.assertEqual(_public_title("  India   announces   new policy  "), "India announces new policy")

    def test_public_title_strips_leading_punctuation(self):
        self.assertEqual(_public_title("***India announces new policy"), "India announces new policy")

    def test_public_feed_is_sorted_by_publication_time_not_id(self):
        rows = [
            {"id": 999, "title": "Older high id", "published_at": "2026-10-06T06:03:55+00:00", "status": "published"},
            {"id": 100, "title": "Newest lower id", "published_at_site": "2026-10-07T04:34:20+00:00", "status": "published"},
            {"id": 998, "title": "Middle item", "published_at": "06 Oct 2026 · 11:06", "status": "published"},
        ]
        ranked = _rank_public(rows)
        self.assertEqual([item["id"] for item in ranked], [100, 999, 998])


if __name__ == "__main__":
    unittest.main()
