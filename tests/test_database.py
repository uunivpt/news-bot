import tempfile
import unittest
from pathlib import Path

from app.database import NewsDatabase
from app.models import NewsItem


class DatabaseTests(unittest.TestCase):
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
