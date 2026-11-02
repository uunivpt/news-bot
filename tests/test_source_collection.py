import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from app.collector import collect_once, load_sources
from app.database import NewsDatabase
from app.models import NewsItem
from app.source_collection import ensure_collection_schema, record_collection
from app import phone_collection


class SourceCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = NewsDatabase(str(Path(self.temporary.name) / "news.db"))

    def tearDown(self):
        self.database.close()
        self.temporary.cleanup()

    def checks(self):
        return {row["source_name"]: dict(row) for row in self.database.conn.execute(
            "SELECT * FROM ph_source_collection").fetchall()}

    def test_real_feed_collection_is_pending_and_duplicate_counts_are_honest(self):
        source = {"name": "TV9 Marathi - Maharashtra", "enabled": True}
        item = NewsItem(source["name"], "rss", "मराठी बातमी", "https://www.tv9marathi.com/maharashtra/example-123.html",
                        summary="A supplied publisher RSS excerpt", public_source=True)
        with patch("app.collector.COLLECTORS", {"rss": lambda source: [item]}), \
             patch("app.collector.cluster_stories"):
            self.assertEqual(collect_once({"rss": [source]}, self.database), (1, 0))
            first = self.checks()[source["name"]]
            self.assertEqual(first["status"], "healthy")
            self.assertEqual((first["item_count"], first["added_count"], first["duplicate_count"]), (1, 1, 0))
            self.assertEqual(collect_once({"rss": [source]}, self.database), (0, 1))
        latest = self.checks()[source["name"]]
        self.assertEqual((latest["added_count"], latest["duplicate_count"]), (0, 1))
        record = dict(self.database.conn.execute("SELECT * FROM news_items").fetchone())
        self.assertEqual(record["status"], "pending")
        self.assertEqual(record["fact_check_status"], "pending")
        self.assertIsNone(record["approved_at"])

    def test_failure_keeps_last_success_without_storing_exception_secrets(self):
        ensure_collection_schema(self.database)
        record_collection(self.database, "rss", "Example", status="healthy", item_count=0, added_count=0, duplicate_count=0)
        success = self.checks()["Example"]["last_success_at"]
        record_collection(self.database, "rss", "Example", status="failed",
                          error=ValueError("https://private.example/?apikey=DO-NOT-SAVE"))
        latest = self.checks()["Example"]
        self.assertEqual(latest["last_success_at"], success)
        self.assertEqual(latest["last_error"], "ValueError")
        self.assertNotIn("DO-NOT-SAVE", json.dumps(latest))
        self.assertIsNone(latest["item_count"])

    def test_missing_api_key_is_not_a_fake_success_or_network_call(self):
        source = {"name": "NewsData.io India", "enabled": True}
        with patch.dict(os.environ, {"NEWSDATA_API_KEY": ""}), \
             patch("app.collector.COLLECTORS", {"newsdata": lambda source: self.fail("Missing key must skip network")}), \
             patch("app.collector.cluster_stories"):
            self.assertEqual(collect_once({"newsdata": [source]}, self.database), (0, 0))
        row = self.checks()[source["name"]]
        self.assertEqual(row["status"], "not_configured")
        self.assertEqual(row["last_error"], "MissingAPIKey")
        self.assertIsNone(row["last_success_at"])

    def test_one_broken_feed_does_not_hide_other_sources_or_fake_zero_success(self):
        def fetch(source):
            if source["name"] == "Broken":
                raise ValueError("https://example.com/private?key=secret")
            return []

        with patch("app.collector.COLLECTORS", {"rss": fetch}), \
             patch("app.collector.cluster_stories"):
            self.assertEqual(collect_once({"rss": [{"name": "Broken"}, {"name": "Empty valid feed"}]}, self.database), (0, 0))
        checks = self.checks()
        self.assertEqual(checks["Broken"]["status"], "failed")
        self.assertEqual(checks["Broken"]["last_error"], "ValueError")
        self.assertIsNone(checks["Broken"]["last_success_at"])
        self.assertEqual(checks["Empty valid feed"]["status"], "healthy")
        self.assertEqual(checks["Empty valid feed"]["item_count"], 0)

    def test_disabled_and_separate_hindi_pipeline_do_not_get_attempts(self):
        with patch("app.collector.cluster_stories"):
            collect_once({"rss": [{"name": "Disabled", "enabled": False}],
                          "hindi_rss": [{"name": "External Hindi", "enabled": True}]}, self.database)
        self.assertEqual(self.checks(), {})

    def test_default_config_is_independent_of_current_working_directory(self):
        original = Path.cwd()
        try:
            os.chdir(self.temporary.name)
            config = load_sources()
        finally:
            os.chdir(original)
        enabled = {source["name"] for source in config["rss"] if source["enabled"]}
        self.assertTrue({"TV9 Marathi - Maharashtra", "ABP Majha - Maharashtra", "The Hindu - India"}.issubset(enabled))

    def test_phone_worker_refuses_cloud_or_nonlocal_databases(self):
        with patch.object(phone_collection.threading, "Thread") as thread:
            for values in [
                {"POLITICSHUB_LOCAL_ADMIN": "", "VERCEL": "", "DATABASE_3URL": "postgresql://postgres@127.0.0.1/politicshub"},
                {"POLITICSHUB_LOCAL_ADMIN": "1", "VERCEL": "1", "DATABASE_3URL": "postgresql://postgres@127.0.0.1/politicshub"},
                {"POLITICSHUB_LOCAL_ADMIN": "1", "VERCEL": "", "DATABASE_3URL": "postgresql://user@external.example/politicshub"},
                {"POLITICSHUB_LOCAL_ADMIN": "1", "VERCEL": "", "DATABASE_3URL": "postgresql://postgres@127.0.0.1/another_database"},
            ]:
                with patch.dict(os.environ, values):
                    self.assertFalse(phone_collection.start_collection_worker())
        thread.assert_not_called()

    def test_background_worker_is_singleton_and_recovers_after_cycle_failure(self):
        stop = threading.Event()
        seen = []

        def cycle(dsn):
            seen.append(dsn)
            if len(seen) == 1:
                raise OSError("private connection detail")
            stop.set()
            return (0, 0)

        with patch.object(phone_collection, "run_cycle", side_effect=cycle), \
             patch.object(phone_collection, "INTERVAL_SECONDS", 0):
            phone_collection._loop("local-test-dsn", stop)
        self.assertEqual(seen, ["local-test-dsn", "local-test-dsn"])
        with patch.dict(os.environ, {"POLITICSHUB_LOCAL_ADMIN": "1", "VERCEL": "", "DATABASE_3URL": "postgresql://postgres@127.0.0.1:5432/politicshub"}), \
             patch.object(phone_collection, "_worker") as running, \
             patch.object(phone_collection.threading, "Thread") as thread:
            running.is_alive.return_value = True
            self.assertFalse(phone_collection.start_collection_worker())
        thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
