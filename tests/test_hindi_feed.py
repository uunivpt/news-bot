import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from app.collector import load_sources
from scripts.build_hindi_feed import story_from_rss


class HindiFeedTests(unittest.TestCase):
    def test_six_attributed_hindi_rss_sources(self):
        sources=load_sources().get("hindi_rss", [])
        self.assertEqual(len(sources), 6)
        self.assertTrue(all(s["check_every_minutes"] == 60 for s in sources))
        self.assertTrue(all(s["category"] == "hindi" and s["enabled"] for s in sources))

    def test_keep_hindi_headline_and_original_url(self):
        now=datetime.now(timezone.utc)
        item=SimpleNamespace(
            title="भारत में नई घोषणा को लेकर बड़ी जानकारी",
            summary="आधिकारिक रिपोर्ट में नई घोषणा का उल्लेख किया गया है।",
            published_at=now.isoformat(), source_name="PIB Hindi",
            url="https://pib.gov.in/PressReleasePage.aspx?PRID=12345")
        story=story_from_rss(item, now)
        self.assertIsNotNone(story)
        self.assertEqual(story["category"], "hindi")
        self.assertEqual(story["title"], item.title)
        self.assertEqual(story["url"], item.url)
        self.assertEqual(story["bot_article"], "")
        self.assertIsNone(story["image_url"])

    def test_non_hindi_is_not_published_into_hindi(self):
        now=datetime.now(timezone.utc)
        item=SimpleNamespace(
            title="English article should not be in Hindi feed", summary="Details.",
            published_at=now.isoformat(), source_name="Example",
            url="https://example.org/report")
        self.assertIsNone(story_from_rss(item,now))


if __name__ == "__main__":
    unittest.main()
