import unittest

from app.newsroom import clean_text, make_summary, process_news, select_sentences, sentences


class NewsroomBotTests(unittest.TestCase):
    def setUp(self):
        self.material = (
            "Breaking update: The city administration announced a new measure on Monday. "
            "Officials said the measure will affect several districts from Tuesday. "
            "The decision follows heavy rainfall recorded across the region. "
            "Authorities asked residents to follow local advisories and avoid unsafe areas. "
            "More details will be released after the next review."
        )

    def test_clean_text_removes_urls_and_handles(self):
        cleaned = clean_text("News @channel https://example.com\nFollow us for more")
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("@channel", cleaned)
        self.assertNotIn("Follow us", cleaned)

    def test_summary_is_shorter_than_material(self):
        result = make_summary("Update", self.material)
        self.assertTrue(result)
        self.assertLess(len(result), len(self.material))
        self.assertGreaterEqual(len(select_sentences(result, 3)), 1)

    def test_process_returns_complete_fields(self):
        result = process_news("Breaking update", self.material, "general")
        self.assertIsNotNone(result)
        self.assertTrue(result["headline"])
        self.assertTrue(result["summary"].endswith("."))
        self.assertTrue(result["article"].endswith("."))
        self.assertIn("What happened:", result["article"])
        self.assertNotIn("https://", result["article"])

    def test_incomplete_final_fragment_is_dropped(self):
        text = (
            "The company announced a new agreement on Tuesday. "
            "Officials said the order was confirmed. "
            "Details including the amount and models and the"
        )
        items = sentences(text)
        self.assertEqual(len(items), 2)
        self.assertTrue(all(x.endswith(".") for x in items))
        self.assertNotIn("and the", items[-1].lower())

    def test_short_material_is_held(self):
        self.assertIsNone(process_news("Tiny update", "Too short."))


if __name__ == "__main__":
    unittest.main()
