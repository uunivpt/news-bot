import json
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from app.collector import load_sources
from scripts.build_hindi_feed import main, story_from_rss


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
            url="https://pib.gov.in/PressReleasePage.aspx?PRID=12345", public_source=True)
        story=story_from_rss(item, now)
        self.assertIsNotNone(story)
        self.assertEqual(story["category"], "hindi")
        self.assertEqual(story["title"], item.title)
        self.assertEqual(story["url"], item.url)
        self.assertEqual(story["source_name"], item.source_name)
        self.assertEqual(story["published_at"], item.published_at)
        self.assertEqual(story["bot_article"], "")
        self.assertIsNone(story["image_url"])

    def test_non_hindi_is_not_published_into_hindi(self):
        now=datetime.now(timezone.utc)
        item=SimpleNamespace(
            title="English article should not be in Hindi feed", summary="Details.",
            published_at=now.isoformat(), source_name="Example",
            url="https://example.org/report", public_source=True)
        self.assertIsNone(story_from_rss(item,now))

    def test_story_requires_explicit_public_source_permission(self):
        now = datetime.now(timezone.utc)
        item = SimpleNamespace(title="भारत में नई घोषणा को लेकर बड़ी जानकारी",
                               summary="मूल प्रकाशक का संक्षिप्त संदर्भ।",
                               published_at=now.isoformat(), source_name="RSS fixture",
                               url="https://example.org/hindi-report")
        self.assertIsNone(story_from_rss(item, now))
        for permission in (False, None, "false", "true", 1):
            with self.subTest(permission=permission):
                item.public_source = permission
                self.assertIsNone(story_from_rss(item, now))
        item.public_source = True
        self.assertIsNotNone(story_from_rss(item, now))

    def test_builder_fetches_only_enabled_explicitly_public_sources(self):
        now = datetime.now(timezone.utc)
        public = {"name": "Permitted RSS fixture", "enabled": True, "public_source": True}
        sources = [public, {"name": "Missing permission"},
                   {"name": "Disabled", "enabled": False, "public_source": True}]
        sources.extend({"name": "Unpermitted fixture", "public_source": value}
                       for value in (False, None, "false", "true", 1))
        item = SimpleNamespace(title="भारत में नई घोषणा को लेकर बड़ी जानकारी",
                               summary="मूल प्रकाशक का संक्षिप्त संदर्भ।",
                               published_at=now.isoformat(), source_name=public["name"],
                               url="https://example.org/hindi-report", public_source=True)
        with tempfile.TemporaryDirectory() as temp, \
             patch('scripts.build_hindi_feed.OUT', Path(temp) / 'hindi.json') as output, \
             patch('scripts.build_hindi_feed.load_sources', return_value={"hindi_rss": sources}), \
             patch('scripts.build_hindi_feed.collect_rss', return_value=[item]) as collect:
            main()
            collect.assert_called_once_with(public)
            rows = json.loads(output.read_text())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['url'], item.url)
        self.assertEqual(rows[0]['published_at'], item.published_at)
        self.assertEqual(rows[0]['source_name'], item.source_name)

    def test_unpermitted_sources_do_not_count_as_successful_collection(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch('scripts.build_hindi_feed.OUT', Path(temp) / 'hindi.json') as output, \
             patch('scripts.build_hindi_feed.load_sources', return_value={"hindi_rss": [{"name": "Private", "public_source": False}]}), \
             patch('scripts.build_hindi_feed.collect_rss', return_value=[]) as collect:
            with self.assertRaisesRegex(SystemExit, 'No Hindi sources responded'):
                main()
            collect.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
