import unittest
from datetime import datetime, timedelta, timezone

from app.models import NewsItem
from scripts.offline_snapshot import public_story, build
from scripts.offline_instagram import choose_story


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

    def test_dedupes_source_urls(self):
        story = public_story(item(), NOW)
        output, changed = build([story], [item()], NOW)
        self.assertEqual(changed, 0)
        self.assertEqual(len(output), 1)

    def test_instagram_cooldown_and_source_selection(self):
        story = public_story(item(), NOW)
        self.assertEqual(choose_story([story], {"posts": []}, NOW)["url"], story["url"])
        self.assertIsNone(choose_story([story], {"last_published_at": NOW.isoformat()}, NOW))
        self.assertIsNone(choose_story([story], {"posts": [{"url": story["url"]}]}, NOW))


if __name__ == "__main__":
    unittest.main()
