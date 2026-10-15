import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import psycopg

from api import index as api
from app.database import NewsDatabase, DatabaseUnavailable, _active_database_target
from app.models import NewsItem
from app.advanced_ops import find_duplicate_story
from app.phase_system import cluster_stories
from scripts.check_provider_health import check_database
from scripts import offline_instagram


class ProviderRecoveryTests(unittest.TestCase):
    def test_production_uses_new_project_and_refuses_previous_project(self):
        new = "postgresql://user:secret@ep-bold-recipe-b5iqrmwg-pooler.c-7.us-east-2.aws.neon.tech/neondb"
        old = "postgresql://user:secret@ep-steep-rice-b5dvvhhb-pooler.c-7.us-east-2.aws.neon.tech/neondb"
        self.assertTrue(_active_database_target(new))
        self.assertFalse(_active_database_target(old))
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "DATABASE_URL": old}), \
             patch("psycopg.connect") as connect:
            with self.assertRaisesRegex(DatabaseUnavailable, "politics 3"):
                NewsDatabase()
        connect.assert_not_called()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = NewsDatabase(str(Path(self.tmp.name) / "news.db"))
        self.db.insert(NewsItem("Example", "rss", "Regional council approves new transport funding", "https://example.org/transport", summary="The council approved new funding for regional transport services."))
        self.db.update(1, status="published", bot_article="Full article payload " * 5000,
                       ai_article="Internal text " * 5000, instagram_error="Private internal error")
        api._PUBLIC_RATE.clear()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_identity_queries_do_not_fetch_article_payloads_and_still_cluster(self):
        queries = []
        self.db.conn.set_trace_callback(queries.append)
        rows = [dict(r) for r in self.db.latest_identities()]
        self.assertEqual(set(rows[0]), {"id", "title", "source_name", "url"})
        self.assertEqual(cluster_stories(self.db), 1)
        duplicate = find_duplicate_story(self.db, 2, rows[0]["title"])
        self.assertEqual(duplicate[1]["id"], 1)
        reads = [q for q in queries if "FROM news_items" in q]
        self.assertTrue(reads)
        self.assertTrue(all("SELECT *" not in q for q in reads))

    def test_public_lists_do_not_transfer_private_article_or_instagram_fields(self):
        with patch.object(api, "db", return_value=self.db), patch.object(self.db, "close"), \
             patch.object(self.db, "latest", side_effect=AssertionError("Full-row listing must not be used")):
            client = api.app.test_client()
            for path in ("/api/search?q=council", "/api/breaking", "/api/trending"):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("Full article payload", response.get_data(as_text=True))
                self.assertNotIn("Private internal error", response.get_data(as_text=True))
        self.assertNotIn("bot_article", dict(self.db.trending()[0]))

    def test_coverage_uses_all_rows_without_fetching_articles(self):
        self.assertEqual(self.db.published_coverage(), {"published": 1, "with_article": 1, "with_image": 0})
        self.db.update(1, bot_article="", image_url="https://example.org/photo.jpg")
        self.assertEqual(self.db.published_coverage(), {"published": 1, "with_article": 0, "with_image": 1})

    def test_health_uses_publication_date_when_new_project_ids_are_different(self):
        self.db.update(1, published_at_site="2026-10-15T06:30:00+00:00")
        self.db.insert(NewsItem("Example", "rss", "An older source brief with a newer insertion ID", "https://example.org/older"))
        self.db.update(2, status="published", published_at_site="2026-10-15T05:00:00+00:00")
        self.assertEqual(self.db.newest_public()["id"], 1)
        with patch.object(api, "db", return_value=self.db), patch.object(self.db, "close"):
            response = api.app.test_client().get("/api/health")
        self.assertEqual(response.json["latest_published_at"], "2026-10-15T06:30:00+00:00")

    def test_database_quota_report_does_not_disclose_connection_credentials(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://private:secret@private-host/db"}), \
             patch("scripts.check_provider_health.psycopg.connect", side_effect=psycopg.OperationalError("private-host secret: exceeded the quota")), \
             contextlib.redirect_stdout(output):
            self.assertFalse(check_database())
        self.assertIn("quota exhausted", output.getvalue())
        self.assertNotIn("secret", output.getvalue())
        self.assertNotIn("private-host", output.getvalue())

    def test_invalid_meta_auth_stops_offline_worker_before_fetch_or_render(self):
        with patch("scripts.check_meta_access.main", return_value=3), \
             patch.object(offline_instagram, "prepare_story") as prepare, \
             patch.object(offline_instagram, "render_remotion_reel") as render, \
             patch.object(offline_instagram, "upload_video") as upload:
            with self.assertRaisesRegex(RuntimeError, "Reauthorize"):
                offline_instagram.main()
        prepare.assert_not_called()
        render.assert_not_called()
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
