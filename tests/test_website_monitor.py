import unittest
from unittest.mock import patch

from app.website_monitor import collect_website


class FakeResponse:
    def __init__(self, url, html):
        self.url = url
        self.text = html
        self.headers = {"content-type": "text/html; charset=utf-8"}

    def raise_for_status(self):
        return None


class WebsiteMonitorTests(unittest.TestCase):
    def test_collects_only_allowed_host_and_path(self):
        index = '''<html><body>
        <a href="/news/one">Valid update</a>
        <a href="/news/two">Another valid update</a>
        <a href="https://evil.example/news/bad">External</a>
        <a href="/about">Not an article</a>
        </body></html>'''
        article = '''<html><head><meta property="og:title" content="Government announces a new measure"></head>
        <body><article><p>The government announced a new measure today after a formal review.</p>
        <p>Officials said the measure will apply from Monday.</p>
        <p>The department published additional implementation details for affected offices.</p></article></body></html>'''

        def fake_get(url, **kwargs):
            if url.endswith("/updates"):
                return FakeResponse(url, index)
            return FakeResponse(url, article)

        source = {
            "name": "Test Government",
            "source_class": "government",
            "category": "india",
            "public_source": True,
            "collection_allowed": True,
            "allowed_hosts": ["example.gov"],
            "sections": ["https://example.gov/updates"],
            "article_path_prefixes": ["/news/"],
            "max_links": 10,
        }
        with patch("app.website_monitor.requests.get", side_effect=fake_get):
            items = collect_website(source)

        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.source_type == "government" for item in items))
        self.assertTrue(all(item.public_source for item in items))
        self.assertTrue(all(item.url.startswith("https://example.gov/news/") for item in items))

    def test_disabled_or_unpermitted_source_returns_nothing(self):
        source = {"name": "Private", "enabled": False, "collection_allowed": False, "sections": ["https://example.com/news"]}
        self.assertEqual(collect_website(source), [])


if __name__ == "__main__":
    unittest.main()
