import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import meta_instagram, news_api
from app.image_acquisition import acquire_story_image
from app.website_monitor import collect_website


class ReliabilityTests(unittest.TestCase):
    @patch.dict(os.environ, {"NEWSDATA_API_KEY": "test"})
    @patch("app.news_api._get_json", return_value={"status": "success", "results": []})
    def test_geographic_category_is_not_sent_to_newsdata(self, fetch):
        news_api.collect_newsdata({"name": "India", "category": "india", "country": "in"})
        self.assertNotIn("category", fetch.call_args.kwargs["params"])
        self.assertEqual(fetch.call_args.kwargs["params"]["country"], "in")

    @patch.dict(os.environ, {"NEWSAPI_KEY": ""})
    def test_missing_key_is_visible(self):
        with self.assertRaisesRegex(RuntimeError, "key is missing"):
            news_api.collect_newsapi({})

    @patch("app.website_monitor._fetch", return_value=None)
    def test_blocked_website_is_not_reported_as_empty_success(self, fetch):
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            collect_website({"name": "Blocked", "url": "https://example.org"})

    @patch("app.meta_instagram._resolve_from_token", return_value="correct-id")
    def test_instagram_resolution_is_shared_by_new_and_retry_paths(self, resolve):
        meta_instagram._resolve_instagram_user.cache_clear()
        for _ in range(2):
            self.assertEqual(meta_instagram._resolve_instagram_user("https://graph.instagram.com/v25.0", "token", "stale"), "correct-id")
        resolve.assert_called_once()
        meta_instagram._resolve_instagram_user.cache_clear()

    @patch("app.image_acquisition._download_and_validate")
    @patch("app.image_acquisition._score_candidate", return_value=50)
    @patch("app.image_acquisition._openverse_search")
    def test_image_uses_second_candidate_after_first_fails(self, search, score, download):
        search.return_value = [dict(url=f"https://example.org/{n}.jpg", foreign_landing_url="https://example.org/photo", license="cc0") for n in (1, 2)]
        download.side_effect = [RuntimeError("403"), (1280, 720)]
        with tempfile.TemporaryDirectory() as tmp:
            result = acquire_story_image({"title": "India Pakistan border conflict"}, tmp)
        self.assertEqual(result["image_url"], "https://example.org/2.jpg")
        self.assertEqual(download.call_count, 2)

    @patch("app.image_acquisition._download_and_validate", side_effect=RuntimeError("404"))
    @patch("app.image_acquisition._score_candidate", return_value=50)
    @patch("app.image_acquisition._openverse_search")
    def test_all_broken_images_return_text_only_metadata(self, search, score, download):
        search.return_value = [dict(url="https://example.org/broken.jpg", foreign_landing_url="https://example.org/photo", license="cc0")]
        with tempfile.TemporaryDirectory() as tmp:
            result = acquire_story_image({"title": "India Pakistan border conflict"}, tmp)
        self.assertEqual(result["image_url"], "")
        self.assertEqual(result["image_local_path"], "")
