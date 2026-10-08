"""Production batch should never post unverified or already-published news."""
import unittest
from datetime import datetime, timedelta, timezone

from scripts.publish_editorial_batch import select_stories


class TestEditorialBatch(unittest.TestCase):
    def test_select_only_source_verified_complete_fresh_not_already_posted(self):
        now = datetime.now(timezone.utc)
        sample = {
            "id": 1, "title": "Five states debate a change to national tax enforcement rules",
            "summary": "A " * 70, "bot_article": "Source-backed explanation. " * 30,
            "source_type": "editorial_verified", "editorial_pick": True,
            "public_source": True, "url": "https://example.com/article-1",
            "published_at": (now - timedelta(hours=1)).isoformat(),
        }
        rows = [sample, dict(sample, id=2, source_type="newsdata"),
                dict(sample, id=3, url="https://example.com/article-3", bot_article="short"),
                dict(sample, id=4, url="https://example.com/article-4",
                    published_at=(now - timedelta(days=4)).isoformat())]
        self.assertEqual(len(select_stories(rows, {"posts":[]}, now)), 1)
        self.assertEqual(select_stories(rows, {"posts":[{"url":sample["url"]}]}, now), [])
        self.assertEqual(select_stories(rows, {"posts":[]}, now, {sample["title"]+"\n\nAlready published"}), [])

if __name__ == "__main__":
    unittest.main()
