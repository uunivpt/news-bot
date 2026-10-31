import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from dataclasses import replace

from app.models import NewsItem
from scripts.offline_snapshot import public_story, build


NOW = datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc)


def item(url="https://example.org/report", summary=None, date=None):
    return NewsItem(
        source_name="Original newsroom",
        source_type="newsdata",
        title="An important development in India was reported today",
        url=url,
        published_at=date or (NOW - timedelta(hours=2)).isoformat(),
        summary=summary or (
            "Officials released the full statement earlier today. "
            "The publicly reported update gives the latest available information. "
            "Further details remain available from the linked original source."
        ),
        category="india",
        public_source=True,
    )


class OfflineNewsFallbackTests(unittest.TestCase):
    def test_source_story_has_link_no_replacement_image_and_complete_sentence(self):
        story = public_story(item(), NOW)
        self.assertIsNotNone(story)
        self.assertEqual(story["source_type"], "newsdata")
        self.assertIsNone(story["image_url"])
        self.assertEqual(story["bot_article"], "")
        self.assertTrue(story["summary"].endswith("."))

    def test_truncated_excerpt_stops_at_sentence_boundary(self):
        value = "This statement confirms the newly announced decision in India. " + (
            "More details " * 60
        )
        story = public_story(item(summary=value), NOW)
        self.assertIsNotNone(story)
        self.assertEqual(story["summary"], "This statement confirms the newly announced decision in India.")

    def test_rejects_stale_unsourced_or_unsafe_items(self):
        self.assertIsNone(public_story(item(date=(NOW-timedelta(days=3)).isoformat()), NOW))
        self.assertIsNone(public_story(item(url="javascript:alert(1)"), NOW))

    def test_rss_standfirst_without_period_is_preserved_in_full(self):
        text = "The hill town uses about 60 lakh gallons a day; officials now pin their hopes on the northeast monsoon"
        story = public_story(replace(item(), source_type="rss", summary=text), NOW)
        self.assertIsNotNone(story)
        self.assertEqual(story["summary"], text)
        self.assertEqual(story["url"], item().url)
        self.assertIsNone(story["image_url"])

    def test_rss_clipped_or_overlong_standfirst_is_not_published(self):
        for text in ("More details are expected about this developing report " * 12,
                     "Officials released details about the latest regional development…",
                     "Officials released details about the latest regional development..."):
            with self.subTest(text=text):
                self.assertIsNone(public_story(replace(item(), source_type="rss", summary=text), NOW))

    def test_build_does_not_mutate_previous_snapshot_categories(self):
        story = public_story(item(), NOW)
        story["category"] = "entertainment"
        story["title"] = "Bollywood actor dies at 82"
        rows, _ = build([story], [], NOW)
        self.assertEqual(story["category"], "entertainment")
        self.assertEqual(rows[0]["category"], "india")

    def test_dedupes_source_urls(self):
        story = public_story(item(), NOW)
        output, changed = build([story], [item()], NOW)
        self.assertEqual(changed, 0)
        self.assertEqual(len(output), 1)

    def test_existing_rss_snapshot_copy_is_repaired_without_new_stories(self):
        story = public_story(replace(item(), source_type="rss"), NOW)
        expected = story["summary"]
        story["summary"] = '&lt;p class="publisher"&gt;' + expected + '&lt;/p&gt;'
        output, changed = build([story], [], NOW)
        self.assertGreater(changed, 0)
        self.assertEqual(output[0]["summary"], expected)
        self.assertIn("&lt;p", story["summary"])


if __name__ == "__main__":
    unittest.main()
