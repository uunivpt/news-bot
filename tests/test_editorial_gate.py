import unittest
from app.editorial_gate import longform_review, word_count

class LongformGateTests(unittest.TestCase):
    def test_short_rss_summary_cannot_pass_even_if_reviewed(self):
        result = longform_review({"bot_article": "News update. " * 30, "summary": "This is a full summary of a relevant report.", "fact_check_status": "reviewed"})
        self.assertFalse(result["passed"])
        self.assertIn("insufficient_original_longform_material", result["errors"])

    def test_eight_hundred_words_still_requires_editor_review(self):
        article = " ".join("detail%s" % i for i in range(820))
        result = longform_review({"bot_article": article, "summary": "An independently reviewed report with verifiable factual detail.", "fact_check_status": "pending"})
        self.assertFalse(result["passed"])
        self.assertIn("editorial_review_required", result["errors"])

    def test_approved_substantive_report_passes_structural_gate(self):
        article = " ".join("detail%s" % i for i in range(820))
        result = longform_review({"bot_article": article, "summary": "An independently reviewed report with verifiable factual detail.", "fact_check_status": "approved"})
        self.assertTrue(result["passed"])
        self.assertEqual(result["words"], 820)

    def test_unicode_word_count(self):
        self.assertEqual(word_count("महाराष्ट्र बातम्या and news"), 4)

if __name__ == "__main__":
    unittest.main()
