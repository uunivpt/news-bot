import unittest

from api.index import _public_title, _rank_public, _public_image_path, _safe_public_image_origin


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

    def test_public_story_images_use_same_origin_proxy(self):
        self.assertEqual(_public_image_path({"id": 42}), "/api/image/42")
        self.assertEqual(_public_image_path({"id": None}), "")

    def test_image_proxy_rejects_unsafe_origins(self):
        self.assertTrue(_safe_public_image_origin("https://static.example.com/photo.jpg"))
        self.assertFalse(_safe_public_image_origin("http://127.0.0.1/private"))
        self.assertFalse(_safe_public_image_origin("http://localhost/private"))
        self.assertFalse(_safe_public_image_origin("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
