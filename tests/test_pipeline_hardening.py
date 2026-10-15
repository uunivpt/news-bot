import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.collector import _safe_http_url
from app.database import NewsDatabase
from app.newsroom import process_news, quality_headline, validate_news_copy
from scripts.auto_publish import _direct_fallback_content, _website_candidates


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


    def test_website_candidates_prioritize_fresh_india_without_old_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = NewsDatabase(path=str(Path(tmp) / "news.db"))
            try:
                now = datetime.now(timezone.utc).isoformat()
                rows = [(1, "india"), (2, "world"), (3, "politics"), (100, "world"), (101, "india"), (102, "technology"), (103, "india")]
                for item_id, category in rows:
                    db.conn.execute(
                        "INSERT INTO news_items "
                        "(id,source_name,source_type,title,url,normalized_url,url_hash,title_hash,collected_at,status,category,fact_check_status) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (item_id, "Test", "rss", f"Story {item_id}", f"https://example.com/{item_id}", f"https://example.com/{item_id}", f"url-{item_id}", f"title-{item_id}", now, "pending", category, "pending"),
                    )
                db.conn.commit()
                selected = _website_candidates(db, 4)
                ids = [int(row["id"]) for row in selected]
                self.assertEqual(ids[0], 103)
                self.assertIn(101, ids)
                self.assertIn(102, ids)
                self.assertNotIn(1, ids)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
