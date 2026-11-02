import os
import unittest
from unittest.mock import Mock, patch

from app import news_api
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
