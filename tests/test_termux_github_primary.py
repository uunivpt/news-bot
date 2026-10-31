import os
import unittest
from unittest.mock import patch

from api import index as api
from app.database import DatabaseUnavailable

STORY = {
    "id": 123456789,
    "title": "Published newsroom report with a verified original source",
    "url": "https://example.org/news",
    "source_name": "Original publisher",
    "source_type": "rss",
    "summary": "A verified source published details of the newly released report today.",
    "published_at": "2026-10-31T08:50:51+00:00",
    "category": "india",
    "public_source": True,
    "status": "published",
}


class TermuxGithubPrimaryTests(unittest.TestCase):
    def setUp(self):
        self.client = api.app.test_client()

    def test_vercel_never_initializes_postgres_even_with_legacy_secret(self):
        with patch.dict(os.environ, {
            "VERCEL": "1",
            "DATABASE_3URL": "postgresql://legacy.invalid/not-used",
        }), patch.object(api, "NewsDatabase") as initialize:
            with self.assertRaises(DatabaseUnavailable):
                api.db()
        initialize.assert_not_called()

    def test_website_health_reports_healthy_github_public_feed(self):
        with patch.dict(os.environ, {"VERCEL": "1"}), \
             patch.object(api, "_snapshot_rows", return_value=[STORY]), \
             patch.object(api, "NewsDatabase") as initialize:
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["ok"])
        self.assertEqual(response.json["mode"], "github_feed")
        self.assertEqual(response.json["storage"], "termux")
        self.assertEqual(response.json["delivery"], "github")
        initialize.assert_not_called()

    def test_health_fails_closed_when_feed_is_empty(self):
        with patch.dict(os.environ, {"VERCEL": "1"}), \
             patch.object(api, "_snapshot_rows", return_value=[]):
            response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json["ok"])

    def test_api_news_uses_published_feed_without_postgres(self):
        with patch.dict(os.environ, {"VERCEL": "1"}), \
             patch.object(api, "_snapshot_rows", return_value=[STORY]), \
             patch.object(api, "NewsDatabase") as initialize:
            response = self.client.get("/api/news?category=india&limit=5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-News-Mode"), "snapshot")
        self.assertEqual(response.json[0]["title"], STORY["title"])
        initialize.assert_not_called()


    def test_public_admin_overview_identifies_termux_storage(self):
        with self.client.session_transaction() as session:
            session["admin_user"] = "owner"
            session["admin_scope"] = "recovery"
        with patch.dict(os.environ, {"VERCEL": "1"}), \
             patch.object(api, "_snapshot_rows", return_value=[STORY]), \
             patch.object(api, "NewsDatabase") as initialize:
            response = self.client.get("/api/admin/workspace")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["mode"], "snapshot")
        self.assertEqual(response.json["data_origin"], "termux_github")
        self.assertTrue(response.json["access"]["read_only"])
        initialize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
