import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.publish_mobile_reviewed import publish


NOW = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)


def reviewed(id=455, approved=True, age_hours=3):
    return {
        "id": id,
        "title": "Regional transport authority announces verified new services",
        "source_name": "Official publisher",
        "source_type": "rss",
        "url": f"https://example.org/news/item-{id}",
        "summary": "A regional transport authority confirmed new public services in its official release today.",
        "bot_summary": "A regional transport authority confirmed new public services in its official release today.",
        "published_at": (NOW - timedelta(hours=age_hours)).isoformat(),
        "published_at_site": (NOW - timedelta(hours=age_hours)).isoformat(),
        "status": "published",
        "public_source": True,
        "approved_at": NOW.isoformat() if approved else None,
        "fact_check_status": "reviewed" if approved else "pending",
    }


class ImmediateApprovedFeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "public").mkdir(parents=True)
        self.feed = self.root / "public/news-data.json"
        self.mobile = self.root / "public/mobile-reviewed.json"
        self.feed.write_text("[]\n", encoding="utf-8")

    def test_approved_mobile_story_published_without_neon(self):
        self.mobile.write_text(json.dumps([reviewed()]), encoding="utf-8")
        result = publish(self.root, now=NOW)
        self.assertEqual(result["inserted"], 1)
        rows = json.loads(self.feed.read_text())
        self.assertEqual(rows[0]["id"], 455)
        self.assertEqual(rows[0]["status"], "published")
        self.assertTrue((self.root / "app/data/public-archive.json.gz").exists())
        self.assertNotIn("approved_at", rows[0])  # No private approval metadata in public output.

    def test_refuse_pending_fact_check_and_preserve_website(self):
        old = self.feed.read_bytes()
        self.mobile.write_text(json.dumps([reviewed(approved=False)]), encoding="utf-8")
        with self.assertRaises(ValueError):
            publish(self.root, now=NOW)
        self.assertEqual(self.feed.read_bytes(), old)

    def test_no_mobile_file_is_noop(self):
        before = self.feed.read_bytes()
        self.assertEqual(publish(self.root, now=NOW)["inserted"], 0)
        self.assertEqual(self.feed.read_bytes(), before)

    def test_no_duplicate_when_workflow_runs_twice(self):
        self.mobile.write_text(json.dumps([reviewed()]), encoding="utf-8")
        self.assertEqual(publish(self.root, now=NOW)["inserted"], 1)
        before = self.feed.read_bytes()
        self.assertEqual(publish(self.root, now=NOW)["inserted"], 0)
        self.assertEqual(self.feed.read_bytes(), before)

    def test_stale_approved_story_is_not_falsely_republished(self):
        self.mobile.write_text(json.dumps([reviewed(age_hours=24 * 8)]), encoding="utf-8")
        self.assertEqual(publish(self.root, now=NOW)["inserted"], 0)
        self.assertEqual(json.loads(self.feed.read_text()), [])

    def test_approved_news_is_also_preserved_when_homepage_is_full(self):
        # Existing feed has 140 newer stories; their earlier public URLs do
        # not get removed from archive by a newly approved phone publication.
        public = [
            {**reviewed(id=i), "published_at": NOW.isoformat(),
             "published_at_site": NOW.isoformat(), "status": "published"}
            for i in range(1000, 1140)
        ]
        self.feed.write_text(json.dumps(public), encoding="utf-8")
        self.mobile.write_text(json.dumps([reviewed()]), encoding="utf-8")
        result = publish(self.root, now=NOW)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(len(json.loads(self.feed.read_text())), 140)
        import gzip
        with gzip.open(self.root / "app/data/public-archive.json.gz", "rt") as f:
            archived = json.load(f)
        self.assertIn(455, {row["id"] for row in archived})


if __name__ == "__main__":
    unittest.main()
