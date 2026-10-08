import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.collector import _safe_http_url
from app.database import NewsDatabase
from app.newsroom import process_news, quality_headline, validate_news_copy
from scripts.auto_publish import _direct_fallback_content, _instagram_candidates, _india_reel_due, _website_candidates, caption


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

    def test_reel_caption_uses_category_and_source_not_generic_tags(self):
        message = caption({
            "title": "Government announces transport improvements for the region",
            "summary": "Officials confirmed the new service will start next month.",
            "category": "india",
            "source_name": "Example Newswire",
            "url": "https://example.org/transport",
        })
        self.assertIn("#IndiaNews", message)
        self.assertIn("#PoliticsHub", message)
        self.assertIn("Source: Example Newswire", message)
        self.assertIn("https://example.org/transport", message)
        self.assertNotIn("#reel #update #news #politics #global", message)
        self.assertLessEqual(len(message), 2200)

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


    def test_website_candidates_prioritize_fresh_india_without_old_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = NewsDatabase(path=str(Path(tmp) / "news.db"))
            try:
                now = datetime.now(timezone.utc).isoformat()
                rows = [(1, "india"), (2, "world"), (3, "politics"), (100, "world"), (101, "india"), (102, "technology"), (103, "india")]
                for item_id, category in rows:
                    db.conn.execute(
                        "INSERT INTO news_items "
                        "(id,source_name,source_type,title,url,normalized_url,url_hash,title_hash,collected_at,status,category,instagram_status,fact_check_status) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (item_id, "Test", "rss", f"Story {item_id}", f"https://example.com/{item_id}", f"https://example.com/{item_id}", f"url-{item_id}", f"title-{item_id}", now, "pending", category, "pending", "pending"),
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
    def test_pending_instagram_retry_backoff_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = NewsDatabase(path=str(Path(tmp) / "news.db"))
            try:
                now = datetime.now(timezone.utc)
                from datetime import timedelta
                future = (now + timedelta(minutes=20)).isoformat()
                db.conn.execute(
                    "INSERT INTO news_items "
                    "(id,source_name,source_type,title,url,normalized_url,url_hash,title_hash,collected_at,status,instagram_status,instagram_attempts,instagram_next_retry_at,fact_check_status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        1, "Test", "rss", "Retry story", "https://example.com/retry",
                        "https://example.com/retry", "retry-url", "retry-title",
                        now.isoformat(), "published", "pending", 1, future, "pending",
                    ),
                )
                db.conn.commit()
                rows = _instagram_candidates(db, "auto", 10, now)
                self.assertEqual(rows, [])
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

    def test_auto_instagram_prioritizes_india_when_recent_reels_have_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = NewsDatabase(path=str(Path(tmp) / "news.db"))
            try:
                now = datetime.now(timezone.utc).isoformat()
                for item_id in (10, 11, 12):
                    db.conn.execute(
                        "INSERT INTO news_items "
                        "(id,source_name,source_type,title,url,normalized_url,url_hash,title_hash,collected_at,status,category,instagram_status,instagram_published_at,fact_check_status) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            item_id, "Test", "rss", f"Published world {item_id}",
                            f"https://example.com/pub-{item_id}", f"https://example.com/pub-{item_id}",
                            f"pub-url-{item_id}", f"pub-title-{item_id}", now, "published",
                            "world", "published", now, "pending",
                        ),
                    )
                for item_id, category in ((1, "world"), (2, "india")):
                    db.conn.execute(
                        "INSERT INTO news_items "
                        "(id,source_name,source_type,title,url,normalized_url,url_hash,title_hash,collected_at,status,category,instagram_status,instagram_selected,fact_check_status) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            item_id, "Test", "rss", f"Candidate {item_id}",
                            f"https://example.com/{item_id}", f"https://example.com/{item_id}",
                            f"url-{item_id}", f"title-{item_id}", now, "published",
                            category, "pending", 0, "pending",
                        ),
                    )
                db.conn.commit()
                self.assertTrue(_india_reel_due(db, 3))
                rows = _instagram_candidates(db, "auto", 1, datetime.now(timezone.utc))
                self.assertEqual([int(x["id"]) for x in rows], [2])

                db.conn.execute(
                    "INSERT INTO news_items "
                    "(id,source_name,source_type,title,url,normalized_url,url_hash,title_hash,collected_at,status,category,instagram_status,instagram_published_at,fact_check_status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        13, "Test", "rss", "Recent India Reel", "https://example.com/13",
                        "https://example.com/13", "url-13", "title-13", now, "published",
                        "india", "published", now, "pending",
                    ),
                )
                db.conn.commit()
                self.assertFalse(_india_reel_due(db, 3))
                rows = _instagram_candidates(db, "auto", 1, datetime.now(timezone.utc))
                self.assertEqual([int(x["id"]) for x in rows], [1])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
