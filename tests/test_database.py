import tempfile
import unittest
from pathlib import Path

from app.database import NewsDatabase
from app.models import NewsItem


class DatabaseTests(unittest.TestCase):

    def test_admin_activity_and_instagram_queue_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = NewsDatabase(str(Path(tmp) / "news.db"))
            db.log_activity("owner", "instagram.queue", 7, "queued")
            activity = [dict(x) for x in db.recent_activity(10)]
            self.assertEqual(activity[0]["action"], "instagram.queue")
            self.assertEqual(activity[0]["item_id"], 7)
            self.assertEqual(db.next_instagram_queue_order(), 1)
            db.close()

    def test_duplicate_url_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = NewsDatabase(str(Path(tmp) / "news.db"))
            item = NewsItem("Test", "rss", "Story", "https://example.com/story")
            self.assertTrue(db.insert(item))
            self.assertFalse(db.insert(item))
            self.assertEqual(db.count(), 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
