import sqlite3
import unittest

from app.advanced_system import (
    ensure_schema, score_story, select_layout, similarity, attach_event,
    publish_lock, is_published, mark_published, source_reliability,
    historical_analytics, record_source, alert,
)


class DB:
    _postgres = False

    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row


class AdvancedSystemTests(unittest.TestCase):
    def test_layout_selector_is_64_and_deterministic(self):
        a = select_layout("politics", "Government announces new policy", 101, False, True)
        b = select_layout("politics", "Government announces new policy", 101, False, True)
        self.assertEqual(a, b)
        self.assertGreaterEqual(a["variant"], 0)
        self.assertLess(a["variant"], 64)
        self.assertIn(a["family"], {"editorial", "split", "quote", "minimal", "dark"})

    def test_similarity_and_scoring(self):
        self.assertEqual(similarity("India announces new policy", "India announces new policy"), 1.0)
        db = DB()
        ensure_schema(db)
        row = {
            "id": 1,
            "title": "Breaking government policy update",
            "summary": "Major update",
            "category": "politics",
            "created_at": "2026-10-01T00:00:00+00:00",
        }
        result = score_story(db, row, source_count=3, verification="CONFIRMED", duplicate_risk=0)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertEqual(result["coverage"], 84)

    def test_event_and_zero_duplicate_lock(self):
        db = DB()
        ensure_schema(db)
        eid = attach_event(db, 1, "Government announces new policy", "politics", "Source A")
        self.assertTrue(eid)
        self.assertTrue(publish_lock(db, 1, "story-key-1"))
        self.assertFalse(publish_lock(db, 2, "story-key-1"))
        self.assertFalse(is_published(db, 1, "instagram"))
        mark_published(db, 1, "instagram", "https://example.test/reel.mp4")
        self.assertTrue(is_published(db, 1, "instagram"))

    def test_source_reliability_metrics(self):
        db = DB()
        ensure_schema(db)
        record_source(db, "Source A", success=True, coverage=True)
        record_source(db, "Source A", success=False, broken=True, coverage=False)
        result = source_reliability(db, "Source A")
        self.assertEqual(result["success_rate"], 50.0)
        self.assertEqual(result["broken_links"], 1)

    def test_historical_analytics_has_real_buckets(self):
        db = DB()
        ensure_schema(db)
        alert(db, "WARNING", "test", "step", 1, "example")
        result = historical_analytics(db, 30)
        self.assertEqual(result["counts"]["alerts"], 1)
        self.assertIsInstance(result["day"], dict)
        self.assertGreaterEqual(sum(result["day"].values()), 1)


if __name__ == "__main__":
    unittest.main()
