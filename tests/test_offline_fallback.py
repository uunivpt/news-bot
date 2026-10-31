import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from dataclasses import replace

from app.models import NewsItem
from scripts.offline_snapshot import public_story, build, mobile_reviewed_story, merge_mobile_reviewed


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


    def test_mobile_feed_rejects_unapproved_or_pending(self):
        row = self._mobile_row()
        row["approved_at"] = None
        self.assertIsNone(mobile_reviewed_story(row, NOW))
        row["approved_at"] = NOW.isoformat()
        row["fact_check_status"] = "pending"
        self.assertIsNone(mobile_reviewed_story(row, NOW))

    @staticmethod
    def _mobile_row(url="https://example.org/mobile-story", story_id=4503599627371000):
        return {
            "id": story_id, "status": "published", "public_source": True,
            "approved_at": NOW.isoformat(), "fact_check_status": "verified",
            "title": "India releases important official policy report today",
            "url": url, "source_name": "Verified Official Source",
            "source_type": "rss", "published_at": NOW.isoformat(),
            "published_at_site": NOW.isoformat(),
            "summary": "Officials released full policy details in a published public notice. The report links directly to the official original source.",
            "category": "india"
        }

    def test_mobile_feed_accepts_admin_reviewed_only_when_approved(self):
        row = self._mobile_row()
        row["fact_check_status"] = "reviewed"
        self.assertIsNotNone(mobile_reviewed_story(row, NOW))
        row["approved_at"] = None
        self.assertIsNone(mobile_reviewed_story(row, NOW))

    def test_mobile_feed_valid_approved_story(self):
        story = mobile_reviewed_story(self._mobile_row(), NOW)
        self.assertIsNotNone(story)
        self.assertEqual(story["status"], "published")
        self.assertNotIn("approved_at", story)
        self.assertEqual(story["bot_article"], "")

    def test_mobile_merge_preserves_existing_article_id_and_dedupes(self):
        prior = public_story(item(url="https://example.org/mobile-story"), NOW)
        approved = self._mobile_row()
        rows, changed = merge_mobile_reviewed([prior], [approved, approved], NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], prior["id"])
        self.assertEqual(rows[0]["bot_article"], prior["bot_article"])
        self.assertEqual(changed, 0)

    def test_mobile_merge_blocks_id_collision(self):
        prior = public_story(item(), NOW)
        incoming = self._mobile_row(story_id=prior["id"])
        rows, changed = merge_mobile_reviewed([prior], [incoming], NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(changed, 0)

    def test_mobile_merge_does_not_modify_existing_snapshot(self):
        prior = public_story(item(), NOW)
        before = dict(prior)
        rows, changed = merge_mobile_reviewed([prior], [self._mobile_row()], NOW)
        self.assertEqual(len(rows), 2)
        self.assertEqual(changed, 1)
        self.assertEqual(prior, before)

if __name__ == "__main__":
    unittest.main()
