"""Publication dates must be real, labeled, consistent, and not invented."""
import json
import re
import unittest
from datetime import datetime, timezone
from api.index import _article_html, _article_publication_datetime


def article(**changes):
    row = {
        "id": 999, "title": "Regional public-service notice explained",
        "category": "india", "status": "published",
        "source_name": "Original Publisher", "source_type": "rss",
        "url": "https://example.org/notice", "summary": "The publisher describes a local services notice.",
        "bot_article": "The official notice identifies the authority and affected area.",
    }
    row.update(changes)
    return row


class ArticlePublicationDateTests(unittest.TestCase):
    def test_iso_date_shows_visible_ist_date_and_matching_iso_schema(self):
        page = _article_html(article(published_at="2026-10-15T08:00:00Z"))
        self.assertIn('datetime="2026-10-15T08:00:00Z"', page)
        self.assertIn("Source published: 15 Oct 2026, 01:30 PM IST", page)
        self.assertIn('content="2026-10-15T08:00:00Z"', page)
        schema = json.loads(re.search(r'<script type="application/ld\+json">([^<]+)</script>', page).group(1))
        self.assertEqual(schema["datePublished"], "2026-10-15T08:00:00Z")
        self.assertNotIn("dateModified", schema)  # No edit time can be inferred from publication.

    def test_real_site_publication_date_is_preferred_to_source_date(self):
        actual, label, original_iso = _article_publication_datetime(article(
            published_at="2026-10-14T08:00:00Z",
            published_at_site="2026-10-15T09:05:00+05:30",
        ))
        self.assertEqual(label, "Published")
        self.assertEqual(original_iso, "2026-10-15T09:05:00+05:30")
        self.assertEqual(actual, datetime(2026, 10, 15, 3, 35, tzinfo=timezone.utc))

    def test_rss_published_date_has_real_timezone(self):
        date, label, published_iso = _article_publication_datetime(article(
            published_at="Thu, 15 Oct 2026 08:00:00 GMT"
        ))
        self.assertEqual(date, datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(label, "Source published")
        self.assertEqual(published_iso, "2026-10-15T08:00:00+00:00")

    def test_missing_date_is_never_invented(self):
        page = _article_html(article())
        self.assertIn("Publication date unavailable", page)
        self.assertNotIn('property="article:published_time"', page)
        schema = json.loads(re.search(r'<script type="application/ld\+json">([^<]+)</script>', page).group(1))
        self.assertNotIn("datePublished", schema)
        self.assertNotIn("dateModified", schema)

    def test_invalid_and_naive_dates_are_omitted(self):
        for raw in ("not a date", "2026-10-15T08:00:00"):
            with self.subTest(value=raw):
                date, label, published_iso = _article_publication_datetime(article(published_at=raw))
                self.assertIsNone(date)
                self.assertIsNone(label)
                self.assertIsNone(published_iso)


if __name__ == "__main__":
    unittest.main()
