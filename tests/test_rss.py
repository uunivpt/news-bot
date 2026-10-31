import unittest
from unittest.mock import patch

from app.rss import collect_rss
from app.source_http import SourceDocument


class RSSCollectorTests(unittest.TestCase):
    def test_collect_rss_uses_bounded_http_request_and_limit(self):
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

        with patch("app.rss.fetch_source", return_value=SourceDocument("https://example.com/feed.xml", b"<rss/>", "application/rss+xml")) as get, patch("app.rss.feedparser.parse", return_value=Feed()):
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
            allowed_hosts=["example.com"],
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source_type, "rss")

    def test_strips_encoded_publisher_markup_and_discards_unsafe_item_links(self):
        feed = b'''<rss version="2.0"><channel><title>Source</title>
        <item><title>Public source report</title><link>https://example.com/report</link>
        <description>&amp;lt;p class="publisher"&amp;gt;A public &amp;lt;strong&amp;gt;source&amp;lt;/strong&amp;gt; report.&amp;lt;/p&amp;gt;</description></item>
        <item><title>Bad link</title><link>javascript:alert(1)</link></item>
        <item><title>Internal link</title><link>http://127.0.0.1/private</link></item>
        </channel></rss>'''
        with patch("app.rss.fetch_source", return_value=SourceDocument("https://example.com/feed", feed, "application/rss+xml")):
            items = collect_rss({"name": "Source", "url": "https://example.com/feed"})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].summary, "A public source report.")


if __name__ == "__main__":
    unittest.main()
