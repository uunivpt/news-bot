import unittest
from unittest.mock import patch

from app.rss import collect_rss


class RSSCollectorTests(unittest.TestCase):
    def test_collect_rss_uses_bounded_http_request_and_limit(self):
        class Response:
            content = b"<rss/>"

            def raise_for_status(self):
                pass

        class Feed:
            bozo = False
            entries = [
                {
                    "title": f"Story {i}",
                    "link": f"https://example.com/{i}",
                    "published": "2026-10-05T00:00:00Z",
                    "summary": "Summary",
                    "id": str(i),
                }
                for i in range(3)
            ]

        with patch("app.rss.requests.get", return_value=Response()) as get,              patch("app.rss.feedparser.parse", return_value=Feed()):
            items = collect_rss({
                "name": "Example",
                "url": "https://example.com/feed.xml",
                "max_items": 2,
                "timeout_seconds": 7,
            })

        get.assert_called_once_with(
            "https://example.com/feed.xml",
            headers=unittest.mock.ANY,
            timeout=7,
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source_type, "rss")


if __name__ == "__main__":
    unittest.main()
