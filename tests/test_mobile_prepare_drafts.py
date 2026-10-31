import unittest
from unittest.mock import Mock, patch

from app.article_fetcher import enrich_source_text
from scripts.mobile_prepare_drafts import prepare


class CanonicalSourceFetchTests(unittest.TestCase):
    def test_primary_source_url_is_fetched_first(self):
        article = {
            "url": "https://news.example.com/story",
            "text": "Verified source material with enough sentences for a news draft.",
            "image_url": None,
        }
        with patch("app.article_fetcher.extract_public_article", return_value=article) as fetch:
            result = enrich_source_text(
                "A report headline", "RSS excerpt without a link",
                "https://news.example.com/story",
            )
        self.assertEqual(result, article)
        fetch.assert_called_once_with("https://news.example.com/story")

    def test_private_primary_source_not_fetched(self):
        with patch("app.article_fetcher.extract_public_article") as fetch:
            result = enrich_source_text("Headline", "A plain RSS summary",
                                        "http://127.0.0.1/private")
        fetch.assert_not_called()
        self.assertEqual(result["text"], "A plain RSS summary")

    def test_url_within_summary_is_fallback_when_primary_unavailable(self):
        text = "More: https://other.example.org/story"
        with patch("app.article_fetcher.extract_public_article",
                   side_effect=[None, {"text": "External public report"}]) as fetch:
            value = enrich_source_text("Headline", text,
                                       "https://news.example.org/story")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(value["text"], "External public report")


class PhoneDraftPreparationTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.db.latest.return_value = [
            {"id": 456, "title": "City announces revised public bus schedule",
             "summary": "The revised bus schedule starts on Monday.",
             "url": "https://example.org/bus", "category": "india",
             "status": "pending", "fact_check_status": "pending",
             "bot_article": None, "bot_summary": None},
        ]
        self.generated = {
            "headline": "City announces revised public bus schedule",
            "summary": "The transport authority confirmed that new services begin on Monday.",
            "article": "The transport authority confirmed that new services begin on Monday. Updated schedules will be posted at stations. Passenger guidance is being prepared before the launch.",
        }

    @patch("scripts.mobile_prepare_drafts.quality_gate", return_value={"passed": True})
    @patch("scripts.mobile_prepare_drafts.validate_news_copy", return_value={"passed": True})
    @patch("scripts.mobile_prepare_drafts.process_news")
    @patch("scripts.mobile_prepare_drafts.enrich_source_text", return_value={"text": "source material"})
    def test_dry_run_makes_no_database_changes(self, fetch, process, validate, qa):
        process.return_value = self.generated
        result = prepare(self.db, limit=5, write=False)
        self.assertEqual(result["ready"], 1)
        self.assertEqual(result["saved"], 0)
        self.db.update.assert_not_called()

    @patch("scripts.mobile_prepare_drafts.quality_gate", return_value={"passed": True})
    @patch("scripts.mobile_prepare_drafts.validate_news_copy", return_value={"passed": True})
    @patch("scripts.mobile_prepare_drafts.process_news")
    @patch("scripts.mobile_prepare_drafts.enrich_source_text", return_value={"text": "source material"})
    def test_write_only_saves_drafts_without_publishing(self, fetch, process, validate, qa):
        process.return_value = self.generated
        result = prepare(self.db, limit=3, write=True)
        self.assertEqual(result["saved"], 1)
        self.db.update.assert_called_once_with(
            456, bot_article=self.generated["article"],
            bot_summary=self.generated["summary"],
        )
        self.assertNotIn("status", self.db.update.call_args.kwargs)
        self.assertNotIn("approved_at", self.db.update.call_args.kwargs)

    def test_preexisting_article_not_overwritten(self):
        self.db.latest.return_value[0]["bot_article"] = "Existing editorial draft"
        result = prepare(self.db, limit=5, write=True)
        self.assertEqual(result["ready"], 0)
        self.db.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
