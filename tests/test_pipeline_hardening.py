import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.collector import _safe_http_url
from app.database import NewsDatabase
from app.newsroom import process_news, quality_headline, validate_news_copy
from scripts.auto_publish import _direct_fallback_content, _instagram_candidates


class PipelineHardeningTests(unittest.TestCase):
    def test_feed_url_must_be_http_or_https(self):
        self.assertTrue(_safe_http_url("https://example.com/story"))
        self.assertTrue(_safe_http_url("http://example.com/story"))
        self.assertFalse(_safe_http_url("javascript:alert(1)"))
        self.assertFalse(_safe_http_url("data:text/html,test"))
        self.assertFalse(_safe_http_url("/relative/path"))

    def test_incomplete_headline_is_rejected_or_rebuilt_from_complete_source(self):
        source = (
            "The government announced a new transport plan on Tuesday. "
            "Officials said the plan will add 120 buses across three districts. "
            "The first phase will begin next month."
        )
        self.assertEqual(quality_headline("Government announces plan for", source), "The government announced a new transport plan on Tuesday")
        self.assertFalse(validate_news_copy("Government announces plan for", "The government announced a new transport plan on Tuesday.", source)["passed"])

    def test_process_news_never_returns_incomplete_copy(self):
        source = (
            "The government announced a new transport plan on Tuesday. "
            "Officials said the plan will add 120 buses across three districts. "
            "The first phase will begin next month."
        )
        result = process_news("Government announces plan for", source)
        self.assertIsNotNone(result)
        self.assertTrue(validate_news_copy(result["headline"], result["summary"], result["article"])["passed"])
        self.assertNotIn("announces plan for", result["headline"].lower())

    def test_process_news_fails_closed_when_source_has_only_fragments(self):
        source = "Government announces a plan for. Officials said the move would."
        self.assertIsNone(process_news("Government announces plan for", source))

    def test_direct_fallback_still_runs_quality_gate(self):
        row = {"id": 1, "title": "A complete headline with enough words", "summary": "Too short."}
        self.assertFalse(_direct_fallback_content(row))

    def test_manual_queue_is_not_limited_to_latest_hundred(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = NewsDatabase(path=str(Path(tmp) / "news.db"))
            try:
                now = datetime.now(timezone.utc).isoformat()
                for item_id in range(1, 125):
                    db.conn.execute(
                        "INSERT INTO news_items "
                        "(id,source_name,source_type,title,url,normalized_url,url_hash,title_hash,collected_at,status,instagram_status,instagram_selected,fact_check_status) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            item_id, "Test", "rss", f"Story {item_id}",
                            f"https://example.com/{item_id}", f"https://example.com/{item_id}",
                            f"url-{item_id}", f"title-{item_id}", now, "published",
                            "pending", 1 if item_id == 1 else 0, "pending",
                        ),
                    )
                db.conn.commit()
                rows = _instagram_candidates(db, "manual", 1, datetime.now(timezone.utc))
                self.assertEqual([int(rows[0]["id"])], [1])
            finally:
                db.close()

    def test_instagram_candidates_only_use_published_stories_in_auto_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = NewsDatabase(path=str(Path(tmp) / "news.db"))
            try:
                now = datetime.now(timezone.utc).isoformat()
                for item_id, status in ((1, "pending"), (2, "published")):
                    db.conn.execute(
                        "INSERT INTO news_items "
                        "(id,source_name,source_type,title,url,normalized_url,url_hash,title_hash,collected_at,status,instagram_status,instagram_selected,fact_check_status) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            item_id, "Test", "rss", f"Story {item_id}",
                            f"https://example.com/{item_id}", f"https://example.com/{item_id}",
                            f"url-{item_id}", f"title-{item_id}", now, status,
                            "pending", 0, "pending",
                        ),
                    )
                db.conn.commit()
                rows = _instagram_candidates(db, "auto", 10, datetime.now(timezone.utc))
                self.assertEqual([int(x["id"]) for x in rows], [2])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
