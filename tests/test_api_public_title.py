import unittest

from api.index import _public_title, _rank_public, _public_image_path, _safe_public_image_origin, _is_source_supplied_image


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

    def test_public_story_images_require_explicit_public_domain_license(self):
        self.assertEqual(_public_image_path({"id": 42, "image_url": "https://source.example/photo.jpg", "image_source": ""}), "")
        self.assertEqual(_public_image_path({"id": 42, "image_url": "https://source.example/photo.jpg", "image_source": "article-source"}), "")
        self.assertEqual(_public_image_path({"id": 42, "image_url": "https://source.example/photo.jpg", "image_source": "article-source", "image_license": "CC0 1.0"}), "/api/image/42")
        self.assertEqual(_public_image_path({"id": 42, "image_url": "https://source.example/photo.jpg", "image_source": "article-source", "image_license": "PDM"}), "/api/image/42")
        self.assertEqual(_public_image_path({"id": 42, "image_url": "https://openverse.example/photo.jpg", "image_source": "Openverse", "image_license": "CC0"}), "")
        self.assertEqual(_public_image_path({"id": 42, "image_url": "", "image_source": "article-source", "image_license": "CC0"}), "")
        self.assertEqual(_public_image_path({"id": None, "image_url": "https://source.example/photo.jpg", "image_source": "article-source", "image_license": "CC0"}), "")

    def test_source_image_detection_requires_source_and_license(self):
        self.assertFalse(_is_source_supplied_image({"image_url": "https://source.example/photo.jpg", "image_source": ""}))
        self.assertFalse(_is_source_supplied_image({"image_url": "https://source.example/photo.jpg", "image_source": "article-source"}))
        self.assertTrue(_is_source_supplied_image({"image_url": "https://source.example/photo.jpg", "image_source": "article-source", "image_license": "cc0"}))
        self.assertTrue(_is_source_supplied_image({"image_url": "https://source.example/photo.jpg", "image_source": "article-source", "image_license": "PDM"}))
        self.assertFalse(_is_source_supplied_image({"image_url": "https://commons.example/photo.jpg", "image_source": "wikimedia", "image_license": "cc0"}))
        self.assertFalse(_is_source_supplied_image({"image_url": "", "image_source": "article-source", "image_license": "cc0"}))


    def test_public_list_query_does_not_transfer_full_articles(self):
        import tempfile
        from pathlib import Path
        from app.database import NewsDatabase
        with tempfile.TemporaryDirectory() as tmp:
            database=NewsDatabase(path=str(Path(tmp)/"public-list.db"))
            try:
                base=("Test Newswire","rss","A complete sample headline about regional infrastructure",
                      "https://example.org/news","https://example.org/news","test-hash","test-title",
                      "2026-10-08T06:00:00+00:00","published","Extended summary of the verified source.")
                database.conn.execute(
                    "INSERT INTO news_items (source_name,source_type,title,url,normalized_url,url_hash,title_hash,collected_at,status,summary,bot_article,category) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (*base[:9],base[9],"Full article text " * 500,"india")
                )
                database.conn.commit()
                cards=[dict(x) for x in database.latest_public(5,"india")]
                self.assertEqual(len(cards),1)
                self.assertIn("title",cards[0])
                self.assertIn("summary",cards[0])
                self.assertIn("image_source",cards[0])
                self.assertNotIn("bot_article",cards[0])
                self.assertNotIn("ai_article",cards[0])
                self.assertIn("bot_article",dict(database.get_by_id(cards[0]["id"],"published")))
            finally:database.close()

    def test_image_proxy_rejects_unsafe_origins(self):
        self.assertTrue(_safe_public_image_origin("https://static.example.com/photo.jpg"))
        self.assertFalse(_safe_public_image_origin("http://127.0.0.1/private"))
        self.assertFalse(_safe_public_image_origin("http://localhost/private"))
        self.assertFalse(_safe_public_image_origin("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
